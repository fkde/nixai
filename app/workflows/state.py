from __future__ import annotations

import json
from typing import Any

from app import database
from app.code_context import CodeContextBuilder
from app.config import Settings
from app.effort import effort_context, normalize_effort
from app.memory import memory_context
from app.models import ImageAttachment, MessageMode
from app.runtime_context import runtime_meta_context
from app.workflow_scratch import WorkflowScratchpad, default_workflow_scratchpad


WorkflowState = dict[str, Any]


def initial_workflow_state(
    settings: Settings,
    chat_id: str,
    user_message: str,
    mode: MessageMode,
    attachments: list[ImageAttachment] | None = None,
    scratchpad: WorkflowScratchpad | None = None,
) -> WorkflowState:
    scratchpad = scratchpad or default_workflow_scratchpad
    workspace = ""
    if mode == "code":
        chat = database.get_chat(chat_id)
        workspace = (chat.workspace_path if chat and chat.workspace_path.strip() else settings.workspace_path).strip()
    history = database.list_messages(chat_id, mode=mode)[-8:]
    code_context = CodeContextBuilder(workspace).build(user_message) if mode == "code" else ""
    attachment_payload = [
        {
            "name": item.name,
            "mime_type": item.mime_type,
            "size": item.size,
            "data": item.data,
        }
        for item in (attachments or [])
    ]
    return {
        "chat_id": chat_id,
        "mode": mode,
        "user_message": user_message,
        "workflow_run_id": scratchpad.new_run_id(),
        "workflow_scratch_path": str(scratchpad.path()),
        "workflow_rounds": [],
        "effort": normalize_effort(settings.effort),
        "effort_context": effort_context(settings.effort),
        "workspace": workspace,
        "runtime_context": runtime_meta_context(user_message),
        "memory": memory_context(),
        "code_context": code_context,
        "agentic_context": "",
        "history": [
            {"role": message.role, "content": message.content[:4000]}
            for message in history
            if message.role in {"user", "assistant"}
        ],
        # MVP: image bytes are run-scoped only and intentionally omitted from
        # message persistence; compact state projection strips `data`.
        "attachments": attachment_payload,
    }


def workflow_state_payload(
    state: WorkflowState,
    scratchpad: WorkflowScratchpad | None = None,
) -> dict[str, Any]:
    scratchpad = scratchpad or default_workflow_scratchpad
    payload = {
        "mode": state.get("mode"),
        "effort": state.get("effort"),
        "user_message": state.get("user_message"),
        "workspace": state.get("workspace"),
        "history": state.get("history", []),
        "plan": state.get("plan"),
        "worker_reports": state.get("worker_reports"),
        "review": state.get("review"),
        "decision": state.get("decision"),
        "retry_feedback": state.get("retry_feedback"),
        "loop_context": state.get("loop_context"),
        "subworkflow_context": state.get("subworkflow_context"),
        "node_results": state.get("node_results", {}),
        "workflow_rounds": compact_workflow_rounds(state.get("workflow_rounds")),
    }
    if state.get("attachments"):
        payload["attachments"] = compact_attachments(state.get("attachments"))
    if state.get("code_context"):
        payload["code_context"] = str(state["code_context"])[:12000]
    if state.get("agentic_context"):
        payload["agentic_context"] = str(state["agentic_context"])[:16000]
    scratch = scratchpad.read_notes(str(state.get("workflow_run_id") or ""))
    if scratch:
        payload["workflow_scratchpad"] = scratch[:16000]
    return payload


def final_answer_payload(
    state: WorkflowState,
    scratchpad: WorkflowScratchpad | None = None,
) -> dict[str, Any]:
    payload = workflow_state_payload(state, scratchpad=scratchpad)
    payload.pop("code_context", None)
    payload.pop("agentic_context", None)
    payload["worker_reports"] = compact_workflow_reports(state.get("worker_reports"), limit=1800)
    payload["workflow_rounds"] = compact_workflow_rounds(state.get("workflow_rounds"), report_limit=1200)
    if "workflow_scratchpad" in payload:
        payload["workflow_scratchpad"] = str(payload["workflow_scratchpad"])[:6000]
    return payload


def compact_workflow_state(
    state: WorkflowState,
    scratchpad: WorkflowScratchpad | None = None,
) -> dict[str, Any]:
    compact = workflow_state_payload(state, scratchpad=scratchpad)
    for key, value in state.items():
        if key in compact or key in _OMITTED_COMPACT_KEYS:
            continue
        compact[key] = _compact_extra_value(value)
    if "code_context" in compact:
        compact["code_context"] = "[omitted]"
    if "agentic_context" in compact:
        compact["agentic_context"] = "[omitted]"
    if state.get("final_answer_streamed"):
        compact["answer_streamed"] = True
    return compact


def compact_attachments(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "name": str(item.get("name") or "")[:200],
                "mime_type": str(item.get("mime_type") or "")[:80],
                "size": item.get("size") if isinstance(item.get("size"), int) else 0,
            }
        )
    return result


_OMITTED_COMPACT_KEYS = {
    "chat_id",
    "workflow_run_id",
    "workflow_scratch_path",
    "runtime_context",
    "memory",
    "code_context",
    "agentic_context",
}


def _compact_extra_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    try:
        encoded = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)[:1000]
    if len(encoded) <= 12000:
        return value
    return {"truncated": encoded[:12000]}


def record_workflow_round(
    state: WorkflowState,
    reports: list[dict[str, Any]],
    review: dict[str, Any],
    decision: dict[str, Any],
) -> None:
    rounds = state.get("workflow_rounds")
    if not isinstance(rounds, list):
        rounds = []
        state["workflow_rounds"] = rounds
    rounds.append(
        {
            "iteration": state.get("iteration"),
            "plan": state.get("plan"),
            "worker_reports": reports,
            "review": review,
            "decision": decision,
        }
    )


def compact_workflow_rounds(rounds: Any, report_limit: int = 3000) -> list[dict[str, Any]]:
    if not isinstance(rounds, list):
        return []
    compact = []
    for item in rounds[-4:]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "iteration": item.get("iteration"),
                "plan_summary": (item.get("plan") or {}).get("summary") if isinstance(item.get("plan"), dict) else "",
                "worker_reports": compact_workflow_reports(item.get("worker_reports"), limit=report_limit),
                "review": item.get("review"),
                "decision": item.get("decision"),
            }
        )
    return compact


def compact_workflow_reports(reports: Any, limit: int = 3000) -> list[dict[str, str]]:
    if not isinstance(reports, list):
        return []
    compact = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        compact.append(
            {
                "id": str(report.get("id") or ""),
                "title": str(report.get("title") or ""),
                "content": str(report.get("content") or "")[:limit],
            }
        )
    return compact
