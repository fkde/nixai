from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from app import database
from app.agentic_schedule import utc_now_dt
from app.config import load_settings
from app.json_utils import parse_json_object_strict
from app.llm.ollama import OllamaClient, OllamaError
from app.models import AgenticTask, AgenticTaskRun
from app.services import AgenticTaskService, compose_role_block
from app.services.tool_policy import AUTO_TOOL_NAMES, ToolPolicyService
from app.tools.registry import registry
from app.workflows.presets import selected_workflow
from app.workflows.runtime_trace import TraceEmitter


# Re-exported for backward compatibility with any external import.
AUTO_TOOLS = AUTO_TOOL_NAMES
MAX_TOOL_CALLS = 5
MAX_ATTEMPTS = 2
logger = logging.getLogger(__name__)


class AgenticRunner:
    def __init__(self, ollama: Optional[OllamaClient] = None) -> None:
        self.settings = load_settings()
        self.ollama = ollama or OllamaClient(self.settings, timeout=90.0)
        self.tool_policy = ToolPolicyService(self.settings)
        self.task_service = AgenticTaskService(max_failure_attempts=MAX_ATTEMPTS)

    async def run_inline(
        self,
        *,
        title: str,
        prompt: str,
        reason: str = "workflow",
        context: dict[str, Any] | None = None,
        trace: TraceEmitter | None = None,
        node_id: str = "tool_agent",
    ) -> dict[str, Any]:
        task = AgenticTask(
            id="workflow-inline",
            title=title.strip() or "Workflow tool agent",
            prompt=self._inline_prompt(prompt, context or {}),
            schedule="once",
            status="active",
            next_run_at=None,
            last_run_at=None,
            failure_count=0,
            created_at=utc_now_dt().isoformat(),
            updated_at=utc_now_dt().isoformat(),
        )
        tool_results: list[dict[str, Any]] = []
        status = "success"
        summary = ""
        error = ""

        try:
            plan = await self._plan(task, reason, [])
            action = str(plan.get("action") or "").strip().lower()
            if action in {"needs_review", "unsupported"}:
                status = "needs_review"
                summary = str(plan.get("summary") or "Tool agent needs review.")
            else:
                tool_results = self._execute_tool_calls(plan.get("tool_calls"), trace=trace, node_id=node_id)
                summary = await self._summarize(task, reason, tool_results)
                if any(not item.get("success") for item in tool_results):
                    status = "needs_review"
                judge = await self._judge(task, reason, tool_results, summary)
                if judge and str(judge.get("status") or "").strip().lower() != "done":
                    status = "needs_review"
                    summary = self._summary_with_judge(summary, judge)
        except Exception as exc:
            logger.warning("inline agentic run failed; entering failover title=%s reason=%s", title, reason, exc_info=True)
            failover = await self._failover(task, reason, exc)
            status = failover["status"]
            summary = failover["summary"]
            tool_results = failover["tool_results"]
            error = str(exc)

        return {"status": status, "summary": summary, "tool_results": tool_results, "error": error}

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
            logger.warning(
                "agentic task run failed; entering failover task_id=%s reason=%s", task.id, reason, exc_info=True
            )
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
        self.task_service.record_run_result(task, status=status)
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
                            f"{compose_role_block('REVIEWER', language_source=self._task_language_source(task), effort=self.settings.effort)}\n\n"
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
        self, task: AgenticTask, reason: str, tool_results: list[dict[str, Any]], summary: str
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
                            f"{compose_role_block('JUDGE', language_source=self._task_language_source(task), effort=self.settings.effort)}\n\n"
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
            logger.warning("agentic judge failed task_id=%s reason=%s", task.id, reason, exc_info=True)
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
                "nixai_tools_search", {"query": task.prompt, "context": {"mode": "read"}, "limit": 5}
            )
            tool_results.append(
                {
                    "tool": "nixai_tools_search",
                    "arguments": {"query": task.prompt},
                    "success": True,
                    "result": search_result,
                }
            )
            summary = (
                "Agentic failover ran tool discovery after an unexpected model response. "
                "The task needs review before further autonomous execution."
            )
        except Exception as failover_exc:
            logger.warning(
                "agentic failover tool discovery failed task_id=%s original_error=%s",
                task.id,
                exc,
                exc_info=True,
            )
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

    def _execute_tool_calls(
        self, tool_calls: Any, *, trace: TraceEmitter | None = None, node_id: str = "tool_agent"
    ) -> list[dict[str, Any]]:
        if not isinstance(tool_calls, list):
            return []
        results = []
        for raw_call in tool_calls[:MAX_TOOL_CALLS]:
            if not isinstance(raw_call, dict):
                continue
            name = str(raw_call.get("name") or "").strip()
            arguments = raw_call.get("arguments") if isinstance(raw_call.get("arguments"), dict) else {}
            if name not in AUTO_TOOLS:
                error = "Tool is not approved for autonomous runs."
                results.append({"tool": name, "arguments": arguments, "success": False, "error": error})
                self._emit_tool_trace(trace, node_id, name, arguments, error=error, allowed=False)
                continue
            if not self._is_autonomous_tool_allowed(name):
                error = "Tool requires user approval. Allow it permanently in settings or disable tool confirmations."
                results.append({"tool": name, "arguments": arguments, "success": False, "error": error})
                self._emit_tool_trace(trace, node_id, name, arguments, error=error, allowed=False)
                continue
            started_iso = utc_now_dt().isoformat()
            started_perf = time.perf_counter()
            try:
                result = registry.call(name, arguments)
                results.append({"tool": name, "arguments": arguments, "success": True, "result": result})
                self._emit_tool_trace(
                    trace,
                    node_id,
                    name,
                    arguments,
                    result=result,
                    allowed=True,
                    started_at=started_iso,
                    duration_ms=int((time.perf_counter() - started_perf) * 1000),
                )
            except Exception as exc:
                logger.warning("autonomous tool call failed tool=%s arguments=%s", name, arguments, exc_info=True)
                results.append({"tool": name, "arguments": arguments, "success": False, "error": str(exc)})
                self._emit_tool_trace(
                    trace,
                    node_id,
                    name,
                    arguments,
                    error=str(exc),
                    allowed=True,
                    started_at=started_iso,
                    duration_ms=int((time.perf_counter() - started_perf) * 1000),
                )
        return results

    def _emit_tool_trace(
        self,
        trace: TraceEmitter | None,
        node_id: str,
        name: str,
        arguments: dict[str, Any],
        *,
        result: Any = None,
        error: Any = None,
        allowed: bool,
        started_at: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        if trace is None:
            return
        trace.emit_tool_call(
            node_id=node_id,
            tool_name=name,
            arguments=arguments,
            result=result,
            error=error,
            approval_context={
                "autonomous": True,
                "allowed": allowed,
                "require_tool_confirmation": self.settings.require_tool_confirmation,
                "always_allowed": self.settings.is_tool_always_allowed(name),
            },
            security_context={
                "auto_tool": name in AUTO_TOOLS,
                "write_capable": False,
                "policy": "scheduled/autonomous-safe allowlist",
            },
            started_at=started_at,
            finished_at=utc_now_dt().isoformat(),
            duration_ms=duration_ms,
            replayable=bool(allowed and error is None),
        )

    def _system_prompt(self, task: AgenticTask) -> str:
        prefix = compose_role_block(
            "ORCHESTRATOR",
            language_source=self._task_language_source(task),
            effort=self.settings.effort,
            include_memory=True,
        )
        return (
            f"{prefix}\n\n"
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

    def _inline_prompt(self, prompt: str, context: dict[str, Any]) -> str:
        if not context:
            return prompt.strip()
        return (
            f"{prompt.strip()}\n\nWorkflow node context:\n{json.dumps(context, ensure_ascii=False, indent=2)[:12000]}"
        ).strip()

    def _is_autonomous_tool_allowed(self, name: str) -> bool:
        return self.tool_policy.is_autonomous(name)

    def _autonomous_tool_definitions(self) -> list[dict[str, Any]]:
        return [tool for tool in registry.public_definitions() if self._is_autonomous_tool_allowed(tool["name"])]

    def _parse_json(self, content: str) -> dict[str, Any]:
        return parse_json_object_strict(
            content,
            not_found_message="Agentic model response did not contain JSON.",
            not_object_message="Agentic model response JSON was not an object.",
        )
