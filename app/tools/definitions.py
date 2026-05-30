from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler
    preview_handler: ToolHandler | None = None
    routing_description: str = ""
    examples: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def public(self, include_route: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
            "routingDescription": self.routing_description,
            "examples": self.examples,
            "meta": self.meta,
        }
        if include_route is not None:
            payload["route"] = include_route
        return payload

    def with_meta(self, meta: dict[str, Any]) -> "ToolDefinition":
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            handler=self.handler,
            preview_handler=self.preview_handler,
            routing_description=self.routing_description,
            examples=self.examples,
            meta=meta,
        )
