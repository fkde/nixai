from __future__ import annotations

import math

from app.tools.definitions import ToolDefinition
from app.tools.routing.embeddings import OllamaEmbeddingClient
from app.tools.routing.hard_filter import ToolHardFilter
from app.tools.routing.keyword import KeywordToolRouter
from app.tools.routing.types import ToolContext, ToolRoute


class CosineToolRouter:
    def __init__(
        self,
        tools: list[ToolDefinition],
        embeddings: OllamaEmbeddingClient,
        minimum_relevance_score: float = 0.24,
        hard_filter: ToolHardFilter | None = None,
        fallback: KeywordToolRouter | None = None,
    ) -> None:
        self.tools = tools
        self.embeddings = embeddings
        self.minimum_relevance_score = minimum_relevance_score
        self.hard_filter = hard_filter or ToolHardFilter()
        self.fallback = fallback or KeywordToolRouter(tools)

    async def select(self, user_input: str, context: ToolContext, limit: int = 8) -> list[ToolRoute]:
        limit = max(1, min(32, limit))
        candidates = self.hard_filter.filter(self.tools, user_input, context)
        if not candidates:
            return self.fallback.select(user_input, context, limit)

        query_embedding = await self.embeddings.embed(self._query_text(user_input, context))
        if query_embedding is None:
            return self.fallback.select(user_input, context, limit)

        tool_embeddings = await self.embeddings.embed_many([self._tool_text(tool) for tool in candidates])
        routes = []
        for tool, embedding in zip(candidates, tool_embeddings):
            if embedding is None:
                return self.fallback.select(user_input, context, limit)
            score = self._cosine_similarity(query_embedding, embedding)
            if score >= self.minimum_relevance_score:
                routes.append(ToolRoute(tool, score, ["cosine"]))

        routes.sort(key=lambda item: item.score, reverse=True)
        selected = routes[:limit]
        if selected:
            return self._with_search_tool(selected, candidates, limit)
        return self.fallback.select(user_input, context, limit)

    def _with_search_tool(
        self, selected: list[ToolRoute], candidates: list[ToolDefinition], limit: int
    ) -> list[ToolRoute]:
        if limit < 4 or len(selected) >= limit or any(route.tool.name == "nixai_tools_search" for route in selected):
            return selected
        search = next((tool for tool in candidates if tool.name == "nixai_tools_search"), None)
        return [*selected, ToolRoute(search, 0.1, ["fallback-search"])] if search else selected

    def _tool_text(self, tool: ToolDefinition) -> str:
        meta = tool.meta
        return " ".join(
            [
                tool.name,
                tool.description,
                tool.routing_description,
                str(meta.get("routingText") or ""),
                " ".join(str(item) for item in meta.get("examples", []) if isinstance(meta.get("examples"), list)),
                " ".join(
                    str(item) for item in meta.get("capabilities", []) if isinstance(meta.get("capabilities"), list)
                ),
            ]
        )

    def _query_text(self, user_input: str, context: ToolContext) -> str:
        parts = [user_input, context.area, context.page_id, context.layout_id, context.theme_id, context.content_type]
        return " ".join(part for part in parts if part)

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        size = min(len(left), len(right))
        if size == 0:
            return 0.0
        dot = sum(left[index] * right[index] for index in range(size))
        left_magnitude = math.sqrt(sum(left[index] * left[index] for index in range(size)))
        right_magnitude = math.sqrt(sum(right[index] * right[index] for index in range(size)))
        if left_magnitude <= 0 or right_magnitude <= 0:
            return 0.0
        return dot / (left_magnitude * right_magnitude)
