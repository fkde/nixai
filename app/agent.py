from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Optional

from app import database
from app.agentic_routing import (
    AGENTIC_WORKFLOW_TOOL,
    DEFAULT_DIRECT_REASON,
    agentic_route_payload,
    agentic_router_prompt,
    agentic_workflow_fallback,
    compact_agentic_history,
    parse_agentic_route_response,
)
from app.agentic_schedule import compute_next_run, utc_now_dt
from app.config import load_settings
from app.context_builder import ModeContextBuilder
from app.effort import normalize_effort
from app.json_utils import parse_json_object
from app.llm.ollama import OllamaClient
from app.models import CreateMessageResponse, Message, MessageMode, new_id, utc_now
from app.task_discovery import TaskDiscovery
from app.title_generation import DEFAULT_CHAT_TITLES, build_chat_title_messages, clean_chat_title
from app.workflows.presets import selected_workflow
from app.workflows.runner import WorkflowRunner


TITLE_GENERATION_RUNNING: set[str] = set()
logger = logging.getLogger(__name__)


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
        run_agentic_workflow = False
        agentic_workflow_route: tuple[bool, str] | None = None
        if mode == "agentic" and workflow is not None and not workflow.is_direct():
            yield {"type": "status", "message": "Choosing response path..."}
            run_agentic_workflow, route_reason = await self._should_run_agentic_workflow(chat_id, user_message)
            agentic_workflow_route = (run_agentic_workflow, route_reason)
            yield {
                "type": "agentic_route",
                "path": "workflow" if run_agentic_workflow else "direct",
                "reason": route_reason,
                "tool": AGENTIC_WORKFLOW_TOOL,
            }
            if run_agentic_workflow:
                yield {"type": "status", "message": f"Using {AGENTIC_WORKFLOW_TOOL}: {route_reason}"}
            else:
                yield {"type": "status", "message": "Answering directly from conversation context."}

        if workflow is not None and not workflow.is_direct() and (mode != "agentic" or run_agentic_workflow):
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

        workflow_answer = await self._workflow_answer(
            chat_id,
            user_message,
            mode,
            agentic_workflow_route=agentic_workflow_route,
        )
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
            title = await self.ollama.chat_payload(
                build_chat_title_messages(user_message, mode),
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
        return clean_chat_title(title)

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

    async def _workflow_answer(
        self,
        chat_id: str,
        user_message: str,
        mode: MessageMode,
        agentic_workflow_route: tuple[bool, str] | None = None,
    ) -> str | None:
        workflow = selected_workflow(self.settings, mode)
        if workflow is None or workflow.is_direct():
            return None
        if mode == "agentic":
            run_workflow, _reason = agentic_workflow_route or await self._should_run_agentic_workflow(
                chat_id,
                user_message,
            )
            if not run_workflow:
                return None
        result = await WorkflowRunner(self.settings, self.ollama).run(workflow, chat_id, user_message, mode)
        return result.answer

    async def _should_run_agentic_workflow(self, chat_id: str, user_message: str) -> tuple[bool, str]:
        workflow = selected_workflow(self.settings, "agentic")
        if workflow is None or workflow.is_direct():
            return False, "No non-direct workflow configured."
        try:
            payload = agentic_route_payload(
                user_message=user_message,
                recent_messages=self._agentic_router_history(chat_id),
                workflow_name=workflow.name,
            )
            content = await self.ollama.chat_payload(
                [
                    {"role": "system", "content": self._agentic_router_prompt()},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                model=self.settings.model_for_role("orchestrator"),
            )
            decision = parse_agentic_route_response(content)
            return decision.run_workflow, decision.reason
        except Exception as exc:
            logger.warning("agentic router failed", exc_info=exc)
            if self._agentic_workflow_fallback(user_message):
                return True, "Fallback matched workflow-style request."
            return False, DEFAULT_DIRECT_REASON

    def _agentic_router_prompt(self) -> str:
        return agentic_router_prompt()

    def _agentic_router_history(self, chat_id: str, limit: int = 8) -> list[dict[str, str]]:
        messages = database.list_messages(chat_id, mode="agentic")
        return compact_agentic_history(messages, limit=limit)

    def _agentic_workflow_fallback(self, user_message: str) -> bool:
        return agentic_workflow_fallback(user_message)

    def _parse_json_object(self, content: str) -> dict[str, Any]:
        return parse_json_object(content)

    async def _history_with_mode_context(self, chat_id: str, mode: MessageMode, user_message: str = "") -> list[Message]:
        history = database.list_messages(chat_id, mode=mode)
        return [self._system_message(chat_id, await self._mode_context(chat_id, mode, user_message)), *history]

    async def _mode_context(self, chat_id: str, mode: MessageMode, user_message: str = "") -> str:
        return await ModeContextBuilder(self.settings, self.ollama).build(chat_id, mode, user_message)

    def _memory_context_block(self) -> str:
        return ModeContextBuilder(self.settings, self.ollama).memory_context_block()

    def _workspace_for_chat(self, chat_id: str) -> str:
        return ModeContextBuilder(self.settings, self.ollama).workspace_for_chat(chat_id)

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
