from __future__ import annotations

from app.agentic_routing import (
    AGENTIC_WORKFLOW_TOOL,
    agentic_route_payload,
    agentic_router_prompt,
    agentic_workflow_fallback,
    compact_agentic_history,
    parse_agentic_route_response,
)
from app.models import Message


def test_parse_agentic_route_response() -> None:
    workflow = parse_agentic_route_response('{"action":"run_agentic_workflow","reason":"Needs tools"}')
    direct = parse_agentic_route_response('```json\n{"action":"answer_direct","reason":"Small follow-up"}\n```')

    assert workflow.run_workflow
    assert workflow.path == "workflow"
    assert workflow.reason == "Needs tools"
    assert not direct.run_workflow
    assert direct.path == "direct"
    assert direct.reason == "Small follow-up"


def test_agentic_workflow_fallback_matches_workflow_keywords_only() -> None:
    assert agentic_workflow_fallback("Bitte analysiere das Workspace-Problem")
    assert agentic_workflow_fallback("Research the implementation")
    assert not agentic_workflow_fallback("Kannst du das kurz umformulieren?")


def test_compact_agentic_history_limits_count_and_content() -> None:
    messages = [
        Message(id=str(index), chat_id="chat", role="user", content=f"message {index} " * 100, mode="agentic", created_at="now")
        for index in range(10)
    ]

    compact = compact_agentic_history(messages, limit=3)

    assert [item["content"].split()[1] for item in compact] == ["7", "8", "9"]
    assert all(len(item["content"]) <= 360 for item in compact)


def test_agentic_router_prompt_and_payload_name_internal_tool() -> None:
    prompt = agentic_router_prompt()
    payload = agentic_route_payload(user_message="Go", recent_messages=[], workflow_name="Deep")

    assert AGENTIC_WORKFLOW_TOOL in prompt
    assert payload["tool_name"] == AGENTIC_WORKFLOW_TOOL
    assert payload["workflow_name"] == "Deep"
