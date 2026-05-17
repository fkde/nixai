from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Optional

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
from app.workflows.nodes import NodeResult
from app.workflows.runtime_trace import TraceEmitter, default_emitter
from app.workflows.phases import (
    WorkflowOllamaClient,
    WorkflowPhaseDeps,
    final_answer,
    markdown_data,
    note,
)
from app.workflows.state import compact_workflow_state, initial_workflow_state


logger = logging.getLogger(__name__)


class WorkflowRunner:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        ollama: Optional[OllamaClient] = None,
        scratchpad: WorkflowScratchpad | None = None,
        final_ollama_factory: Callable[[], WorkflowOllamaClient] | None = None,
        trace_factory: Callable[[str, str], TraceEmitter] | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.ollama = ollama or OllamaClient(self.settings)
        self.scratchpad = scratchpad or default_workflow_scratchpad
        self.final_ollama_factory = final_ollama_factory
        self.trace_factory = trace_factory or default_emitter

    async def run(
        self,
        workflow: WorkflowDefinition,
        chat_id: str,
        user_message: str,
        mode: MessageMode,
        on_event: Callable[[WorkflowEvent], None] | None = None,
        on_run_started: Callable[[str], None] | None = None,
    ) -> WorkflowResult:
        state = self._initial_state(chat_id, user_message, mode)
        if on_run_started is not None:
            run_id = str(state.get("workflow_run_id") or "")
            if run_id:
                try:
                    on_run_started(run_id)
                except Exception:
                    logger.warning("on_run_started callback raised run_id=%s", run_id, exc_info=True)
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
        self._persist_started(workflow, chat_id, mode, state, events, initial_input=user_message)
        trace = self._build_trace(workflow.id, state)
        deps.trace = trace
        if trace is not None:
            trace.emit(
                "run_started",
                node_id="workflow",
                payload={"initial_input": user_message, "mode": mode, "workflow_name": workflow.name},
            )

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
            self._emit_run_stopped(trace, result)
            return result

        result = await WorkflowGraphExecutor().run(workflow, state, deps, event_sink, trace=trace)
        self._persist_finished(result, state)
        self._emit_run_stopped(trace, result)
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
        trace = self._build_trace(workflow.id, state)
        deps.trace = trace
        result = await WorkflowGraphExecutor().run(
            workflow, state, deps, event_sink, start_node_ids=next_nodes, trace=trace
        )
        self._persist_finished(result, state)
        self._emit_run_stopped(trace, result)
        return result

    async def fork(
        self,
        workflow: WorkflowDefinition,
        original_run: Any,
        *,
        from_step_id: str,
        edited_output: Any,
        label: str = "",
        on_event: Callable[[WorkflowEvent], None] | None = None,
    ) -> WorkflowResult:
        source_node_id = from_step_id.strip()
        node = workflow.node(source_node_id)
        if node is None:
            raise ValueError("Fork source step was not found in the workflow.")
        if node.type in {"for_each", "while"}:
            raise ValueError("Forking from container nodes is not supported yet.")

        rows = database.list_trace_events(original_run.id)
        parsed_events = [self._trace_row_to_event(row) for row in rows]
        source_event = self._find_fork_source_event(parsed_events, source_node_id)
        if source_event is None:
            raise ValueError("Fork source step has no completed output snapshot.")
        if source_event["payload"].get("output_snapshot_truncated"):
            raise ValueError("Cannot fork from a truncated output snapshot.")

        source_seq = int(source_event["seq"])
        replay_events = [event for event in parsed_events if int(event["seq"]) <= source_seq]
        for event in replay_events:
            if event["type"] == "node_finished" and event["payload"].get("output_snapshot_truncated"):
                raise ValueError("Cannot replay a run that contains truncated output snapshots before the fork point.")

        state = self._initial_state(original_run.chat_id, original_run.initial_input or "", original_run.mode)
        state["fork_of_run_id"] = original_run.id
        state["fork_at_step_id"] = source_node_id
        if label.strip():
            state["fork_label"] = label.strip()[:120]

        events: list[WorkflowEvent] = []
        event_sink = WorkflowEventSink(events, on_event)
        deps = self._phase_deps(event_sink)
        executor = WorkflowGraphExecutor()
        self._replay_state_until(workflow, state, deps, event_sink, executor, replay_events)
        self._apply_fork_output(workflow, state, deps, event_sink, executor, source_node_id, edited_output)
        replay_events = [
            self._edited_fork_trace_event(event, source_seq, edited_output) for event in replay_events
        ]

        next_nodes = executor._next_node_ids(workflow, source_node_id, state)
        if not next_nodes:
            raise ValueError("Fork source step has no continuation edge.")

        self._persist_started(
            workflow,
            original_run.chat_id,
            original_run.mode,
            state,
            events,
            initial_input=original_run.initial_input or "",
            fork_of_run_id=original_run.id,
            fork_at_step_id=source_node_id,
        )
        trace = self._build_trace(workflow.id, state)
        deps.trace = trace
        if trace is not None:
            trace.emit(
                "run_started",
                node_id="workflow",
                payload={
                    "initial_input": original_run.initial_input or "",
                    "mode": original_run.mode,
                    "workflow_name": workflow.name,
                    "fork_of": {"run_id": original_run.id, "step_id": source_node_id},
                },
            )
            self._copy_fork_trace_events(trace, replay_events)

        result = await executor.run(workflow, state, deps, event_sink, start_node_ids=next_nodes, trace=trace)
        self._persist_finished(result, state)
        self._emit_run_stopped(trace, result)
        result.state["workflow_run_id"] = state.get("workflow_run_id")
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
        *,
        initial_input: str = "",
        fork_of_run_id: str | None = None,
        fork_at_step_id: str | None = None,
    ) -> None:
        try:
            database.create_workflow_run(
                str(state.get("workflow_run_id") or ""),
                workflow_id=workflow.id,
                chat_id=chat_id,
                mode=mode,
                state_json=json.dumps(state, ensure_ascii=False, default=str),
                events_json=json.dumps([event.model_dump() for event in events], ensure_ascii=False),
                initial_input=initial_input,
                fork_of_run_id=fork_of_run_id,
                fork_at_step_id=fork_at_step_id,
            )
        except Exception:
            logger.warning(
                "workflow_run persistence failed (start) workflow_id=%s chat_id=%s",
                workflow.id,
                chat_id,
                exc_info=True,
            )

    def _trace_row_to_event(self, row: Any) -> dict[str, Any]:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            payload = {}
        return {
            "seq": row["seq"],
            "step_id": row["step_id"],
            "parent_step_id": row["parent_step_id"],
            "node_id": row["node_id"],
            "type": row["type"],
            "ts": row["ts"],
            "payload": payload if isinstance(payload, dict) else {},
        }

    def _find_fork_source_event(self, events: list[dict[str, Any]], source_node_id: str) -> dict[str, Any] | None:
        for event in reversed(events):
            if event["node_id"] == source_node_id and event["type"] == "node_finished":
                return event
        return None

    def _replay_state_until(
        self,
        workflow: WorkflowDefinition,
        state: dict[str, object],
        deps: WorkflowPhaseDeps,
        event_sink: WorkflowEventSink,
        executor: WorkflowGraphExecutor,
        events: list[dict[str, Any]],
    ) -> None:
        for event in events:
            if event["type"] != "node_finished":
                continue
            node_id = str(event["node_id"] or "")
            node = workflow.node(node_id)
            if node is None:
                continue
            payload = event["payload"]
            result = NodeResult(
                node_id=node_id,
                status=str(payload.get("status") or "done"),  # type: ignore[arg-type]
                output=payload.get("output_snapshot"),
                summary=str(payload.get("summary") or ""),
            )
            executor._store_result(state, result)
            executor._apply_compatible_state(node.output, result, state, deps, workflow, event_sink)

    def _apply_fork_output(
        self,
        workflow: WorkflowDefinition,
        state: dict[str, object],
        deps: WorkflowPhaseDeps,
        event_sink: WorkflowEventSink,
        executor: WorkflowGraphExecutor,
        source_node_id: str,
        edited_output: Any,
    ) -> None:
        node = workflow.node(source_node_id)
        if node is None:
            return
        result = NodeResult(node_id=source_node_id, status="done", output=edited_output, summary="Fork output edited.")
        executor._store_result(state, result)
        executor._apply_compatible_state(node.output, result, state, deps, workflow, event_sink)

    def _copy_fork_trace_events(self, trace: TraceEmitter, events: list[dict[str, Any]]) -> None:
        step_map: dict[str, str] = {}
        for event in events:
            if event["type"] == "run_started":
                continue
            parent = event.get("parent_step_id")
            mapped_parent = step_map.get(str(parent)) if parent else None
            new_step_id = trace.emit(
                event["type"],
                node_id=str(event["node_id"] or "workflow"),
                payload=event["payload"],
                parent_step_id=mapped_parent,
            )
            if event["type"] == "node_started" and event.get("step_id"):
                step_map[str(event["step_id"])] = new_step_id

    def _edited_fork_trace_event(
        self, event: dict[str, Any], source_seq: int, edited_output: Any
    ) -> dict[str, Any]:
        if int(event["seq"]) != source_seq or event["type"] != "node_finished":
            return event
        updated = {**event, "payload": {**event["payload"]}}
        updated["payload"]["output_snapshot"] = edited_output
        updated["payload"]["output_snapshot_truncated"] = False
        updated["payload"]["summary"] = "Fork output edited."
        return updated

    def _build_trace(self, workflow_id: str, state: dict[str, object]) -> TraceEmitter | None:
        run_id = str(state.get("workflow_run_id") or "").strip()
        if not run_id:
            return None
        try:
            return self.trace_factory(run_id, workflow_id)
        except Exception:
            logger.warning("trace_emitter init failed run_id=%s", run_id, exc_info=True)
            return None

    def _emit_run_finished(self, trace: TraceEmitter | None, result: WorkflowResult) -> None:
        self._emit_run_stopped(trace, result)

    def _emit_run_stopped(self, trace: TraceEmitter | None, result: WorkflowResult) -> None:
        if trace is None:
            return
        if result.status == "paused":
            event_type = "run_paused"
        else:
            event_type = "run_failed" if result.status == "failed" else "run_finished"
        payload: dict[str, object] = {"status": result.status, "final_output": result.answer}
        trace.emit(event_type, node_id="workflow", payload=payload)
        # only close the bus when the run truly terminates; pause states stay open for resume
        if result.status in {"done", "failed"}:
            try:
                from app.workflows.run_bus import get_run_bus

                get_run_bus().close(trace.run_id)
            except Exception:
                logger.warning("run_bus close failed run_id=%s", trace.run_id, exc_info=True)

    def _persist_finished(self, result: WorkflowResult, state: dict[str, object]) -> None:
        run_id = str(state.get("workflow_run_id") or "")
        if not run_id:
            return
        pause = state.get("pause") if isinstance(state.get("pause"), dict) else {}
        current_node = str((pause or {}).get("node") or "")
        finished = result.status not in {"needs_user", "paused"}
        try:
            database.update_workflow_run(
                run_id,
                status=result.status if result.status in {"done", "failed", "needs_user", "paused"} else "failed",
                state_json=json.dumps(state, ensure_ascii=False, default=str),
                events_json=json.dumps([event.model_dump() for event in result.events], ensure_ascii=False),
                current_node=current_node,
                finished=finished,
            )
        except Exception:
            logger.warning(
                "workflow_run persistence failed (finish) run_id=%s status=%s",
                run_id,
                result.status,
                exc_info=True,
            )
