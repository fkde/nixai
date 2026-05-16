from __future__ import annotations

from typing import Any

from app.tools.catalog import ToolCatalog
from app.tools.definitions import ToolDefinition
from app.tools.factories import create_base_tool_definitions


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: list[ToolDefinition] | None = None

    def definitions(self) -> list[ToolDefinition]:
        if self._definitions is None:
            self._definitions = ToolCatalog().enrich(create_base_tool_definitions(self._search_tool))
        return self._definitions

    def public_definitions(self) -> list[dict[str, Any]]:
        return [definition.public() for definition in self.definitions()]

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        arguments = arguments or {}
        for definition in self.definitions():
            if definition.name == name:
                return definition.handler(arguments)
        raise ValueError(f"Unknown tool: {name}")

    def _search_tool(self, args: dict[str, Any]) -> dict[str, Any]:
        from app.tools.routing.semantic import SemanticToolRouter, ToolContext

        context = args.get("context") if isinstance(args.get("context"), dict) else {}
        if isinstance(args.get("capabilities"), list):
            context["capabilities"] = args["capabilities"]
        if str(args.get("mode") or "").strip():
            context["mode"] = str(args["mode"]).strip().lower()

        selected = SemanticToolRouter(self.definitions()).select(
            str(args.get("query") or ""),
            ToolContext.from_dict(context),
            int(args.get("limit") or 8),
        )
        return {"success": True, "tools": [item.tool.public(item.route_payload()) for item in selected]}


registry = ToolRegistry()
