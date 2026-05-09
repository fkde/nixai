from __future__ import annotations

from typing import Any

from app.tools.definitions import ToolDefinition
from app.tools.routing.types import ToolContext


class ToolHardFilter:
    def filter(self, tools: list[ToolDefinition], user_input: str, context: ToolContext) -> list[ToolDefinition]:
        query = (user_input + " " + " ".join(str(value) for value in context.ui_context.values() if _is_scalar(value))).lower()
        write_intent = self._has_write_intent(query)
        destructive_intent = self._has_destructive_intent(query)
        requested_mode = context.requested_mode()
        requested_capabilities = context.requested_capabilities()

        return [
            tool
            for tool in tools
            if self._allows(tool, context, write_intent, destructive_intent, requested_mode, requested_capabilities)
        ]

    def _allows(
        self,
        tool: ToolDefinition,
        context: ToolContext,
        write_intent: bool,
        destructive_intent: bool,
        requested_mode: str | None,
        requested_capabilities: list[str],
    ) -> bool:
        meta = tool.meta
        risk = str(meta.get("risk") or "read")
        mode = str(meta.get("mode") or "read")

        if risk == "write" and not write_intent:
            return False
        if meta.get("destructive") is True and not destructive_intent:
            return False
        if requested_mode is not None and mode != requested_mode:
            return False
        if requested_capabilities and not _intersects(_capabilities(meta), requested_capabilities):
            return False

        return self._area_allows_tool(context, meta, risk)

    def _area_allows_tool(self, context: ToolContext, meta: dict[str, Any], risk: str) -> bool:
        if risk != "write":
            return True
        if context.normalized_area() == "":
            return str(meta.get("mode") or "read") != "write" and meta.get("destructive") is not True
        return _intersects(_capabilities(meta), ["filesystem.write", "command.run"])

    def _has_write_intent(self, query: str) -> bool:
        return any(
            needle in query
            for needle in [
                "create",
                "add",
                "append",
                "write",
                "update",
                "delete",
                "publish",
                "commit",
                "erstelle",
                "füge",
                "fuege",
                "ergänze",
                "aendere",
                "ändere",
                "speichere",
                "loesche",
                "lösche",
            ]
        )

    def _has_destructive_intent(self, query: str) -> bool:
        return any(needle in query for needle in ["delete", "remove", "discard", "rollback", "loesche", "lösche", "entferne"])


def _capabilities(meta: dict[str, Any]) -> list[str]:
    values = meta.get("capabilities")
    return [str(value) for value in values] if isinstance(values, list) else []


def _intersects(left: list[str], right: list[str]) -> bool:
    return any(value in left for value in right)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))
