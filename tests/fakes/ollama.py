from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Optional

from app.models import Message, OllamaModelInfo


class FakeOllamaClient:
    def __init__(
        self,
        response_text: str = "Fake Ollama response.",
        stream_chunks: Optional[list[str]] = None,
    ) -> None:
        self.response_text = response_text
        self.stream_chunks = stream_chunks or ["Fake ", "stream ", "response."]
        self.chat_calls: list[dict[str, Any]] = []
        self.chat_payload_calls: list[dict[str, Any]] = []
        self.stream_chat_calls: list[dict[str, Any]] = []
        self.stream_payload_calls: list[dict[str, Any]] = []

    async def list_models(self) -> list[str]:
        return [model.name for model in await self.list_model_catalog()]

    async def list_model_catalog(self) -> list[OllamaModelInfo]:
        return [
            OllamaModelInfo(name="fake-chat", kind="chat", capabilities=["chat"]),
            OllamaModelInfo(name="fake-embed", kind="embedding", capabilities=["embedding"]),
        ]

    async def chat(self, messages: list[Message], model: Optional[str] = None) -> str:
        self.chat_calls.append({"messages": messages, "model": model})
        return self.response_text

    async def chat_payload(
        self,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
        response_format: str | dict[str, Any] | None = None,
    ) -> str:
        self.chat_payload_calls.append(
            {
                "messages": messages,
                "model": model,
                "response_format": response_format,
            }
        )
        system_text = "\n".join(message.get("content", "") for message in messages if message.get("role") == "system")
        if response_format == "json":
            return self._json_response_for_prompt(system_text)
        if "TASK_DISCOVERY" in system_text or "scheduled Agentic Tasks" in system_text:
            return json.dumps(
                {
                    "kind": "chat",
                    "confidence": 0.1,
                    "title": "Fake chat",
                    "prompt": "",
                    "schedule": "",
                    "missing_info": [],
                    "reason": "Fake client defaults to conversational handling.",
                }
            )
        if "route an AGENTIC-mode request" in system_text:
            return json.dumps({"action": "answer_direct", "reason": "Fake direct route."})
        if "chat title" in system_text.lower() or "return plain text only" in system_text.lower():
            return "Fake Chat Title"
        return self.response_text

    async def stream_chat(self, messages: list[Message], model: Optional[str] = None) -> AsyncIterator[dict[str, object]]:
        self.stream_chat_calls.append({"messages": messages, "model": model})
        for chunk in self.stream_chunks:
            yield {"type": "token", "content": chunk}
        yield {
            "type": "done",
            "eval_count": len(self.stream_chunks),
            "eval_duration": 1_000_000_000,
            "prompt_eval_count": 1,
            "prompt_eval_duration": 1_000_000,
        }

    async def stream_payload(
        self,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
    ) -> AsyncIterator[dict[str, object]]:
        self.stream_payload_calls.append({"messages": messages, "model": model})
        for chunk in self.stream_chunks:
            yield {"type": "token", "content": chunk}
        yield {
            "type": "done",
            "eval_count": len(self.stream_chunks),
            "eval_duration": 1_000_000_000,
            "prompt_eval_count": 1,
            "prompt_eval_duration": 1_000_000,
        }

    def _json_response_for_prompt(self, system_text: str) -> str:
        lowered = system_text.lower()
        if "judge" in lowered:
            return json.dumps({"status": "done", "reason": "Fake judge approved.", "feedback": []})
        if "review" in lowered:
            return json.dumps({"status": "approved", "summary": "Fake review approved.", "findings": []})
        return json.dumps(
            {
                "title": "Fake plan",
                "summary": "Fake workflow plan.",
                "acceptance_criteria": ["Return a deterministic answer."],
                "work_items": [
                    {
                        "id": "main",
                        "title": "Answer",
                        "instructions": "Return a deterministic answer.",
                        "owned_paths": [],
                    }
                ],
            }
        )
