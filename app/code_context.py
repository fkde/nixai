from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.tools import filesystem, git
from app.tools.workspace import WorkspaceError, workspace_root


MAX_RESULT_CHARS = 8_000
MAX_CONTEXT_CHARS = 24_000


class CodeContextBuilder:
    def __init__(self, workspace_path: str = "") -> None:
        self.workspace_path = workspace_path

    def build(self, user_message: str) -> str:
        sections = [
            "NixAI code mode tool policy:",
            "- The model never receives direct native shell access.",
            "- Context is gathered through NixAI workspace tools only.",
            "- Read-only filesystem and Git inspection may run automatically.",
            "- Tests/build commands stay allowlisted and require explicit user intent.",
            "",
        ]

        try:
            root = workspace_root(self.workspace_path)
        except WorkspaceError as exc:
            return "\n".join([*sections, f"Workspace error: {exc}"])

        sections.append(f"Workspace: {root}")
        for result in self._collect_tool_results(user_message):
            sections.extend(["", self._format_result(result)])

        context = "\n".join(sections)
        if len(context) > MAX_CONTEXT_CHARS:
            context = context[:MAX_CONTEXT_CHARS].rstrip() + "\n...[code context truncated]"
        return context

    def _collect_tool_results(self, user_message: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        lower = user_message.casefold()

        if self._asks_for_project_overview(lower):
            results.append(self._call("nixai_workspace_list_files", {"path": "."}))

        path = self._extract_path(user_message)
        if path:
            results.append(self._call("nixai_workspace_read_file", {"path": path}))

        query = self._extract_search_query(user_message)
        if query:
            results.append(self._call("nixai_workspace_search_files", {"query": query}))

        if self._mentions_git_status(lower):
            results.append(self._call("nixai_git_status", {}))

        if self._mentions_git_diff(lower):
            results.append(self._call("nixai_git_diff", {}))

        if self._mentions_tests(lower):
            results.append(
                {
                    "tool": "nixai_run_command",
                    "arguments": {},
                    "result": "Test/build commands are available only through the allowlist and should be requested explicitly.",
                }
            )

        if not results:
            results.append(self._call("nixai_workspace_list_files", {"path": "."}))
        return results

    def _call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if tool == "nixai_workspace_list_files":
                result = filesystem.list_files(str(arguments.get("path") or "."), self.workspace_path)
            elif tool == "nixai_workspace_read_file":
                result = filesystem.read_file(str(arguments.get("path") or ""), self.workspace_path)
            elif tool == "nixai_workspace_search_files":
                result = filesystem.search_files(str(arguments.get("query") or ""), self.workspace_path)
            elif tool == "nixai_git_status":
                result = git.git_status(self.workspace_path)
            elif tool == "nixai_git_diff":
                result = git.git_diff(self.workspace_path)
            else:
                result = f"Tool is not available in code context: {tool}"
        except Exception as exc:
            result = f"Tool error: {exc}"
        return {"tool": tool, "arguments": arguments, "result": result}

    def _format_result(self, item: dict[str, Any]) -> str:
        result = item["result"]
        if isinstance(result, list):
            rendered = "\n".join(str(value) for value in result[:200])
            if len(result) > 200:
                rendered += f"\n... {len(result) - 200} more result(s)"
        else:
            rendered = str(result)

        if len(rendered) > MAX_RESULT_CHARS:
            rendered = rendered[:MAX_RESULT_CHARS].rstrip() + "\n...[tool result truncated]"
        return f"Tool: {item['tool']}\nArguments: {item['arguments']}\nResult:\n{rendered}"

    def _asks_for_project_overview(self, lower: str) -> bool:
        terms = ["dateien", "files", "struktur", "structure", "tree", "ordner", "overview", "projekt"]
        return any(term in lower for term in terms)

    def _mentions_git_status(self, lower: str) -> bool:
        return "git status" in lower or "status" in lower and "git" in lower

    def _mentions_git_diff(self, lower: str) -> bool:
        return "git diff" in lower or "diff" in lower or "änderungen" in lower or "aenderungen" in lower

    def _mentions_tests(self, lower: str) -> bool:
        return any(term in lower for term in ["test", "tests", "phpunit", "build", "prüf", "pruef"])

    def _extract_path(self, text: str) -> str | None:
        for candidate in self._quoted_or_bare_tokens(text):
            if "/" not in candidate and "." not in Path(candidate).name:
                continue
            if re.search(r"\.(py|js|ts|html|css|md|json|toml|txt|yml|yaml|php|sh)$", candidate, re.IGNORECASE):
                return candidate
        return None

    def _extract_search_query(self, text: str) -> str | None:
        quoted = re.findall(r"`([^`]{2,120})`|\"([^\"]{2,120})\"|'([^']{2,120})'", text)
        for groups in quoted:
            value = next((group for group in groups if group), "").strip()
            if value and not self._looks_like_path(value):
                return value

        match = re.search(r"(?:suche|search|finde|find|where is|wo ist)\s+(.{2,120})", text, re.IGNORECASE)
        if match:
            return match.group(1).strip(" .?")

        return None

    def _quoted_or_bare_tokens(self, text: str) -> list[str]:
        tokens: list[str] = []
        for groups in re.findall(r"`([^`]+)`|\"([^\"]+)\"|'([^']+)'", text):
            tokens.extend(group for group in groups if group)
        tokens.extend(re.findall(r"\b[\w./-]+\.[A-Za-z0-9]{1,8}\b", text))
        return tokens

    def _looks_like_path(self, value: str) -> bool:
        return "/" in value or bool(re.search(r"\.[A-Za-z0-9]{1,8}$", value))
