"""Tool policy / approval helpers.

Consolidates the previously scattered constants and approval logic:
- ``AUTO_TOOLS`` (formerly in ``app/agentic_runner.py``)
- ``CONTEXT_TOOL_NAMES`` (formerly in ``app/agentic_context.py``)
- Approval gating in ``app/api/tools.py``
"""

from __future__ import annotations

from typing import Any

from app.config import Settings


AUTO_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "nixai_workspace_list_files",
        "nixai_workspace_read_file",
        "nixai_workspace_search_files",
        "nixai_git_status",
        "nixai_git_diff",
        "nixai_tools_search",
        "nixai_notify_desktop",
        "nixai_web_search",
        "nixai_web_check_url",
        "nixai_web_fetch_url",
    }
)


CONTEXT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "nixai_tools_search",
        "nixai_workspace_list_files",
        "nixai_workspace_read_file",
        "nixai_workspace_search_files",
        "nixai_git_status",
        "nixai_git_diff",
        "nixai_web_search",
        "nixai_web_fetch_url",
        "nixai_web_check_url",
    }
)


# Tools that never require user confirmation when executed autonomously by
# scheduled tasks. They are user-facing and bounded by the OS.
_AUTONOMOUS_NO_APPROVAL: frozenset[str] = frozenset({"nixai_notify_desktop"})


class ToolPolicyService:
    """Encapsulates tool approval / autonomous execution rules."""

    auto_tools: frozenset[str] = AUTO_TOOL_NAMES
    context_tools: frozenset[str] = CONTEXT_TOOL_NAMES

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ----- autonomous (scheduler) --------------------------------------------

    def is_autonomous(self, name: str) -> bool:
        """Allowed to be executed by a scheduled agentic task."""
        if name not in self.auto_tools:
            return False
        if name in _AUTONOMOUS_NO_APPROVAL:
            return True
        if not self.settings.require_tool_confirmation:
            return True
        return self.settings.is_tool_always_allowed(name)

    def is_context_tool(self, name: str) -> bool:
        """Allowed for the AgenticContextBuilder evidence-gathering loop."""
        return name in self.context_tools

    # ----- interactive chat call (API) ---------------------------------------

    def requires_confirmation(self, name: str) -> bool:
        return self.settings.require_tool_confirmation and not self.settings.is_tool_always_allowed(name)

    def is_always_allowed(self, name: str) -> bool:
        return self.settings.is_tool_always_allowed(name)

    def annotate(self, tool: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of a tool definition with policy metadata."""
        meta = dict(tool.get("meta") or {})
        meta["requiresConfirmation"] = self.requires_confirmation(tool["name"])
        meta["alwaysAllowed"] = self.is_always_allowed(tool["name"])
        annotated = dict(tool)
        annotated["meta"] = meta
        return annotated
