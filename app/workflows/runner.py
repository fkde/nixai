from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any, Optional

from app import database
from app.code_context import CodeContextBuilder
from app.config import Settings, load_settings
from app.llm.ollama import OllamaClient
from app.memory import memory_context
from app.models import MessageMode
from app.roles import role_prompt
from app.runtime_context import runtime_meta_context
from app.workflows.models import WorkflowDefinition, WorkflowEvent, WorkflowNode, WorkflowResult


class WorkflowRunner:
    def __init__(self, settings: Optional[Settings] = None, ollama: Optional[OllamaClient] = None) -> None:
        self.settings = settings or load_settings()
        self.ollama = ollama or OllamaClient(self.settings)
        self._on_event: Callable[[WorkflowEvent], None] | None = None

    async def run(
        self,
        workflow: WorkflowDefinition,
        chat_id: str,
        user_message: str,
        mode: MessageMode,
        on_event: Callable[[WorkflowEvent], None] | None = None,
    ) -> WorkflowResult:
        self._on_event = on_event
        try:
            state = self._initial_state(chat_id, user_message, mode)
            events: list[WorkflowEvent] = []

            self._event(events, "start", "status", f"Workflow started: {workflow.name}")
            plan = await self._build_plan(workflow, state, events)
            state["plan"] = plan

            max_iterations = workflow.max_iterations
            reports: list[dict[str, Any]] = []
            review: dict[str, Any] = {}
            decision: dict[str, Any] = {"status": "done", "reason": ""}

            for iteration in range(1, max_iterations + 1):
                state["iteration"] = iteration
                if max_iterations > 1:
                    self._event(events, "loop", "status", f"Workflow iteration {iteration}/{max_iterations} started.")
                reports = await self._run_workers(workflow, state, events)
                state["worker_reports"] = reports
                review = await self._review(workflow, state, events)
                state["review"] = review
                decision = await self._judge(workflow, state, events)
                state["decision"] = decision

                status = str(decision.get("status") or "done").strip().lower()
                if status != "retry":
                    break
                if iteration >= max_iterations:
                    decision["status"] = "needs_user"
                    decision["reason"] = decision.get("reason") or "Retry limit reached."
                    break
                state["retry_feedback"] = decision.get("feedback") or decision.get("reason") or "Retry requested."
                self._event(events, "judge", "retry", f"Judge requested another worker pass ({iteration + 1}/{max_iterations}).")

            answer = await self._final_answer(workflow, state, events)
            return WorkflowResult(
                workflow_id=workflow.id,
                answer=answer,
                status=str(decision.get("status") or "done"),
                events=events,
                state=self._compact_state(state),
            )
        finally:
            self._on_event = None

    def _initial_state(self, chat_id: str, user_message: str, mode: MessageMode) -> dict[str, Any]:
        workspace = ""
        if mode == "code":
            chat = database.get_chat(chat_id)
            workspace = (chat.workspace_path if chat and chat.workspace_path.strip() else self.settings.workspace_path).strip()
        history = database.list_messages(chat_id, mode=mode)[-8:]
        code_context = CodeContextBuilder(workspace).build(user_message) if mode == "code" else ""
        return {
            "chat_id": chat_id,
            "mode": mode,
            "user_message": user_message,
            "workspace": workspace,
            "runtime_context": runtime_meta_context(user_message),
            "memory": memory_context(),
            "code_context": code_context,
            "history": [
                {"role": message.role, "content": message.content[:4000]}
                for message in history
                if message.role in {"user", "assistant"}
            ],
        }

    async def _build_plan(
        self,
        workflow: WorkflowDefinition,
        state: dict[str, Any],
        events: list[WorkflowEvent],
    ) -> dict[str, Any]:
        node = workflow.node("orchestrator") or self._first_node(workflow, "role")
        if node is None:
            return self._fallback_plan(state["user_message"])

        self._event(events, node.id, "status", "Summarizing task for orchestrator.")
        prompt = (
            f"{role_prompt(node.role or 'ORCHESTRATOR')}\n\n"
            f"{state['runtime_context']}\n\n"
            f"Shared reviewed memory:\n{state['memory']}\n\n"
            "Create a compact execution plan for this NixAI workflow.\n"
            "Return strict JSON only with this schema:\n"
            "{"
            "\"summary\":\"...\","
            "\"acceptance_criteria\":[\"...\"],"
            "\"work_items\":[{\"id\":\"short-id\",\"title\":\"...\",\"instructions\":\"...\",\"owned_paths\":[\"optional/path\"]}]"
            "}\n"
            f"Maximum work items: {node.max_items}.\n"
            "Keep work items independent when possible so worker_pool can run them in parallel."
        )
        content = await self._role_call(node, prompt, self._state_payload(state))
        plan = self._parse_json(content, self._fallback_plan(state["user_message"]))
        plan["work_items"] = self._normalize_work_items(plan.get("work_items"), state["user_message"], node.max_items)
        self._event(events, node.id, "done", f"Orchestrator created {len(plan['work_items'])} work item(s).")
        return plan

    async def _run_workers(
        self,
        workflow: WorkflowDefinition,
        state: dict[str, Any],
        events: list[WorkflowEvent],
    ) -> list[dict[str, Any]]:
        node = workflow.node("workers") or self._first_node(workflow, "worker_pool")
        if node is None:
            return []

        work_items = self._normalize_work_items(
            state.get("plan", {}).get("work_items"),
            state["user_message"],
            node.max_items,
        )
        limit = max(1, min(node.max_parallel, len(work_items)))
        semaphore = asyncio.Semaphore(limit)
        self._event(events, node.id, "status", f"Orchestrator spawned {len(work_items)} worker item(s), max parallel {limit}.")

        async def run_item(item: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                item_id = str(item.get("id") or "work-item")
                title = str(item.get("title") or item_id)
                self._event(events, item_id, "status", f"Worker started: {title}.")
                prompt = self._worker_prompt(node, item, state)
                content = await self._role_call(node, prompt, self._state_payload(state))
                self._event(events, item_id, "done", f"Worker completed: {title}.")
                return {"id": item_id, "title": title, "content": content.strip()}

        reports = await asyncio.gather(*(run_item(item) for item in work_items))
        self._event(events, node.id, "done", f"Worker pool completed {len(reports)} report(s).")
        return reports

    async def _review(
        self,
        workflow: WorkflowDefinition,
        state: dict[str, Any],
        events: list[WorkflowEvent],
    ) -> dict[str, Any]:
        node = workflow.node("reviewer") or self._first_node(workflow, "reviewer")
        if node is None:
            return {"status": "approved", "summary": "No reviewer node configured.", "findings": []}

        self._event(events, node.id, "status", "Reviewer is checking worker reports.")
        prompt = (
            f"{role_prompt(node.role or 'REVIEWER')}\n\n"
            f"{state['runtime_context']}\n\n"
            "Review the worker reports against the plan and acceptance criteria.\n"
            "Return strict JSON only with this schema:\n"
            "{\"status\":\"approved|changes_requested\",\"summary\":\"...\",\"findings\":[{\"severity\":\"low|medium|high\",\"message\":\"...\"}]}.\n"
            "Do not invent test results or file changes."
        )
        content = await self._role_call(node, prompt, self._state_payload(state))
        review = self._parse_json(content, {"status": "changes_requested", "summary": content.strip(), "findings": []})
        self._event(events, node.id, "done", f"Reviewer status: {review.get('status', 'unknown')}.")
        return review

    async def _judge(
        self,
        workflow: WorkflowDefinition,
        state: dict[str, Any],
        events: list[WorkflowEvent],
    ) -> dict[str, Any]:
        node = workflow.node("judge") or self._first_node(workflow, "judge")
        if node is None:
            return {"status": "done", "reason": "No judge node configured.", "feedback": []}

        self._event(events, node.id, "status", "Judge is deciding whether the task is done.")
        prompt = (
            f"{role_prompt(node.role or 'JUDGE')}\n\n"
            f"{state['runtime_context']}\n\n"
            "Decide whether this workflow has enough evidence to answer the user.\n"
            "Return strict JSON only with this schema:\n"
            "{\"status\":\"done|retry|needs_user\",\"reason\":\"...\",\"feedback\":[\"...\"],\"final_answer\":\"optional user-facing answer\"}.\n"
            "Use retry only when a worker can improve the result without asking the user. "
            "Use needs_user when required information, approval, or tool access is missing."
        )
        content = await self._role_call(node, prompt, self._state_payload(state))
        decision = self._parse_json(content, {"status": "done", "reason": content.strip(), "feedback": []})
        status = str(decision.get("status") or "done").strip().lower()
        if status not in {"done", "retry", "needs_user"}:
            decision["status"] = "done"
        self._event(events, node.id, "done", f"Judge decision: {decision.get('status', 'done')}.")
        return decision

    async def _final_answer(
        self,
        workflow: WorkflowDefinition,
        state: dict[str, Any],
        events: list[WorkflowEvent],
    ) -> str:
        decision = state.get("decision") if isinstance(state.get("decision"), dict) else {}
        final_answer = str(decision.get("final_answer") or "").strip()
        if final_answer:
            return final_answer

        status = str(decision.get("status") or "done").strip().lower()
        if status == "needs_user":
            reason = str(decision.get("reason") or "I need more input before I can finish this.").strip()
            feedback = decision.get("feedback") if isinstance(decision.get("feedback"), list) else []
            lines = [reason]
            lines.extend(f"- {item}" for item in feedback if str(item).strip())
            return "\n".join(lines).strip()

        self._event(events, "final", "status", "Preparing final answer.")
        prompt = (
            f"{role_prompt('ORCHESTRATOR')}\n\n"
            f"{state['runtime_context']}\n\n"
            "Write the final answer for the user from the workflow state. "
            "Match the user's language. Be concise, concrete, and transparent about missing verification. "
            "Do not mention internal JSON unless it matters."
        )
        return (
            await self.ollama.chat_payload(
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(self._state_payload(state), ensure_ascii=False)},
                ],
                model=self.settings.model_for_role("orchestrator"),
            )
        ).strip()

    async def _role_call(self, node: WorkflowNode, system_prompt: str, payload: dict[str, Any]) -> str:
        role = node.role or self._role_for_node_type(node.type)
        return await self.ollama.chat_payload(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            model=self.settings.model_for_role(role),
        )

    def _worker_prompt(self, node: WorkflowNode, item: dict[str, Any], state: dict[str, Any]) -> str:
        retry_feedback = state.get("retry_feedback")
        prompt = (
            f"{role_prompt(node.role or 'WORKER')}\n\n"
            f"{state['runtime_context']}\n\n"
            f"Shared reviewed memory:\n{state['memory']}\n\n"
            "Execute this assigned workflow item as far as possible from the provided context.\n"
            "Return concise Markdown with: result, evidence, open risks, and recommended next checks.\n"
            "Do not claim tools, tests, or file edits were run unless they are visible in the supplied context.\n\n"
            f"Assigned item:\n{json.dumps(item, ensure_ascii=False, indent=2)}"
        )
        if state.get("code_context"):
            prompt += f"\n\nWorkspace context:\n{state['code_context']}"
        if retry_feedback:
            prompt += f"\n\nRetry feedback from Judge:\n{retry_feedback}"
        return prompt

    def _state_payload(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "mode": state.get("mode"),
            "user_message": state.get("user_message"),
            "workspace": state.get("workspace"),
            "history": state.get("history", []),
            "plan": state.get("plan"),
            "worker_reports": state.get("worker_reports"),
            "review": state.get("review"),
            "decision": state.get("decision"),
            "retry_feedback": state.get("retry_feedback"),
        }
        if state.get("code_context"):
            payload["code_context"] = str(state["code_context"])[:12000]
        return payload

    def _compact_state(self, state: dict[str, Any]) -> dict[str, Any]:
        compact = self._state_payload(state)
        if "code_context" in compact:
            compact["code_context"] = "[omitted]"
        return compact

    def _parse_json(self, content: str, fallback: dict[str, Any]) -> dict[str, Any]:
        clean = content.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```(?:json)?", "", clean, flags=re.IGNORECASE).strip()
            clean = re.sub(r"```$", "", clean).strip()
        try:
            parsed = json.loads(clean)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", clean)
            if not match:
                return fallback
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                return fallback
        return parsed if isinstance(parsed, dict) else fallback

    def _normalize_work_items(self, raw_items: Any, user_message: str, limit: int) -> list[dict[str, Any]]:
        if not isinstance(raw_items, list):
            return [self._default_work_item(user_message)]
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
        return items or [self._default_work_item(user_message)]

    def _fallback_plan(self, user_message: str) -> dict[str, Any]:
        return {
            "summary": "Handle the user's request directly.",
            "acceptance_criteria": ["Answer the user's request accurately and transparently."],
            "work_items": [self._default_work_item(user_message)],
        }

    def _default_work_item(self, user_message: str) -> dict[str, Any]:
        return {
            "id": "main",
            "title": "Handle request",
            "instructions": user_message,
            "owned_paths": [],
        }

    def _first_node(self, workflow: WorkflowDefinition, node_type: str) -> WorkflowNode | None:
        return next((node for node in workflow.nodes if node.type == node_type), None)

    def _role_for_node_type(self, node_type: str) -> str:
        mapping = {
            "worker_pool": "worker",
            "reviewer": "reviewer",
            "judge": "judge",
            "role": "orchestrator",
        }
        return mapping.get(node_type, "assistant")

    def _event(
        self,
        events: list[WorkflowEvent],
        node: str,
        event_type: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        event = WorkflowEvent(node=node, type=event_type, message=message, details=details or {})
        events.append(event)
        if self._on_event is not None:
            self._on_event(event)
