from __future__ import annotations

import re
from typing import Any

from app.tools.definitions import ToolDefinition
from app.tools.routing.hard_filter import ToolHardFilter
from app.tools.routing.types import ToolContext, ToolRoute


class KeywordToolRouter:
    def __init__(self, tools: list[ToolDefinition], hard_filter: ToolHardFilter | None = None) -> None:
        self.tools = tools
        self.hard_filter = hard_filter or ToolHardFilter()

    def select(self, user_input: str, context: ToolContext, limit: int = 8) -> list[ToolRoute]:
        limit = max(1, min(32, limit))
        user_input = user_input.strip()
        if not user_input or self._wants_catalog(user_input):
            return [ToolRoute(tool, 0.1, ["catalog"]) for tool in self.tools[:limit]]

        candidates = self.hard_filter.filter(self.tools, user_input, context)
        query = self._query_text(user_input, context).lower()
        query_tokens = self._tokens(query)
        write_intent = self._has_write_intent(query)

        routes = []
        for tool in candidates:
            route = self._route(tool, query, query_tokens, context, write_intent)
            if route.score > 0.0:
                routes.append(route)

        routes.sort(key=lambda item: item.score, reverse=True)
        selected = routes[:limit]
        if selected:
            return self._with_search_tool(selected, candidates, limit)
        return self._search_only(candidates, "no-match-search")

    def _with_search_tool(self, selected: list[ToolRoute], candidates: list[ToolDefinition], limit: int) -> list[ToolRoute]:
        if limit < 4 or len(selected) >= limit or any(route.tool.name == "nixai_tools_search" for route in selected):
            return selected
        search = next((tool for tool in candidates if tool.name == "nixai_tools_search"), None)
        return [*selected, ToolRoute(search, 0.1, ["fallback-search"])] if search else selected

    def _search_only(self, candidates: list[ToolDefinition], reason: str) -> list[ToolRoute]:
        search = next((tool for tool in candidates if tool.name == "nixai_tools_search"), None)
        return [ToolRoute(search, 0.1, [reason])] if search else []

    def _route(
        self,
        tool: ToolDefinition,
        query: str,
        query_tokens: list[str],
        context: ToolContext,
        write_intent: bool,
    ) -> ToolRoute:
        meta = tool.meta
        tool_text = " ".join(
            [
                tool.name,
                tool.description,
                str(meta.get("routingText") or ""),
                " ".join(str(item) for item in meta.get("examples", []) if isinstance(meta.get("examples"), list)),
                " ".join(str(item) for item in meta.get("tags", []) if isinstance(meta.get("tags"), list)),
                " ".join(self._capabilities(meta)),
            ]
        ).lower()

        score = 0.0
        reasons = []
        tool_tokens = set(self._tokens(tool_text))
        token_score = sum(1.0 for token in query_tokens if token in tool_tokens)
        if token_score > 0:
            score += token_score
            reasons.append("tokens")

        area_score = self._area_score(context, meta, tool_text)
        if area_score > 0:
            score += area_score
            reasons.append("area")

        capability_score = self._capability_score(query, meta)
        if capability_score > 0:
            score += capability_score
            reasons.append("capability")

        if write_intent and meta.get("mode") == "write":
            score += 6.0
            reasons.append("write")

        if self._matches_examples(query, meta.get("examples", [])):
            score += 4.0
            reasons.append("examples")

        return ToolRoute(tool, score, sorted(set(reasons)))

    def _query_text(self, message: str, context: ToolContext) -> str:
        parts = [message, context.area, context.page_id, context.layout_id, context.theme_id, context.content_type]
        parts.extend(str(context.ui_context.get(key) or "") for key in ["selectedRegion", "theme", "path", "command"])
        return " ".join(part for part in parts if part)

    def _tokens(self, text: str) -> list[str]:
        words = re.split(r"[^a-zA-Z0-9\u00C0-\u017F]+", text.lower())
        stop = {
            "und",
            "oder",
            "der",
            "die",
            "das",
            "ein",
            "eine",
            "ist",
            "sind",
            "wie",
            "was",
            "mir",
            "mal",
            "bitte",
            "hier",
            "mit",
            "ohne",
            "für",
            "fuer",
            "kann",
            "kannst",
            "with",
            "the",
            "for",
            "and",
            "this",
            "that",
        }
        return sorted({word for word in words if len(word) >= 3 and word not in stop})

    def _area_score(self, context: ToolContext, meta: dict[str, Any], tool_text: str) -> float:
        area = context.normalized_area()
        if not area:
            return 0.0
        capabilities = self._capabilities(meta)
        if area in {"workspace", "project"} and any(cap.startswith("filesystem.") for cap in capabilities):
            return 3.0
        if area == "git" and any(cap.startswith("git.") for cap in capabilities):
            return 3.0
        if area in {"test", "tests", "build"} and "command.run" in capabilities:
            return 3.0
        return 0.0

    def _capability_score(self, query: str, meta: dict[str, Any]) -> float:
        capabilities = self._capabilities(meta)
        mapping = {
            "filesystem.list": ["list", "files", "dateien", "struktur", "tree"],
            "filesystem.read": ["read", "öffne", "oeffne", "zeige", "file", "datei", "content"],
            "filesystem.search": ["search", "find", "suche", "wo", "symbol"],
            "git.status": ["git", "status", "changed", "änderungen", "aenderungen"],
            "git.diff": ["diff", "changes", "review", "patch"],
            "command.run": ["test", "phpunit", "composer", "npm", "build", "run"],
            "tools.read": ["tool", "tools", "werkzeug"],
            "internet.search": ["search", "research", "recherche", "recherchiere", "trends", "current", "aktuell", "internet"],
            "notification.send": ["notify", "notification", "alert", "reminder", "mac", "macos", "benachrichtigung"],
            "internet.fetch": ["web", "url", "http", "https", "internet", "website", "fetch", "read"],
        }
        score = 0.0
        for capability, needles in mapping.items():
            if capability not in capabilities:
                continue
            if any(needle in query for needle in needles):
                score += 2.0
        return score

    def _matches_examples(self, query: str, examples: Any) -> bool:
        if not isinstance(examples, list):
            return False
        query_tokens = self._tokens(query)
        for example in examples:
            example_text = str(example).lower()
            if sum(1 for token in query_tokens if token in example_text) >= 2:
                return True
        return False

    def _has_write_intent(self, query: str) -> bool:
        return any(needle in query for needle in ["create", "add", "write", "update", "delete", "erstelle", "ändere", "aendere"])

    def _wants_catalog(self, message: str) -> bool:
        message = message.lower()
        return any(needle in message for needle in ["welche tools", "alle tools", "tool liste", "available tools", "list tools"])

    def _capabilities(self, meta: dict[str, Any]) -> list[str]:
        values = meta.get("capabilities")
        return [str(value) for value in values] if isinstance(values, list) else []
