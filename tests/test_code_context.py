from __future__ import annotations

from pathlib import Path

from app.code_context import CodeContextBuilder
from app.tools.workspace import WorkspaceError


class FakeCodeTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def workspace_root(self, workspace_path: str) -> Path:
        self.calls.append(("workspace_root", workspace_path))
        return Path("/workspace")

    def list_files(self, path: str, workspace_path: str) -> object:
        self.calls.append(("list_files", path))
        return ["README.md", "src/app.py"]

    def read_file(self, path: str, workspace_path: str) -> object:
        self.calls.append(("read_file", path))
        if path == "app.py":
            raise ValueError("missing")
        return "print('ok')"

    def search_files(self, query: str, workspace_path: str) -> object:
        self.calls.append(("search_files", query))
        return ["src/app.py"]

    def git_status(self, workspace_path: str) -> object:
        self.calls.append(("git_status", workspace_path))
        return "clean"

    def git_diff(self, workspace_path: str) -> object:
        self.calls.append(("git_diff", workspace_path))
        return "diff --git"


def test_code_context_uses_injected_tools() -> None:
    tools = FakeCodeTools()
    context = CodeContextBuilder("/workspace", tools=tools).build("Projekt struktur mit git status und diff")

    assert "Workspace: /workspace" in context
    assert "README.md" in context
    assert "clean" in context
    assert "diff --git" in context
    assert ("list_files", ".") in tools.calls
    assert ("git_status", "/workspace") in tools.calls
    assert ("git_diff", "/workspace") in tools.calls


def test_code_context_read_path_fallback_uses_search_result() -> None:
    tools = FakeCodeTools()
    context = CodeContextBuilder("/workspace", tools=tools).build("Bitte lies app.py")

    assert "Tool error: missing" in context
    assert "Tool: nixai_workspace_search_files" in context
    assert "Arguments: {'path': 'src/app.py'}" in context
    assert "print('ok')" in context


def test_code_context_reports_workspace_error() -> None:
    class BrokenTools(FakeCodeTools):
        def workspace_root(self, workspace_path: str) -> Path:
            raise WorkspaceError("no workspace")

    context = CodeContextBuilder("/missing", tools=BrokenTools()).build("anything")

    assert "Workspace error: no workspace" in context
