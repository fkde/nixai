from __future__ import annotations

import re
from typing import Any

from app.tools.definitions import ToolDefinition


class ToolCatalog:
    def enrich(self, definitions: list[ToolDefinition]) -> list[ToolDefinition]:
        return [definition.with_meta(self._metadata(definition)) for definition in definitions]

    def _metadata(self, definition: ToolDefinition) -> dict[str, Any]:
        name = definition.name.strip().lower()
        description = definition.description.strip().lower()
        text = f"{name} {description} {definition.routing_description.lower()}"
        risk = self._risk(text, name)

        return {
            "category": self._category(text, name),
            "source": "nixai",
            "risk": risk,
            "destructive": self._destructive(text, name),
            "mode": "write" if risk == "write" else "read",
            "capabilities": self._capabilities(text, name),
            "routingText": self._routing_text(definition),
            "examples": self._examples(definition, name),
            "tags": self._tags(name, description),
            "autoRun": definition.meta.get("autoRun", risk == "read"),
            **definition.meta,
        }

    def _category(self, text: str, name: str) -> str:
        if name == "nixai_tools_search":
            return "tools"
        if self._contains(text, ["notification", "notify", "desktop", "macos"]):
            return "notification"
        if self._contains(text, ["web", "url", "http", "internet", "website"]):
            return "internet"
        if self._contains(text, ["git", "diff", "status"]):
            return "git"
        if self._contains(text, ["file", "filesystem", "read", "search", "workspace"]):
            return "filesystem"
        if self._contains(text, ["test", "phpunit", "composer", "npm", "build", "command"]):
            return "shell"
        return "workspace"

    def _risk(self, text: str, name: str) -> str:
        if self._contains(text, ["notification", "notify", "send alert"]):
            return "external"
        if self._contains(text, ["web", "url", "http", "internet", "website"]):
            return "external"
        if self._contains(text, ["write", "update", "delete", "remove", "commit", "create file", "edit"]):
            return "write"
        return "read"

    def _destructive(self, text: str, name: str) -> bool:
        return self._contains(f"{text} {name}", ["delete", "remove", "discard", "reset", "rollback"])

    def _capabilities(self, text: str, name: str) -> list[str]:
        capabilities: list[str] = []
        if name == "nixai_tools_search":
            capabilities.append("tools.read")
        if self._contains(text, ["list", "file", "workspace"]):
            capabilities.append("filesystem.list")
        if self._contains(text, ["read file", "content", "open file"]):
            capabilities.append("filesystem.read")
        if self._contains(text, ["search", "find"]):
            capabilities.append("filesystem.search")
        if self._contains(text, ["git status"]):
            capabilities.append("git.status")
        if self._contains(text, ["git diff", "diff"]):
            capabilities.append("git.diff")
        if self._contains(text, ["test", "phpunit", "composer", "npm", "build", "command"]):
            capabilities.append("command.run")
        if self._contains(text, ["notification", "notify", "desktop", "macos"]):
            capabilities.append("notification.send")
        if self._contains(text, ["web", "url", "http", "internet", "website"]):
            capabilities.append("internet.fetch")
        return sorted(set(capabilities or ["workspace.read"]))

    def _routing_text(self, definition: ToolDefinition) -> str:
        properties = definition.input_schema.get("properties", {})
        property_names = " ".join(properties.keys()) if isinstance(properties, dict) else ""
        return " ".join(
            part.strip()
            for part in [
                definition.name,
                definition.description,
                definition.routing_description,
                " ".join(definition.examples),
                property_names,
            ]
            if part.strip()
        )

    def _examples(self, definition: ToolDefinition, name: str) -> list[str]:
        examples = [example.strip() for example in definition.examples if example.strip()]
        if name == "nixai_tools_search":
            examples.extend(["Find more tools for this request", "Welche Tools passen hierzu?"])
        return examples

    def _tags(self, name: str, description: str) -> list[str]:
        stop = {"nixai", "returns", "return", "and", "for", "the", "with", "from", "into", "optional"}
        tags = []
        for word in re.split(r"[^a-z0-9]+", f"{name} {description}".lower()):
            if len(word) < 3 or word in stop or word in tags:
                continue
            tags.append(word)
            if len(tags) >= 18:
                break
        return tags

    def _contains(self, haystack: str, needles: list[str]) -> bool:
        return any(needle in haystack for needle in needles)
