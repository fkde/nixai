from __future__ import annotations

from typing import Optional

from app import database
from app.agentic_schedule import compute_next_run, utc_now_dt
from app.code_context import CodeContextBuilder
from app.config import load_settings
from app.llm.ollama import OllamaClient
from app.mistakes import mistakes_context
from app.models import CreateMessageResponse, Message, MessageMode, new_id, utc_now
from app.roles import role_prompt
from app.task_discovery import TaskDiscovery


class Agent:
    def __init__(self, ollama: Optional[OllamaClient] = None) -> None:
        self.settings = load_settings()
        self.ollama = ollama or OllamaClient(self.settings)

    async def run(self, chat_id: str, user_message: str, mode: MessageMode = "chat") -> CreateMessageResponse:
        chat = database.get_chat(chat_id)
        if chat is None:
            raise ValueError("Chat not found")

        user = database.add_message(chat_id, "user", user_message, mode=mode)
        database.update_chat_title_if_default(chat_id, user_message)

        discovery = await TaskDiscovery(self.settings, self.ollama).discover(user_message) if mode == "agentic" else None
        task = self._create_agentic_task(discovery) if discovery and discovery.is_recurring_task else None
        if task is not None:
            answer = (
                f"[agentic] Ich habe einen wiederkehrenden Task angelegt: {task.title}\n\n"
                f"Schedule: {task.schedule}\n"
                f"Status: {task.status}\n\n"
                f"TaskDiscovery: {discovery.reason or 'recurring_task'}\n\n"
                "Die Ausfuehrung ist in dieser ersten Version noch nicht aktiv. "
                "Du kannst den Task in den Einstellungen bearbeiten, pausieren oder loeschen."
            )
        elif discovery and discovery.missing_info:
            answer = (
                "[agentic] Ich brauche noch ein paar Angaben, bevor ich daraus einen wiederkehrenden Task mache:\n\n"
                + "\n".join(f"- {item}" for item in discovery.missing_info)
            )
        else:
            history = self._history_with_mode_context(chat_id, mode, user_message)
            answer = await self.ollama.chat(history, model=self.settings.model_for_role(self._model_role_for_mode(mode)))
        assistant = database.add_message(chat_id, "assistant", answer, mode=mode)
        return CreateMessageResponse(user_message=user, assistant_message=assistant)

    def _history_with_mode_context(self, chat_id: str, mode: MessageMode, user_message: str = "") -> list[Message]:
        history = database.list_messages(chat_id)
        return [self._system_message(chat_id, self._mode_context(mode, user_message)), *history]

    def _mode_context(self, mode: MessageMode, user_message: str = "") -> str:
        if mode == "code":
            workspace = self.settings.workspace_path
            return (
                f"{role_prompt('WORKER')}\n\n"
                f"{self._mistakes_context_block()}\n\n"
                "NixAI mode: CODE.\n"
                f"Configured workspace: {workspace}\n"
                "Help with code and project understanding. Prefer workspace-grounded answers. "
                "Do not claim that files, Git, or tests were inspected unless tool results are provided.\n\n"
                f"{CodeContextBuilder().build(user_message)}"
            )
        if mode == "agentic":
            return (
                f"{role_prompt('ORCHESTRATOR')}\n\n"
                f"{self._mistakes_context_block()}\n\n"
                "NixAI mode: AGENTIC.\n"
                "Guide the user through a controlled agent workflow. If the request sounds recurring, "
                "ask for missing schedule details or confirm the recurring task plan. "
                "The current POC can store agentic task definitions, but does not execute them yet."
            )
        return (
            f"{role_prompt('ASSISTANT')}\n\n"
            "NixAI mode: CHAT. Answer conversationally without assuming workspace tool access."
        )

    def _mistakes_context_block(self) -> str:
        return "Shared mistakes and corrections:\n" + mistakes_context()

    def _system_message(self, chat_id: str, content: str) -> Message:
        return Message(id=new_id(), chat_id=chat_id, role="system", content=content, mode="chat", created_at=utc_now())

    def _model_role_for_mode(self, mode: MessageMode) -> str:
        if mode == "code":
            return "worker"
        if mode == "agentic":
            return "orchestrator"
        return "assistant"

    def _create_agentic_task(self, discovery):
        task = database.create_agentic_task(
            title=discovery.title,
            prompt=discovery.prompt,
            schedule=discovery.schedule,
        )
        return database.update_agentic_task_schedule_state(
            task.id,
            next_run_at=compute_next_run(task.schedule, utc_now_dt()),
        ) or task
