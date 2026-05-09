from __future__ import annotations

import re
from typing import Optional

from app import database
from app.config import load_settings
from app.llm.ollama import OllamaClient
from app.models import CreateMessageResponse, Message, MessageMode, new_id, utc_now
from app.roles import role_prompt


class Agent:
    def __init__(self, ollama: Optional[OllamaClient] = None) -> None:
        self.settings = load_settings()
        self.ollama = ollama or OllamaClient(self.settings)

    async def run(self, chat_id: str, user_message: str, mode: MessageMode = "chat") -> CreateMessageResponse:
        chat = database.get_chat(chat_id)
        if chat is None:
            raise ValueError("Chat not found")

        user = database.add_message(chat_id, "user", user_message, mode=mode)
        database.update_chat_title_if_default(chat_id, user_message)

        task = self._maybe_create_agentic_task(user_message) if mode == "agentic" else None
        if task is not None:
            answer = (
                f"[agentic] Ich habe einen wiederkehrenden Task angelegt: {task.title}\n\n"
                f"Schedule: {task.schedule}\n"
                f"Status: {task.status}\n\n"
                "Die Ausfuehrung ist in dieser ersten Version noch nicht aktiv. "
                "Du kannst den Task in den Einstellungen bearbeiten, pausieren oder loeschen."
            )
        else:
            history = self._history_with_mode_context(chat_id, mode)
            answer = await self.ollama.chat(history, model=self.settings.model_for_role(self._model_role_for_mode(mode)))
        assistant = database.add_message(chat_id, "assistant", answer, mode=mode)
        return CreateMessageResponse(user_message=user, assistant_message=assistant)

    def _history_with_mode_context(self, chat_id: str, mode: MessageMode) -> list[Message]:
        history = database.list_messages(chat_id)
        return [self._system_message(chat_id, self._mode_context(mode)), *history]

    def _mode_context(self, mode: MessageMode) -> str:
        if mode == "code":
            workspace = self.settings.workspace_path
            return (
                f"{role_prompt('WORKER')}\n\n"
                "NixAI mode: CODE.\n"
                f"Configured workspace: {workspace}\n"
                "Help with code and project understanding. Prefer workspace-grounded answers. "
                "Do not claim that files, Git, or tests were inspected unless tool results are provided."
            )
        if mode == "agentic":
            return (
                f"{role_prompt('ORCHESTRATOR')}\n\n"
                "NixAI mode: AGENTIC.\n"
                "Guide the user through a controlled agent workflow. If the request sounds recurring, "
                "ask for missing schedule details or confirm the recurring task plan. "
                "The current POC can store agentic task definitions, but does not execute them yet."
            )
        return (
            f"{role_prompt('ASSISTANT')}\n\n"
            "NixAI mode: CHAT. Answer conversationally without assuming workspace tool access."
        )

    def _system_message(self, chat_id: str, content: str) -> Message:
        return Message(id=new_id(), chat_id=chat_id, role="system", content=content, mode="chat", created_at=utc_now())

    def _model_role_for_mode(self, mode: MessageMode) -> str:
        if mode == "code":
            return "worker"
        if mode == "agentic":
            return "orchestrator"
        return "assistant"

    def _maybe_create_agentic_task(self, user_message: str):
        schedule = self._extract_schedule(user_message)
        if schedule is None:
            return None
        title = self._title_from_prompt(user_message)
        return database.create_agentic_task(title=title, prompt=user_message, schedule=schedule)

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
        time_text = "18:00"
        if time_match:
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
