from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.tools import filesystem, git, internet, notification, shell
from app.tools.definitions import ToolDefinition, ToolHandler


ToolFactory = Callable[[], ToolDefinition]


def _string_schema(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}


def make_workspace_list_files_tool() -> ToolDefinition:
    return ToolDefinition(
        name="nixai_workspace_list_files",
        description="Lists files inside the configured workspace.",
        routing_description="Use when the user asks what files exist, wants a project overview, or needs workspace structure.",
        input_schema=_object_schema({"path": _string_schema("Workspace-relative directory or file path.")}),
        handler=lambda args: filesystem.list_files(str(args.get("path") or ".")),
        examples=["List project files", "Welche Dateien gibt es?", "Show workspace structure"],
    )


def make_workspace_read_file_tool() -> ToolDefinition:
    return ToolDefinition(
        name="nixai_workspace_read_file",
        description="Reads a UTF-8 text file inside the configured workspace.",
        routing_description="Use when a specific file path must be inspected before answering.",
        input_schema=_object_schema({"path": _string_schema("Workspace-relative file path.")}, ["path"]),
        handler=lambda args: filesystem.read_file(str(args.get("path") or "")),
        examples=["Read README.md", "Öffne app/main.py", "Show this file"],
    )


def make_workspace_search_files_tool() -> ToolDefinition:
    return ToolDefinition(
        name="nixai_workspace_search_files",
        description="Searches workspace file names and text contents for a query.",
        routing_description="Use when the user asks where something is implemented or mentions a symbol, function, or phrase.",
        input_schema=_object_schema({"query": _string_schema("Search query.")}, ["query"]),
        handler=lambda args: filesystem.search_files(str(args.get("query") or "")),
        examples=["Search for Agent", "Wo ist git_diff?", "Find config usage"],
    )


def make_git_status_tool() -> ToolDefinition:
    return ToolDefinition(
        name="nixai_git_status",
        description="Returns git status for the configured workspace.",
        routing_description="Use when the user asks for repository state, changed files, or cleanliness.",
        input_schema=_object_schema({}),
        handler=lambda args: git.git_status(),
        examples=["Git status", "Welche Änderungen gibt es?", "Is the tree clean?"],
    )


def make_git_diff_tool() -> ToolDefinition:
    return ToolDefinition(
        name="nixai_git_diff",
        description="Returns git diff for the configured workspace.",
        routing_description="Use when the user asks what changed or wants to review modifications.",
        input_schema=_object_schema({}),
        handler=lambda args: git.git_diff(),
        examples=["Show diff", "Was wurde geändert?", "Review current changes"],
    )


def make_shell_command_tool() -> ToolDefinition:
    return ToolDefinition(
        name="nixai_run_command",
        description="Runs one explicitly allowlisted command in the configured workspace.",
        routing_description="Use for tests or build checks only when the command is on the allowlist.",
        input_schema=_object_schema({"command": _string_schema("Allowlisted command to run.")}, ["command"]),
        handler=lambda args: shell.run_command(str(args.get("command") or "")),
        examples=["Run npm test", "composer phpunit ausführen", "Run git status"],
        meta={"autoRun": False},
    )


def make_desktop_notification_tool() -> ToolDefinition:
    return ToolDefinition(
        name="nixai_notify_desktop",
        description="Sends a macOS desktop notification from NixAI.",
        routing_description="Use when the user asks NixAI to notify them, alert them, or send a local Mac notification.",
        input_schema=_object_schema(
            {
                "title": _string_schema("Short notification title."),
                "message": _string_schema("Notification body text."),
                "subtitle": _string_schema("Optional notification subtitle."),
                "sound": _string_schema('Optional macOS notification sound name, or "none" for silent.'),
            },
            ["message"],
        ),
        handler=lambda args: notification.notify_desktop(
            str(args.get("title") or "NixAI"),
            str(args.get("message") or ""),
            str(args.get("subtitle") or ""),
            str(args.get("sound") or "Glass"),
        ),
        examples=["Notify me when the task is done", "Mac Notification senden", "Schick mir eine lokale Erinnerung"],
        meta={"autoRun": False},
    )


def make_web_search_tool() -> ToolDefinition:
    return ToolDefinition(
        name="nixai_web_search",
        description="Searches the public web and returns result titles and URLs.",
        routing_description=(
            "Use when the user asks to research, investigate, find current information, "
            "or discover relevant public web pages."
        ),
        input_schema=_object_schema(
            {
                "query": _string_schema("Search query."),
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            ["query"],
        ),
        handler=lambda args: internet.search_web(str(args.get("query") or ""), int(args.get("limit") or 5)),
        examples=["Search current AI trends", "Recherchiere aktuelle Internet-Trends", "Find sources about this topic"],
        meta={"autoRun": False},
    )


def make_web_fetch_url_tool() -> ToolDefinition:
    return ToolDefinition(
        name="nixai_web_fetch_url",
        description="Fetches text content from a public http or https URL.",
        routing_description="Use when the user asks to read a specific public web page or retrieve internet content from a URL.",
        input_schema=_object_schema({"url": _string_schema("Public http or https URL to fetch.")}, ["url"]),
        handler=lambda args: internet.fetch_url(str(args.get("url") or "")),
        examples=["Fetch https://example.com", "Read this URL", "Hole den Inhalt dieser Webseite"],
        meta={"autoRun": False},
    )


def make_web_check_url_tool() -> ToolDefinition:
    return ToolDefinition(
        name="nixai_web_check_url",
        description="Checks a public http or https URL and returns status metadata without reading the full body.",
        routing_description="Use when the user asks whether a website is reachable or wants lightweight URL metadata.",
        input_schema=_object_schema({"url": _string_schema("Public http or https URL to check.")}, ["url"]),
        handler=lambda args: internet.check_url(str(args.get("url") or "")),
        examples=["Check https://example.com", "Ist diese URL erreichbar?", "Website Status prüfen"],
        meta={"autoRun": False},
    )


def make_tool_search_tool(handler: ToolHandler) -> ToolDefinition:
    return ToolDefinition(
        name="nixai_tools_search",
        description="Searches the registered NixAI tools for the current request and context.",
        routing_description="Use when the visible tools do not clearly cover the user request.",
        input_schema=_object_schema(
            {
                "query": _string_schema("Tool search query."),
                "context": {"type": "object", "description": "Optional routing context.", "additionalProperties": True},
                "capabilities": {"type": "array", "items": {"type": "string"}},
                "mode": _string_schema("Optional mode filter such as read or write."),
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
            },
            ["query"],
        ),
        handler=handler,
        examples=["Find more tools", "Welche Tools passen?", "Search tools by capability"],
    )


def base_tool_factories(search_handler: ToolHandler) -> list[ToolFactory]:
    return [
        make_workspace_list_files_tool,
        make_workspace_read_file_tool,
        make_workspace_search_files_tool,
        make_git_status_tool,
        make_git_diff_tool,
        make_shell_command_tool,
        make_desktop_notification_tool,
        make_web_search_tool,
        make_web_fetch_url_tool,
        make_web_check_url_tool,
        lambda: make_tool_search_tool(search_handler),
    ]


def create_base_tool_definitions(search_handler: ToolHandler) -> list[ToolDefinition]:
    return [factory() for factory in base_tool_factories(search_handler)]
