from __future__ import annotations

import sqlite3
from typing import Optional

from app.db.connection import get_connection
from app.models import AgenticTask, AgenticTaskRun, TaskRunStatus, TaskStatus, new_id, utc_now


def row_to_agentic_task(row: sqlite3.Row) -> AgenticTask:
    return AgenticTask(**dict(row))


def row_to_agentic_task_run(row: sqlite3.Row) -> AgenticTaskRun:
    return AgenticTaskRun(**dict(row))


def list_agentic_tasks() -> list[AgenticTask]:
    with get_connection() as db:
        rows = db.execute(
            """
            SELECT id, title, prompt, schedule, status, next_run_at, last_run_at, failure_count, created_at, updated_at
            FROM agentic_tasks
            ORDER BY updated_at DESC
            """
        ).fetchall()
    return [row_to_agentic_task(row) for row in rows]


def get_agentic_task(task_id: str) -> Optional[AgenticTask]:
    with get_connection() as db:
        row = db.execute(
            """
            SELECT id, title, prompt, schedule, status, next_run_at, last_run_at, failure_count, created_at, updated_at
            FROM agentic_tasks
            WHERE id = ?
            """,
            (task_id,),
        ).fetchone()
    return row_to_agentic_task(row) if row else None


def create_agentic_task(title: str, prompt: str, schedule: str, status: TaskStatus = "active") -> AgenticTask:
    now = utc_now()
    task = AgenticTask(
        id=new_id(),
        title=" ".join(title.strip().split())[:120],
        prompt=prompt.strip(),
        schedule=schedule.strip(),
        status=status,
        next_run_at=None,
        last_run_at=None,
        failure_count=0,
        created_at=now,
        updated_at=now,
    )
    with get_connection() as db:
        db.execute(
            """
            INSERT INTO agentic_tasks (id, title, prompt, schedule, status, next_run_at, last_run_at, failure_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.id,
                task.title,
                task.prompt,
                task.schedule,
                task.status,
                task.next_run_at,
                task.last_run_at,
                task.failure_count,
                task.created_at,
                task.updated_at,
            ),
        )
    return task


def update_agentic_task(task_id: str, title: str, prompt: str, schedule: str, status: TaskStatus) -> Optional[AgenticTask]:
    now = utc_now()
    with get_connection() as db:
        result = db.execute(
            """
            UPDATE agentic_tasks
            SET title = ?, prompt = ?, schedule = ?, status = ?, next_run_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (" ".join(title.strip().split())[:120], prompt.strip(), schedule.strip(), status, now, task_id),
        )
    if result.rowcount == 0:
        return None
    return get_agentic_task(task_id)


def delete_agentic_task(task_id: str) -> bool:
    with get_connection() as db:
        result = db.execute("DELETE FROM agentic_tasks WHERE id = ?", (task_id,))
    return result.rowcount > 0


def list_due_agentic_tasks(now: str, limit: int = 10) -> list[AgenticTask]:
    with get_connection() as db:
        rows = db.execute(
            """
            SELECT id, title, prompt, schedule, status, next_run_at, last_run_at, failure_count, created_at, updated_at
            FROM agentic_tasks
            WHERE status = 'active'
              AND (next_run_at IS NULL OR next_run_at <= ?)
            ORDER BY COALESCE(next_run_at, created_at) ASC
            LIMIT ?
            """,
            (now, limit),
        ).fetchall()
    return [row_to_agentic_task(row) for row in rows]


def update_agentic_task_schedule_state(
    task_id: str,
    *,
    next_run_at: str | None,
    last_run_at: str | None = None,
    failure_count: int | None = None,
    status: TaskStatus | None = None,
) -> Optional[AgenticTask]:
    now = utc_now()
    assignments = ["next_run_at = ?", "updated_at = ?"]
    values: list[object] = [next_run_at, now]
    if last_run_at is not None:
        assignments.append("last_run_at = ?")
        values.append(last_run_at)
    if failure_count is not None:
        assignments.append("failure_count = ?")
        values.append(failure_count)
    if status is not None:
        assignments.append("status = ?")
        values.append(status)
    values.append(task_id)
    with get_connection() as db:
        result = db.execute(
            f"UPDATE agentic_tasks SET {', '.join(assignments)} WHERE id = ?",
            values,
        )
    if result.rowcount == 0:
        return None
    return get_agentic_task(task_id)


def create_agentic_task_run(task_id: str, attempt: int = 1) -> AgenticTaskRun:
    run = AgenticTaskRun(
        id=new_id(),
        task_id=task_id,
        status="running",
        summary="",
        tool_results="[]",
        error="",
        attempt=attempt,
        started_at=utc_now(),
        finished_at=None,
    )
    with get_connection() as db:
        db.execute(
            """
            INSERT INTO agentic_task_runs (id, task_id, status, summary, tool_results, error, attempt, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.id,
                run.task_id,
                run.status,
                run.summary,
                run.tool_results,
                run.error,
                run.attempt,
                run.started_at,
                run.finished_at,
            ),
        )
    return run


def finish_agentic_task_run(
    run_id: str,
    *,
    status: TaskRunStatus,
    summary: str = "",
    tool_results: str = "[]",
    error: str = "",
) -> Optional[AgenticTaskRun]:
    with get_connection() as db:
        result = db.execute(
            """
            UPDATE agentic_task_runs
            SET status = ?, summary = ?, tool_results = ?, error = ?, finished_at = ?
            WHERE id = ?
            """,
            (status, summary, tool_results, error, utc_now(), run_id),
        )
    if result.rowcount == 0:
        return None
    return get_agentic_task_run(run_id)


def get_agentic_task_run(run_id: str) -> Optional[AgenticTaskRun]:
    with get_connection() as db:
        row = db.execute(
            """
            SELECT id, task_id, status, summary, tool_results, error, attempt, started_at, finished_at
            FROM agentic_task_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
    return row_to_agentic_task_run(row) if row else None


def list_agentic_task_runs(task_id: str, limit: int = 20) -> list[AgenticTaskRun]:
    with get_connection() as db:
        rows = db.execute(
            """
            SELECT id, task_id, status, summary, tool_results, error, attempt, started_at, finished_at
            FROM agentic_task_runs
            WHERE task_id = ?
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (task_id, limit),
        ).fetchall()
    return [row_to_agentic_task_run(row) for row in rows]
