from __future__ import annotations

import asyncio
import json
from typing import Any

from app.config import Settings
from app.workflow_scratch import InMemoryWorkflowScratchpad
from app.workflows.events import WorkflowEventSink
from app.workflows.models import WorkflowDefinition
from app.workflows.phases import (
    WorkflowPhaseDeps,
    build_plan,
    final_answer,
    judge,
    replan_for_retry,
    review,
    run_workers,
)
from app.workflows.state import WorkflowState
from tests.fakes.ollama import FakeOllamaClient


def test_build_plan_phase_uses_fake_ollama_and_records_note() -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    client = StaticJsonOllamaClient(plan_payload())
    title_updates = []
    deps = phase_deps(client, scratchpad, update_chat_title=lambda chat_id, plan: title_updates.append((chat_id, plan)))

    plan = run_async(build_plan(workflow_definition(), state, deps))

    assert plan["title"] == "Fake plan"
    assert plan["work_items"][0]["id"] == "main"
    assert plan["complexity"] == "low"
    assert plan["recommended_workers"] == 1
    assert title_updates[0][0] == "chat-1"
    assert deps.event_sink.events[-1].message == "Orchestrator created 1 work item(s)."
    assert "Initial workflow plan" in scratchpad.read_notes("run-1")
    assert client.chat_payload_calls[-1]["response_format"] == "json"


def test_replan_for_retry_phase_includes_retry_context() -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    state["retry_feedback"] = ["Tighten the answer"]
    client = StaticJsonOllamaClient(plan_payload())
    deps = phase_deps(client, scratchpad)

    plan = run_async(replan_for_retry(workflow_definition(), state, deps))

    assert plan["summary"] == "Fake workflow plan."
    assert "Retry workflow plan" in scratchpad.read_notes("run-1")
    payload = json.loads(client.chat_payload_calls[-1]["messages"][1]["content"])
    assert payload["retry_feedback"] == ["Tighten the answer"]


def test_run_workers_phase_returns_individual_reports(fake_ollama) -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    state["plan"] = {
        "work_items": [
            {"id": "alpha", "title": "Alpha", "instructions": "Do alpha"},
            {"id": "beta", "title": "Beta", "instructions": "Do beta"},
        ]
    }
    fake_ollama.response_text = "worker report"
    deps = phase_deps(fake_ollama, scratchpad)

    reports = run_async(run_workers(workflow_definition(), state, deps))

    assert [report["id"] for report in reports] == ["alpha", "beta"]
    assert all(report["content"] == "worker report" for report in reports)
    assert deps.event_sink.events[-1].message == "Worker pool completed 2 report(s)."
    assert fake_ollama.chat_payload_calls[-1]["response_format"] is None


def test_run_workers_phase_uses_planner_recommended_parallelism(fake_ollama) -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    state["plan"] = {
        "recommended_workers": 1,
        "work_items": [
            {"id": "alpha", "title": "Alpha", "instructions": "Do alpha"},
            {"id": "beta", "title": "Beta", "instructions": "Do beta"},
        ],
    }
    fake_ollama.response_text = "worker report"
    deps = phase_deps(fake_ollama, scratchpad)

    reports = run_async(run_workers(workflow_definition(), state, deps))

    assert [report["worker"] for report in reports] == ["worker-1", "worker-1"]
    status = next(
        event.message for event in deps.event_sink.events if event.node == "workers" and event.type == "status"
    )
    assert "recommended workers 1" in status
    assert "max worker instances 2" in status
    assert "active parallel 1" in status


def test_review_phase_parses_json_review(fake_ollama) -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    state["worker_reports"] = [{"id": "main", "title": "Main", "content": "done"}]
    deps = phase_deps(fake_ollama, scratchpad)

    result = run_async(review(workflow_definition(), state, deps))

    assert result["status"] == "approved"
    assert result["summary"] == "Fake review approved."
    assert deps.event_sink.events[-1].message == "Reviewer status: approved."


def test_judge_phase_normalizes_unknown_status() -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    client = StaticJsonOllamaClient({"status": "surprised", "reason": "Unexpected", "feedback": []})
    deps = phase_deps(client, scratchpad)

    decision = run_async(judge(workflow_definition(), state, deps))

    assert decision["status"] == "done"
    assert deps.event_sink.events[-1].message == "Judge decision: done."


def test_final_answer_phase_streams_tokens_to_callback(fake_ollama) -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    state["decision"] = {"status": "done", "reason": "Complete"}
    fake_ollama.stream_chunks = ["Final ", "answer."]
    callbacks = []
    deps = phase_deps(fake_ollama, scratchpad, callback=callbacks.append, final_ollama_factory=lambda: fake_ollama)

    answer = run_async(final_answer(workflow_definition(), state, deps))

    assert answer == "Final answer."
    assert state["final_answer_streamed"] is True
    assert [event.message for event in callbacks if event.type == "token"] == ["Final ", "answer."]
    assert [event.type for event in deps.event_sink.events] == ["status"]


def test_build_plan_falls_back_when_response_is_not_json() -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    client = RawTextOllamaClient("not actually json")
    deps = phase_deps(client, scratchpad)

    plan = run_async(build_plan(workflow_definition(), state, deps))

    assert plan["title"] == "Handle Request"
    assert plan["work_items"][0]["id"] == "main"
    assert plan["work_items"][0]["instructions"] == "Please handle this"


def test_replan_for_retry_falls_back_on_invalid_json() -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    state["retry_feedback"] = ["Try again"]
    client = RawTextOllamaClient("{ not valid json")
    deps = phase_deps(client, scratchpad)

    plan = run_async(replan_for_retry(workflow_definition(), state, deps))

    assert plan["title"] == "Handle Request"
    assert plan["work_items"][0]["id"] == "main"


def test_review_phase_falls_back_when_response_is_plain_text() -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    client = RawTextOllamaClient("Needs more work please.")
    deps = phase_deps(client, scratchpad)

    result = run_async(review(workflow_definition(), state, deps))

    assert result["status"] == "changes_requested"
    assert result["summary"] == "Needs more work please."
    assert deps.event_sink.events[-1].message == "Reviewer status: changes_requested."


def test_judge_phase_falls_back_when_response_is_plain_text() -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    client = RawTextOllamaClient("All looks good.")
    deps = phase_deps(client, scratchpad)

    decision = run_async(judge(workflow_definition(), state, deps))

    assert decision["status"] == "done"
    assert decision["reason"] == "All looks good."


def test_final_answer_skips_streaming_when_decision_needs_user() -> None:
    scratchpad = InMemoryWorkflowScratchpad()
    state = workflow_state(scratchpad)
    state["decision"] = {
        "status": "needs_user",
        "reason": "Need clarification on the target",
        "feedback": ["Which file?", ""],
    }
    client = FakeOllamaClient()
    deps = phase_deps(client, scratchpad, final_ollama_factory=lambda: client)

    answer = run_async(final_answer(workflow_definition(), state, deps))

    assert answer.startswith("Need clarification on the target")
    assert "- Which file?" in answer
    assert client.stream_payload_calls == []


class StaticJsonOllamaClient(FakeOllamaClient):
    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__()
        self.payload = payload

    async def chat_payload(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        response_format: str | dict[str, Any] | None = None,
    ) -> str:
        self.chat_payload_calls.append({"messages": messages, "model": model, "response_format": response_format})
        return json.dumps(self.payload)


class RawTextOllamaClient(FakeOllamaClient):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text

    async def chat_payload(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        response_format: str | dict[str, Any] | None = None,
    ) -> str:
        self.chat_payload_calls.append({"messages": messages, "model": model, "response_format": response_format})
        return self.text


def workflow_definition() -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "id": "wf-test",
            "name": "Test Workflow",
            "nodes": [
                {"id": "orchestrator", "type": "role", "role": "ORCHESTRATOR", "expects_json": True, "max_items": 2},
                {"id": "workers", "type": "worker_pool", "role": "WORKER", "worker_instances": 2, "max_parallel": 2},
                {"id": "reviewer", "type": "reviewer", "role": "REVIEWER", "expects_json": True},
                {"id": "judge", "type": "judge", "role": "JUDGE", "expects_json": True},
            ],
        }
    )


def plan_payload() -> dict[str, Any]:
    return {
        "title": "Fake plan",
        "summary": "Fake workflow plan.",
        "complexity": "low",
        "recommended_workers": 1,
        "acceptance_criteria": ["Return a deterministic answer."],
        "work_items": [
            {"id": "main", "title": "Answer", "instructions": "Return a deterministic answer.", "owned_paths": []}
        ],
    }


def workflow_state(scratchpad: InMemoryWorkflowScratchpad) -> WorkflowState:
    return {
        "chat_id": "chat-1",
        "mode": "chat",
        "user_message": "Please handle this",
        "workflow_run_id": "run-1",
        "workflow_scratch_path": str(scratchpad.path()),
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


def phase_deps(
    ollama, scratchpad: InMemoryWorkflowScratchpad, *, callback=None, update_chat_title=None, final_ollama_factory=None
) -> WorkflowPhaseDeps:
    return WorkflowPhaseDeps(
        settings=Settings(effort="medium"),
        ollama=ollama,
        event_sink=WorkflowEventSink(callback=callback),
        scratchpad=scratchpad,
        update_chat_title=update_chat_title or (lambda _chat_id, _plan: None),
        final_ollama_factory=final_ollama_factory,
    )


def run_async(coro):
    return asyncio.run(coro)
