from __future__ import annotations

from app.config import Settings
from app.workflows.models import WorkflowResult
from app.workflows.models import WorkflowDefinition
from app.workflows.runner import WorkflowRunner
from app.workflows.runtime_trace import InMemoryTracePersistence, SqliteTracePersistence, TraceEmitter
from tests.fakes.ollama import FakeOllamaClient


def _runner_with_persistence() -> tuple[WorkflowRunner, InMemoryTracePersistence]:
    persistence = InMemoryTracePersistence()

    def factory(run_id: str, workflow_id: str) -> TraceEmitter:
        return TraceEmitter(run_id=run_id, workflow_id=workflow_id, persistence=persistence)

    fake = FakeOllamaClient()
    runner = WorkflowRunner(
        settings=Settings(effort="medium"),
        ollama=fake,
        trace_factory=factory,
        final_ollama_factory=lambda: fake,
    )
    return runner, persistence


def test_build_trace_returns_none_without_run_id() -> None:
    runner, _ = _runner_with_persistence()
    assert runner._build_trace("wf", {}) is None
    assert runner._build_trace("wf", {"workflow_run_id": ""}) is None


def test_build_trace_returns_emitter_when_run_id_present() -> None:
    runner, _ = _runner_with_persistence()
    trace = runner._build_trace("wf", {"workflow_run_id": "run-1"})
    assert trace is not None
    assert trace.run_id == "run-1"
    assert trace.workflow_id == "wf"


def test_emit_run_finished_writes_done_status() -> None:
    runner, persistence = _runner_with_persistence()
    trace = runner._build_trace("wf", {"workflow_run_id": "run-1"})
    runner._emit_run_finished(
        trace,
        WorkflowResult(workflow_id="wf", answer="hello", status="done"),
    )
    assert [event.type for event in persistence.events] == ["run_finished"]
    payload = persistence.events[0].payload
    assert payload["status"] == "done"
    assert payload["final_output"] == "hello"


def test_emit_run_finished_writes_failed_status() -> None:
    runner, persistence = _runner_with_persistence()
    trace = runner._build_trace("wf", {"workflow_run_id": "run-1"})
    runner._emit_run_finished(
        trace,
        WorkflowResult(workflow_id="wf", answer="", status="failed"),
    )
    assert [event.type for event in persistence.events] == ["run_failed"]


def test_emit_run_finished_writes_paused_status() -> None:
    runner, persistence = _runner_with_persistence()
    trace = runner._build_trace("wf", {"workflow_run_id": "run-1"})
    runner._emit_run_finished(
        trace,
        WorkflowResult(workflow_id="wf", answer="", status="paused"),
    )
    assert [event.type for event in persistence.events] == ["run_paused"]
    assert persistence.events[0].payload["status"] == "paused"


def test_emit_run_finished_with_none_trace_is_noop() -> None:
    runner, persistence = _runner_with_persistence()
    runner._emit_run_finished(None, WorkflowResult(workflow_id="wf", answer="x", status="done"))
    assert persistence.events == []


def test_on_run_started_callback_fires_with_run_id(db, tmp_path, monkeypatch) -> None:
    import asyncio

    from app.workflows.models import WorkflowDefinition

    runner, _ = _runner_with_persistence()
    chat = db.create_chat(title="t", workspace_path="")
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf",
            "name": "Direct",
            "execution": "direct",
            "nodes": [{"id": "answer", "type": "answer", "output": "final_answer"}],
            "edges": [],
        }
    )

    received: list[str] = []

    asyncio.run(
        runner.run(
            workflow,
            chat.id,
            "hello",
            "chat",
            on_run_started=lambda run_id: received.append(run_id),
        )
    )

    assert len(received) == 1 and received[0]


def test_on_run_started_callback_failure_is_swallowed(db) -> None:
    import asyncio

    from app.workflows.models import WorkflowDefinition

    runner, _ = _runner_with_persistence()
    chat = db.create_chat(title="t", workspace_path="")
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf",
            "name": "Direct",
            "execution": "direct",
            "nodes": [{"id": "answer", "type": "answer", "output": "final_answer"}],
            "edges": [],
        }
    )

    def boom(_run_id: str) -> None:
        raise RuntimeError("boom")

    # Must not raise; runner continues to completion.
    result = asyncio.run(runner.run(workflow, chat.id, "hello", "chat", on_run_started=boom))
    assert result.status == "done"


def test_fork_replays_to_step_applies_edited_output_and_persists_child(db) -> None:
    import asyncio

    from app.workflow_scratch import InMemoryWorkflowScratchpad

    chat = db.create_chat(title="t", workspace_path="")
    db.create_workflow_run("parent", workflow_id="wf", chat_id=chat.id, mode="chat", initial_input="hello")
    emitter = TraceEmitter(run_id="parent", workflow_id="wf", persistence=SqliteTracePersistence())
    emitter.emit("run_started", node_id="workflow")
    emitter.emit("node_started", node_id="draft")
    emitter.emit(
        "node_finished",
        node_id="draft",
        payload={"status": "done", "output_snapshot": {"text": "bad"}, "output_snapshot_truncated": False},
    )
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf",
            "name": "Forkable",
            "nodes": [
                {"id": "draft", "type": "manual", "output": "draft"},
                {"id": "answer", "type": "answer", "output": "final_answer"},
            ],
            "edges": [{"from": "draft", "to": "answer"}],
        }
    )
    fake = FakeOllamaClient()
    runner = WorkflowRunner(
        settings=Settings(effort="medium"),
        ollama=fake,
        scratchpad=InMemoryWorkflowScratchpad(),
        final_ollama_factory=lambda: fake,
    )

    result = asyncio.run(
        runner.fork(workflow, db.get_workflow_run("parent"), from_step_id="draft", edited_output={"text": "fixed"})
    )

    child = db.get_workflow_run(result.state["workflow_run_id"])
    assert result.state["draft"] == {"text": "fixed"}
    assert child is not None
    assert child.fork_of_run_id == "parent"
    assert child.fork_at_node_id == "draft"


def test_default_trace_factory_uses_sqlite_persistence() -> None:
    runner = WorkflowRunner(settings=Settings(effort="medium"), ollama=FakeOllamaClient())
    trace = runner._build_trace("wf", {"workflow_run_id": "run-default"})
    # falls back to SqliteTracePersistence; do not actually insert (no chat row)
    assert trace is not None
    assert trace.run_id == "run-default"


def test_copy_fork_trace_events_skips_terminal_run_events(db) -> None:
    """Regression P1-8: when forking from a completed run, the parent's
    run_finished / run_failed / run_paused must NOT be copied into the child.

    If they were, the child's SSE bus would emit `run_finished` before the
    forked execution actually finishes, confusing the frontend reducer.
    """
    from app.workflows.runner import WorkflowRunner
    from app.workflows.runtime_trace import InMemoryTracePersistence, TraceEmitter

    runner = WorkflowRunner(settings=Settings(effort="medium"), ollama=FakeOllamaClient())
    persistence = InMemoryTracePersistence()
    trace = TraceEmitter(run_id="child", workflow_id="wf", persistence=persistence)

    parent_events = [
        {"seq": 1, "type": "run_started", "node_id": "workflow", "step_id": "s1", "payload": {}},
        {"seq": 2, "type": "node_started", "node_id": "draft", "step_id": "s2", "payload": {}},
        {
            "seq": 3,
            "type": "node_finished",
            "node_id": "draft",
            "step_id": "s3",
            "parent_step_id": None,
            "payload": {"status": "done", "output_snapshot": "out"},
        },
        {"seq": 4, "type": "run_finished", "node_id": "workflow", "step_id": "s4", "payload": {"status": "done"}},
        {"seq": 5, "type": "run_failed", "node_id": "workflow", "step_id": "s5", "payload": {"error": "x"}},
        {"seq": 6, "type": "run_paused", "node_id": "workflow", "step_id": "s6", "payload": {}},
    ]

    runner._copy_fork_trace_events(trace, parent_events)

    copied_types = [event.type for event in persistence.events]
    # node_started + node_finished only — every run_* lifecycle event was skipped.
    assert "run_started" not in copied_types
    assert "run_finished" not in copied_types
    assert "run_failed" not in copied_types
    assert "run_paused" not in copied_types
    assert copied_types == ["node_started", "node_finished"]


def test_replay_runs_downstream_subgraph_and_records_replay_metadata(db) -> None:
    """Smoke test for runner.replay end-to-end.

    Seeds a completed parent run with a clean trace, then re-runs the
    downstream subgraph starting at `b`. The child run inherits the parent's
    fork metadata and carries the replay plan in its state.
    """
    import asyncio

    from app.workflow_scratch import InMemoryWorkflowScratchpad

    chat = db.create_chat(title="t", workspace_path="")
    parent_id = "replay-parent"
    db.create_workflow_run(parent_id, workflow_id="wf-r", chat_id=chat.id, mode="chat", initial_input="hello")
    em = TraceEmitter(run_id=parent_id, workflow_id="wf-r", persistence=SqliteTracePersistence())
    em.emit("run_started", node_id="workflow")
    em.emit("node_started", node_id="a", payload={"node_type": "role"})
    em.emit(
        "node_finished",
        node_id="a",
        payload={"status": "done", "output_snapshot": "plan", "output_snapshot_truncated": False},
    )
    em.emit("node_started", node_id="b", payload={"node_type": "role"})
    em.emit(
        "node_finished",
        node_id="b",
        payload={"status": "done", "output_snapshot": "draft", "output_snapshot_truncated": False},
    )

    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf-r",
            "name": "Replayable",
            "nodes": [
                {"id": "a", "type": "role", "output": "plan"},
                {"id": "b", "type": "role", "input": ["plan"], "output": "draft"},
                {"id": "answer", "type": "answer", "input": ["draft"], "output": "final_answer"},
            ],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "answer"}],
        }
    )
    fake = FakeOllamaClient()
    runner = WorkflowRunner(
        settings=Settings(effort="medium"),
        ollama=fake,
        scratchpad=InMemoryWorkflowScratchpad(),
        final_ollama_factory=lambda: fake,
    )

    result = asyncio.run(runner.replay(workflow, db.get_workflow_run(parent_id), start_node_id="b"))

    child_id = result.state["workflow_run_id"]
    child = db.get_workflow_run(child_id)
    assert child is not None
    assert child.fork_of_run_id == parent_id
    assert child.fork_at_node_id == "b"
    assert result.status == "done"
    # Replay plan recorded for diagnostics
    plan = result.state.get("replay_plan") or {}
    assert plan.get("start_node_id") == "b"
    assert "b" in plan.get("replay_node_ids", [])


def test_replay_rejects_unknown_start_node(db) -> None:
    """Replay must surface plan blockers as ValueError instead of silently
    starting at the wrong place."""
    import asyncio
    import pytest

    from app.workflow_scratch import InMemoryWorkflowScratchpad

    chat = db.create_chat(title="t", workspace_path="")
    db.create_workflow_run("replay-bad", workflow_id="wf", chat_id=chat.id, mode="chat")
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf",
            "name": "Single",
            "nodes": [{"id": "answer", "type": "answer", "output": "final_answer"}],
            "edges": [],
        }
    )
    fake = FakeOllamaClient()
    runner = WorkflowRunner(
        settings=Settings(effort="medium"),
        ollama=fake,
        scratchpad=InMemoryWorkflowScratchpad(),
        final_ollama_factory=lambda: fake,
    )

    with pytest.raises(ValueError):
        asyncio.run(runner.replay(workflow, db.get_workflow_run("replay-bad"), start_node_id="ghost"))


def test_copy_fork_trace_events_remaps_parent_step_id_to_new_ids(db) -> None:
    """Parent → child step_id mapping: child events must point to the child's
    new step_ids, not the parent's stale ones."""
    from app.workflows.runner import WorkflowRunner
    from app.workflows.runtime_trace import InMemoryTracePersistence, TraceEmitter

    runner = WorkflowRunner(settings=Settings(effort="medium"), ollama=FakeOllamaClient())
    persistence = InMemoryTracePersistence()
    trace = TraceEmitter(run_id="child", workflow_id="wf", persistence=persistence)

    # Parent: for_each container 's-loop' wraps body 's-body' which spawns an llm_call 's-llm'.
    parent_events = [
        {"seq": 1, "type": "node_started", "node_id": "loop", "step_id": "s-loop", "parent_step_id": None, "payload": {}},
        {"seq": 2, "type": "node_started", "node_id": "body", "step_id": "s-body", "parent_step_id": "s-loop", "payload": {}},
        {"seq": 3, "type": "llm_call", "node_id": "body", "step_id": "s-llm", "parent_step_id": "s-body", "payload": {}},
        {"seq": 4, "type": "node_finished", "node_id": "body", "step_id": "s-bfin", "parent_step_id": "s-loop", "payload": {"output_snapshot": "ok"}},
        {"seq": 5, "type": "node_finished", "node_id": "loop", "step_id": "s-lfin", "parent_step_id": None, "payload": {"output_snapshot": []}},
    ]

    runner._copy_fork_trace_events(trace, parent_events)

    # Two node_started events produced two new step_ids; map old → new.
    started = [e for e in persistence.events if e.type == "node_started"]
    new_loop = next(e for e in started if e.node_id == "loop")
    new_body = next(e for e in started if e.node_id == "body")

    # body's new parent must point at the *new* loop step_id, not "s-loop"
    assert new_body.parent_step_id == new_loop.step_id
    assert new_body.parent_step_id != "s-loop"

    # llm_call's parent must point at the *new* body step_id
    new_llm = next(e for e in persistence.events if e.type == "llm_call")
    assert new_llm.parent_step_id == new_body.step_id
    assert new_llm.parent_step_id != "s-body"

    # node_finished events (which have parent_step_id but aren't node_started)
    # should also remap parents.
    finished_body = next(e for e in persistence.events if e.type == "node_finished" and e.node_id == "body")
    assert finished_body.parent_step_id == new_loop.step_id
