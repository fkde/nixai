from __future__ import annotations

import json
import httpx
from collections.abc import AsyncIterator
from typing import Optional

from app.config import Settings
from app.models import Message


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, settings: Settings, timeout: float = 120.0) -> None:
        self.settings = settings
        self.timeout = timeout

    async def list_models(self) -> list[str]:
        url = self.settings.ollama_base_url.rstrip("/") + "/api/tags"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama model list request failed: {exc}") from exc

        data = response.json()
        models = data.get("models", [])
        names = [model.get("name") for model in models if isinstance(model, dict)]
        return sorted(name for name in names if isinstance(name, str))

    async def chat(self, messages: list[Message], model: Optional[str] = None) -> str:
        return await self.chat_payload(
            [
                {"role": message.role, "content": message.content}
                for message in messages
                if message.role in {"user", "assistant", "system"}
            ],
            model=model,
        )

    async def chat_payload(self, messages: list[dict[str, str]], model: Optional[str] = None) -> str:
        payload = {
            "model": model or self.settings.model_for_role("assistant"),
            "messages": messages,
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

    async def stream_chat(self, messages: list[Message], model: Optional[str] = None) -> AsyncIterator[dict[str, object]]:
        payload = [
            {"role": message.role, "content": message.content}
            for message in messages
            if message.role in {"user", "assistant", "system"}
        ]
        async for event in self.stream_payload(payload, model=model):
            yield event

    async def stream_payload(self, messages: list[dict[str, str]], model: Optional[str] = None) -> AsyncIterator[dict[str, object]]:
        payload = {
            "model": model or self.settings.model_for_role("assistant"),
            "messages": messages,
            "stream": True,
        }

        url = self.settings.ollama_base_url.rstrip("/") + "/api/chat"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        content = data.get("message", {}).get("content")
                        if isinstance(content, str) and content:
                            yield {"type": "token", "content": content}
                        if data.get("done"):
                            yield {
                                "type": "done",
                                "eval_count": data.get("eval_count"),
                                "eval_duration": data.get("eval_duration"),
                                "prompt_eval_count": data.get("prompt_eval_count"),
                                "prompt_eval_duration": data.get("prompt_eval_duration"),
                            }
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise OllamaError(f"Ollama stream failed: {exc}") from exc
