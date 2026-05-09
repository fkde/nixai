from __future__ import annotations

from typing import Optional

from app import database
from app.config import load_settings
from app.llm.ollama import OllamaClient
from app.models import CreateMessageResponse


class Agent:
    def __init__(self, ollama: Optional[OllamaClient] = None) -> None:
        self.settings = load_settings()
        self.ollama = ollama or OllamaClient(self.settings)

    async def run(self, chat_id: str, user_message: str) -> CreateMessageResponse:
        chat = database.get_chat(chat_id)
        if chat is None:
            raise ValueError("Chat not found")

        user = database.add_message(chat_id, "user", user_message)
        database.update_chat_title_if_default(chat_id, user_message)
        history = database.list_messages(chat_id)
        answer = await self.ollama.chat(history)
        assistant = database.add_message(chat_id, "assistant", answer)
        return CreateMessageResponse(user_message=user, assistant_message=assistant)
