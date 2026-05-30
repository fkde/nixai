from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.tools.definitions import ToolDefinition


@dataclass(frozen=True)
class ToolContext:
    area: str = ""
    page_id: str | None = None
    layout_id: str | None = None
    theme_id: str | None = None
    content_type: str | None = None
    ui_context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, context: dict[str, Any] | None) -> "ToolContext":
        context = context or {}
        return cls(
            area=_string_value(context.get("area")) or "",
            page_id=_string_value(context.get("pageId") or context.get("page_id")),
            layout_id=_string_value(context.get("layoutId") or context.get("layout_id")),
            theme_id=_string_value(context.get("themeId") or context.get("theme_id") or context.get("theme")),
            content_type=_string_value(context.get("contentType") or context.get("content_type")),
            ui_context=context,
        )

    def normalized_area(self) -> str:
        return self.area.replace("-", "").replace("_", "").lower()

    def summary(self) -> str:
        return " ".join(
            part for part in [self.area, self.page_id, self.layout_id, self.theme_id, self.content_type] if part
        )

    def requested_capabilities(self) -> list[str]:
        values = self.ui_context.get("capabilities") or self.ui_context.get("requestedCapabilities") or []
        if not isinstance(values, list):
            return []
        return sorted({str(value).strip() for value in values if str(value).strip()})

    def requested_mode(self) -> str | None:
        value = _string_value(self.ui_context.get("mode"))
        return value.lower() if value else None


@dataclass(frozen=True)
class ToolRoute:
    tool: ToolDefinition
    score: float
    reasons: list[str] = field(default_factory=list)

    def route_payload(self) -> dict[str, Any]:
        return {"score": self.score, "reasons": self.reasons}


def _string_value(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip()
    return text or None
