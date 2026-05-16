from __future__ import annotations

import asyncio
from contextlib import suppress

from app import database
from app.agentic_runner import AgenticRunner
from app.agentic_schedule import utc_now_dt
from app.services import AgenticTaskService


class AgenticScheduler:
    def __init__(self, interval_seconds: float = 30.0) -> None:
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._running: set[str] = set()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def status(self) -> dict[str, object]:
        return {
            "running": self._task is not None and not self._task.done(),
            "active_runs": sorted(self._running),
            "interval_seconds": self.interval_seconds,
        }

    async def run_once(self) -> int:
        now = utc_now_dt()
        service = AgenticTaskService()
        count = 0
        for task in database.list_due_agentic_tasks(now.isoformat(), limit=5):
            if task.id in self._running:
                continue
            if task.next_run_at is None:
                service.ensure_next_run(task)
                continue
            self._running.add(task.id)
            try:
                await AgenticRunner().run_task(task, reason="scheduled")
                count += 1
            finally:
                self._running.discard(task.id)
        return count

    async def run_task_now(self, task_id: str) -> object:
        task = database.get_agentic_task(task_id)
        if task is None:
            raise ValueError("Agentic task not found")
        if task.id in self._running:
            raise ValueError("Agentic task is already running")
        self._running.add(task.id)
        try:
            return await AgenticRunner().run_task(task, reason="manual")
        finally:
            self._running.discard(task.id)

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self.interval_seconds)


scheduler = AgenticScheduler()
