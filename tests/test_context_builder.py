from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.context_builder import ModeContextBuilder


def test_chat_context_contains_assistant_contract() -> None:
    builder = ModeContextBuilder(Settings(effort="minimum"))

    context = run_async(builder.build("missing", "chat", "Hallo"))

    assert "NixAI mode: CHAT" in context
    assert "Answer conversationally" in context
    assert "# ASSISTANT" in context


def test_code_context_uses_chat_workspace(db, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "app.py").write_text("print('hi')\n", encoding="utf-8")
    chat = db.create_chat("Code", workspace_path=str(workspace))
    builder = ModeContextBuilder(Settings(effort="minimum", workspace_path=str(tmp_path / "fallback")))

    context = run_async(builder.build(chat.id, "code", "Projekt struktur"))

    assert "NixAI mode: CODE" in context
    assert f"Configured workspace: {workspace}" in context
    assert "app.py" in context


def test_code_context_uses_injected_tools_from_mode_builder(db) -> None:
    class FakeCodeTools:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def workspace_root(self, workspace_path: str) -> Path:
            self.calls.append(("workspace_root", workspace_path))
            return Path("/fake/workspace")

        def list_files(self, path: str, workspace_path: str) -> object:
            self.calls.append(("list_files", workspace_path))
            return ["fake.py"]

        def read_file(self, path: str, workspace_path: str) -> object:
            self.calls.append(("read_file", path))
            return "fake content"

        def search_files(self, query: str, workspace_path: str) -> object:
            self.calls.append(("search_files", query))
            return []

        def git_status(self, workspace_path: str) -> object:
            self.calls.append(("git_status", workspace_path))
            return "clean"

        def git_diff(self, workspace_path: str) -> object:
            self.calls.append(("git_diff", workspace_path))
            return ""

    tools = FakeCodeTools()
    chat = db.create_chat("Injected", workspace_path="/fake/workspace")
    builder = ModeContextBuilder(Settings(effort="minimum"), code_tools=tools)

    context = run_async(builder.build(chat.id, "code", "Projekt struktur"))

    assert "Workspace: /fake/workspace" in context
    assert "fake.py" in context
    assert ("workspace_root", "/fake/workspace") in tools.calls
    assert ("list_files", "/fake/workspace") in tools.calls


def test_code_context_accepts_builder_factory(db) -> None:
    class FakeCodeContextBuilder:
        def __init__(self, workspace: str) -> None:
            self.workspace = workspace

        def build(self, user_message: str) -> str:
            return f"factory context for {self.workspace}: {user_message}"

    chat = db.create_chat("Factory", workspace_path="/factory/workspace")
    builder = ModeContextBuilder(
        Settings(effort="minimum"),
        code_context_builder_factory=lambda workspace: FakeCodeContextBuilder(workspace),
    )

    context = run_async(builder.build(chat.id, "code", "lies app.py"))

    assert "factory context for /factory/workspace: lies app.py" in context


def test_agentic_context_includes_tool_context(monkeypatch) -> None:
    class FakeAgenticContextBuilder:
        def __init__(self, settings, ollama=None) -> None:
            self.settings = settings
            self.ollama = ollama

        async def build(self, user_message: str) -> str:
            return f"fake tools for {user_message}"

    monkeypatch.setattr("app.context_builder.AgenticContextBuilder", FakeAgenticContextBuilder)
    builder = ModeContextBuilder(Settings(effort="minimum"))

    context = run_async(builder.build("missing", "agentic", "Analysiere"))

    assert "NixAI mode: AGENTIC" in context
    assert "fake tools for Analysiere" in context
    assert "# ORCHESTRATOR" in context


def run_async(coro):
    import asyncio

    return asyncio.run(coro)
