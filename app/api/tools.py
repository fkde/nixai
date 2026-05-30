from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import load_settings, save_settings
from app.services.tool_policy import ToolPolicyService
from app.tools.registry import registry
from app.tools.routing.semantic import SemanticToolRouter
from app.tools.routing.types import ToolContext


router = APIRouter(prefix="/api/tools", tags=["tools"])
logger = logging.getLogger(__name__)


class SelectToolsRequest(BaseModel):
    message: str = ""
    input: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    limit: int = 8


class CallToolRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False
    always_allow: bool = False


@router.get("")
def list_tools() -> dict[str, Any]:
    policy = ToolPolicyService(load_settings())
    return {"success": True, "tools": [policy.annotate(tool) for tool in registry.public_definitions()]}


@router.post("/select")
async def select_tools(request: SelectToolsRequest) -> dict[str, Any]:
    message = request.message.strip() or request.input.strip()
    selected = await SemanticToolRouter(registry.definitions()).select_async(
        message, ToolContext.from_dict(request.context), request.limit
    )
    return {"success": True, "tools": [route.tool.public(route.route_payload()) for route in selected]}


@router.post("/call")
def call_tool(request: CallToolRequest) -> dict[str, Any]:
    name = request.name.strip()
    if not name:
        return {"success": True, "tool": "", "result": {"success": False, "error": "Tool name is required."}}

    settings = load_settings()
    policy = ToolPolicyService(settings)
    if policy.requires_confirmation(name) and not request.approved:
        definition = next((tool for tool in registry.public_definitions() if tool["name"] == name), None)
        if definition is None:
            raise HTTPException(status_code=400, detail=f"Unknown tool: {name}")
        try:
            preview = registry.preview(name, request.arguments)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        arguments = request.arguments
        if isinstance(preview, dict) and isinstance(preview.get("commit_arguments"), dict):
            arguments = preview["commit_arguments"]
        return {
            "success": False,
            "tool": name,
            "approval_required": True,
            "tool_definition": definition,
            "arguments": arguments,
            "preview": preview,
            "message": "Tool call requires user approval.",
        }

    if request.always_allow and not policy.requires_per_call_confirmation(name) and not policy.is_always_allowed(name):
        settings.always_allowed_tools.append(name)
        save_settings(settings)

    try:
        return {"success": True, "tool": name, "result": registry.call(name, request.arguments)}
    except Exception as exc:
        logger.warning("tool API call failed tool=%s arguments=%s", name, request.arguments, exc_info=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
