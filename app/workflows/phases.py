from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.config import Settings
from app.effort import effort_max_items, effort_max_parallel
from app.json_utils import parse_json_object
from app.workflow_scratch import WorkflowScratchpad
from app.workflows.events import WorkflowEventSink
from app.workflows.models import WorkflowDefinition, WorkflowNode
from app.workflows.runtime_trace import TraceEmitter
from app.workflows.prompts import (
    append_node_instruction,
    build_final_answer_prompt,
    build_judge_prompt,
    build_plan_prompt,
    build_retry_plan_prompt,
    build_review_prompt,
    build_worker_prompt,
)
from app.workflows.state import WorkflowState, final_answer_payload, workflow_state_payload


class WorkflowOllamaClient(Protocol):
    async def chat_payload(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        response_format: str | dict[str, Any] | None = None,
    ) -> str: ...

    def stream_payload(
        self, messages: list[dict[str, Any]], model: str | None = None
    ) -> AsyncIterator[dict[str, object]]: ...


def noop_update_chat_title(_chat_id: str, _plan: dict[str, Any]) -> None:
    return None


@dataclass
class WorkflowPhaseDeps:
    settings: Settings
    ollama: WorkflowOllamaClient
    event_sink: WorkflowEventSink
    scratchpad: WorkflowScratchpad
    update_chat_title: Callable[[str, dict[str, Any]], None] = noop_update_chat_title
    final_ollama_factory: Callable[[], WorkflowOllamaClient] | None = None
    trace: TraceEmitter | None = None


async def build_plan(workflow: WorkflowDefinition, state: WorkflowState, deps: WorkflowPhaseDeps) -> dict[str, Any]:
    node = workflow.node("orchestrator") or first_node(workflow, "role")
    if node is None:
        return fallback_plan(state["user_message"])

    max_items = effort_max_items(node.max_items, state.get("effort"))
    deps.event_sink.emit(node.id, "status", "Summarizing task for orchestrator.")
    prompt = build_plan_prompt(
        role=node.role,
        runtime_context=state["runtime_context"],
        effort_context=state["effort_context"],
        memory=state["memory"],
        max_items=max_items,
    )
    content = await role_call(node, prompt, state_payload(state, deps), deps)
    plan = parse_json_object(content, fallback=fallback_plan(state["user_message"]))
    plan["work_items"] = normalize_work_items(plan.get("work_items"), state["user_message"], max_items)
    plan = normalize_plan_metadata(plan, len(plan["work_items"]), max_items)
    deps.update_chat_title(str(state.get("chat_id") or ""), plan)
    deps.event_sink.emit(node.id, "done", f"Orchestrator created {len(plan['work_items'])} work item(s).")
    note(deps, state, "Initial workflow plan", markdown_data(plan))
    return plan


async def replan_for_retry(
    workflow: WorkflowDefinition, state: WorkflowState, deps: WorkflowPhaseDeps
) -> dict[str, Any]:
    node = workflow.node("orchestrator") or first_node(workflow, "role")
    if node is None:
        return fallback_plan(state["user_message"])

    max_items = effort_max_items(node.max_items, state.get("effort"))
    deps.event_sink.emit(node.id, "status", "Replanning retry with prior findings.")
    prompt = build_retry_plan_prompt(
        role=node.role,
        runtime_context=state["runtime_context"],
        effort_context=state["effort_context"],
        memory=state["memory"],
        max_items=max_items,
    )
    content = await role_call(node, prompt, state_payload(state, deps), deps)
    plan = parse_json_object(content, fallback=fallback_plan(state["user_message"]))
    plan["work_items"] = normalize_work_items(plan.get("work_items"), state["user_message"], max_items)
    plan = normalize_plan_metadata(plan, len(plan["work_items"]), max_items)
    deps.event_sink.emit(node.id, "done", f"Orchestrator replanned {len(plan['work_items'])} retry item(s).")
    note(deps, state, "Retry workflow plan", markdown_data(plan))
    return plan


async def run_workers(
    workflow: WorkflowDefinition, state: WorkflowState, deps: WorkflowPhaseDeps
) -> list[dict[str, Any]]:
    node = workflow.node("workers") or first_node(workflow, "worker_pool")
    if node is None:
        return []

    work_items = normalize_work_items(
        state.get("plan", {}).get("work_items"),
        state["user_message"],
        effort_max_items(node.max_items, state.get("effort")),
    )
    pool_size = max(1, node.worker_instances)
    concurrency_cap = max(1, node.max_parallel)
    recommended_workers = recommended_worker_count(state.get("plan"), len(work_items))
    configured_parallel = min(pool_size, concurrency_cap, recommended_workers)
    limit = max(1, min(effort_max_parallel(configured_parallel, state.get("effort")), len(work_items)))
    semaphore = asyncio.Semaphore(limit)
    deps.event_sink.emit(
        node.id,
        "status",
        (
            f"Orchestrator spawned {len(work_items)} worker item(s), "
            f"recommended workers {recommended_workers}, max worker instances {pool_size}, "
            f"concurrency cap {concurrency_cap}, active parallel {limit}."
        ),
    )

    async def run_item(item: dict[str, Any], item_index: int) -> dict[str, Any]:
        async with semaphore:
            item_id = str(item.get("id") or "work-item")
            title = str(item.get("title") or item_id)
            worker_label = f"worker-{(item_index % limit) + 1}"
            deps.event_sink.emit(item_id, "status", f"{worker_label} started: {title}.")
            prompt = worker_prompt(node, item, state)
            content = await role_call(node, prompt, state_payload(state, deps), deps, include_node_instruction=False)
            deps.event_sink.emit(item_id, "done", f"{worker_label} completed: {title}.")
            return {"id": item_id, "title": title, "worker": worker_label, "content": content.strip()}

    reports = await asyncio.gather(*(run_item(item, index) for index, item in enumerate(work_items)))
    deps.event_sink.emit(node.id, "done", f"Worker pool completed {len(reports)} report(s).")
    return reports


async def review(workflow: WorkflowDefinition, state: WorkflowState, deps: WorkflowPhaseDeps) -> dict[str, Any]:
    node = (
        workflow.node("report")
        or workflow.node("reviewer")
        or first_node(workflow, "report")
        or first_node(workflow, "reviewer")
    )
    if node is None:
        return {"status": "approved", "summary": "No reviewer node configured.", "findings": []}

    deps.event_sink.emit(node.id, "status", "Reviewer is checking worker reports.")
    prompt = build_review_prompt(
        role=node.role, runtime_context=state["runtime_context"], effort_context=state["effort_context"]
    )
    content = await role_call(node, prompt, state_payload(state, deps), deps)
    parsed = parse_json_object(
        content, fallback={"status": "changes_requested", "summary": content.strip(), "findings": []}
    )
    deps.event_sink.emit(node.id, "done", f"Reviewer status: {parsed.get('status', 'unknown')}.")
    return parsed


async def judge(workflow: WorkflowDefinition, state: WorkflowState, deps: WorkflowPhaseDeps) -> dict[str, Any]:
    node = (
        workflow.node("decision")
        or workflow.node("judge")
        or first_node(workflow, "decision")
        or first_node(workflow, "judge")
    )
    if node is None:
        return {"status": "done", "reason": "No judge node configured.", "feedback": []}

    deps.event_sink.emit(node.id, "status", "Judge is deciding whether the task is done.")
    prompt = build_judge_prompt(
        role=node.role, runtime_context=state["runtime_context"], effort_context=state["effort_context"]
    )
    content = await role_call(node, prompt, state_payload(state, deps), deps)
    decision = parse_json_object(content, fallback={"status": "done", "reason": content.strip(), "feedback": []})
    status = str(decision.get("status") or "done").strip().lower()
    if status not in {"done", "retry", "needs_user"}:
        decision["status"] = "done"
    deps.event_sink.emit(node.id, "done", f"Judge decision: {decision.get('status', 'done')}.")
    return decision


async def final_answer(
    workflow: WorkflowDefinition, state: WorkflowState, deps: WorkflowPhaseDeps, node_id: str = "answer"
) -> str:
    node = workflow.node(node_id)
    decision = state.get("decision") if isinstance(state.get("decision"), dict) else {}
    status = str(decision.get("status") or "done").strip().lower()
    if status == "needs_user":
        reason = str(decision.get("reason") or "I need more input before I can finish this.").strip()
        feedback = decision.get("feedback") if isinstance(decision.get("feedback"), list) else []
        lines = [reason]
        lines.extend(f"- {item}" for item in feedback if str(item).strip())
        return "\n".join(lines).strip()

    deps.event_sink.emit(node_id, "status", "Preparing final answer.")
    prompt = build_final_answer_prompt(
        runtime_context=state["runtime_context"],
        effort_context=state["effort_context"],
        role=node.role if node is not None else "ORCHESTRATOR",
    )
    if node is not None:
        prompt = append_node_instruction(prompt, node)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(final_payload(state, deps), ensure_ascii=False)},
    ]
    chunks: list[str] = []
    client = deps.final_ollama_factory() if deps.final_ollama_factory is not None else deps.ollama
    final_role = node.role if node is not None else "orchestrator"
    final_model = deps.settings.model_for_role(final_role or "orchestrator")
    started_at = asyncio.get_event_loop().time()
    tokens_in: int | None = None
    tokens_out: int | None = None
    async for event in client.stream_payload(messages, model=final_model):
        event_type = event.get("type")
        if event_type == "token":
            content = str(event.get("content") or "")
            if content:
                chunks.append(content)
                deps.event_sink.emit(node_id, "token", content, record=False)
        elif event_type == "done":
            raw_in = event.get("prompt_eval_count")
            raw_out = event.get("eval_count")
            tokens_in = int(raw_in) if isinstance(raw_in, (int, float)) else None
            tokens_out = int(raw_out) if isinstance(raw_out, (int, float)) else None
    answer = "".join(chunks).strip()
    if not answer:
        raise RuntimeError("Final synthesis completed without text.")
    if deps.trace is not None:
        deps.trace.emit_llm_call(
            node_id=node_id,
            model=final_model or "",
            prompt=messages,
            response=answer,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_ms=int((asyncio.get_event_loop().time() - started_at) * 1000),
        )
    state["final_answer_streamed"] = deps.event_sink.has_callback
    return answer


async def role_call(
    node: WorkflowNode,
    system_prompt: str,
    payload: dict[str, Any],
    deps: WorkflowPhaseDeps,
    *,
    include_node_instruction: bool = True,
) -> str:
    role = node.role or role_for_node_type(node.type)
    prompt = append_node_instruction(system_prompt, node) if include_node_instruction else system_prompt
    if node.expects_json:
        prompt = (
            f"{prompt}\n\n"
            "## Output Format\n"
            "Return strict valid JSON only — a single JSON object that fits "
            "the schema implied by the role and inputs. Do not wrap it in "
            "Markdown code fences, do not add any text before or after the "
            "object, and do not include explanations or commentary."
        )
    model = deps.settings.model_for_role(role)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    started_at = asyncio.get_event_loop().time()
    response = await deps.ollama.chat_payload(
        messages, model=model, response_format="json" if node.expects_json else None
    )
    if deps.trace is not None:
        deps.trace.emit_llm_call(
            node_id=node.id,
            model=model or "",
            prompt=messages,
            response=response,
            duration_ms=int((asyncio.get_event_loop().time() - started_at) * 1000),
        )
    return response


def worker_prompt(node: WorkflowNode, item: dict[str, Any], state: WorkflowState) -> str:
    return build_worker_prompt(
        role=node.role,
        runtime_context=state["runtime_context"],
        effort_context=state["effort_context"],
        memory=state["memory"],
        item=item,
        code_context=str(state.get("code_context") or ""),
        agentic_context=str(state.get("agentic_context") or ""),
        retry_feedback=state.get("retry_feedback"),
        node_instruction=node.prompt,
    )


def state_payload(state: WorkflowState, deps: WorkflowPhaseDeps) -> dict[str, Any]:
    return workflow_state_payload(state, scratchpad=deps.scratchpad)


def final_payload(state: WorkflowState, deps: WorkflowPhaseDeps) -> dict[str, Any]:
    return final_answer_payload(state, scratchpad=deps.scratchpad)


def normalize_work_items(raw_items: Any, user_message: str, limit: int) -> list[dict[str, Any]]:
    if not isinstance(raw_items, list):
        return [default_work_item(user_message)]
    items = []
    for index, item in enumerate(raw_items[:limit], start=1):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or f"item-{index}").strip()
        title = str(item.get("title") or item_id).strip()
        instructions = str(item.get("instructions") or item.get("description") or title).strip()
        owned_paths = item.get("owned_paths") if isinstance(item.get("owned_paths"), list) else []
        items.append(
            {
                "id": item_id or f"item-{index}",
                "title": title or f"Work item {index}",
                "instructions": instructions or user_message,
                "owned_paths": [str(path) for path in owned_paths if str(path).strip()],
            }
        )
    return items or [default_work_item(user_message)]


def normalize_plan_metadata(plan: dict[str, Any], work_item_count: int, max_items: int) -> dict[str, Any]:
    complexity = str(plan.get("complexity") or "").strip().lower()
    if complexity not in {"low", "medium", "high"}:
        complexity = complexity_from_work_items(work_item_count)
    plan["complexity"] = complexity
    plan["recommended_workers"] = clamp_int(plan.get("recommended_workers"), 1, min(max_items, work_item_count))
    return plan


def recommended_worker_count(plan: Any, work_item_count: int) -> int:
    if not isinstance(plan, dict):
        return max(1, work_item_count)
    return clamp_int(plan.get("recommended_workers"), 1, work_item_count)


def complexity_from_work_items(work_item_count: int) -> str:
    if work_item_count <= 1:
        return "low"
    if work_item_count <= 3:
        return "medium"
    return "high"


def clamp_int(value: Any, minimum: int, maximum: int) -> int:
    upper = max(minimum, int(maximum or minimum))
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = upper
    return max(minimum, min(upper, parsed))


def fallback_plan(user_message: str) -> dict[str, Any]:
    return {
        "title": "Handle Request",
        "summary": "Handle the user's request directly.",
        "confidence": 0.5,
        "complexity": "low",
        "recommended_workers": 1,
        "acceptance_criteria": ["Answer the user's request accurately and transparently."],
        "work_items": [default_work_item(user_message)],
    }


def default_work_item(user_message: str) -> dict[str, Any]:
    return {"id": "main", "title": "Handle request", "instructions": user_message, "owned_paths": []}


def note(deps: WorkflowPhaseDeps, state: WorkflowState, title: str, body: str = "") -> None:
    deps.scratchpad.append_note(str(state.get("workflow_run_id") or "workflow"), title, body)


def markdown_data(value: Any) -> str:
    if isinstance(value, str):
        return value[:40_000]
    return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2)[:40_000] + "\n```"


def first_node(workflow: WorkflowDefinition, node_type: str) -> WorkflowNode | None:
    return next((node for node in workflow.nodes if node.type == node_type), None)


def role_for_node_type(node_type: str) -> str:
    mapping = {
        "worker_pool": "worker",
        "reviewer": "reviewer",
        "report": "reviewer",
        "judge": "judge",
        "decision": "judge",
        "role": "orchestrator",
        "answer": "orchestrator",
    }
    return mapping.get(node_type, "assistant")
