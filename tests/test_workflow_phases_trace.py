from __future__ import annotations

from app.workflows.phases import build_plan, final_answer
from app.workflows.runtime_trace import InMemoryTracePersistence, TraceEmitter
from tests.fakes.ollama import FakeOllamaClient
from tests.test_workflow_phases import (
    StaticJsonOllamaClient,
    phase_deps as base_phase_deps,
    plan_payload,
    run_async,
    workflow_definition,
    workflow_state,
)
from app.workflow_scratch import InMemoryWorkflowScratchpad


def _deps_with_trace(client, scratchpad):
    persistence = InMemoryTracePersistence()
    deps = base_phase_deps(client, scratchpad)
    deps.trace = TraceEmitter(run_id="run-1", workflow_id="wf-test", persistence=persistence)
    return deps, persistence


def test_role_call_via_build_plan_emits_llm_call_event() -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    client = StaticJsonOllamaClient(plan_payload())
    deps, persistence = _deps_with_trace(client, scratchpad)

    run_async(build_plan(workflow_definition(), state, deps))

    llm_calls = [event for event in persistence.events if event.type == "llm_call"]
    assert len(llm_calls) == 1
    payload = llm_calls[0].payload
    assert llm_calls[0].node_id == "orchestrator"
    assert payload["model"]  # non-empty model id from settings
    assert isinstance(payload["prompt"], list) and payload["prompt"][0]["role"] == "system"
    assert "Fake plan" in payload["response"]
    assert payload["tokens_in"] is None and payload["tokens_out"] is None  # non-streaming has no token counts
    assert isinstance(payload["duration_ms"], int) and payload["duration_ms"] >= 0


def test_role_call_without_trace_does_not_break() -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    client = StaticJsonOllamaClient(plan_payload())
    deps = base_phase_deps(client, scratchpad)  # no trace

    plan = run_async(build_plan(workflow_definition(), state, deps))

    assert plan["title"] == "Fake plan"


def test_final_answer_stream_emits_llm_call_with_token_counts() -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    state["decision"] = {"status": "done", "reason": "All good."}
    client = FakeOllamaClient(stream_chunks=["Final ", "answer."])
    deps, persistence = _deps_with_trace(client, scratchpad)

    answer = run_async(final_answer(workflow_definition(), state, deps))

    assert answer == "Final answer."
    llm_calls = [event for event in persistence.events if event.type == "llm_call"]
    assert len(llm_calls) == 1
    payload = llm_calls[0].payload
    assert payload["response"] == "Final answer."
    # FakeOllamaClient.stream_payload yields a done event with eval_count = len(stream_chunks) and prompt_eval_count = 1
    assert payload["tokens_in"] == 1
    assert payload["tokens_out"] == 2
    assert llm_calls[0].node_id == "answer"


def test_final_answer_needs_user_does_not_emit_llm_call() -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    state["decision"] = {"status": "needs_user", "reason": "Need more info.", "feedback": ["Which file?"]}
    client = FakeOllamaClient()
    deps, persistence = _deps_with_trace(client, scratchpad)

    run_async(final_answer(workflow_definition(), state, deps))

    assert all(event.type != "llm_call" for event in persistence.events)
