from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any, Optional

from app import database
from app.agentic_context import AgenticContextBuilder
from app.code_context import CodeContextBuilder
from app.config import Settings, load_settings
from app.effort import effort_context, effort_max_items, effort_max_parallel, normalize_effort
from app.llm.ollama import OllamaClient
from app.memory import memory_context
from app.models import MessageMode
from app.roles import role_prompt
from app.runtime_context import runtime_meta_context
from app.workflow_scratch import append_workflow_note, new_workflow_run_id, read_workflow_notes, workflow_scratch_path
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
            append_workflow_note(
                str(state["workflow_run_id"]),
                f"Workflow started: {workflow.name}",
                self._markdown_data(
                    {
                        "mode": mode,
                        "chat_id": chat_id,
                        "request": user_message,
                        "scratchpad": state["workflow_scratch_path"],
                    }
                ),
            )
            if mode == "agentic":
                self._event(events, "context", "status", "Preparing agentic tool context.")
                state["agentic_context"] = await AgenticContextBuilder(self.settings, self.ollama).build(user_message)
                self._note(state, "Agentic tool context", state["agentic_context"] or "No tool context gathered.")
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
                self._note(state, f"Iteration {iteration} worker reports", self._markdown_data(reports))
                review = await self._review(workflow, state, events)
                state["review"] = review
                self._note(state, f"Iteration {iteration} review", self._markdown_data(review))
                decision = await self._judge(workflow, state, events)
                state["decision"] = decision
                self._note(state, f"Iteration {iteration} judge decision", self._markdown_data(decision))
                self._record_round(state, reports, review, decision)

                status = str(decision.get("status") or "done").strip().lower()
                if status != "retry":
                    break
                if iteration >= max_iterations:
                    decision["status"] = "done"
                    decision["reason"] = (
                        "Retry limit reached. Synthesize the best user-facing answer from all available evidence, "
                        "including caveats and missing verification."
                    )
                    state["decision"] = decision
                    self._event(events, "judge", "done", "Retry limit reached; synthesizing final answer from available evidence.")
                    self._note(state, "Retry limit reached", self._markdown_data(decision))
                    break
                state["retry_feedback"] = decision.get("feedback") or decision.get("reason") or "Retry requested."
                self._event(events, "judge", "retry", f"Judge requested another worker pass ({iteration + 1}/{max_iterations}).")
                state["plan"] = await self._replan_for_retry(workflow, state, events)

            answer = await self._final_answer(workflow, state, events)
            self._note(state, "Final answer", answer)
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
            "workflow_run_id": new_workflow_run_id(),
            "workflow_scratch_path": str(workflow_scratch_path()),
            "workflow_rounds": [],
            "effort": normalize_effort(self.settings.effort),
            "effort_context": effort_context(self.settings.effort),
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

    async def _build_plan(
        self,
        workflow: WorkflowDefinition,
        state: dict[str, Any],
        events: list[WorkflowEvent],
    ) -> dict[str, Any]:
        node = workflow.node("orchestrator") or self._first_node(workflow, "role")
        if node is None:
            return self._fallback_plan(state["user_message"])

        max_items = effort_max_items(node.max_items, state.get("effort"))
        self._event(events, node.id, "status", "Summarizing task for orchestrator.")
        prompt = (
            f"{role_prompt(node.role or 'ORCHESTRATOR')}\n\n"
            f"{state['runtime_context']}\n\n"
            f"{state['effort_context']}\n\n"
            f"Shared reviewed memory:\n{state['memory']}\n\n"
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
        content = await self._role_call(node, prompt, self._state_payload(state))
        plan = self._parse_json(content, self._fallback_plan(state["user_message"]))
        plan["work_items"] = self._normalize_work_items(plan.get("work_items"), state["user_message"], max_items)
        self._update_chat_title_from_plan(str(state.get("chat_id") or ""), plan)
        self._event(events, node.id, "done", f"Orchestrator created {len(plan['work_items'])} work item(s).")
        self._note(state, "Initial workflow plan", self._markdown_data(plan))
        return plan

    async def _replan_for_retry(
        self,
        workflow: WorkflowDefinition,
        state: dict[str, Any],
        events: list[WorkflowEvent],
    ) -> dict[str, Any]:
        node = workflow.node("orchestrator") or self._first_node(workflow, "role")
        if node is None:
            return self._fallback_plan(state["user_message"])

        max_items = effort_max_items(node.max_items, state.get("effort"))
        self._event(events, node.id, "status", "Replanning retry with prior findings.")
        prompt = (
            f"{role_prompt(node.role or 'ORCHESTRATOR')}\n\n"
            f"{state['runtime_context']}\n\n"
            f"{state['effort_context']}\n\n"
            f"Shared reviewed memory:\n{state['memory']}\n\n"
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
        content = await self._role_call(node, prompt, self._state_payload(state))
        plan = self._parse_json(content, self._fallback_plan(state["user_message"]))
        plan["work_items"] = self._normalize_work_items(plan.get("work_items"), state["user_message"], max_items)
        self._event(events, node.id, "done", f"Orchestrator replanned {len(plan['work_items'])} retry item(s).")
        self._note(state, "Retry workflow plan", self._markdown_data(plan))
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
            effort_max_items(node.max_items, state.get("effort")),
        )
        pool_size = max(1, node.worker_instances)
        concurrency_cap = max(1, node.max_parallel)
        configured_parallel = min(pool_size, concurrency_cap)
        limit = max(1, min(effort_max_parallel(configured_parallel, state.get("effort")), len(work_items)))
        semaphore = asyncio.Semaphore(limit)
        self._event(
            events,
            node.id,
            "status",
            (
                f"Orchestrator spawned {len(work_items)} worker item(s), "
                f"worker pool {pool_size}, concurrency cap {concurrency_cap}, active parallel {limit}."
            ),
        )

        async def run_item(item: dict[str, Any], item_index: int) -> dict[str, Any]:
            async with semaphore:
                item_id = str(item.get("id") or "work-item")
                title = str(item.get("title") or item_id)
                worker_label = f"worker-{(item_index % limit) + 1}"
                self._event(events, item_id, "status", f"{worker_label} started: {title}.")
                prompt = self._worker_prompt(node, item, state)
                content = await self._role_call(node, prompt, self._state_payload(state))
                self._event(events, item_id, "done", f"{worker_label} completed: {title}.")
                return {"id": item_id, "title": title, "worker": worker_label, "content": content.strip()}

        reports = await asyncio.gather(*(run_item(item, index) for index, item in enumerate(work_items)))
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
            f"{state['effort_context']}\n\n"
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
            f"{state['effort_context']}\n\n"
            "Decide whether this workflow has enough evidence to answer the user.\n"
            "Return strict JSON only with this schema:\n"
            "{\"status\":\"done|retry|needs_user\",\"reason\":\"...\",\"feedback\":[\"...\"],\"final_answer\":\"optional user-facing answer\"}.\n"
            "Use retry only when a worker can improve the result without asking the user. "
            "Use needs_user when required information, approval, or tool access is missing. "
            "If the only missing piece is final synthesis or wording, use done and provide a user-facing final_answer. "
            "Never put internal deliberation, reviewer-only commentary, or retry rationale in final_answer."
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
            f"{state['effort_context']}\n\n"
            "Write the final answer for the user from the workflow state. "
            "Match the user's language. Be concise, concrete, and transparent about missing verification. "
            "Synthesize across all workflow rounds, worker reports, review findings, judge feedback, and the workflow scratchpad. "
            "Never output internal Judge/Reviewer reasoning as the answer. Do not say a retry is required. "
            "If evidence is incomplete, give the best grounded answer and clearly label what could not be verified. "
            "Do not mention internal JSON unless it matters."
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(self._final_answer_payload(state), ensure_ascii=False)},
        ]
        chunks: list[str] = []
        final_ollama = OllamaClient(self.settings, timeout=600.0)
        async for event in final_ollama.stream_payload(messages, model=self.settings.model_for_role("orchestrator")):
            if event.get("type") == "token":
                content = str(event.get("content") or "")
                if content:
                    chunks.append(content)
                    self._event(events, "final", "token", content, record=False)
        answer = "".join(chunks).strip()
        if not answer:
            raise RuntimeError("Final synthesis completed without text.")
        state["final_answer_streamed"] = bool(self._on_event)
        return answer

    async def _role_call(self, node: WorkflowNode, system_prompt: str, payload: dict[str, Any]) -> str:
        role = node.role or self._role_for_node_type(node.type)
        prompt = system_prompt
        if node.expects_json:
            # Force JSON output at two layers: a clear instruction in the prompt
            # so the model knows what shape to produce, and Ollama's strict
            # response_format so it cannot wrap the answer in Markdown fences
            # or chat preamble. Users only flip the switch — the runner adds
            # the boilerplate so role markdown stays focused on the role itself.
            prompt = (
                f"{system_prompt}\n\n"
                "## Output Format\n"
                "Return strict valid JSON only — a single JSON object that fits "
                "the schema implied by the role and inputs. Do not wrap it in "
                "Markdown code fences, do not add any text before or after the "
                "object, and do not include explanations or commentary."
            )
        return await self.ollama.chat_payload(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            model=self.settings.model_for_role(role),
            response_format="json" if node.expects_json else None,
        )

    def _worker_prompt(self, node: WorkflowNode, item: dict[str, Any], state: dict[str, Any]) -> str:
        retry_feedback = state.get("retry_feedback")
        prompt = (
            f"{role_prompt(node.role or 'WORKER')}\n\n"
            f"{state['runtime_context']}\n\n"
            f"{state['effort_context']}\n\n"
            f"Shared reviewed memory:\n{state['memory']}\n\n"
            "Execute this assigned workflow item as far as possible from the provided context.\n"
            "Return concise Markdown with: result, evidence, open risks, and recommended next checks.\n"
            "Do not claim tools, tests, or file edits were run unless they are visible in the supplied context.\n\n"
            f"Assigned item:\n{json.dumps(item, ensure_ascii=False, indent=2)}"
        )
        if state.get("code_context"):
            prompt += f"\n\nWorkspace context:\n{state['code_context']}"
        if state.get("agentic_context"):
            prompt += f"\n\nAgentic tool context:\n{state['agentic_context']}"
        if retry_feedback:
            prompt += f"\n\nRetry feedback from Judge:\n{retry_feedback}"
        return prompt

    def _state_payload(self, state: dict[str, Any]) -> dict[str, Any]:
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
            "workflow_rounds": self._compact_rounds(state.get("workflow_rounds")),
        }
        if state.get("code_context"):
            payload["code_context"] = str(state["code_context"])[:12000]
        if state.get("agentic_context"):
            payload["agentic_context"] = str(state["agentic_context"])[:16000]
        scratch = read_workflow_notes(str(state.get("workflow_run_id") or ""))
        if scratch:
            payload["workflow_scratchpad"] = scratch[:16000]
        return payload

    def _final_answer_payload(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = self._state_payload(state)
        payload.pop("code_context", None)
        payload.pop("agentic_context", None)
        payload["worker_reports"] = self._compact_reports(state.get("worker_reports"), limit=1800)
        payload["workflow_rounds"] = self._compact_rounds(state.get("workflow_rounds"), report_limit=1200)
        if "workflow_scratchpad" in payload:
            payload["workflow_scratchpad"] = str(payload["workflow_scratchpad"])[:6000]
        return payload

    def _compact_state(self, state: dict[str, Any]) -> dict[str, Any]:
        compact = self._state_payload(state)
        if "code_context" in compact:
            compact["code_context"] = "[omitted]"
        if "agentic_context" in compact:
            compact["agentic_context"] = "[omitted]"
        if state.get("final_answer_streamed"):
            compact["answer_streamed"] = True
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
            "title": "Handle Request",
            "summary": "Handle the user's request directly.",
            "acceptance_criteria": ["Answer the user's request accurately and transparently."],
            "work_items": [self._default_work_item(user_message)],
        }

    def _update_chat_title_from_plan(self, chat_id: str, plan: dict[str, Any]) -> None:
        if not chat_id:
            return
        title = self._clean_chat_title(str(plan.get("title") or ""))
        if not title:
            title = self._clean_chat_title(str(plan.get("summary") or ""))
        if title:
            database.update_chat_title_if_default(chat_id, title)

    def _clean_chat_title(self, title: str) -> str:
        clean = " ".join(str(title or "").strip().split())
        clean = clean.strip("\"'`“”„")
        clean = clean.removeprefix("- ").removeprefix("* ").strip()
        clean = clean.rstrip(".:;")
        if not clean or clean in {"New Chat", "Neuer Chat"}:
            return ""
        words = clean.split()
        if len(words) > 7:
            clean = " ".join(words[:7])
        return clean[:56]

    def _default_work_item(self, user_message: str) -> dict[str, Any]:
        return {
            "id": "main",
            "title": "Handle request",
            "instructions": user_message,
            "owned_paths": [],
        }

    def _record_round(
        self,
        state: dict[str, Any],
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

    def _compact_rounds(self, rounds: Any, report_limit: int = 3000) -> list[dict[str, Any]]:
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
                    "worker_reports": self._compact_reports(item.get("worker_reports"), limit=report_limit),
                    "review": item.get("review"),
                    "decision": item.get("decision"),
                }
            )
        return compact

    def _compact_reports(self, reports: Any, limit: int = 3000) -> list[dict[str, str]]:
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

    def _note(self, state: dict[str, Any], title: str, body: str = "") -> None:
        append_workflow_note(str(state.get("workflow_run_id") or "workflow"), title, body)

    def _markdown_data(self, value: Any) -> str:
        if isinstance(value, str):
            return value[:40_000]
        return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2)[:40_000] + "\n```"

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
        record: bool = True,
    ) -> None:
        event = WorkflowEvent(node=node, type=event_type, message=message, details=details or {})
        if record:
            events.append(event)
        if self._on_event is not None:
            self._on_event(event)
