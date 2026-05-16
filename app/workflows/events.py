from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.workflows.models import WorkflowEvent


WorkflowEventCallback = Callable[[WorkflowEvent], None]


class WorkflowEventSink:
    def __init__(
        self, events: list[WorkflowEvent] | None = None, callback: WorkflowEventCallback | None = None
    ) -> None:
        self.events = events if events is not None else []
        self.callback = callback

    @property
    def has_callback(self) -> bool:
        return self.callback is not None

    def emit(
        self, node: str, event_type: str, message: str, details: dict[str, Any] | None = None, *, record: bool = True
    ) -> WorkflowEvent:
        event = WorkflowEvent(node=node, type=event_type, message=message, details=details or {})
        if record:
            self.events.append(event)
        if self.callback is not None:
            self.callback(event)
        return event


class StreamStatsBuilder:
    @staticmethod
    def from_event(event: Mapping[str, object]) -> dict[str, object]:
        stats: dict[str, object] = {
            "eval_count": event.get("eval_count"),
            "eval_duration": event.get("eval_duration"),
            "prompt_eval_count": event.get("prompt_eval_count"),
            "prompt_eval_duration": event.get("prompt_eval_duration"),
        }
        eval_count = stats["eval_count"]
        eval_duration = stats["eval_duration"]
        if isinstance(eval_count, (int, float)) and isinstance(eval_duration, (int, float)) and eval_duration > 0:
            stats["tokens_per_second"] = round(float(eval_count) / (float(eval_duration) / 1_000_000_000), 2)
        return stats
