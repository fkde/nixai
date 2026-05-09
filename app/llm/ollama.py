from __future__ import annotations

import httpx
from typing import Optional

from app.config import Settings
from app.models import Message


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, settings: Settings, timeout: float = 120.0) -> None:
        self.settings = settings
        self.timeout = timeout

    async def chat(self, messages: list[Message], model: Optional[str] = None) -> str:
        payload = {
            "model": model or self.settings.default_model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
                if message.role in {"user", "assistant", "system"}
            ],
            "stream": False,
        }

        url = self.settings.ollama_base_url.rstrip("/") + "/api/chat"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc

        data = response.json()
        content = data.get("message", {}).get("content")
        if not isinstance(content, str):
            raise OllamaError("Ollama response did not contain message.content")
        return content
