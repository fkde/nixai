from __future__ import annotations

import json
from typing import Any

from app.roles import role_prompt


def build_plan_prompt(
    *,
    role: str,
    runtime_context: str,
    effort_context: str,
    memory: str,
    max_items: int,
) -> str:
    return (
        f"{role_prompt(role or 'ORCHESTRATOR')}\n\n"
        f"{runtime_context}\n\n"
        f"{effort_context}\n\n"
        f"Shared reviewed memory:\n{memory}\n\n"
        "Create a compact execution plan for this NixAI workflow.\n"
        "Match the user's language for title and summary.\n"
        "Return strict JSON only with this schema:\n"
        "{"
        "\"title\":\"2-6 word chat title\","
        "\"summary\":\"...\","
        "\"acceptance_criteria\":[\"...\"],"
        "\"work_items\":[{\"id\":\"short-id\",\"title\":\"...\",\"instructions\":\"...\",\"owned_paths\":[\"optional/path\"]}]"
        "}\n"
        f"Maximum work items for this effort level: {max_items}.\n"
        "Keep work items independent when possible so worker_pool can run them in parallel."
    )


def build_retry_plan_prompt(
    *,
    role: str,
    runtime_context: str,
    effort_context: str,
    memory: str,
    max_items: int,
) -> str:
    return (
        f"{role_prompt(role or 'ORCHESTRATOR')}\n\n"
        f"{runtime_context}\n\n"
        f"{effort_context}\n\n"
        f"Shared reviewed memory:\n{memory}\n\n"
        "Revise the workflow plan for the next retry pass.\n"
        "Use the previous worker reports, reviewer findings, judge feedback, and workflow scratchpad.\n"
        "Do not repeat completed work. Convert the retry feedback into concrete worker instructions.\n"
        "If the missing piece is final synthesis, create a single synthesis work item that consolidates existing evidence instead of asking workers to rediscover the same facts.\n"
        "Match the user's language for title and summary.\n"
        "Return strict JSON only with this schema:\n"
        "{"
        "\"title\":\"2-6 word chat title\","
        "\"summary\":\"...\","
        "\"acceptance_criteria\":[\"...\"],"
        "\"work_items\":[{\"id\":\"short-id\",\"title\":\"...\",\"instructions\":\"...\",\"owned_paths\":[\"optional/path\"]}]"
        "}\n"
        f"Maximum work items for this effort level: {max_items}."
    )


def build_review_prompt(*, role: str, runtime_context: str, effort_context: str) -> str:
    return (
        f"{role_prompt(role or 'REVIEWER')}\n\n"
        f"{runtime_context}\n\n"
        f"{effort_context}\n\n"
        "Review the worker reports against the plan and acceptance criteria.\n"
        "Return strict JSON only with this schema:\n"
        "{\"status\":\"approved|changes_requested\",\"summary\":\"...\",\"findings\":[{\"severity\":\"low|medium|high\",\"message\":\"...\"}]}.\n"
        "Do not invent test results or file changes."
    )


def build_judge_prompt(*, role: str, runtime_context: str, effort_context: str) -> str:
    return (
        f"{role_prompt(role or 'JUDGE')}\n\n"
        f"{runtime_context}\n\n"
        f"{effort_context}\n\n"
        "Decide whether this workflow has enough evidence to answer the user.\n"
        "Return strict JSON only with this schema:\n"
        "{\"status\":\"done|retry|needs_user\",\"reason\":\"...\",\"feedback\":[\"...\"],\"final_answer\":\"optional user-facing answer\"}.\n"
        "Use retry only when a worker can improve the result without asking the user. "
        "Use needs_user when required information, approval, or tool access is missing. "
        "If the only missing piece is final synthesis or wording, use done and provide a user-facing final_answer. "
        "Never put internal deliberation, reviewer-only commentary, or retry rationale in final_answer."
    )


def build_final_answer_prompt(*, runtime_context: str, effort_context: str) -> str:
    return (
        f"{role_prompt('ORCHESTRATOR')}\n\n"
        f"{runtime_context}\n\n"
        f"{effort_context}\n\n"
        "Write the final answer for the user from the workflow state. "
        "Match the user's language. Be concise, concrete, and transparent about missing verification. "
        "Synthesize across all workflow rounds, worker reports, review findings, judge feedback, and the workflow scratchpad. "
        "Never output internal Judge/Reviewer reasoning as the answer. Do not say a retry is required. "
        "If evidence is incomplete, give the best grounded answer and clearly label what could not be verified. "
        "Do not mention internal JSON unless it matters."
    )


def build_worker_prompt(
    *,
    role: str,
    runtime_context: str,
    effort_context: str,
    memory: str,
    item: dict[str, Any],
    code_context: str = "",
    agentic_context: str = "",
    retry_feedback: object = None,
) -> str:
    prompt = (
        f"{role_prompt(role or 'WORKER')}\n\n"
        f"{runtime_context}\n\n"
        f"{effort_context}\n\n"
        f"Shared reviewed memory:\n{memory}\n\n"
        "Execute this assigned workflow item as far as possible from the provided context.\n"
        "Return concise Markdown with: result, evidence, open risks, and recommended next checks.\n"
        "Do not claim tools, tests, or file edits were run unless they are visible in the supplied context.\n\n"
        f"Assigned item:\n{json.dumps(item, ensure_ascii=False, indent=2)}"
    )
    if code_context:
        prompt += f"\n\nWorkspace context:\n{code_context}"
    if agentic_context:
        prompt += f"\n\nAgentic tool context:\n{agentic_context}"
    if retry_feedback:
        prompt += f"\n\nRetry feedback from Judge:\n{retry_feedback}"
    return prompt
