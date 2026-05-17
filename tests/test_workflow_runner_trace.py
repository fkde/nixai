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
    assert child.fork_at_step_id == "draft"


def test_default_trace_factory_uses_sqlite_persistence() -> None:
    runner = WorkflowRunner(settings=Settings(effort="medium"), ollama=FakeOllamaClient())
    trace = runner._build_trace("wf", {"workflow_run_id": "run-default"})
    # falls back to SqliteTracePersistence; do not actually insert (no chat row)
    assert trace is not None
    assert trace.run_id == "run-default"
