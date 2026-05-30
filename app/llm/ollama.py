from __future__ import annotations

import asyncio
import json
import re
import httpx
from collections.abc import AsyncIterator
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from app.config import Settings
from app.models import Message, OllamaModelInfo, OllamaModelKind


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, settings: Settings, timeout: float = 120.0) -> None:
        self.settings = settings
        self.timeout = timeout

    async def list_models(self) -> list[str]:
        catalog = await self.list_model_catalog()
        return [model.name for model in catalog]

    async def list_model_catalog(self) -> list[OllamaModelInfo]:
        try:
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                data = await self._get_json(client, "/api/tags")
                models = data.get("models", [])
                tag_models = [model for model in models if isinstance(model, dict)]
                semaphore = asyncio.Semaphore(4)

                async def build_model(tag_model: dict[str, Any]) -> OllamaModelInfo:
                    async with semaphore:
                        return await self._build_model_info(client, tag_model)

                catalog = await asyncio.gather(*(build_model(model) for model in tag_models))
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama model list request failed: {exc}") from exc

        return sorted(catalog, key=lambda model: model.name.lower())

    async def _build_model_info(self, client: httpx.AsyncClient, tag_model: dict[str, Any]) -> OllamaModelInfo:
        name = tag_model.get("name") or tag_model.get("model")
        if not isinstance(name, str) or not name:
            return OllamaModelInfo(name="", kind="unknown", error="Missing model name in Ollama tags response.")

        show_payload: dict[str, Any] = {}
        show_error = ""
        try:
            data = await self._post_json(client, "/api/show", {"model": name})
            if isinstance(data, dict):
                show_payload = data
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            show_error = str(exc)

        tag_details = tag_model.get("details") if isinstance(tag_model.get("details"), dict) else {}
        show_details = show_payload.get("details") if isinstance(show_payload.get("details"), dict) else {}
        details: dict[str, Any] = {**tag_details, **show_details}
        model_info = show_payload.get("model_info") if isinstance(show_payload.get("model_info"), dict) else {}
        capabilities = _string_list(show_payload.get("capabilities"))
        if not capabilities:
            capabilities = ["embedding"] if _classify_model(name, details, model_info, []) == "embedding" else ["chat"]

        return OllamaModelInfo(
            name=name,
            kind=_classify_model(name, details, model_info, capabilities),
            family=_string_value(details.get("family")),
            families=_string_list(details.get("families")),
            parameter_size=_string_value(details.get("parameter_size")),
            quantization_level=_string_value(details.get("quantization_level")),
            format=_string_value(details.get("format")),
            size=tag_model.get("size") if isinstance(tag_model.get("size"), int) else None,
            digest=_string_value(tag_model.get("digest")),
            modified_at=_string_value(tag_model.get("modified_at")),
            details=details,
            model_info=model_info,
            capabilities=capabilities,
            error=show_error,
        )

    async def chat(self, messages: list[Message], model: Optional[str] = None) -> str:
        return await self.chat_payload(
            [
                {"role": message.role, "content": message.content}
                for message in messages
                if message.role in {"user", "assistant", "system"}
            ],
            model=model,
        )

    async def chat_payload(
        self,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
        response_format: str | dict[str, Any] | None = None,
    ) -> str:
        payload = self.chat_payload_request(messages, model=model, stream=False)
        if response_format is not None:
            payload["format"] = response_format

        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                data = await self._post_json(client, "/api/chat", payload)
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama request failed: {exc}") from exc

        content = data.get("message", {}).get("content")
        if not isinstance(content, str):
            raise OllamaError("Ollama response did not contain message.content")
        return clean_model_content(content)

    async def stream_chat(self, messages: list[Message], model: Optional[str] = None) -> AsyncIterator[dict[str, object]]:
        payload = [
            {"role": message.role, "content": message.content}
            for message in messages
            if message.role in {"user", "assistant", "system"}
        ]
        async for event in self.stream_payload(payload, model=model):
            yield event

    async def stream_payload(
        self,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
    ) -> AsyncIterator[dict[str, object]]:
        payload = self.chat_payload_request(messages, model=model, stream=True)

        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                last_exc: httpx.HTTPError | None = None
                for url in self._url_candidates("/api/chat"):
                    emitted_any = False
                    try:
                        async with client.stream("POST", url, json=payload) as response:
                            response.raise_for_status()
                            reasoning_filter = StreamingReasoningFilter()
                            async for line in response.aiter_lines():
                                if not line.strip():
                                    continue
                                data = json.loads(line)
                                content = data.get("message", {}).get("content")
                                if isinstance(content, str) and content:
                                    visible = reasoning_filter.feed(content)
                                    if visible:
                                        emitted_any = True
                                        yield {"type": "token", "content": visible}
                                if data.get("done"):
                                    visible = reasoning_filter.flush()
                                    if visible:
                                        emitted_any = True
                                        yield {"type": "token", "content": visible}
                                    yield {
                                        "type": "done",
                                        "eval_count": data.get("eval_count"),
                                        "eval_duration": data.get("eval_duration"),
                                        "prompt_eval_count": data.get("prompt_eval_count"),
                                        "prompt_eval_duration": data.get("prompt_eval_duration"),
                                    }
                            return
                    except httpx.HTTPError as exc:
                        if emitted_any:
                            # Do not restart from a fallback URL once tokens were already emitted.
                            # A restart would duplicate partial output in the UI.
                            raise
                        last_exc = exc
                if last_exc is not None:
                    raise last_exc
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise OllamaError(f"Ollama stream failed: {exc}") from exc

    async def _get_json(self, client: httpx.AsyncClient, path: str) -> dict[str, Any]:
        last_exc: httpx.HTTPError | None = None
        for url in self._url_candidates(path):
            try:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else {}
            except httpx.HTTPError as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        return {}

    async def _post_json(self, client: httpx.AsyncClient, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        last_exc: httpx.HTTPError | None = None
        for url in self._url_candidates(path):
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else {}
            except httpx.HTTPError as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        return {}

    def _url_candidates(self, path: str) -> list[str]:
        base = self.settings.ollama_base_url.rstrip("/")
        candidates = [base + path]
        parsed = urlsplit(base)
        if parsed.hostname == "localhost":
            netloc = parsed.netloc.replace("localhost", "127.0.0.1", 1)
            fallback = urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), parsed.query, parsed.fragment))
            candidates.append(fallback + path)
        return candidates

    def chat_payload_request(
        self,
        messages: list[dict[str, Any]],
        model: Optional[str] = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        return {
            "model": model or self.settings.model_for_role("assistant"),
            "messages": messages,
            "stream": stream,
        }


def _string_value(value: object) -> str:
    return value if isinstance(value, str) else ""


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def clean_model_content(content: str) -> str:
    text = str(content or "")
    text = re.sub(r"(?is)<think\b[^>]*>.*?</think>\s*", "", text)
    text = re.sub(r"(?is)^\s*<think\b[^>]*>.*$", "", text)
    return text.strip()


class StreamingReasoningFilter:
    START_TAG = "<think"
    END_TAG = "</think>"

    def __init__(self) -> None:
        self.buffer = ""
        self.in_think = False

    def feed(self, chunk: str) -> str:
        self.buffer += str(chunk or "")
        output: list[str] = []
        while self.buffer:
            lower = self.buffer.lower()
            if self.in_think:
                end = lower.find(self.END_TAG)
                if end < 0:
                    self.buffer = self.buffer[-(len(self.END_TAG) - 1) :]
                    break
                close = lower.find(">", end)
                if close < 0:
                    self.buffer = self.buffer[end:]
                    break
                self.buffer = self.buffer[close + 1 :]
                self.in_think = False
                continue

            start = lower.find(self.START_TAG)
            if start < 0:
                keep = _partial_suffix_length(lower, self.START_TAG)
                emit = self.buffer[:-keep] if keep else self.buffer
                if emit:
                    output.append(emit)
                    self.buffer = self.buffer[len(emit) :]
                break

            if start > 0:
                output.append(self.buffer[:start])
            close = lower.find(">", start)
            if close < 0:
                self.buffer = self.buffer[start:]
                break
            self.buffer = self.buffer[close + 1 :]
            self.in_think = True

        return "".join(output)

    def flush(self) -> str:
        if self.in_think:
            self.buffer = ""
            return ""
        visible = clean_model_content(self.buffer)
        self.buffer = ""
        return visible


def _partial_suffix_length(text: str, tag_start: str) -> int:
    max_len = min(len(text), len(tag_start) - 1)
    for length in range(max_len, 0, -1):
        if tag_start.startswith(text[-length:]):
            return length
    return 0


def _classify_model(
    name: str,
    details: dict[str, Any],
    model_info: dict[str, Any],
    capabilities: list[str],
) -> OllamaModelKind:
    normalized_capabilities = {capability.lower() for capability in capabilities}
    if "embedding" in normalized_capabilities:
        return "embedding"
    if normalized_capabilities.intersection({"completion", "chat", "tools", "thinking"}):
        return "chat"

    text_parts = [
        name,
        _string_value(details.get("family")),
        " ".join(_string_list(details.get("families"))),
        _string_value(model_info.get("general.architecture")),
    ]
    normalized = " ".join(text_parts).lower()
    embedding_markers = (
        "embed",
        "embedding",
        "nomic-bert",
        "sentence-transformer",
        "all-minilm",
        "bge-",
        "e5-",
        "gte-",
    )
    if any(marker in normalized for marker in embedding_markers):
        return "embedding"

    model_info_keys = " ".join(str(key).lower() for key in model_info.keys())
    if "pooling" in model_info_keys:
        return "embedding"

    return "chat"
