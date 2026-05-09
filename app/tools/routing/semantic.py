from __future__ import annotations

from app.config import load_settings
from app.tools.definitions import ToolDefinition
from app.tools.routing.cosine import CosineToolRouter
from app.tools.routing.embeddings import OllamaEmbeddingClient
from app.tools.routing.keyword import KeywordToolRouter
from app.tools.routing.types import ToolContext, ToolRoute


class SemanticToolRouter:
    def __init__(self, tools: list[ToolDefinition], fallback: KeywordToolRouter | None = None) -> None:
        self.tools = tools
        self.fallback = fallback or KeywordToolRouter(tools)

    async def select_async(self, user_input: str, context: ToolContext, limit: int = 8) -> list[ToolRoute]:
        settings = load_settings()
        embedding_model = settings.embedding_model.strip()
        if embedding_model:
            router = CosineToolRouter(
                self.tools,
                OllamaEmbeddingClient(settings.ollama_base_url, embedding_model, settings.embedding_timeout),
                minimum_relevance_score=settings.routing_min_score,
                fallback=self.fallback,
            )
            return await router.select(user_input, context, limit)
        return self.fallback.select(user_input, context, limit)

    def select(self, user_input: str, context: ToolContext, limit: int = 8) -> list[ToolRoute]:
        return self.fallback.select(user_input, context, limit)
