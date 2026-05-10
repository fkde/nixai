from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Optional

from app import database
from app.agentic_context import AgenticContextBuilder
from app.agentic_schedule import compute_next_run, utc_now_dt
from app.code_context import CodeContextBuilder
from app.config import load_settings
from app.effort import effort_context, normalize_effort
from app.llm.ollama import OllamaClient
from app.memory import memory_context
from app.models import CreateMessageResponse, Message, MessageMode, new_id, utc_now
from app.roles import role_prompt
from app.runtime_context import runtime_meta_context
from app.task_discovery import TaskDiscovery
from app.workflows.presets import selected_workflow
from app.workflows.runner import WorkflowRunner


TITLE_GENERATION_RUNNING: set[str] = set()
DEFAULT_CHAT_TITLES = {"Neuer Chat", "New Chat"}


class Agent:
    def __init__(self, ollama: Optional[OllamaClient] = None, effort: str | None = None) -> None:
        self.settings = load_settings()
        if effort is not None:
            self.settings.effort = normalize_effort(effort)
        self.ollama = ollama or OllamaClient(self.settings)

    async def run(self, chat_id: str, user_message: str, mode: MessageMode = "chat") -> CreateMessageResponse:
        user, answer = await self._answer(chat_id, user_message, mode)
        self._schedule_chat_title_generation(chat_id, user_message, mode)
        assistant = database.add_message(chat_id, "assistant", answer, mode=mode)
        return CreateMessageResponse(user_message=user, assistant_message=assistant)

    async def stream(self, chat_id: str, user_message: str, mode: MessageMode = "chat") -> AsyncIterator[dict[str, object]]:
        user = self._store_user_message(chat_id, user_message, mode)
        yield {"type": "user_message", "message": user.model_dump()}

        static_answer = None
        if mode == "agentic":
            yield {"type": "status", "message": "Checking task intent..."}
            static_answer = await self._agentic_static_answer(user_message)

        if static_answer is not None:
            yield {"type": "status", "message": "Preparing agentic task..."}
            streamed = ""
            async for chunk in self._stream_static_text(static_answer):
                streamed += chunk
                yield {"type": "token", "content": chunk}
            assistant = database.add_message(chat_id, "assistant", static_answer, mode=mode)
            self._schedule_chat_title_generation(chat_id, user_message, mode)
            yield {"type": "assistant_message", "message": assistant.model_dump()}
            yield {"type": "done", "stats": {"eval_count": len(streamed.split())}}
            return

        workflow = selected_workflow(self.settings, mode)
        if workflow is not None and not workflow.is_direct():
            yield {"type": "status", "message": f"Running workflow: {workflow.name}"}
            queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()

            def on_workflow_event(event) -> None:
                if event.node == "final" and event.type == "token":
                    queue.put_nowait({"type": "token", "content": event.message})
                    return
                queue.put_nowait(
                    {
                        "type": "workflow_status",
                        "message": event.message,
                        "node": event.node,
                        "status": event.type,
                    }
                )

            runner = WorkflowRunner(self.settings, self.ollama)
            task = asyncio.create_task(runner.run(workflow, chat_id, user_message, mode, on_event=on_workflow_event))
            while not task.done() or not queue.empty():
                try:
                    workflow_event = await asyncio.wait_for(queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                yield workflow_event
            result = await task
            streamed = ""
            if result.state.get("answer_streamed"):
                streamed = result.answer
            else:
                async for chunk in self._stream_static_text(result.answer):
                    streamed += chunk
                    yield {"type": "token", "content": chunk}
            assistant = database.add_message(chat_id, "assistant", result.answer, mode=mode)
            self._schedule_chat_title_generation(chat_id, user_message, mode)
            yield {"type": "assistant_message", "message": assistant.model_dump()}
            yield {"type": "done", "stats": {"eval_count": len(streamed.split())}}
            return

        workflow_answer = await self._workflow_answer(chat_id, user_message, mode)
        if workflow_answer is not None:
            streamed = ""
            async for chunk in self._stream_static_text(workflow_answer):
                streamed += chunk
                yield {"type": "token", "content": chunk}
            assistant = database.add_message(chat_id, "assistant", workflow_answer, mode=mode)
            self._schedule_chat_title_generation(chat_id, user_message, mode)
            yield {"type": "assistant_message", "message": assistant.model_dump()}
            yield {"type": "done", "stats": {"eval_count": len(streamed.split())}}
            return

        content_parts: list[str] = []
        if mode == "agentic":
            yield {"type": "status", "message": "Preparing agentic context..."}
        history = await self._history_with_mode_context(chat_id, mode, user_message)
        async for event in self.ollama.stream_chat(history, model=self.settings.model_for_role(self._model_role_for_mode(mode))):
            if event.get("type") == "token":
                content = str(event.get("content") or "")
                content_parts.append(content)
                yield {"type": "token", "content": content}
            elif event.get("type") == "done":
                answer = "".join(content_parts)
                assistant = database.add_message(chat_id, "assistant", answer, mode=mode)
                self._schedule_chat_title_generation(chat_id, user_message, mode)
                yield {"type": "assistant_message", "message": assistant.model_dump()}
                yield {"type": "done", "stats": self._stream_stats(event)}

    async def _answer(self, chat_id: str, user_message: str, mode: MessageMode) -> tuple[Message, str]:
        user = self._store_user_message(chat_id, user_message, mode)
        static_answer = await self._agentic_static_answer(user_message) if mode == "agentic" else None
        if static_answer is not None:
            return user, static_answer
        workflow_answer = await self._workflow_answer(chat_id, user_message, mode)
        if workflow_answer is not None:
            return user, workflow_answer
        history = await self._history_with_mode_context(chat_id, mode, user_message)
        answer = await self.ollama.chat(history, model=self.settings.model_for_role(self._model_role_for_mode(mode)))
        return user, answer

    def _store_user_message(self, chat_id: str, user_message: str, mode: MessageMode) -> Message:
        chat = database.get_chat(chat_id)
        if chat is None:
            raise ValueError("Chat not found")

        user = database.add_message(chat_id, "user", user_message, mode=mode)
        return user

    def _schedule_chat_title_generation(self, chat_id: str, user_message: str, mode: MessageMode) -> None:
        chat = database.get_chat(chat_id)
        if chat is None or chat.title not in DEFAULT_CHAT_TITLES or chat_id in TITLE_GENERATION_RUNNING:
            return
        TITLE_GENERATION_RUNNING.add(chat_id)
        asyncio.create_task(self._generate_chat_title(chat_id, user_message, mode))

    async def _generate_chat_title(self, chat_id: str, user_message: str, mode: MessageMode) -> None:
        try:
            prompt = (
                "Generate a concise chat title for the user's request.\n"
                "Rules:\n"
                "- Return only the title.\n"
                "- 2 to 6 words.\n"
                "- Match the user's language.\n"
                "- No quotes, no markdown, no trailing punctuation.\n"
                "- Prefer a useful summary over copying the full sentence.\n\n"
                f"Mode: {mode}\n"
                f"User request: {user_message}"
            )
            title = await self.ollama.chat_payload(
                [
                    {
                        "role": "system",
                        "content": f"{runtime_meta_context(user_message)}\n\nYou write short app sidebar titles. Return plain text only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                model=self.settings.model_for_role("assistant"),
            )
            clean_title = self._clean_chat_title(title)
            if clean_title:
                database.update_chat_title_if_default(chat_id, clean_title)
        except Exception:
            return
        finally:
            TITLE_GENERATION_RUNNING.discard(chat_id)

    def _clean_chat_title(self, title: str) -> str:
        clean = " ".join(str(title or "").strip().split())
        clean = clean.strip("\"'`“”„")
        clean = clean.removeprefix("- ").removeprefix("* ").strip()
        clean = clean.rstrip(".:;")
        if not clean or clean in DEFAULT_CHAT_TITLES:
            return ""
        return clean[:56]

    async def _agentic_static_answer(self, user_message: str) -> str | None:
        discovery = await TaskDiscovery(self.settings, self.ollama).discover(user_message)
        task = self._create_agentic_task(discovery) if discovery and discovery.is_scheduled_task else None
        if task is not None:
            task_type = "einmaliger" if discovery.is_one_shot_task else "wiederkehrender"
            answer = (
                f"**Task angelegt:** {task.title}\n\n"
                f"- **Typ:** {task_type} Task\n"
                f"- **Zeitplan:** {task.schedule}\n"
                f"- **Status:** {task.status}\n\n"
                "Du kannst ihn in den Settings bearbeiten, pausieren, loeschen oder manuell starten."
            )
        elif discovery and discovery.canonical_kind in {"recurring_task", "one_shot_task", "one_time_task"} and discovery.missing_info:
            answer = (
                "Ich brauche noch ein paar Angaben, bevor ich daraus einen geplanten Task mache:\n\n"
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

    async def _workflow_answer(self, chat_id: str, user_message: str, mode: MessageMode) -> str | None:
        workflow = selected_workflow(self.settings, mode)
        if workflow is None or workflow.is_direct():
            return None
        result = await WorkflowRunner(self.settings, self.ollama).run(workflow, chat_id, user_message, mode)
        return result.answer

    async def _history_with_mode_context(self, chat_id: str, mode: MessageMode, user_message: str = "") -> list[Message]:
        history = database.list_messages(chat_id, mode=mode)
        return [self._system_message(chat_id, await self._mode_context(chat_id, mode, user_message)), *history]

    async def _mode_context(self, chat_id: str, mode: MessageMode, user_message: str = "") -> str:
        meta_context = runtime_meta_context(user_message)
        effort_block = effort_context(self.settings.effort)
        if mode == "code":
            workspace = self._workspace_for_chat(chat_id)
            return (
                f"{role_prompt('WORKER')}\n\n"
                f"{meta_context}\n\n"
                f"{effort_block}\n\n"
                f"{self._memory_context_block()}\n\n"
                "NixAI mode: CODE.\n"
                f"Configured workspace: {workspace}\n"
                "Help with code and project understanding. Prefer workspace-grounded answers. "
                "Do not claim that files, Git, or tests were inspected unless tool results are provided.\n\n"
                f"{CodeContextBuilder(workspace).build(user_message)}"
            )
        if mode == "agentic":
            agentic_context = await AgenticContextBuilder(self.settings, self.ollama).build(user_message)
            research_block = f"\n\n{agentic_context}" if agentic_context else ""
            return (
                f"{role_prompt('ORCHESTRATOR')}\n\n"
                f"{meta_context}\n\n"
                f"{effort_block}\n\n"
                f"{self._memory_context_block()}\n\n"
                "NixAI mode: AGENTIC.\n"
                "Act as an autonomous local orchestrator, not only as a scheduler. "
                "If NixAI tool context is supplied, use it as evidence for the answer and do not fall back to training-data disclaimers. "
                "If the request sounds recurring or one-time scheduled, TaskDiscovery may already have created the task; do not ask for schedule details unless the user is explicitly scheduling something. "
                "The current POC can store and run scheduled Agentic Tasks with approved tools."
                f"{research_block}"
            )
        return (
            f"{role_prompt('ASSISTANT')}\n\n"
            f"{meta_context}\n\n"
            f"{effort_block}\n\n"
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
