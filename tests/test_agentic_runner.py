from __future__ import annotations

import asyncio
import json
from typing import Optional

from app import database
from app.agentic_runner import AgenticRunner
from app.services import AgenticTaskService
from tests.fakes.ollama import FakeOllamaClient


class ScriptedOllamaClient(FakeOllamaClient):
    """Returns predetermined string payloads in order."""

    def __init__(self, payloads: list[str]) -> None:
        super().__init__()
        self._payloads = list(payloads)

    async def chat_payload(
        self,
        messages,
        model: Optional[str] = None,
        response_format=None,
    ) -> str:
        self.chat_payload_calls.append({"messages": messages, "model": model, "response_format": response_format})
        if not self._payloads:
            return "{}"
        return self._payloads.pop(0)


def _make_task(_db):
    return AgenticTaskService().create_task(
        title="t",
        prompt="p",
        schedule="daily at 09:00",
    )


def test_run_task_marks_needs_review_when_action_unsupported(db) -> None:
    task = _make_task(db)
    runner = AgenticRunner(
        ollama=ScriptedOllamaClient([json.dumps({"action": "unsupported", "summary": "no tool"})])
    )

    result = asyncio.run(runner.run_task(task, reason="test"))

    assert result.status == "needs_review"
    after = database.get_agentic_task(task.id)
    assert after.failure_count == 1


def test_run_task_failover_persists_when_model_returns_garbage(db) -> None:
    task = _make_task(db)
    runner = AgenticRunner(ollama=ScriptedOllamaClient(["no json at all"]))

    result = asyncio.run(runner.run_task(task, reason="test"))

    assert result.status == "needs_review"
    assert result.error
    after = database.get_agentic_task(task.id)
    assert after.last_run_at is not None
