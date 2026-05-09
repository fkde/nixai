from __future__ import annotations

import json
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.config import Settings
from app.llm.ollama import OllamaClient, OllamaError
from app.roles import role_prompt


class TaskDiscoveryResult(BaseModel):
    kind: str = "chat"
    confidence: float = 0.0
    title: str = ""
    prompt: str = ""
    schedule: str = ""
    missing_info: list[str] = Field(default_factory=list)
    reason: str = ""

    @property
    def is_recurring_task(self) -> bool:
        return self.kind == "recurring_task" and self.confidence >= 0.62 and bool(self.schedule.strip())


class TaskDiscovery:
    def __init__(self, settings: Settings, ollama: Optional[OllamaClient] = None) -> None:
        self.settings = settings
        self.ollama = ollama or OllamaClient(settings, timeout=30.0)

    async def discover(self, user_message: str) -> TaskDiscoveryResult:
        try:
            result = await self._discover_with_model(user_message)
        except OllamaError:
            result = self._fallback(user_message)
        if not result.prompt:
            result.prompt = user_message
        if not result.title:
            result.title = self._title_from_prompt(user_message)
        return result

    async def _discover_with_model(self, user_message: str) -> TaskDiscoveryResult:
        content = await self.ollama.chat_payload(
            [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": user_message},
            ],
            model=self.settings.model_for_role("task_discovery"),
        )
        data = self._parse_json(content)
        return TaskDiscoveryResult.model_validate(data)

    def _system_prompt(self) -> str:
        return (
            f"{role_prompt('TASK_DISCOVERY')}\n\n"
            "Current NixAI capability: recurring tasks can be stored as definitions, "
            "but cannot be executed automatically yet. Return JSON only."
        )

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
                raise OllamaError("TaskDiscovery response did not contain JSON")
            parsed = json.loads(match.group(0))
        if not isinstance(parsed, dict):
            raise OllamaError("TaskDiscovery response JSON was not an object")
        return parsed

    def _fallback(self, text: str) -> TaskDiscoveryResult:
        schedule = self._extract_schedule(text)
        if schedule is None:
            return TaskDiscoveryResult(kind="chat", confidence=0.2, prompt=text, reason="No recurring schedule found.")
        return TaskDiscoveryResult(
            kind="recurring_task",
            confidence=0.7,
            title=self._title_from_prompt(text),
            prompt=text,
            schedule=schedule,
            reason="Fallback detected recurring schedule wording.",
        )

    def _extract_schedule(self, text: str) -> Optional[str]:
        lower = text.casefold()
        recurring_markers = [
            "jeden ",
            "jede ",
            "taeglich",
            "täglich",
            "woechentlich",
            "wöchentlich",
            "monatlich",
            "every ",
            "daily",
            "weekly",
            "monthly",
        ]
        if not any(marker in lower for marker in recurring_markers):
            return None
        time_match = re.search(r"\b(?:um\s*)?([01]?\d|2[0-3])[:.]?([0-5]\d)?\s*(?:uhr)?\b", lower)
        if not time_match:
            return None
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or "0")
        time_text = f"{hour:02d}:{minute:02d}"
        if any(marker in lower for marker in ["woechentlich", "wöchentlich", "weekly"]):
            return f"weekly at {time_text}"
        if any(marker in lower for marker in ["monatlich", "monthly"]):
            return f"monthly at {time_text}"
        return f"daily at {time_text}"

    def _title_from_prompt(self, prompt: str) -> str:
        clean = " ".join(prompt.strip().split())
        clean = re.sub(r"^(bitte|please)\s+", "", clean, flags=re.IGNORECASE)
        return clean[:80] or "Agentic Task"
