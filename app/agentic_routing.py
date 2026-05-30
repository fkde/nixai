from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.json_utils import parse_json_object
from app.models import Message


AGENTIC_WORKFLOW_TOOL = "run_agentic_workflow"
DEFAULT_DIRECT_REASON = "Model chose direct reply."


@dataclass(frozen=True)
class AgenticRouteDecision:
    run_workflow: bool
    reason: str

    @property
    def path(self) -> str:
        return "workflow" if self.run_workflow else "direct"


def agentic_router_prompt(tool_name: str = AGENTIC_WORKFLOW_TOOL) -> str:
    return (
        "You route an AGENTIC-mode request in NixAI.\n"
        f"You may either call the internal tool '{tool_name}' or answer directly without workflow.\n\n"
        "Return strict JSON only with schema:\n"
        "{\"action\":\"answer_direct|run_agentic_workflow\",\"reason\":\"short reason\"}\n\n"
        "Decision rules:\n"
        "- Prefer answer_direct for simple follow-up questions, clarifications, yes/no checks, rewrites, or short conversational replies.\n"
        "- Choose run_agentic_workflow only when the answer likely needs multi-step reasoning, tool usage, workflow evidence, or you are materially uncertain.\n"
        "- If the user references previous assistant output and asks a small follow-up, keep answer_direct.\n"
        "- Keep reason under 140 characters."
    )


def agentic_route_payload(
    *,
    user_message: str,
    recent_messages: list[dict[str, str]],
    workflow_name: str,
    tool_name: str = AGENTIC_WORKFLOW_TOOL,
) -> dict[str, object]:
    return {
        "user_message": user_message,
        "recent_messages": recent_messages,
        "workflow_name": workflow_name,
        "tool_name": tool_name,
    }


def compact_agentic_history(messages: list[Message], limit: int = 8) -> list[dict[str, str]]:
    selected = messages[-limit:]
    compact: list[dict[str, str]] = []
    for message in selected:
        text = " ".join((message.content or "").split())
        compact.append({"role": message.role, "content": text[:360]})
    return compact


def parse_agentic_route_response(
    content: object, *, default_reason: str = DEFAULT_DIRECT_REASON, tool_name: str = AGENTIC_WORKFLOW_TOOL
) -> AgenticRouteDecision:
    parsed = parse_json_object(content)
    action = str(parsed.get("action") or "").strip().lower()
    reason = str(parsed.get("reason") or default_reason).strip() or default_reason
    return AgenticRouteDecision(run_workflow=action == tool_name, reason=reason)


def agentic_workflow_fallback(user_message: object) -> bool:
    text = str(user_message or "").strip().lower()
    keywords = ["analyse", "analysiere", "research", "recherche", "vergleich", "workflow", "workspace"]
    return any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in keywords)
