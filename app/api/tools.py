from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.tools.registry import registry
from app.tools.routing.semantic import SemanticToolRouter
from app.tools.routing.types import ToolContext


router = APIRouter(prefix="/api/tools", tags=["tools"])


class SelectToolsRequest(BaseModel):
    message: str = ""
    input: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    limit: int = 8


class CallToolRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_tools() -> dict[str, Any]:
    return {"success": True, "tools": registry.public_definitions()}


@router.post("/select")
async def select_tools(request: SelectToolsRequest) -> dict[str, Any]:
    message = request.message.strip() or request.input.strip()
    selected = await SemanticToolRouter(registry.definitions()).select_async(
        message,
        ToolContext.from_dict(request.context),
        request.limit,
    )
    return {"success": True, "tools": [route.tool.public(route.route_payload()) for route in selected]}


@router.post("/call")
def call_tool(request: CallToolRequest) -> dict[str, Any]:
    if not request.name.strip():
        return {"success": True, "tool": "", "result": {"success": False, "error": "Tool name is required."}}

    try:
        return {"success": True, "tool": request.name, "result": registry.call(request.name, request.arguments)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
