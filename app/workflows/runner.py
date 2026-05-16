from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from app import database
from app.agentic_context import AgenticContextBuilder
from app.config import Settings, load_settings
from app.llm.ollama import OllamaClient
from app.models import MessageMode
from app.title_generation import clean_chat_title
from app.workflow_scratch import WorkflowScratchpad, default_workflow_scratchpad
from app.workflows.events import WorkflowEventSink
from app.workflows.models import WorkflowDefinition, WorkflowEvent, WorkflowResult
from app.workflows.phases import (
    WorkflowOllamaClient,
    WorkflowPhaseDeps,
    build_plan,
    final_answer,
    judge,
    markdown_data,
    note,
    replan_for_retry,
    review,
    run_workers,
)
from app.workflows.state import compact_workflow_state, initial_workflow_state, record_workflow_round


class WorkflowRunner:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        ollama: Optional[OllamaClient] = None,
        scratchpad: WorkflowScratchpad | None = None,
        final_ollama_factory: Callable[[], WorkflowOllamaClient] | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.ollama = ollama or OllamaClient(self.settings)
        self.scratchpad = scratchpad or default_workflow_scratchpad
        self.final_ollama_factory = final_ollama_factory

    async def run(
        self,
        workflow: WorkflowDefinition,
        chat_id: str,
        user_message: str,
        mode: MessageMode,
        on_event: Callable[[WorkflowEvent], None] | None = None,
    ) -> WorkflowResult:
        state = self._initial_state(chat_id, user_message, mode)
        events: list[WorkflowEvent] = []
        event_sink = WorkflowEventSink(events, on_event)
        deps = self._phase_deps(event_sink)

        event_sink.emit("start", "status", f"Workflow started: {workflow.name}")
        note(
            deps,
            state,
            f"Workflow started: {workflow.name}",
            markdown_data(
                {
                    "mode": mode,
                    "chat_id": chat_id,
                    "request": user_message,
                    "scratchpad": state["workflow_scratch_path"],
                }
            ),
        )

        if mode == "agentic":
            event_sink.emit("context", "status", "Preparing agentic tool context.")
            state["agentic_context"] = await AgenticContextBuilder(self.settings, self.ollama).build(user_message)
            note(deps, state, "Agentic tool context", state["agentic_context"] or "No tool context gathered.")

        plan = await build_plan(workflow, state, deps)
        state["plan"] = plan

        max_iterations = workflow.max_iterations
        reports = []
        review_result = {}
        decision = {"status": "done", "reason": ""}

        for iteration in range(1, max_iterations + 1):
            state["iteration"] = iteration
            if max_iterations > 1:
                event_sink.emit("loop", "status", f"Workflow iteration {iteration}/{max_iterations} started.")

            reports = await run_workers(workflow, state, deps)
            state["worker_reports"] = reports
            note(deps, state, f"Iteration {iteration} worker reports", markdown_data(reports))

            review_result = await review(workflow, state, deps)
            state["review"] = review_result
            note(deps, state, f"Iteration {iteration} review", markdown_data(review_result))

            decision = await judge(workflow, state, deps)
            state["decision"] = decision
            note(deps, state, f"Iteration {iteration} judge decision", markdown_data(decision))
            record_workflow_round(state, reports, review_result, decision)

            status = str(decision.get("status") or "done").strip().lower()
            if status != "retry":
                break
            if iteration >= max_iterations:
                decision["status"] = "done"
                decision["reason"] = (
                    "Retry limit reached. Synthesize the best user-facing answer from all available evidence, "
                    "including caveats and missing verification."
                )
                state["decision"] = decision
                event_sink.emit(
                    "judge",
                    "done",
                    "Retry limit reached; synthesizing final answer from available evidence.",
                )
                note(deps, state, "Retry limit reached", markdown_data(decision))
                break
            state["retry_feedback"] = decision.get("feedback") or decision.get("reason") or "Retry requested."
            event_sink.emit("judge", "retry", f"Judge requested another worker pass ({iteration + 1}/{max_iterations}).")
            state["plan"] = await replan_for_retry(workflow, state, deps)

        answer = await final_answer(workflow, state, deps)
        note(deps, state, "Final answer", answer)
        return WorkflowResult(
            workflow_id=workflow.id,
            answer=answer,
            status=str(decision.get("status") or "done"),
            events=events,
            state=compact_workflow_state(state, scratchpad=self.scratchpad),
        )

    def _initial_state(self, chat_id: str, user_message: str, mode: MessageMode) -> dict[str, object]:
        return initial_workflow_state(self.settings, chat_id, user_message, mode, scratchpad=self.scratchpad)

    def _phase_deps(self, event_sink: WorkflowEventSink) -> WorkflowPhaseDeps:
        return WorkflowPhaseDeps(
            settings=self.settings,
            ollama=self.ollama,
            event_sink=event_sink,
            scratchpad=self.scratchpad,
            update_chat_title=self._update_chat_title_from_plan,
            final_ollama_factory=self.final_ollama_factory or self._default_final_ollama,
        )

    def _default_final_ollama(self) -> WorkflowOllamaClient:
        return OllamaClient(self.settings, timeout=600.0)

    def _update_chat_title_from_plan(self, chat_id: str, plan: dict[str, object]) -> None:
        if not chat_id:
            return
        title = self._clean_chat_title(str(plan.get("title") or ""))
        if not title:
            title = self._clean_chat_title(str(plan.get("summary") or ""))
        if title:
            database.update_chat_title_if_default(chat_id, title)

    def _clean_chat_title(self, title: str) -> str:
        return clean_chat_title(title, max_words=7)
