from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.config import Settings
from app.workflow_scratch import InMemoryWorkflowScratchpad
from app.workflows.events import WorkflowEventSink
from app.workflows.executor import WorkflowGraphExecutor
from app.workflows.models import WorkflowDefinition, WorkflowNode
from app.workflows.nodes import NodeResult
from app.workflows.phases import WorkflowPhaseDeps
from app.workflows.resolver import NodeInputResolver
from app.workflows.state import WorkflowState
from tests.fakes.ollama import FakeOllamaClient


def test_deep_orchestra_like_graph_runs_until_answer() -> None:
    handlers = {
        "role": StaticNodeHandler("plan", {"summary": "Plan", "work_items": [{"id": "main"}]}),
        "worker_pool": StaticNodeHandler("worker_reports", [{"id": "main", "content": "Report"}]),
        "reviewer": StaticNodeHandler("review", {"status": "approved", "summary": "Looks good"}),
        "judge": StaticNodeHandler("decision", {"status": "done", "reason": "Complete"}),
        "answer": StaticNodeHandler("final_answer", "Final answer."),
    }

    result = run_async(
        WorkflowGraphExecutor(handlers=handlers).run(workflow_definition(), state(), deps(), event_sink())
    )

    assert result.status == "done"
    assert result.answer == "Final answer."
    assert result.state["node_results"]["answer"]["output"] == "Final answer."


def test_retry_edge_runs_another_pass_then_answer() -> None:
    worker = CountingNodeHandler("worker_reports", lambda count: [{"id": f"run-{count}", "content": "Report"}])
    judge = SequenceNodeHandler(
        "decision",
        [
            {"status": "retry", "reason": "Try again", "feedback": ["More detail"]},
            {"status": "done", "reason": "Complete"},
        ],
    )
    handlers = {
        "role": StaticNodeHandler("plan", {"summary": "Plan", "work_items": [{"id": "main"}]}),
        "worker_pool": worker,
        "reviewer": StaticNodeHandler("review", {"status": "approved"}),
        "judge": judge,
        "answer": StaticNodeHandler("final_answer", "Final answer."),
    }

    result = run_async(
        WorkflowGraphExecutor(handlers=handlers).run(workflow_definition(), state(), deps(), event_sink())
    )

    assert result.status == "done"
    assert worker.count == 2
    assert result.state["retry_feedback"] == ["More detail"]
    assert len(result.state["workflow_rounds"]) == 2


def test_retry_edge_is_limited_by_workflow_max_iterations() -> None:
    worker = CountingNodeHandler("worker_reports", lambda count: [{"id": f"run-{count}", "content": "Report"}])
    handlers = {
        "role": StaticNodeHandler("plan", {"summary": "Plan", "work_items": [{"id": "main"}]}),
        "worker_pool": worker,
        "reviewer": StaticNodeHandler("review", {"status": "approved"}),
        "judge": StaticNodeHandler("decision", {"status": "retry", "reason": "Again"}),
        "answer": StaticNodeHandler("final_answer", "Best available answer."),
    }
    workflow = workflow_definition(max_iterations=1)

    result = run_async(WorkflowGraphExecutor(handlers=handlers).run(workflow, state(), deps(), event_sink()))

    assert result.status == "done"
    assert worker.count == 1
    assert result.state["decision"]["status"] == "done"


def test_needs_user_finishes_cleanly() -> None:
    handlers = {
        "role": StaticNodeHandler("plan", {"summary": "Plan", "work_items": [{"id": "main"}]}),
        "worker_pool": StaticNodeHandler("worker_reports", []),
        "reviewer": StaticNodeHandler("review", {"status": "changes_requested"}),
        "judge": StaticNodeHandler("decision", {"status": "needs_user", "reason": "Which workspace?"}),
        "answer": StaticNodeHandler("final_answer", "Which workspace?", status="needs_user"),
    }

    result = run_async(
        WorkflowGraphExecutor(handlers=handlers).run(workflow_definition(), state(), deps(), event_sink())
    )

    assert result.status == "needs_user"
    assert result.answer == "Which workspace?"


def test_pause_signal_stops_after_current_step_and_keeps_state(db) -> None:
    chat = db.create_chat(title="t", workspace_path="")
    db.create_workflow_run("run-1", workflow_id="wf-test", chat_id=chat.id, mode="chat")
    db.request_workflow_run_signal("run-1", "pause")
    handlers = {
        "role": StaticNodeHandler("plan", {"summary": "Plan", "work_items": [{"id": "main"}]}),
        "worker_pool": StaticNodeHandler("worker_reports", [{"id": "main"}]),
    }

    result = run_async(
        WorkflowGraphExecutor(handlers=handlers).run(workflow_definition(), state(), deps(), event_sink())
    )

    assert result.status == "paused"
    assert result.state["plan"]["summary"] == "Plan"
    assert result.state["pause"]["node"] == "orchestrator"
    assert not db.has_workflow_run_signal("run-1", "pause")


def test_unsupported_node_is_controlled_failure() -> None:
    workflow = WorkflowDefinition.model_validate(
        {"id": "bad", "name": "Bad", "nodes": [{"id": "mystery", "type": "mystery"}]}
    )

    result = run_async(WorkflowGraphExecutor().run(workflow, state(), deps(), event_sink()))

    assert result.status == "failed"
    assert "Unsupported workflow node type" in result.answer
    assert result.state["node_results"]["mystery"]["status"] == "failed"


def test_failed_node_can_follow_error_edge() -> None:
    handlers = {"role": FailingOnceNodeHandler("boom"), "answer": StaticNodeHandler("final_answer", "Recovered.")}
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "error-edge",
            "name": "Error Edge",
            "nodes": [
                {"id": "start", "type": "role", "output": "plan"},
                {"id": "fallback", "type": "answer", "output": "final_answer"},
            ],
            "edges": [{"from": "start", "to": "fallback", "when": "error"}],
        }
    )

    result = run_async(WorkflowGraphExecutor(handlers=handlers).run(workflow, state(), deps(), event_sink()))

    assert result.status == "done"
    assert result.answer == "Recovered."
    assert result.state["node_results"]["start"]["status"] == "failed"


def test_node_retry_recovers_before_error_edge() -> None:
    handler = FailingOnceNodeHandler("plan", output={"summary": "Recovered"})
    handlers = {"role": handler, "answer": StaticNodeHandler("final_answer", "Done.")}
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "retry-node",
            "name": "Retry Node",
            "nodes": [
                {"id": "start", "type": "role", "output": "plan", "retry": {"max": 1, "backoff": 0}},
                {"id": "answer", "type": "answer", "output": "final_answer"},
                {"id": "fallback", "type": "answer", "output": "final_answer"},
            ],
            "edges": [{"from": "start", "to": "answer"}, {"from": "start", "to": "fallback", "when": "error"}],
        }
    )

    result = run_async(WorkflowGraphExecutor(handlers=handlers).run(workflow, state(), deps(), event_sink()))

    assert result.status == "done"
    assert result.answer == "Done."
    assert handler.count == 2
    assert result.state["node_results"]["start"]["status"] == "done"


def test_for_each_node_runs_configured_body_for_each_item() -> None:
    worker = ItemEchoNodeHandler()
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "foreach",
            "name": "For Each",
            "nodes": [
                {
                    "id": "loop",
                    "type": "for_each",
                    "input": "plan.work_items",
                    "output": "reports",
                    "config": {"body": ["worker"]},
                },
                {"id": "worker", "type": "role", "output": "report"},
                {"id": "answer", "type": "answer", "output": "final_answer"},
            ],
            "edges": [{"from": "loop", "to": "answer"}],
        }
    )
    initial = state()
    initial["plan"] = {"work_items": [{"id": "a"}, {"id": "b"}]}

    result = run_async(
        WorkflowGraphExecutor(handlers={"role": worker, "answer": StaticNodeHandler("final_answer", "Done.")}).run(
            workflow, initial, deps(), event_sink()
        )
    )

    assert result.status == "done"
    assert result.state["reports"] == [{"id": "a"}, {"id": "b"}]


def test_while_node_runs_until_break_condition() -> None:
    increment = IncrementNodeHandler()
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "while",
            "name": "While",
            "nodes": [
                {
                    "id": "loop",
                    "type": "while",
                    "output": "iterations",
                    "break_when": "counter >= 2",
                    "config": {"body": ["increment"], "max_iterations": 4},
                },
                {"id": "increment", "type": "role", "output": "counter"},
                {"id": "answer", "type": "answer", "output": "final_answer"},
            ],
            "edges": [{"from": "loop", "to": "answer"}],
        }
    )
    initial = state()
    initial["counter"] = 0

    result = run_async(
        WorkflowGraphExecutor(handlers={"role": increment, "answer": StaticNodeHandler("final_answer", "Done.")}).run(
            workflow, initial, deps(), event_sink()
        )
    )

    assert result.status == "done"
    assert result.state["counter"] == 2
    assert result.state["iterations"] == [1, 2]


def test_pause_node_stops_mid_workflow_with_prompt() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "pause",
            "name": "Pause",
            "nodes": [
                {"id": "start", "type": "role", "output": "plan"},
                {"id": "ask", "type": "pause", "prompt": "Which source should I use?", "output": "pause"},
                {"id": "answer", "type": "answer", "output": "final_answer"},
            ],
            "edges": [{"from": "start", "to": "ask"}, {"from": "ask", "to": "answer"}],
        }
    )

    result = run_async(
        WorkflowGraphExecutor(handlers={"role": StaticNodeHandler("plan", {"summary": "Plan"})}).run(
            workflow, state(), deps(), event_sink()
        )
    )

    assert result.status == "needs_user"
    assert result.state["pause"]["prompt"] == "Which source should I use?"
    assert "answer" not in result.state["node_results"]


def test_judge_needs_user_routes_to_pause_node() -> None:
    handlers = {
        "role": StaticNodeHandler("plan", {"summary": "Plan", "work_items": [{"id": "main"}]}),
        "worker_pool": StaticNodeHandler("worker_reports", []),
        "reviewer": StaticNodeHandler("review", {"status": "approved"}),
        "judge": StaticNodeHandler(
            "decision",
            {"status": "needs_user", "reason": "Which source should I use?", "feedback": ["Pick docs or code."]},
        ),
    }
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "needs-user-pause",
            "name": "Needs User Pause",
            "nodes": [
                {"id": "orchestrator", "type": "role", "output": "plan"},
                {"id": "workers", "type": "worker_pool", "output": "worker_reports"},
                {"id": "reviewer", "type": "reviewer", "output": "review"},
                {"id": "judge", "type": "judge", "output": "decision"},
                {"id": "ask_user", "type": "pause", "input": ["decision"], "output": "pause"},
                {"id": "answer", "type": "answer", "output": "final_answer"},
            ],
            "edges": [
                {"from": "orchestrator", "to": "workers"},
                {"from": "workers", "to": "reviewer"},
                {"from": "reviewer", "to": "judge"},
                {"from": "judge", "to": "ask_user", "when": "decision.status == 'needs_user'"},
                {"from": "ask_user", "to": "orchestrator"},
                {"from": "judge", "to": "answer", "when": "decision.status == 'done'"},
            ],
        }
    )

    result = run_async(WorkflowGraphExecutor(handlers=handlers).run(workflow, state(), deps(), event_sink()))

    assert result.status == "needs_user"
    assert result.state["pause"]["node"] == "ask_user"
    assert "Which source should I use?" in result.state["pause"]["prompt"]
    assert "Pick docs or code." in result.state["pause"]["prompt"]
    assert "answer" not in result.state["node_results"]


def test_workflow_node_runs_referenced_subworkflow(monkeypatch: pytest.MonkeyPatch) -> None:
    child = WorkflowDefinition.model_validate(
        {"id": "child", "name": "Child", "nodes": [{"id": "child_answer", "type": "answer", "output": "final_answer"}]}
    )

    def fake_get_workflow(workflow_id: str, mode: str | None = None) -> WorkflowDefinition | None:
        del mode
        return child if workflow_id == "child" else None

    monkeypatch.setattr("app.workflows.presets.get_workflow", fake_get_workflow)
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "parent",
            "name": "Parent",
            "nodes": [
                {"id": "sub", "type": "workflow", "ref": "child", "output": "child_result"},
                {"id": "answer", "type": "answer", "output": "final_answer"},
            ],
            "edges": [{"from": "sub", "to": "answer"}],
        }
    )

    result = run_async(
        WorkflowGraphExecutor(handlers={"answer": StaticNodeHandler("final_answer", "Child done.")}).run(
            workflow, state(), deps(), event_sink()
        )
    )

    assert result.status == "done"
    assert result.state["child_result"]["final_answer"] == "Child done."


def test_tool_agent_node_uses_inline_agentic_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeAgenticRunner:
        def __init__(self, ollama: Any) -> None:
            self.ollama = ollama

        async def run_inline(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return {"status": "success", "summary": kwargs["title"], "tool_results": [{"success": True}], "error": ""}

    monkeypatch.setattr("app.agentic_runner.AgenticRunner", FakeAgenticRunner)
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "tool-agent",
            "name": "Tool Agent",
            "nodes": [
                {
                    "id": "research",
                    "type": "tool_agent",
                    "title": "Research",
                    "input": ["user_message"],
                    "output": "research_result",
                    "prompt": "Use approved tools to verify the current facts.",
                },
                {"id": "answer", "type": "answer", "output": "final_answer"},
            ],
            "edges": [{"from": "research", "to": "answer"}],
        }
    )

    result = run_async(WorkflowGraphExecutor().run(workflow, state(), deps(), event_sink()))

    assert result.status == "done"
    assert result.state["research_result"]["status"] == "success"
    assert calls[-1]["prompt"] == "Use approved tools to verify the current facts."
    assert calls[-1]["context"] == {"user_message": "Please handle this"}


class StaticNodeHandler:
    def __init__(self, output_name: str, output: Any, status: str = "done") -> None:
        self.output_name = output_name
        self.output = output
        self.status = status

    async def run(
        self,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        resolver: NodeInputResolver,
    ) -> NodeResult:
        return NodeResult(node_id=node.id, status=self.status, output=self.output)


class CountingNodeHandler:
    def __init__(self, output_name: str, factory) -> None:
        self.output_name = output_name
        self.factory = factory
        self.count = 0

    async def run(
        self,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        resolver: NodeInputResolver,
    ) -> NodeResult:
        self.count += 1
        return NodeResult(node_id=node.id, status="done", output=self.factory(self.count))


class SequenceNodeHandler:
    def __init__(self, output_name: str, outputs: list[Any]) -> None:
        self.output_name = output_name
        self.outputs = outputs
        self.index = 0

    async def run(
        self,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        resolver: NodeInputResolver,
    ) -> NodeResult:
        output = self.outputs[min(self.index, len(self.outputs) - 1)]
        self.index += 1
        status = str(output.get("status") or "done") if isinstance(output, dict) else "done"
        return NodeResult(node_id=node.id, status=status, output=output)


class FailingOnceNodeHandler:
    def __init__(self, output_name: str, output: Any = None) -> None:
        self.output_name = output_name
        self.output = output
        self.count = 0

    async def run(
        self,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        resolver: NodeInputResolver,
    ) -> NodeResult:
        self.count += 1
        if self.count == 1:
            raise RuntimeError("first attempt failed")
        return NodeResult(node_id=node.id, status="done", output=self.output)


class ItemEchoNodeHandler:
    async def run(
        self,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        resolver: NodeInputResolver,
    ) -> NodeResult:
        return NodeResult(node_id=node.id, status="done", output=state.get("item"))


class IncrementNodeHandler:
    async def run(
        self,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        state: WorkflowState,
        deps: WorkflowPhaseDeps,
        resolver: NodeInputResolver,
    ) -> NodeResult:
        return NodeResult(node_id=node.id, status="done", output=int(state.get("counter") or 0) + 1)


def workflow_definition(max_iterations: int = 2) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "id": "wf-test",
            "name": "Test Workflow",
            "max_iterations": max_iterations,
            "nodes": [
                {"id": "orchestrator", "type": "role", "output": "plan"},
                {"id": "workers", "type": "worker_pool", "output": "worker_reports"},
                {"id": "reviewer", "type": "reviewer", "output": "review"},
                {"id": "judge", "type": "judge", "output": "decision"},
                {"id": "answer", "type": "answer", "output": "final_answer"},
            ],
            "edges": [
                {"from": "orchestrator", "to": "workers"},
                {"from": "workers", "to": "reviewer"},
                {"from": "reviewer", "to": "judge"},
                {"from": "judge", "to": "workers", "when": "decision.status == 'retry'"},
                {"from": "judge", "to": "answer", "when": "decision.status == 'done'"},
                {"from": "judge", "to": "answer", "when": "decision.status == 'needs_user'"},
            ],
        }
    )


def state() -> WorkflowState:
    return {
        "chat_id": "chat-1",
        "mode": "chat",
        "user_message": "Please handle this",
        "workflow_run_id": "run-1",
        "workflow_scratch_path": "memory",
        "workflow_rounds": [],
        "effort": "medium",
        "effort_context": "effort",
        "workspace": "",
        "runtime_context": "runtime",
        "memory": "memory",
        "code_context": "",
        "agentic_context": "",
        "history": [],
    }


def deps() -> WorkflowPhaseDeps:
    scratchpad = InMemoryWorkflowScratchpad()
    return WorkflowPhaseDeps(
        settings=Settings(effort="medium"),
        ollama=FakeOllamaClient(),
        event_sink=WorkflowEventSink(),
        scratchpad=scratchpad,
    )


def event_sink() -> WorkflowEventSink:
    return WorkflowEventSink()


def run_async(coro):
    return asyncio.run(coro)


def test_compile_workflow_injects_auto_edges_from_io_input() -> None:
    """P1-9: an io.input node without explicit outbound edges auto-connects
    to every non-IO node that isn't already an edge target."""
    from app.workflows.executor import compile_workflow_for_execution

    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf",
            "name": "Boundary",
            "nodes": [
                {"id": "input", "type": "io", "config": {"boundary": "input"}, "output": "user_message"},
                {"id": "answer", "type": "answer", "output": "final_answer"},
            ],
            "edges": [],
        }
    )
    compiled = compile_workflow_for_execution(workflow)
    edge_pairs = [(edge.from_node, edge.to) for edge in compiled.edges]
    assert ("input", "answer") in edge_pairs
    # Original is untouched
    assert workflow.edges == []


def test_compile_workflow_is_noop_when_input_has_explicit_edges() -> None:
    from app.workflows.executor import compile_workflow_for_execution

    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf",
            "name": "Boundary",
            "nodes": [
                {"id": "input", "type": "io", "config": {"boundary": "input"}, "output": "user_message"},
                {"id": "answer", "type": "answer", "output": "final_answer"},
            ],
            "edges": [{"from": "input", "to": "answer"}],
        }
    )
    compiled = compile_workflow_for_execution(workflow)
    assert compiled.edges == workflow.edges
    # Same object reference would be best, but model_copy is also fine.


def test_compile_workflow_skips_pause_sources_when_collecting_targets() -> None:
    from app.workflows.executor import compile_workflow_for_execution

    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf",
            "name": "PauseSkip",
            "nodes": [
                {"id": "input", "type": "io", "config": {"boundary": "input"}, "output": "user_message"},
                {"id": "a", "type": "answer", "output": "final_answer"},
                {"id": "pause", "type": "pause"},
                {"id": "b", "type": "answer", "output": "final_answer"},
            ],
            # b is only reachable from pause — so the auto-edge from input
            # should still treat it as a valid root.
            "edges": [{"from": "pause", "to": "b"}],
        }
    )
    compiled = compile_workflow_for_execution(workflow)
    targets = sorted(edge.to for edge in compiled.edges if edge.from_node == "input")
    assert "a" in targets and "b" in targets
