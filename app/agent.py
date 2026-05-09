from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Optional

from app import database
from app.agentic_schedule import compute_next_run, utc_now_dt
from app.code_context import CodeContextBuilder
from app.config import load_settings
from app.llm.ollama import OllamaClient
from app.memory import memory_context
from app.models import CreateMessageResponse, Message, MessageMode, new_id, utc_now
from app.roles import role_prompt
from app.task_discovery import TaskDiscovery


class Agent:
    def __init__(self, ollama: Optional[OllamaClient] = None) -> None:
        self.settings = load_settings()
        self.ollama = ollama or OllamaClient(self.settings)

    async def run(self, chat_id: str, user_message: str, mode: MessageMode = "chat") -> CreateMessageResponse:
        user, answer = await self._answer(chat_id, user_message, mode)
        assistant = database.add_message(chat_id, "assistant", answer, mode=mode)
        return CreateMessageResponse(user_message=user, assistant_message=assistant)

    async def stream(self, chat_id: str, user_message: str, mode: MessageMode = "chat") -> AsyncIterator[dict[str, object]]:
        user = self._store_user_message(chat_id, user_message, mode)
        yield {"type": "user_message", "message": user.model_dump()}

        static_answer = None
        if mode == "agentic":
            yield {"type": "status", "message": "TaskDiscovery prüft die Aufgabe..."}
            static_answer = await self._agentic_static_answer(user_message)

        if static_answer is not None:
            yield {"type": "status", "message": "Agentic Task wird vorbereitet..."}
            streamed = ""
            async for chunk in self._stream_static_text(static_answer):
                streamed += chunk
                yield {"type": "token", "content": chunk}
            assistant = database.add_message(chat_id, "assistant", static_answer, mode=mode)
            yield {"type": "assistant_message", "message": assistant.model_dump()}
            yield {"type": "done", "stats": {"eval_count": len(streamed.split())}}
            return

        content_parts: list[str] = []
        history = self._history_with_mode_context(chat_id, mode, user_message)
        async for event in self.ollama.stream_chat(history, model=self.settings.model_for_role(self._model_role_for_mode(mode))):
            if event.get("type") == "token":
                content = str(event.get("content") or "")
                content_parts.append(content)
                yield {"type": "token", "content": content}
            elif event.get("type") == "done":
                answer = "".join(content_parts)
                assistant = database.add_message(chat_id, "assistant", answer, mode=mode)
                yield {"type": "assistant_message", "message": assistant.model_dump()}
                yield {"type": "done", "stats": self._stream_stats(event)}

    async def _answer(self, chat_id: str, user_message: str, mode: MessageMode) -> tuple[Message, str]:
        user = self._store_user_message(chat_id, user_message, mode)
        static_answer = await self._agentic_static_answer(user_message) if mode == "agentic" else None
        if static_answer is not None:
            return user, static_answer
        history = self._history_with_mode_context(chat_id, mode, user_message)
        answer = await self.ollama.chat(history, model=self.settings.model_for_role(self._model_role_for_mode(mode)))
        return user, answer

    def _store_user_message(self, chat_id: str, user_message: str, mode: MessageMode) -> Message:
        chat = database.get_chat(chat_id)
        if chat is None:
            raise ValueError("Chat not found")

        user = database.add_message(chat_id, "user", user_message, mode=mode)
        database.update_chat_title_if_default(chat_id, user_message)
        return user

    async def _agentic_static_answer(self, user_message: str) -> str | None:
        discovery = await TaskDiscovery(self.settings, self.ollama).discover(user_message)
        task = self._create_agentic_task(discovery) if discovery and discovery.is_recurring_task else None
        if task is not None:
            answer = (
                f"[agentic] Ich habe einen wiederkehrenden Task angelegt: {task.title}\n\n"
                f"Schedule: {task.schedule}\n"
                f"Status: {task.status}\n\n"
                f"TaskDiscovery: {discovery.reason or 'recurring_task'}\n\n"
                "Der Scheduler kann den Task ausfuehren, solange NixAI laeuft. "
                "Du kannst ihn in den Einstellungen bearbeiten, pausieren, loeschen oder manuell starten."
            )
        elif discovery and discovery.missing_info:
            answer = (
                "[agentic] Ich brauche noch ein paar Angaben, bevor ich daraus einen wiederkehrenden Task mache:\n\n"
                + "\n".join(f"- {item}" for item in discovery.missing_info)
            )
        else:
            answer = None
        return answer

    async def _stream_static_text(self, text: str) -> AsyncIterator[str]:
        parts = text.split(" ")
        for index, part in enumerate(parts):
            suffix = "" if index == len(parts) - 1 else " "
            yield part + suffix
            await asyncio.sleep(0.012)

    def _history_with_mode_context(self, chat_id: str, mode: MessageMode, user_message: str = "") -> list[Message]:
        history = database.list_messages(chat_id, mode=mode)
        return [self._system_message(chat_id, self._mode_context(chat_id, mode, user_message)), *history]

    def _mode_context(self, chat_id: str, mode: MessageMode, user_message: str = "") -> str:
        if mode == "code":
            workspace = self._workspace_for_chat(chat_id)
            return (
                f"{role_prompt('WORKER')}\n\n"
                f"{self._memory_context_block()}\n\n"
                "NixAI mode: CODE.\n"
                f"Configured workspace: {workspace}\n"
                "Help with code and project understanding. Prefer workspace-grounded answers. "
                "Do not claim that files, Git, or tests were inspected unless tool results are provided.\n\n"
                f"{CodeContextBuilder(workspace).build(user_message)}"
            )
        if mode == "agentic":
            return (
                f"{role_prompt('ORCHESTRATOR')}\n\n"
                f"{self._memory_context_block()}\n\n"
                "NixAI mode: AGENTIC.\n"
                "Guide the user through a controlled agent workflow. If the request sounds recurring, "
                "ask for missing schedule details or confirm the recurring task plan. "
                "The current POC can store and run scheduled Agentic Tasks with approved tools."
            )
        return (
            f"{role_prompt('ASSISTANT')}\n\n"
            "NixAI mode: CHAT. Answer conversationally without assuming workspace tool access."
        )

    def _memory_context_block(self) -> str:
        return "Shared reviewed memory:\n" + memory_context()

    def _workspace_for_chat(self, chat_id: str) -> str:
        chat = database.get_chat(chat_id)
        return (chat.workspace_path if chat and chat.workspace_path.strip() else self.settings.workspace_path).strip()

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

    def _stream_stats(self, event: dict[str, object]) -> dict[str, object]:
        stats = {
            "eval_count": event.get("eval_count"),
            "eval_duration": event.get("eval_duration"),
            "prompt_eval_count": event.get("prompt_eval_count"),
            "prompt_eval_duration": event.get("prompt_eval_duration"),
        }
        eval_count = stats["eval_count"]
        eval_duration = stats["eval_duration"]
        if isinstance(eval_count, (int, float)) and isinstance(eval_duration, (int, float)) and eval_duration > 0:
            stats["tokens_per_second"] = round(float(eval_count) / (float(eval_duration) / 1_000_000_000), 2)
        return stats
