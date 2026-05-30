from __future__ import annotations

import json
from typing import Any, Optional

from app import database
from app.config import load_settings
from app.json_utils import parse_json_object_strict
from app.llm.ollama import OllamaClient, OllamaError
from app.mistakes import append_mistake_entry
from app.models import Message, utc_now


class MistakeDistiller:
    def __init__(self, ollama: Optional[OllamaClient] = None) -> None:
        self.settings = load_settings()
        self.ollama = ollama or OllamaClient(self.settings, timeout=45.0)

    async def process_downvote(self, message_id: str) -> None:
        message = database.get_message(message_id)
        if message is None:
            return
        history = database.list_messages(message.chat_id)
        entry = await self.distill(message, history)
        append_mistake_entry(entry)

    async def distill(self, message: Message, history: list[Message]) -> str:
        try:
            data = await self._distill_with_model(message, history)
        except (OllamaError, ValueError, json.JSONDecodeError):
            data = self._fallback(message, history)
        return self._format_entry(data, message)

    async def _distill_with_model(self, message: Message, history: list[Message]) -> dict[str, Any]:
        content = await self.ollama.chat_payload(
            [
                {"role": "system", "content": self._system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "downvoted_message": message.model_dump(),
                            "chat_history": [item.model_dump() for item in history[-12:]],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            model=self.settings.model_for_role("reviewer"),
        )
        parsed = self._parse_json(content)
        if not isinstance(parsed, dict):
            raise ValueError("Mistake distillation did not return an object.")
        return parsed

    def _system_prompt(self) -> str:
        return (
            "You distill a downvoted assistant answer into a concise MISTAKES.md entry. "
            "Return strict JSON only with keys: title, mistake, impact, correction, evidence. "
            "Do not invent facts. If the exact mistake is unclear, describe the likely issue as requiring review."
        )

    def _parse_json(self, content: str) -> dict[str, Any]:
        return parse_json_object_strict(
            content,
            not_found_message="Distiller response did not contain JSON",
            not_object_message="Distiller response JSON was not an object",
        )

    def _fallback(self, message: Message, history: list[Message]) -> dict[str, Any]:
        previous_user = next((item.content for item in reversed(history) if item.role == "user"), "")
        return {
            "title": "Downvoted assistant response requires review",
            "mistake": "The user marked an assistant response as unhelpful or incorrect.",
            "impact": "The answer may contain an incorrect assumption, missing context, or insufficient verification.",
            "correction": "Review the chat context before repeating this pattern. Ask for missing details or cite tool evidence when relevant.",
            "evidence": f"User prompt: {previous_user[:300]} | Assistant response: {message.content[:300]}",
        }

    def _format_entry(self, data: dict[str, Any], message: Message) -> str:
        title = str(data.get("title") or "Downvoted assistant response").strip()
        mistake = str(data.get("mistake") or "The assistant response was downvoted.").strip()
        impact = str(data.get("impact") or "The impact needs review.").strip()
        correction = str(
            data.get("correction") or "Review the context and avoid repeating this response pattern."
        ).strip()
        evidence = str(data.get("evidence") or f"Message ID: {message.id}").strip()
        return (
            f"### {utc_now()} - {title}\n"
            f"- Message: `{message.id}`\n"
            f"- Mistake: {mistake}\n"
            f"- Impact: {impact}\n"
            f"- Correction: {correction}\n"
            f"- Evidence: {evidence}"
        )
