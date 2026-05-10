from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Optional

from app import database
from app.agentic_schedule import compute_next_run, is_one_shot_schedule, utc_now_dt
from app.config import load_settings
from app.effort import effort_context
from app.llm.ollama import OllamaClient, OllamaError
from app.memory import memory_context
from app.models import AgenticTask, AgenticTaskRun
from app.roles import role_prompt
from app.runtime_context import runtime_meta_context
from app.tools.registry import registry
from app.workflows.presets import selected_workflow


AUTO_TOOLS = {
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
MAX_TOOL_CALLS = 5
MAX_ATTEMPTS = 2


class AgenticRunner:
    def __init__(self, ollama: Optional[OllamaClient] = None) -> None:
        self.settings = load_settings()
        self.ollama = ollama or OllamaClient(self.settings, timeout=90.0)

    async def run_task(self, task: AgenticTask, reason: str = "scheduled") -> AgenticTaskRun:
        attempt = max(task.failure_count + 1, 1)
        run = database.create_agentic_task_run(task.id, attempt=attempt)
        tool_results: list[dict[str, Any]] = []
        status = "success"
        summary = ""
        error = ""

        try:
            plan = await self._plan(task, reason, [])
            if not isinstance(plan, dict):
                raise ValueError("Agentic model did not return a JSON object.")

            action = str(plan.get("action") or "").strip().lower()
            if action in {"needs_review", "unsupported"}:
                status = "needs_review"
                summary = str(plan.get("summary") or "Task needs review.")
            else:
                tool_results = self._execute_tool_calls(plan.get("tool_calls"))
                summary = await self._summarize(task, reason, tool_results)
                if any(not item.get("success") for item in tool_results):
                    status = "needs_review"
                judge = await self._judge(task, reason, tool_results, summary)
                if judge and str(judge.get("status") or "").strip().lower() != "done":
                    status = "needs_review"
                    summary = self._summary_with_judge(summary, judge)
        except Exception as exc:
            failover = await self._failover(task, reason, exc)
            status = failover["status"]
            summary = failover["summary"]
            tool_results = failover["tool_results"]
            error = str(exc)

        finished = database.finish_agentic_task_run(
            run.id,
            status=status,
            summary=summary,
            tool_results=json.dumps(tool_results, ensure_ascii=False),
            error=error,
        )
        one_shot = is_one_shot_schedule(task.schedule)
        next_run_at = None if one_shot else compute_next_run(task.schedule, utc_now_dt())
        failure_count = 0 if status == "success" else min(task.failure_count + 1, MAX_ATTEMPTS)
        task_status = "paused" if one_shot or (failure_count >= MAX_ATTEMPTS and status != "success") else None
        database.update_agentic_task_schedule_state(
            task.id,
            next_run_at=next_run_at,
            last_run_at=utc_now_dt().isoformat(),
            failure_count=failure_count,
            status=task_status,
        )
        return finished or run

    async def _plan(self, task: AgenticTask, reason: str, prior_errors: list[str]) -> dict[str, Any]:
        content = await self.ollama.chat_payload(
            [
                {"role": "system", "content": self._system_prompt(task)},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "task": task.model_dump(),
                            "language_source": self._task_language_source(task),
                            "reason": reason,
                            "available_tools": self._autonomous_tool_definitions(),
                            "prior_errors": prior_errors,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            model=self.settings.model_for_role("orchestrator"),
        )
        return self._parse_json(content)

    async def _summarize(self, task: AgenticTask, reason: str, tool_results: list[dict[str, Any]]) -> str:
        try:
            content = await self.ollama.chat_payload(
                [
                    {
                        "role": "system",
                        "content": (
                            f"{role_prompt('REVIEWER')}\n\n"
                            f"{runtime_meta_context(self._task_language_source(task))}\n\n"
                            f"{effort_context(self.settings.effort)}\n\n"
                            "Summarize this scheduled task run in compact Markdown.\n"
                            "Hard limits: maximum 4 short lines, no long review essay, no recommendations when everything succeeded.\n"
                            "Mention failed tool calls only when present.\n"
                            "For desktop notifications, never claim the user visibly received a banner. "
                            "Say the notification tool reported success or failure based only on tool_results.\n"
                            "Suggested format:\n"
                            "**Result:** ...\n"
                            "**Tools:** ...\n"
                            "**Status:** ..."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"task": task.model_dump(), "reason": reason, "tool_results": tool_results},
                            ensure_ascii=False,
                        ),
                    },
                ],
                model=self.settings.model_for_role("reviewer"),
            )
            return content.strip()[:4000] or "Task run completed."
        except OllamaError:
            if not tool_results:
                return "Task run completed without tool output."
            successful = sum(1 for item in tool_results if item.get("success"))
            return f"Task run completed with {successful}/{len(tool_results)} successful tool call(s)."

    async def _judge(
        self,
        task: AgenticTask,
        reason: str,
        tool_results: list[dict[str, Any]],
        summary: str,
    ) -> dict[str, Any] | None:
        workflow = selected_workflow(self.settings, "agentic")
        if workflow is None or workflow.is_direct() or workflow.node("judge") is None:
            return None
        try:
            content = await self.ollama.chat_payload(
                [
                    {
                        "role": "system",
                        "content": (
                            f"{role_prompt('JUDGE')}\n\n"
                            f"{runtime_meta_context(self._task_language_source(task))}\n\n"
                            f"{effort_context(self.settings.effort)}\n\n"
                            "You judge a scheduled NixAI Agentic Task run. "
                            "Return strict JSON only: "
                            "{\"status\":\"done|needs_user|retry\",\"reason\":\"...\",\"feedback\":[\"...\"]}. "
                            "Use needs_user when approval, missing access, or missing evidence prevents safe completion."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "task": task.model_dump(),
                                "reason": reason,
                                "summary": summary,
                                "tool_results": tool_results,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                model=self.settings.model_for_role("judge"),
            )
            parsed = self._parse_json(content)
            status = str(parsed.get("status") or "done").strip().lower()
            if status not in {"done", "needs_user", "retry"}:
                parsed["status"] = "done"
            return parsed
        except Exception:
            return {"status": "needs_user", "reason": "Judge could not validate the run result.", "feedback": []}

    def _summary_with_judge(self, summary: str, judge: dict[str, Any]) -> str:
        reason = str(judge.get("reason") or "Judge requested review.").strip()
        feedback = judge.get("feedback") if isinstance(judge.get("feedback"), list) else []
        lines = [summary.strip(), "", f"**Judge:** {reason}"]
        lines.extend(f"- {item}" for item in feedback if str(item).strip())
        return "\n".join(lines).strip()

    async def _failover(self, task: AgenticTask, reason: str, exc: Exception) -> dict[str, Any]:
        tool_results: list[dict[str, Any]] = []
        try:
            if not self._is_autonomous_tool_allowed("nixai_tools_search"):
                raise ValueError("nixai_tools_search requires user approval.")
            search_result = registry.call(
                "nixai_tools_search",
                {"query": task.prompt, "context": {"mode": "read"}, "limit": 5},
            )
            tool_results.append(
                {"tool": "nixai_tools_search", "arguments": {"query": task.prompt}, "success": True, "result": search_result}
            )
            summary = (
                "Agentic failover ran tool discovery after an unexpected model response. "
                "The task needs review before further autonomous execution."
            )
        except Exception as failover_exc:
            tool_results.append(
                {
                    "tool": "nixai_tools_search",
                    "arguments": {"query": task.prompt},
                    "success": False,
                    "error": str(failover_exc),
                }
            )
            summary = "Agentic failover also failed. The task has been marked for review."
        await asyncio.sleep(0)
        return {"status": "needs_review", "summary": summary, "tool_results": tool_results}

    def _execute_tool_calls(self, tool_calls: Any) -> list[dict[str, Any]]:
        if not isinstance(tool_calls, list):
            return []
        results = []
        for raw_call in tool_calls[:MAX_TOOL_CALLS]:
            if not isinstance(raw_call, dict):
                continue
            name = str(raw_call.get("name") or "").strip()
            arguments = raw_call.get("arguments") if isinstance(raw_call.get("arguments"), dict) else {}
            if name not in AUTO_TOOLS:
                results.append({"tool": name, "arguments": arguments, "success": False, "error": "Tool is not approved for autonomous runs."})
                continue
            if not self._is_autonomous_tool_allowed(name):
                results.append(
                    {
                        "tool": name,
                        "arguments": arguments,
                        "success": False,
                        "error": "Tool requires user approval. Allow it permanently in settings or disable tool confirmations.",
                    }
                )
                continue
            try:
                result = registry.call(name, arguments)
                results.append({"tool": name, "arguments": arguments, "success": True, "result": result})
            except Exception as exc:
                results.append({"tool": name, "arguments": arguments, "success": False, "error": str(exc)})
        return results

    def _system_prompt(self, task: AgenticTask) -> str:
        return (
            f"{role_prompt('ORCHESTRATOR')}\n\n"
            f"{runtime_meta_context(self._task_language_source(task))}\n\n"
            f"{effort_context(self.settings.effort)}\n\n"
            f"Shared reviewed memory:\n{memory_context()}\n\n"
            "You are running a scheduled NixAI Agentic Task.\n"
            "Return strict JSON only. Use only listed tools. If tools are missing for the user's request, return needs_review.\n"
            "For reminder, alert, or notification tasks, use nixai_notify_desktop when it is listed. "
            "Call it exactly once with a concise title and the user-facing reminder text. "
            "The notification title and message are user-facing: write them in the same language as the task title and prompt. "
            "If title and prompt disagree, prefer the title language. Do not translate German reminders into English. "
            "If a reminder needs a notification and nixai_notify_desktop is not listed, return needs_review.\n"
            "Schema: {\"action\":\"use_tools|done|needs_review\",\"tool_calls\":[{\"name\":\"...\",\"arguments\":{}}],\"summary\":\"...\"}"
        )

    def _task_language_source(self, task: AgenticTask) -> str:
        return "\n".join(part for part in [task.title.strip(), task.prompt.strip()] if part)

    def _is_autonomous_tool_allowed(self, name: str) -> bool:
        if name not in AUTO_TOOLS:
            return False
        if name == "nixai_notify_desktop":
            return True
        return not self.settings.require_tool_confirmation or self.settings.is_tool_always_allowed(name)

    def _autonomous_tool_definitions(self) -> list[dict[str, Any]]:
        return [tool for tool in registry.public_definitions() if self._is_autonomous_tool_allowed(tool["name"])]

    def _parse_json(self, content: str) -> dict[str, Any]:
        clean = content.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```(?:json)?", "", clean, flags=re.IGNORECASE).strip()
            clean = re.sub(r"```$", "", clean).strip()
        try:
            parsed = json.loads(clean)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", clean)
            if not match:
                raise ValueError("Agentic model response did not contain JSON.")
            parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise ValueError("Agentic model response JSON was not an object.")
        return parsed
