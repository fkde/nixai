from __future__ import annotations

import json
import re
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from app.agentic_schedule import normalize_one_shot_schedule, parse_one_shot_schedule, utc_now_dt
from app.config import Settings
from app.effort import effort_context
from app.json_utils import parse_json_object_strict
from app.llm.ollama import OllamaClient, OllamaError
from app.roles import role_prompt
from app.runtime_context import runtime_meta_context


class TaskDiscoveryResult(BaseModel):
    kind: str = "chat"
    confidence: float = 0.0
    title: str = ""
    prompt: str = ""
    schedule: str = ""
    missing_info: list[str] = Field(default_factory=list)
    reason: str = ""

    @property
    def canonical_kind(self) -> str:
        return self.kind.strip().casefold().replace("-", "_").replace(" ", "_")

    @property
    def is_recurring_task(self) -> bool:
        return self.canonical_kind == "recurring_task" and self.confidence >= 0.62 and bool(self.schedule.strip())

    @property
    def is_one_shot_task(self) -> bool:
        return self.canonical_kind in {"one_shot_task", "one_time_task"} and self.confidence >= 0.62 and bool(self.schedule.strip())

    @property
    def is_scheduled_task(self) -> bool:
        return self.is_recurring_task or self.is_one_shot_task


class TaskDiscovery:
    def __init__(self, settings: Settings, ollama: Optional[OllamaClient] = None) -> None:
        self.settings = settings
        self.ollama = ollama or OllamaClient(settings, timeout=30.0)

    async def discover(self, user_message: str) -> TaskDiscoveryResult:
        try:
            result = await self._discover_with_model(user_message)
            result = await self._review_if_needed(user_message, result)
        except (OllamaError, ValidationError):
            result = self._fallback(user_message)
        result = self._finalize_result(user_message, result)
        result = await self._repair_if_invalid(user_message, result)
        return result

    def _finalize_result(self, user_message: str, result: TaskDiscoveryResult) -> TaskDiscoveryResult:
        if result.canonical_kind in {"one_time_task"}:
            result.kind = "one_shot_task"
        elif result.canonical_kind in {"recurring_task", "one_shot_task", "chat"}:
            result.kind = result.canonical_kind
        if result.canonical_kind == "chat":
            result.missing_info = []
            result.schedule = ""
        if not result.prompt:
            result.prompt = user_message
        if not result.title:
            result.title = self._title_from_prompt(user_message)
        if result.is_one_shot_task:
            result.schedule = normalize_one_shot_schedule(result.schedule)
        return result

    async def _discover_with_model(self, user_message: str) -> TaskDiscoveryResult:
        content = await self.ollama.chat_payload(
            [
                {"role": "system", "content": self._system_prompt(user_message)},
                {"role": "user", "content": user_message},
            ],
            model=self.settings.model_for_role("task_discovery"),
        )
        data = self._parse_json(content)
        return TaskDiscoveryResult.model_validate(data)

    async def _repair_if_invalid(self, user_message: str, result: TaskDiscoveryResult) -> TaskDiscoveryResult:
        if not self._one_shot_is_past(result):
            return result
        try:
            repaired = await self._repair_with_model(user_message, result)
        except (OllamaError, ValidationError):
            result.missing_info = ["The requested one-time schedule resolved to the past. Please confirm the intended future date/time."]
            result.schedule = ""
            return result
        repaired = self._finalize_result(user_message, repaired)
        if self._one_shot_is_past(repaired):
            repaired.missing_info = ["The requested one-time schedule resolved to the past. Please confirm the intended future date/time."]
            repaired.schedule = ""
        return repaired

    async def _repair_with_model(self, user_message: str, result: TaskDiscoveryResult) -> TaskDiscoveryResult:
        content = await self.ollama.chat_payload(
            [
                {"role": "system", "content": self._repair_prompt(user_message)},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "user_message": user_message,
                            "invalid_result": result.model_dump(),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            model=self.settings.model_for_role("task_discovery"),
        )
        data = self._parse_json(content)
        return TaskDiscoveryResult.model_validate(data)

    async def _review_if_needed(self, user_message: str, result: TaskDiscoveryResult) -> TaskDiscoveryResult:
        try:
            reviewed = await self._review_with_model(user_message, result)
        except (OllamaError, ValidationError):
            return result
        if reviewed.is_scheduled_task or reviewed.missing_info or reviewed.canonical_kind == "chat":
            return reviewed
        return result

    async def _review_with_model(self, user_message: str, result: TaskDiscoveryResult) -> TaskDiscoveryResult:
        content = await self.ollama.chat_payload(
            [
                {"role": "system", "content": self._review_prompt(user_message)},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "user_message": user_message,
                            "first_result": result.model_dump(),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            model=self.settings.model_for_role("task_discovery"),
        )
        data = self._parse_json(content)
        return TaskDiscoveryResult.model_validate(data)

    def _system_prompt(self, user_message: str) -> str:
        return (
            f"{role_prompt('TASK_DISCOVERY')}\n\n"
            "The following runtime instructions override any older role text above.\n\n"
            f"{runtime_meta_context(user_message)}\n\n"
            f"{effort_context(self.settings.effort)}\n\n"
            "Current NixAI capability: scheduled Agentic Tasks can be stored and executed while NixAI is running. "
            "A scheduled task can be either one-shot or recurring. Return JSON only.\n\n"
            "Intent rules:\n"
            "- Use kind=\"one_shot_task\" for a single reminder, alert, follow-up, or task run at a specific future time.\n"
            "- Use kind=\"recurring_task\" only when the user explicitly asks for repetition, such as every day, daily, weekly, monthly, every Monday, or similar wording.\n"
            "- A phrase like 'remind me at 14:01' or 'erinnere mich um 14:01 Uhr' is one_shot_task unless the user explicitly says it should repeat.\n"
            "- Do not turn a one-time reminder into a daily task just because it contains a time.\n"
            "- Use kind=\"chat\" when the user is just asking a question or discussing a possible task.\n\n"
            "- Use kind=\"chat\" for unscheduled research, investigation, web browsing, current-trends, comparison, or analysis requests. "
            "Those are Agentic work, but they are not scheduled tasks.\n"
            "- Never ask for schedule details for a research question unless the user explicitly asks NixAI to run it later or repeatedly.\n\n"
            "Schedule format rules:\n"
            "- For one_shot_task, set schedule to exactly: once at <ISO 8601 local datetime with timezone offset>.\n"
            "- Preserve the user's local wall-clock time for clock-only requests. Do not convert it to UTC in the schedule text.\n"
            "- The hour and minute in the ISO local datetime must exactly match the user's stated clock time.\n"
            "- Use the current local date for clock-only times when that time is still in the future today; otherwise use the next future local date.\n"
            "- Never invent a past date for a one_shot_task.\n"
            "- Example: if local date is 2026-05-10 and local timezone is UTC+02:00, 'um 14:01 Uhr' becomes once at 2026-05-10T14:01:00+02:00, never 12:01 or 16:01.\n"
            "- For recurring_task, use normalized schedules like: daily at 18:00, weekly monday at 09:00, monthly on day 1 at 08:00.\n"
            "- If date or time is missing or ambiguous, leave schedule empty and list the missing information.\n\n"
            "Prompt rules:\n"
            "- Preserve the user's requested action in prompt.\n"
            "- Do not translate title or prompt. Keep both in the same language as the user's request.\n"
            "- If the user wrote German, title and prompt must be German; if the user wrote English, title and prompt must be English.\n"
            "- CRITICAL: For reminders, alerts, wake-ups, and follow-ups, the prompt MUST clearly say that NixAI should send a local Mac desktop notification when the task runs. "
            "Write that notification instruction in the same language as the user's request. "
            "This applies to both one_shot_task and recurring_task."
        )

    def _review_prompt(self, user_message: str) -> str:
        return (
            "You review a TaskDiscovery JSON result for NixAI. Return corrected JSON only.\n\n"
            f"{runtime_meta_context(user_message)}\n\n"
            f"{effort_context(self.settings.effort)}\n\n"
            "Correction rules:\n"
            "- If the user asks for a reminder, alert, follow-up, or scheduled action at one specific future time, use kind=\"one_shot_task\".\n"
            "- If the user explicitly asks for repetition, use kind=\"recurring_task\".\n"
            "- If first_result is recurring_task only because the user gave a time, correct it to one_shot_task.\n"
            "- A phrase like 'remind me at 14:01' or 'erinnere mich um 14:01 Uhr' is one_shot_task unless the user explicitly says it should repeat.\n"
            "- If the user is only chatting, asking a question, or giving an unscheduled instruction, keep kind=\"chat\".\n"
            "- Do not classify ordinary chat as a task.\n"
            "- If the user asks to research the internet, investigate current trends, compare current sources, or browse for information, use kind=\"chat\" with missing_info=[] unless they explicitly ask to schedule that research.\n"
            "- Do not turn unscheduled Agentic work into a planned task.\n"
            "- For one_shot_task, set schedule to exactly: once at <ISO 8601 local datetime with timezone offset>.\n"
            "- Preserve the user's local wall-clock time for clock-only requests. Do not convert it to UTC in the schedule text.\n"
            "- The hour and minute in the ISO local datetime must exactly match the user's stated clock time.\n"
            "- If first_result uses +00:00 for a clock-only user time but the runtime local timezone is not UTC, correct it to the local offset and preserve the same clock time.\n"
            "- Use the current local date for clock-only times when that time is still in the future today; otherwise use the next future local date.\n"
            "- Never invent a past date for a one_shot_task.\n"
            "- For recurring_task, use schedules like daily at 18:00, weekly monday at 09:00, monthly on day 1 at 08:00.\n"
            "- If the user wants a reminder but the date or time is missing, leave schedule empty and fill missing_info.\n"
            "- Do not translate title or prompt. Correct translated text back into the user's language.\n"
            "- Reminder prompts must clearly say that NixAI should send a local Mac desktop notification when the task runs, in the user's language.\n\n"
            "JSON schema:\n"
            '{"kind":"recurring_task | one_shot_task | chat","confidence":0.0,"title":"","prompt":"","schedule":"","missing_info":[],"reason":""}'
        )

    def _repair_prompt(self, user_message: str) -> str:
        return (
            "You repair an invalid NixAI TaskDiscovery JSON result. Return corrected JSON only.\n\n"
            f"{runtime_meta_context(user_message)}\n\n"
            f"{effort_context(self.settings.effort)}\n\n"
            "The prior result resolved a one-shot schedule to the past. Correct it.\n"
            "Rules:\n"
            "- Preserve the user's requested local wall-clock time.\n"
            "- The hour and minute in the ISO local datetime must exactly match the user's stated clock time.\n"
            "- Use the current local date if the requested clock time is still in the future today.\n"
            "- If the requested clock time already passed today, use the next future local date.\n"
            "- Include the local timezone offset in the schedule text.\n"
            "- Do not convert clock-only user times to UTC in the schedule text.\n"
            "- Do not translate title or prompt. Keep user-facing text in the user's language.\n"
            "- If the future date/time cannot be determined, leave schedule empty and fill missing_info.\n\n"
            "JSON schema:\n"
            '{"kind":"recurring_task | one_shot_task | chat","confidence":0.0,"title":"","prompt":"","schedule":"","missing_info":[],"reason":""}'
        )

    def _one_shot_is_past(self, result: TaskDiscoveryResult) -> bool:
        if not result.is_one_shot_task:
            return False
        due_at = parse_one_shot_schedule(result.schedule)
        return due_at is not None and due_at <= utc_now_dt()

    def _parse_json(self, content: str) -> dict[str, object]:
        return parse_json_object_strict(
            content,
            error_factory=OllamaError,
            not_found_message="TaskDiscovery response did not contain JSON",
            not_object_message="TaskDiscovery response JSON was not an object",
        )

    def _fallback(self, text: str) -> TaskDiscoveryResult:
        return TaskDiscoveryResult(
            kind="chat",
            confidence=0.2,
            prompt=text,
            reason="TaskDiscovery model was unavailable; task intent was not inferred programmatically.",
        )

    def _title_from_prompt(self, prompt: str) -> str:
        clean = " ".join(prompt.strip().split())
        clean = re.sub(r"^(bitte|please)\s+", "", clean, flags=re.IGNORECASE)
        return clean[:80] or "Agentic Task"
