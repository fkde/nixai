from __future__ import annotations

import json
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
from app.workflows.executor import WorkflowGraphExecutor
from app.workflows.models import WorkflowDefinition, WorkflowEvent, WorkflowResult
from app.workflows.phases import (
    WorkflowOllamaClient,
    WorkflowPhaseDeps,
    final_answer,
    markdown_data,
    note,
)
from app.workflows.state import compact_workflow_state, initial_workflow_state


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
        self._persist_started(workflow, chat_id, mode, state, events)

        if mode == "agentic":
            event_sink.emit("context", "status", "Preparing agentic tool context.")
            state["agentic_context"] = await AgenticContextBuilder(self.settings, self.ollama).build(user_message)
            note(deps, state, "Agentic tool context", state["agentic_context"] or "No tool context gathered.")

        if workflow.is_direct():
            state["decision"] = {"status": "done", "reason": "Direct workflow."}
            answer = await final_answer(workflow, state, deps)
            note(deps, state, "Final answer", answer)
            result = WorkflowResult(
                workflow_id=workflow.id,
                answer=answer,
                status="done",
                events=events,
                state=compact_workflow_state(state, scratchpad=self.scratchpad),
            )
            self._persist_finished(result, state)
            return result

        result = await WorkflowGraphExecutor().run(workflow, state, deps, event_sink)
        self._persist_finished(result, state)
        return result

    async def resume(
        self,
        workflow: WorkflowDefinition,
        state: dict[str, object],
        feedback: str = "",
        on_event: Callable[[WorkflowEvent], None] | None = None,
    ) -> WorkflowResult:
        events: list[WorkflowEvent] = []
        event_sink = WorkflowEventSink(events, on_event)
        deps = self._phase_deps(event_sink)
        pause = state.get("pause") if isinstance(state.get("pause"), dict) else {}
        paused_node = str((pause or {}).get("node") or state.get("current_node") or "").strip()
        if feedback.strip():
            state["resume_feedback"] = feedback.strip()
            state["user_feedback"] = feedback.strip()
            note(deps, state, "User resume feedback", feedback.strip())
        next_nodes = WorkflowGraphExecutor()._next_node_ids(workflow, paused_node, state) if paused_node else []
        if not next_nodes:
            return WorkflowResult(
                workflow_id=workflow.id,
                answer="This workflow run cannot be resumed because no continuation edge was found.",
                status="failed",
                events=events,
                state=compact_workflow_state(state, scratchpad=self.scratchpad),
            )
        event_sink.emit(paused_node, "resume", "Resuming workflow from paused node.")
        state.pop("pause", None)
        result = await WorkflowGraphExecutor().run(workflow, state, deps, event_sink, start_node_ids=next_nodes)
        self._persist_finished(result, state)
        return result

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

    def _persist_started(
        self,
        workflow: WorkflowDefinition,
        chat_id: str,
        mode: MessageMode,
        state: dict[str, object],
        events: list[WorkflowEvent],
    ) -> None:
        try:
            database.create_workflow_run(
                str(state.get("workflow_run_id") or ""),
                workflow_id=workflow.id,
                chat_id=chat_id,
                mode=mode,
                state_json=json.dumps(state, ensure_ascii=False, default=str),
                events_json=json.dumps([event.model_dump() for event in events], ensure_ascii=False),
            )
        except Exception:
            return

    def _persist_finished(self, result: WorkflowResult, state: dict[str, object]) -> None:
        run_id = str(state.get("workflow_run_id") or "")
        if not run_id:
            return
        pause = state.get("pause") if isinstance(state.get("pause"), dict) else {}
        current_node = str((pause or {}).get("node") or "")
        finished = result.status not in {"needs_user"}
        try:
            database.update_workflow_run(
                run_id,
                status=result.status if result.status in {"done", "failed", "needs_user"} else "failed",
                state_json=json.dumps(state, ensure_ascii=False, default=str),
                events_json=json.dumps([event.model_dump() for event in result.events], ensure_ascii=False),
                current_node=current_node,
                finished=finished,
            )
        except Exception:
            return
