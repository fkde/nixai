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
from app.workflows.replay import ReplayScope, WorkflowReplayPlanner
from app.workflows.runtime_trace import TraceEmitter, default_emitter
from app.workflows.phases import WorkflowOllamaClient, WorkflowPhaseDeps, final_answer, markdown_data, note
from app.workflows.state import compact_workflow_state, initial_workflow_state


logger = logging.getLogger(__name__)

# Sentinel for "no edited output" so callers can pass None as a legitimate value.
_SENTINEL: Any = object()


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
        attachments: list[Any] | None = None,
        on_event: Callable[[WorkflowEvent], None] | None = None,
        on_run_started: Callable[[str], None] | None = None,
    ) -> WorkflowResult:
        state = self._initial_state(chat_id, user_message, mode, attachments=attachments)
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
        next_nodes = WorkflowGraphExecutor().next_node_ids(workflow, paused_node, state) if paused_node else []
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
        # `from_step_id` carries a node_id (legacy field name kept for the API
        # contract; the value has always been the node identifier).
        source_node_id = from_step_id.strip()
        node = workflow.node(source_node_id)
        if node is None:
            raise ValueError("Fork source step was not found in the workflow.")
        if node.type in {"for_each", "while"}:
            raise ValueError("Forking from container nodes is not supported yet.")

        parsed_events = self._load_parsed_trace(original_run.id)
        source_event = self._find_fork_source_event(parsed_events, source_node_id)
        if source_event is None:
            raise ValueError("Fork source step has no completed output snapshot.")
        if source_event["payload"].get("output_snapshot_truncated"):
            raise ValueError("Cannot fork from a truncated output snapshot.")

        source_seq = int(source_event["seq"])
        replay_events = [event for event in parsed_events if int(event["seq"]) <= source_seq]

        def resolve_start_nodes(state: dict[str, Any], executor: WorkflowGraphExecutor) -> list[str]:
            next_nodes = executor.next_node_ids(workflow, source_node_id, state)
            if not next_nodes:
                raise ValueError("Fork source step has no continuation edge.")
            return next_nodes

        return await self._execute_with_replay_prefix(
            workflow=workflow,
            original_run=original_run,
            fork_node_id=source_node_id,
            replay_events=replay_events,
            label=label,
            on_event=on_event,
            run_started_extras={"fork_of": {"run_id": original_run.id, "node_id": source_node_id}},
            resolve_start_nodes=resolve_start_nodes,
            edited_output=edited_output,
            edited_at_seq=source_seq,
        )

    async def replay(
        self,
        workflow: WorkflowDefinition,
        original_run: Any,
        *,
        start_node_id: str,
        scope: ReplayScope = "downstream",
        label: str = "",
        on_event: Callable[[WorkflowEvent], None] | None = None,
    ) -> WorkflowResult:
        start_node_id = start_node_id.strip()
        if scope != "downstream":
            raise ValueError("Only downstream replay execution is supported for now.")
        if workflow.node(start_node_id) is None:
            raise ValueError("Replay start node was not found in the workflow.")

        parsed_events = self._load_parsed_trace(original_run.id)
        node_states = [database.node_state_row_to_dict(row) for row in database.list_node_states(original_run.id)]
        plan = WorkflowReplayPlanner().build_plan(
            workflow=workflow,
            run_id=original_run.id,
            start_node_id=start_node_id,
            scope=scope,
            events=parsed_events,
            node_states=node_states,
        )
        if not plan.can_replay:
            detail = "; ".join(plan.blockers[:3]) or "Replay plan is blocked."
            raise ValueError(detail)

        replay_prefix = [event for event in parsed_events if int(event["seq"]) <= plan.replay_until_seq]

        result = await self._execute_with_replay_prefix(
            workflow=workflow,
            original_run=original_run,
            fork_node_id=start_node_id,
            replay_events=replay_prefix,
            label=label,
            on_event=on_event,
            run_started_extras={
                "replay_of": {
                    "run_id": original_run.id,
                    "start_node_id": start_node_id,
                    "scope": scope,
                    "replay_until_seq": plan.replay_until_seq,
                }
            },
            resolve_start_nodes=lambda _state, _executor: [start_node_id],
            state_extras={
                "replay": {
                    "source_run_id": original_run.id,
                    "start_node_id": start_node_id,
                    "scope": scope,
                    "replay_node_ids": plan.replay_node_ids,
                    "replay_until_seq": plan.replay_until_seq,
                }
            },
            result_state_extras={"replay_plan": plan.model_dump()},
        )
        return result

    def _load_parsed_trace(self, run_id: str) -> list[dict[str, Any]]:
        return [self._trace_row_to_event(row) for row in database.list_trace_events(run_id)]

    async def _execute_with_replay_prefix(
        self,
        *,
        workflow: WorkflowDefinition,
        original_run: Any,
        fork_node_id: str,
        replay_events: list[dict[str, Any]],
        label: str,
        on_event: Callable[[WorkflowEvent], None] | None,
        run_started_extras: dict[str, Any],
        resolve_start_nodes: Callable[[dict[str, Any], WorkflowGraphExecutor], list[str]],
        edited_output: Any = _SENTINEL,
        edited_at_seq: int | None = None,
        state_extras: dict[str, Any] | None = None,
        result_state_extras: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        """Shared backbone for fork() and replay().

        Reproduces a parent run's state up to `fork_node_id`, optionally
        rewrites the output at `edited_at_seq`, persists the new run, copies
        the trace prefix into the child's stream, then executes the workflow
        from `resolve_start_nodes`.
        """
        self._validate_replay_events(replay_events)

        state = self._initial_state(original_run.chat_id, original_run.initial_input or "", original_run.mode)
        state["fork_of_run_id"] = original_run.id
        state["fork_at_node_id"] = fork_node_id
        if state_extras:
            state.update(state_extras)
        if label.strip():
            state["fork_label"] = label.strip()[:120]

        events: list[WorkflowEvent] = []
        event_sink = WorkflowEventSink(events, on_event)
        deps = self._phase_deps(event_sink)
        executor = WorkflowGraphExecutor()
        self._replay_state_until(workflow, state, deps, event_sink, executor, replay_events)

        if edited_output is not _SENTINEL and edited_at_seq is not None:
            self._apply_fork_output(workflow, state, deps, event_sink, executor, fork_node_id, edited_output)
            replay_events = [
                self._edited_fork_trace_event(event, edited_at_seq, edited_output) for event in replay_events
            ]

        start_node_ids = resolve_start_nodes(state, executor)

        self._persist_started(
            workflow,
            original_run.chat_id,
            original_run.mode,
            state,
            events,
            initial_input=original_run.initial_input or "",
            fork_of_run_id=original_run.id,
            fork_at_node_id=fork_node_id,
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
                    **run_started_extras,
                },
            )
            self._copy_fork_trace_events(trace, replay_events)

        result = await executor.run(workflow, state, deps, event_sink, start_node_ids=start_node_ids, trace=trace)
        self._persist_finished(result, state)
        self._emit_run_stopped(trace, result)
        result.state["workflow_run_id"] = state.get("workflow_run_id")
        if result_state_extras:
            result.state.update(result_state_extras)
        return result

    def _initial_state(
        self, chat_id: str, user_message: str, mode: MessageMode, attachments: list[Any] | None = None
    ) -> dict[str, object]:
        return initial_workflow_state(
            self.settings, chat_id, user_message, mode, attachments=attachments, scratchpad=self.scratchpad
        )

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
        fork_at_node_id: str | None = None,
    ) -> None:
        try:
            database.create_workflow_run(
                str(state.get("workflow_run_id") or ""),
                workflow_id=workflow.id,
                chat_id=chat_id,
                mode=mode,
                state_json=json.dumps(self._persistable_state(state), ensure_ascii=False, default=str),
                events_json=json.dumps([event.model_dump() for event in events], ensure_ascii=False),
                initial_input=initial_input,
                fork_of_run_id=fork_of_run_id,
                fork_at_node_id=fork_at_node_id,
            )
        except Exception:
            logger.warning(
                "workflow_run persistence failed (start) workflow_id=%s chat_id=%s", workflow.id, chat_id, exc_info=True
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

    def _validate_replay_events(self, events: list[dict[str, Any]]) -> None:
        for event in events:
            payload = event["payload"]
            if event["type"] == "node_finished":
                if "output_snapshot" not in payload:
                    raise ValueError("Cannot replay a run with missing node output snapshots.")
                if payload.get("output_snapshot_truncated"):
                    raise ValueError("Cannot replay a run that contains truncated node output snapshots.")
            if event["type"] == "tool_call":
                if payload.get("arguments_snapshot_truncated") or payload.get("result_snapshot_truncated"):
                    raise ValueError("Cannot replay a run that contains truncated tool call snapshots.")
                if payload.get("error_snapshot_truncated"):
                    raise ValueError("Cannot replay a run that contains truncated tool error snapshots.")

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

    # Run-lifecycle events from the parent run must never be replayed onto a
    # fork or replay child: the child emits its own run_started at the start
    # and its own run_finished / run_failed / run_paused at the end. Copying
    # the parent's terminal events would close the child's SSE bus prematurely
    # and confuse the frontend reducer ("status: done" before execution finished).
    _NON_REPLAYED_TRACE_TYPES = frozenset({"run_started", "run_finished", "run_failed", "run_paused"})

    def _copy_fork_trace_events(self, trace: TraceEmitter, events: list[dict[str, Any]]) -> None:
        step_map: dict[str, str] = {}
        for event in events:
            if event["type"] in self._NON_REPLAYED_TRACE_TYPES:
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

    def _edited_fork_trace_event(self, event: dict[str, Any], source_seq: int, edited_output: Any) -> dict[str, Any]:
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
                state_json=json.dumps(self._persistable_state(state), ensure_ascii=False, default=str),
                events_json=json.dumps([event.model_dump() for event in result.events], ensure_ascii=False),
                current_node=current_node,
                finished=finished,
            )
        except Exception:
            logger.warning(
                "workflow_run persistence failed (finish) run_id=%s status=%s", run_id, result.status, exc_info=True
            )

    def _persistable_state(self, state: dict[str, object]) -> dict[str, object]:
        payload = dict(state)
        attachments = payload.get("attachments")
        if isinstance(attachments, list):
            payload["attachments"] = [
                {key: value for key, value in item.items() if key != "data"}
                for item in attachments
                if isinstance(item, dict)
            ]
        return payload
