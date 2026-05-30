from __future__ import annotations

import contextlib
import json
import logging
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Protocol

from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)


TraceEventType = Literal[
    "run_started",
    "run_paused",
    "run_finished",
    "run_failed",
    "node_started",
    "node_finished",
    "node_failed",
    "edge_traversed",
    "llm_call",
    "tool_call",
]


SNAPSHOT_INLINE_CAP = 64 * 1024


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_step_id() -> str:
    return uuid.uuid4().hex


def cap_snapshot(value: Any, *, cap: int = SNAPSHOT_INLINE_CAP) -> tuple[Any, bool]:
    """Return (value, truncated). Serialises non-string values for measurement."""
    if value is None:
        return None, False
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    if len(text.encode("utf-8")) <= cap:
        return value, False
    truncated_text = text.encode("utf-8")[:cap].decode("utf-8", errors="ignore")
    return truncated_text, True


class TraceEvent(BaseModel):
    """Single structural trace event persisted in workflow_run_events.

    The `type`/`payload` pair is a discriminated union by convention; callers
    are expected to populate the payload according to the type. Persistence is
    payload-agnostic (stored as JSON), so this stays flexible without losing
    strictness at the call site.
    """

    step_id: str = Field(default_factory=_new_step_id)
    run_id: str
    parent_step_id: Optional[str] = None
    workflow_id: str
    node_id: str
    type: TraceEventType
    ts: str = Field(default_factory=_now_iso)
    payload: dict[str, Any] = Field(default_factory=dict)


class TracePersistence(Protocol):
    def insert(self, event: TraceEvent) -> int: ...


class TraceBus(Protocol):
    def publish(self, run_id: str, event: TraceEvent, seq: int) -> None: ...


class InMemoryTracePersistence:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def insert(self, event: TraceEvent) -> int:
        self.events.append(event)
        return len(self.events)


class NullTraceBus:
    def publish(self, run_id: str, event: TraceEvent, seq: int) -> None:  # noqa: D401
        return None


class TraceEmitter:
    """Emits structural workflow trace events.

    Behavioural guarantees:
    * Persistence failures are logged and swallowed — execution must not break.
    * `scope(step_id)` pushes a parent-step context; nested emits inherit it.
    * `step_id` is returned from each `emit` so callers can use it as a parent.
    """

    def __init__(
        self, *, run_id: str, workflow_id: str, persistence: TracePersistence, bus: TraceBus | None = None
    ) -> None:
        self.run_id = run_id
        self.workflow_id = workflow_id
        self.persistence = persistence
        self.bus = bus or NullTraceBus()
        self._parent_stack: list[str] = []

    @property
    def current_parent(self) -> Optional[str]:
        return self._parent_stack[-1] if self._parent_stack else None

    @contextlib.contextmanager
    def scope(self, step_id: str) -> Iterator[None]:
        self._parent_stack.append(step_id)
        try:
            yield
        finally:
            if self._parent_stack and self._parent_stack[-1] == step_id:
                self._parent_stack.pop()
            else:
                # defensive: pop matching id even if scope nesting is broken
                try:
                    self._parent_stack.remove(step_id)
                except ValueError:
                    pass

    def emit_llm_call(
        self,
        *,
        node_id: str,
        model: str,
        prompt: Any,
        response: Any,
        duration_ms: int,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
    ) -> str:
        prompt_snapshot, prompt_truncated = cap_snapshot(prompt)
        response_snapshot, response_truncated = cap_snapshot(response)
        return self.emit(
            "llm_call",
            node_id=node_id,
            payload={
                "model": model,
                "prompt": prompt_snapshot,
                "prompt_truncated": prompt_truncated,
                "response": response_snapshot,
                "response_truncated": response_truncated,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "duration_ms": duration_ms,
            },
        )

    def emit_tool_call(
        self,
        *,
        node_id: str,
        tool_name: str,
        arguments: Any,
        result: Any = None,
        error: Any = None,
        approval_context: dict[str, Any] | None = None,
        security_context: dict[str, Any] | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        duration_ms: int = 0,
        replayable: bool = False,
    ) -> str:
        arguments_snapshot, arguments_truncated = cap_snapshot(arguments)
        result_snapshot, result_truncated = cap_snapshot(result)
        error_snapshot, error_truncated = cap_snapshot(error)
        return self.emit(
            "tool_call",
            node_id=node_id,
            payload={
                "tool_name": tool_name,
                "status": "failed" if error else "done",
                "arguments_snapshot": arguments_snapshot,
                "arguments_snapshot_truncated": arguments_truncated,
                "result_snapshot": result_snapshot,
                "result_snapshot_truncated": result_truncated,
                "error_snapshot": error_snapshot,
                "error_snapshot_truncated": error_truncated,
                "approval_context": approval_context or {},
                "security_context": security_context or {},
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_ms": duration_ms,
                "replayable": replayable,
            },
        )

    def emit(
        self,
        type: TraceEventType,
        *,
        node_id: str,
        payload: dict[str, Any] | None = None,
        parent_step_id: Optional[str] = None,
        step_id: Optional[str] = None,
    ) -> str:
        event = TraceEvent(
            step_id=step_id or _new_step_id(),
            run_id=self.run_id,
            parent_step_id=parent_step_id if parent_step_id is not None else self.current_parent,
            workflow_id=self.workflow_id,
            node_id=node_id,
            type=type,
            payload=payload or {},
        )
        try:
            seq = self.persistence.insert(event)
        except Exception:
            logger.warning(
                "trace_emitter persist failed run_id=%s type=%s node_id=%s", self.run_id, type, node_id, exc_info=True
            )
            return event.step_id
        try:
            self.bus.publish(self.run_id, event, seq)
        except Exception:
            logger.warning("trace_emitter publish failed run_id=%s type=%s", self.run_id, type, exc_info=True)
        return event.step_id


class SqliteTracePersistence:
    """Persists trace events atomically into workflow_run_events + projections.

    The raw event row and its derived projection rows (workflow_node_states,
    workflow_tool_calls) share a single transaction so a partial failure
    cannot leave the run-event log out of sync with its read-model.
    """

    def insert(self, event: TraceEvent) -> int:
        from app.db.connection import get_connection
        from app.db.workflow_state import apply_trace_event_to_runtime_state
        from app.db.workflow_trace import insert_trace_event

        with get_connection() as db:
            seq = insert_trace_event(
                step_id=event.step_id,
                run_id=event.run_id,
                workflow_id=event.workflow_id,
                node_id=event.node_id,
                type=event.type,
                ts=event.ts,
                payload_json=json.dumps(event.payload, ensure_ascii=False, default=str),
                parent_step_id=event.parent_step_id,
                db=db,
            )
            try:
                apply_trace_event_to_runtime_state(event, seq, db=db)
            except Exception:
                # Roll back the trace insert too so the log stays consistent
                # with the projections. The caller (TraceEmitter.emit) catches
                # this and continues without breaking workflow execution.
                logger.warning(
                    "runtime state projection failed run_id=%s type=%s node_id=%s — rolling back trace insert",
                    event.run_id,
                    event.type,
                    event.node_id,
                    exc_info=True,
                )
                raise
        return seq


def default_emitter(run_id: str, workflow_id: str, bus: TraceBus | None = None) -> TraceEmitter:
    if bus is None:
        from app.workflows.run_bus import get_run_bus

        bus = get_run_bus()
    return TraceEmitter(run_id=run_id, workflow_id=workflow_id, persistence=SqliteTracePersistence(), bus=bus)


__all__ = [
    "SNAPSHOT_INLINE_CAP",
    "InMemoryTracePersistence",
    "NullTraceBus",
    "SqliteTracePersistence",
    "TraceBus",
    "TraceEmitter",
    "TraceEvent",
    "TraceEventType",
    "TracePersistence",
    "cap_snapshot",
    "default_emitter",
]
