from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel

from app.config import load_settings
from app.json_utils import parse_json_object_strict
from app.llm.ollama import OllamaClient, OllamaError
from app.memory import append_memory_entry
from app.mistakes import MistakeEntry


class MistakeSolution(BaseModel):
    title: str
    instruction: str
    rationale: str = ""


class MistakeReview:
    def __init__(self, ollama: Optional[OllamaClient] = None) -> None:
        self.settings = load_settings()
        self.ollama = ollama or OllamaClient(self.settings, timeout=45.0)

    async def propose_solution(self, entry: MistakeEntry) -> MistakeSolution:
        try:
            content = await self.ollama.chat_payload(
                [
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": entry.content},
                ],
                model=self.settings.model_for_role("reviewer"),
            )
            parsed = self._parse_json(content)
            return MistakeSolution.model_validate(parsed)
        except (OllamaError, ValueError, json.JSONDecodeError):
            return self._fallback(entry)

    def accept_solution(self, entry: MistakeEntry, solution: MistakeSolution):
        return append_memory_entry(
            title=solution.title,
            instruction=solution.instruction,
            source=f"MISTAKES.md entry {entry.id}: {entry.title}",
        )

    def _system_prompt(self) -> str:
        return (
            "You convert a reviewed MISTAKES.md entry into a durable MEMORY.md instruction. "
            "Return strict JSON only with keys: title, instruction, rationale. "
            "The instruction must be actionable, future-facing, and phrased as a reminder for the assistant."
        )

    def _parse_json(self, content: str) -> dict[str, Any]:
        return parse_json_object_strict(
            content,
            not_found_message="Solution response did not contain JSON.",
            not_object_message="Solution response was not a JSON object.",
        )

    def _fallback(self, entry: MistakeEntry) -> MistakeSolution:
        return MistakeSolution(
            title=entry.title or "Reviewed mistake",
            instruction="Before answering, check whether this request matches a previously downvoted pattern and ask for missing evidence instead of guessing.",
            rationale="Fallback generated because the model did not return a valid solution.",
        )
