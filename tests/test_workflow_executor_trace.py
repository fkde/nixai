from __future__ import annotations

from typing import Any

from app.workflows.executor import WorkflowGraphExecutor
from app.workflows.models import WorkflowDefinition, WorkflowNode
from app.workflows.nodes import NodeResult
from app.workflows.phases import WorkflowPhaseDeps
from app.workflows.resolver import NodeInputResolver
from app.workflows.runtime_trace import InMemoryTracePersistence, TraceEmitter
from app.workflows.state import WorkflowState
from tests.test_workflow_executor import (
    ItemEchoNodeHandler,
    StaticNodeHandler,
    deps,
    event_sink,
    run_async,
    state,
    workflow_definition,
)


def _emitter() -> tuple[TraceEmitter, InMemoryTracePersistence]:
    persistence = InMemoryTracePersistence()
    emitter = TraceEmitter(run_id="run-1", workflow_id="wf", persistence=persistence)
    return emitter, persistence


def test_linear_run_emits_started_finished_for_every_node_and_edge_events() -> None:
    handlers = {
        "role": StaticNodeHandler("plan", {"summary": "Plan", "work_items": [{"id": "main"}]}),
        "worker_pool": StaticNodeHandler("worker_reports", [{"id": "main", "content": "Report"}]),
        "reviewer": StaticNodeHandler("review", {"status": "approved", "summary": "ok"}),
        "judge": StaticNodeHandler("decision", {"status": "done", "reason": "Complete"}),
        "answer": StaticNodeHandler("final_answer", "Final answer."),
    }
    emitter, persistence = _emitter()

    result = run_async(
        WorkflowGraphExecutor(handlers=handlers).run(
            workflow_definition(), state(), deps(), event_sink(), trace=emitter
        )
    )

    assert result.status == "done"
    types_by_node = [(event.type, event.node_id) for event in persistence.events]
    # Every executed node has a started+finished pair
    started = [node_id for kind, node_id in types_by_node if kind == "node_started"]
    finished = [node_id for kind, node_id in types_by_node if kind == "node_finished"]
    assert started == ["orchestrator", "workers", "reviewer", "judge", "answer"]
    assert finished == started
    # Edge events fire after every non-terminal node
    edges = [event for event in persistence.events if event.type == "edge_traversed"]
    assert {(edge.payload["from"], edge.payload["to"]) for edge in edges} == {
        ("orchestrator", "workers"),
        ("workers", "reviewer"),
        ("reviewer", "judge"),
        ("judge", "answer"),
    }
    # No node_failed in a clean run
    assert all(event.type != "node_failed" for event in persistence.events)


def test_node_finished_payload_contains_snapshot_and_duration() -> None:
    handlers = {
        "role": StaticNodeHandler("plan", {"summary": "Plan", "work_items": [{"id": "main"}]}),
        "worker_pool": StaticNodeHandler("worker_reports", [{"id": "main"}]),
        "reviewer": StaticNodeHandler("review", {"status": "approved"}),
        "judge": StaticNodeHandler("decision", {"status": "done"}),
        "answer": StaticNodeHandler("final_answer", "Final."),
    }
    emitter, persistence = _emitter()

    run_async(
        WorkflowGraphExecutor(handlers=handlers).run(
            workflow_definition(), state(), deps(), event_sink(), trace=emitter
        )
    )

    answer_finished = next(
        event for event in persistence.events if event.type == "node_finished" and event.node_id == "answer"
    )
    assert answer_finished.payload["output_snapshot"] == "Final."
    assert answer_finished.payload["status"] == "done"
    assert isinstance(answer_finished.payload["duration_ms"], int)
    assert answer_finished.payload["duration_ms"] >= 0


def test_failing_node_emits_node_failed_and_only_error_edge() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf",
            "name": "Failing",
            "nodes": [
                {"id": "start", "type": "role", "output": "plan"},
                {"id": "answer", "type": "answer", "output": "final_answer"},
                {"id": "rescue", "type": "answer", "output": "final_answer"},
            ],
            "edges": [
                {"from": "start", "to": "answer"},
                {"from": "start", "to": "rescue", "when": "error"},
            ],
        }
    )

    class FailingHandler:
        async def run(self, workflow, node, state, deps, resolver):
            return NodeResult(node_id=node.id, status="failed", error="boom")

    handlers = {
        "role": FailingHandler(),
        "answer": StaticNodeHandler("final_answer", "Saved."),
    }
    emitter, persistence = _emitter()

    run_async(WorkflowGraphExecutor(handlers=handlers).run(workflow, state(), deps(), event_sink(), trace=emitter))

    failed_events = [event for event in persistence.events if event.type == "node_failed"]
    assert [event.node_id for event in failed_events] == ["start"]
    assert failed_events[0].payload["error"] == "boom"
    # only the error-edge is reported as traversed, not the happy-path edge
    edges = [event for event in persistence.events if event.type == "edge_traversed"]
    assert [(edge.payload["from"], edge.payload["to"], edge.payload["when"]) for edge in edges] == [
        ("start", "rescue", "error"),
    ]


def test_for_each_iterations_share_parent_step_id_of_for_each_node() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf",
            "name": "ForEach",
            "nodes": [
                {"id": "iter", "type": "for_each", "input": ["items"], "config": {"body": ["echo"]}, "output": "results"},
                {"id": "echo", "type": "echo"},
                {"id": "answer", "type": "answer", "output": "final_answer"},
            ],
            "edges": [
                {"from": "iter", "to": "answer"},
            ],
        }
    )
    handlers = {
        "echo": ItemEchoNodeHandler(),
        "answer": StaticNodeHandler("final_answer", "done"),
    }
    initial = state()
    initial["items"] = ["a", "b", "c"]
    emitter, persistence = _emitter()

    run_async(WorkflowGraphExecutor(handlers=handlers).run(workflow, initial, deps(), event_sink(), trace=emitter))

    iter_started = next(event for event in persistence.events if event.type == "node_started" and event.node_id == "iter")
    body_started = [
        event for event in persistence.events if event.type == "node_started" and event.node_id == "echo"
    ]
    assert len(body_started) == 3
    # Every body execution inherits the for_each's started step_id as parent
    assert all(event.parent_step_id == iter_started.step_id for event in body_started)
    # The iter's own started/finished events sit at the root (no parent)
    assert iter_started.parent_step_id is None


def test_trace_is_optional_executor_runs_without_it() -> None:
    handlers = {
        "role": StaticNodeHandler("plan", {"summary": "Plan", "work_items": [{"id": "x"}]}),
        "worker_pool": StaticNodeHandler("worker_reports", [{"id": "x"}]),
        "reviewer": StaticNodeHandler("review", {"status": "approved"}),
        "judge": StaticNodeHandler("decision", {"status": "done"}),
        "answer": StaticNodeHandler("final_answer", "ok"),
    }

    result = run_async(
        WorkflowGraphExecutor(handlers=handlers).run(workflow_definition(), state(), deps(), event_sink())
    )

    assert result.status == "done"


def test_input_snapshot_captures_referenced_state_keys() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf",
            "name": "Snap",
            "nodes": [
                {"id": "answer", "type": "answer", "input": ["greeting", "user_message"], "output": "final_answer"},
            ],
            "edges": [],
        }
    )
    handlers = {"answer": StaticNodeHandler("final_answer", "ok")}
    initial = state()
    initial["greeting"] = "hello"
    emitter, persistence = _emitter()

    run_async(WorkflowGraphExecutor(handlers=handlers).run(workflow, initial, deps(), event_sink(), trace=emitter))

    started = next(event for event in persistence.events if event.type == "node_started")
    assert started.payload["input_snapshot"] == {"greeting": "hello", "user_message": "Please handle this"}


def test_handler_emitted_events_inherit_node_started_as_parent() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf",
            "name": "Inherit",
            "nodes": [
                {"id": "answer", "type": "answer", "output": "final_answer"},
            ],
            "edges": [],
        }
    )
    emitter, persistence = _emitter()

    class HandlerEmittingChild:
        async def run(self, workflow, node, state, deps, resolver):
            # Simulate a child event emitted from inside a node handler.
            emitter.emit("llm_call", node_id=node.id, payload={"model": "fake"})
            return NodeResult(node_id=node.id, status="done", output="ok")

    handlers = {"answer": HandlerEmittingChild()}

    run_async(WorkflowGraphExecutor(handlers=handlers).run(workflow, state(), deps(), event_sink(), trace=emitter))

    started = next(event for event in persistence.events if event.type == "node_started")
    child = next(event for event in persistence.events if event.type == "llm_call")
    assert child.parent_step_id == started.step_id


def test_unknown_node_id_in_start_list_emits_node_failed() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf",
            "name": "Unknown",
            "nodes": [
                {"id": "answer", "type": "answer", "output": "final_answer"},
            ],
            "edges": [],
        }
    )
    handlers = {"answer": StaticNodeHandler("final_answer", "ok")}
    emitter, persistence = _emitter()

    run_async(
        WorkflowGraphExecutor(handlers=handlers).run(
            workflow, state(), deps(), event_sink(), start_node_ids=["ghost"], trace=emitter
        )
    )

    failed = [event for event in persistence.events if event.type == "node_failed" and event.node_id == "ghost"]
    assert failed, "unknown node should emit node_failed"
