from __future__ import annotations

from typing import Any

from app import database
from app.code_context import CodeContextBuilder
from app.config import Settings
from app.effort import effort_context, normalize_effort
from app.memory import memory_context
from app.models import MessageMode
from app.runtime_context import runtime_meta_context
from app.workflow_scratch import new_workflow_run_id, read_workflow_notes, workflow_scratch_path


WorkflowState = dict[str, Any]


def initial_workflow_state(settings: Settings, chat_id: str, user_message: str, mode: MessageMode) -> WorkflowState:
    workspace = ""
    if mode == "code":
        chat = database.get_chat(chat_id)
        workspace = (chat.workspace_path if chat and chat.workspace_path.strip() else settings.workspace_path).strip()
    history = database.list_messages(chat_id, mode=mode)[-8:]
    code_context = CodeContextBuilder(workspace).build(user_message) if mode == "code" else ""
    return {
        "chat_id": chat_id,
        "mode": mode,
        "user_message": user_message,
        "workflow_run_id": new_workflow_run_id(),
        "workflow_scratch_path": str(workflow_scratch_path()),
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
    }


def workflow_state_payload(state: WorkflowState) -> dict[str, Any]:
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
        "workflow_rounds": compact_workflow_rounds(state.get("workflow_rounds")),
    }
    if state.get("code_context"):
        payload["code_context"] = str(state["code_context"])[:12000]
    if state.get("agentic_context"):
        payload["agentic_context"] = str(state["agentic_context"])[:16000]
    scratch = read_workflow_notes(str(state.get("workflow_run_id") or ""))
    if scratch:
        payload["workflow_scratchpad"] = scratch[:16000]
    return payload


def final_answer_payload(state: WorkflowState) -> dict[str, Any]:
    payload = workflow_state_payload(state)
    payload.pop("code_context", None)
    payload.pop("agentic_context", None)
    payload["worker_reports"] = compact_workflow_reports(state.get("worker_reports"), limit=1800)
    payload["workflow_rounds"] = compact_workflow_rounds(state.get("workflow_rounds"), report_limit=1200)
    if "workflow_scratchpad" in payload:
        payload["workflow_scratchpad"] = str(payload["workflow_scratchpad"])[:6000]
    return payload


def compact_workflow_state(state: WorkflowState) -> dict[str, Any]:
    compact = workflow_state_payload(state)
    if "code_context" in compact:
        compact["code_context"] = "[omitted]"
    if "agentic_context" in compact:
        compact["agentic_context"] = "[omitted]"
    if state.get("final_answer_streamed"):
        compact["answer_streamed"] = True
    return compact


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
