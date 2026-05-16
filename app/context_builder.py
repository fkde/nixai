from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from app import database
from app.agentic_context import AgenticContextBuilder
from app.code_context import CodeContextBuilder, CodeContextTools
from app.config import Settings
from app.effort import effort_context
from app.llm.ollama import OllamaClient
from app.memory import memory_context
from app.models import MessageMode
from app.roles import role_prompt
from app.runtime_context import runtime_meta_context


CodeContextBuilderFactory = Callable[[str], CodeContextBuilder]


class ModeContextBuilder:
    """Build the system context block for a chat mode.

    Agent owns the conversational flow; this builder owns prompt assembly and
    bounded tool-context gathering for each mode.
    """

    def __init__(
        self,
        settings: Settings,
        ollama: Optional[OllamaClient] = None,
        code_tools: CodeContextTools | None = None,
        code_context_builder_factory: CodeContextBuilderFactory | None = None,
    ) -> None:
        self.settings = settings
        self.ollama = ollama
        self.code_tools = code_tools
        self.code_context_builder_factory = code_context_builder_factory

    async def build(self, chat_id: str, mode: MessageMode, user_message: str = "") -> str:
        meta_context = runtime_meta_context(user_message)
        effort_block = effort_context(self.settings.effort)
        if mode == "code":
            return self._build_code_context(chat_id, user_message, meta_context, effort_block)
        if mode == "agentic":
            return await self._build_agentic_context(user_message, meta_context, effort_block)
        return self._build_chat_context(meta_context, effort_block)

    def workspace_for_chat(self, chat_id: str) -> str:
        chat = database.get_chat(chat_id)
        return (chat.workspace_path if chat and chat.workspace_path.strip() else self.settings.workspace_path).strip()

    def memory_context_block(self) -> str:
        return "Shared reviewed memory:\n" + memory_context()

    def _build_code_context(self, chat_id: str, user_message: str, meta_context: str, effort_block: str) -> str:
        workspace = self.workspace_for_chat(chat_id)
        return (
            f"{role_prompt('WORKER')}\n\n"
            f"{meta_context}\n\n"
            f"{effort_block}\n\n"
            f"{self.memory_context_block()}\n\n"
            "NixAI mode: CODE.\n"
            f"Configured workspace: {workspace}\n"
            "Help with code and project understanding. Prefer workspace-grounded answers. "
            "Do not claim that files, Git, or tests were inspected unless tool results are provided.\n\n"
            f"{self._code_context_builder(workspace).build(user_message)}"
        )

    def _code_context_builder(self, workspace: str) -> CodeContextBuilder:
        if self.code_context_builder_factory is not None:
            return self.code_context_builder_factory(workspace)
        return CodeContextBuilder(workspace, tools=self.code_tools)

    async def _build_agentic_context(self, user_message: str, meta_context: str, effort_block: str) -> str:
        agentic_context = await AgenticContextBuilder(self.settings, self.ollama).build(user_message)
        research_block = f"\n\n{agentic_context}" if agentic_context else ""
        return (
            f"{role_prompt('ORCHESTRATOR')}\n\n"
            f"{meta_context}\n\n"
            f"{effort_block}\n\n"
            f"{self.memory_context_block()}\n\n"
            "NixAI mode: AGENTIC.\n"
            "Act as an autonomous local orchestrator, not only as a scheduler. "
            "If NixAI tool context is supplied, use it as evidence for the answer and do not fall back to training-data disclaimers. "
            "If the request sounds recurring or one-time scheduled, TaskDiscovery may already have created the task; do not ask for schedule details unless the user is explicitly scheduling something. "
            "The current POC can store and run scheduled Agentic Tasks with approved tools."
            f"{research_block}"
        )

    def _build_chat_context(self, meta_context: str, effort_block: str) -> str:
        return (
            f"{role_prompt('ASSISTANT')}\n\n"
            f"{meta_context}\n\n"
            f"{effort_block}\n\n"
            "NixAI mode: CHAT. Answer conversationally without assuming workspace tool access."
        )
