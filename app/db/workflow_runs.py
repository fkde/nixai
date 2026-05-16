from __future__ import annotations

import sqlite3
from typing import Optional

from app.db.connection import get_connection
from app.models import MessageMode, WorkflowRun, WorkflowRunStatus, utc_now


def row_to_workflow_run(row: sqlite3.Row) -> WorkflowRun:
    return WorkflowRun(**dict(row))


def create_workflow_run(
    run_id: str,
    *,
    workflow_id: str,
    chat_id: str,
    mode: MessageMode,
    state_json: str = "{}",
    events_json: str = "[]",
    current_node: str = "",
) -> WorkflowRun:
    now = utc_now()
    run = WorkflowRun(
        id=run_id,
        workflow_id=workflow_id,
        chat_id=chat_id,
        mode=mode,
        status="running",
        current_node=current_node,
        state_json=state_json,
        events_json=events_json,
        created_at=now,
        updated_at=now,
        finished_at=None,
    )
    with get_connection() as db:
        db.execute(
            """
            INSERT OR REPLACE INTO workflow_runs
              (id, workflow_id, chat_id, mode, status, current_node, state_json, events_json, created_at, updated_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run.id,
                run.workflow_id,
                run.chat_id,
                run.mode,
                run.status,
                run.current_node,
                run.state_json,
                run.events_json,
                run.created_at,
                run.updated_at,
                run.finished_at,
            ),
        )
    return run


def update_workflow_run(
    run_id: str,
    *,
    status: WorkflowRunStatus,
    state_json: str,
    events_json: str,
    current_node: str = "",
    finished: bool = False,
) -> Optional[WorkflowRun]:
    now = utc_now()
    finished_at = now if finished else None
    with get_connection() as db:
        result = db.execute(
            """
            UPDATE workflow_runs
            SET status = ?, state_json = ?, events_json = ?, current_node = ?, updated_at = ?, finished_at = ?
            WHERE id = ?
            """,
            (status, state_json, events_json, current_node, now, finished_at, run_id),
        )
    if result.rowcount == 0:
        return None
    return get_workflow_run(run_id)


def get_workflow_run(run_id: str) -> Optional[WorkflowRun]:
    with get_connection() as db:
        row = db.execute(
            """
            SELECT id, workflow_id, chat_id, mode, status, current_node, state_json, events_json, created_at, updated_at, finished_at
            FROM workflow_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
    return row_to_workflow_run(row) if row else None
