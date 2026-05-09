from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from app.config import data_dir


class OllamaEmbeddingClient:
    def __init__(self, base_url: str, model: str, timeout: float = 1.5, cache_dir: Path | None = None) -> None:
        self.base_url = base_url.strip().rstrip("/")
        self.model = model.strip()
        self.timeout = timeout if timeout > 0 else 1.5
        self.cache_dir = cache_dir or data_dir() / "embedding-cache"
        self.memory_cache: dict[str, list[float]] = {}

    async def embed(self, text: str) -> list[float] | None:
        values = await self.embed_many([text])
        return values[0] if values else None

    async def embed_many(self, texts: list[str]) -> list[list[float] | None]:
        results: list[list[float] | None] = [None] * len(texts)
        missing_texts: list[str] = []
        missing_indexes: list[int] = []

        for index, text in enumerate(texts):
            text = text.strip()
            if not text:
                continue
            cached = self._read_cached(text)
            if cached is not None:
                results[index] = cached
                continue
            missing_indexes.append(index)
            missing_texts.append(text)

        if missing_texts:
            embeddings = await self._embed_batch(missing_texts)
            for offset, index in enumerate(missing_indexes):
                embedding = embeddings[offset] if offset < len(embeddings) else None
                if embedding is not None:
                    self._write_cached(missing_texts[offset], embedding)
                results[index] = embedding

        return results

    async def _embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        if not self.base_url or not self.model:
            return [None] * len(texts)
        payload = await self._request("/api/embed", {"model": self.model, "input": texts})
        embeddings = payload.get("embeddings") if isinstance(payload, dict) else None
        if isinstance(embeddings, list):
            return [self._normalize(item) for item in embeddings]

        fallback = []
        for text in texts:
            payload = await self._request("/api/embeddings", {"model": self.model, "prompt": text})
            fallback.append(self._normalize(payload.get("embedding") if isinstance(payload, dict) else None))
        return fallback

    async def _request(self, path: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.base_url + path, json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError:
            return {}

    def _cache_key(self, text: str) -> str:
        return hashlib.sha256(f"{self.model}\n{text}".encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / key[:2] / f"{key}.json"

    def _read_cached(self, text: str) -> list[float] | None:
        key = self._cache_key(text)
        if key in self.memory_cache:
            return self.memory_cache[key]
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if payload.get("model") != self.model:
            return None
        embedding = self._normalize(payload.get("embedding"))
        if embedding is not None:
            self.memory_cache[key] = embedding
        return embedding

    def _write_cached(self, text: str, embedding: list[float]) -> None:
        key = self._cache_key(text)
        self.memory_cache[key] = embedding
        path = self._cache_path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"model": self.model, "embedding": embedding}), encoding="utf-8")
        except OSError:
            return

    def _normalize(self, value: object) -> list[float] | None:
        if not isinstance(value, list) or not value:
            return None
        normalized: list[float] = []
        for item in value:
            if not isinstance(item, (int, float)):
                return None
            normalized.append(float(item))
        return normalized
