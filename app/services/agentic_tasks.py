"""Centralized agentic task lifecycle helpers.

Removes duplicate schedule recomputation and "finalize a run" logic that was
previously spread across the API layer (``app/api/agentic_tasks.py``), the
chat agent (``app/agent.py``), the runner (``app/agentic_runner.py``), and the
scheduler (``app/agentic_scheduler.py``).
"""

from __future__ import annotations

from typing import Optional

from app import database
from app.agentic_schedule import compute_next_run, is_one_shot_schedule, utc_now_dt
from app.models import AgenticTask, TaskStatus


MAX_FAILURE_ATTEMPTS = 2


class AgenticTaskService:
    """Pure helper around ``app.database`` for agentic task operations."""

    def __init__(self, max_failure_attempts: int = MAX_FAILURE_ATTEMPTS) -> None:
        self.max_failure_attempts = max_failure_attempts

    # ----- creation / mutation -----------------------------------------------

    def create_task(self, *, title: str, prompt: str, schedule: str, status: TaskStatus = "active") -> AgenticTask:
        task = database.create_agentic_task(title=title, prompt=prompt, schedule=schedule, status=status)
        return self._reschedule_now(task)

    def update_task(
        self, task_id: str, *, title: str, prompt: str, schedule: str, status: TaskStatus
    ) -> Optional[AgenticTask]:
        task = database.update_agentic_task(task_id, title=title, prompt=prompt, schedule=schedule, status=status)
        if task is None:
            return None
        return self._reschedule_now(task)

    def delete_task(self, task_id: str) -> bool:
        return database.delete_agentic_task(task_id)

    # ----- scheduling --------------------------------------------------------

    def ensure_next_run(self, task: AgenticTask) -> AgenticTask:
        """Initialize ``next_run_at`` for a task that lacks one."""
        if task.next_run_at is not None:
            return task
        return self._reschedule_now(task)

    def compute_next_run_at(self, schedule: str) -> str:
        return compute_next_run(schedule, utc_now_dt())

    def is_one_shot(self, schedule: str) -> bool:
        return is_one_shot_schedule(schedule)

    # ----- run lifecycle -----------------------------------------------------

    def record_run_result(self, task: AgenticTask, *, status: str) -> None:
        """Apply schedule/failure-state changes after a finished run."""
        one_shot = is_one_shot_schedule(task.schedule)
        next_run_at = None if one_shot else compute_next_run(task.schedule, utc_now_dt())
        failure_count = 0 if status == "success" else min(task.failure_count + 1, self.max_failure_attempts)
        task_status: TaskStatus | None = None
        if one_shot or (failure_count >= self.max_failure_attempts and status != "success"):
            task_status = "paused"
        database.update_agentic_task_schedule_state(
            task.id,
            next_run_at=next_run_at,
            last_run_at=utc_now_dt().isoformat(),
            failure_count=failure_count,
            status=task_status,
        )

    # ----- internals ---------------------------------------------------------

    def _reschedule_now(self, task: AgenticTask) -> AgenticTask:
        next_run_at = compute_next_run(task.schedule, utc_now_dt())
        updated = database.update_agentic_task_schedule_state(task.id, next_run_at=next_run_at)
        return updated or task
