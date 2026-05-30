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
    initial_input: str = "",
    fork_of_run_id: str | None = None,
    fork_at_node_id: str | None = None,
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
        initial_input=initial_input,
        fork_of_run_id=fork_of_run_id,
        fork_at_node_id=fork_at_node_id,
        created_at=now,
        updated_at=now,
        finished_at=None,
    )
    with get_connection() as db:
        db.execute(
            """
            INSERT OR REPLACE INTO workflow_runs
              (id, workflow_id, chat_id, mode, status, current_node, state_json, events_json, initial_input, fork_of_run_id, fork_at_node_id, created_at, updated_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                run.initial_input,
                run.fork_of_run_id,
                run.fork_at_node_id,
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
            SELECT id, workflow_id, chat_id, mode, status, current_node, state_json, events_json, initial_input,
                   fork_of_run_id, fork_at_node_id, created_at, updated_at, finished_at
            FROM workflow_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
    return row_to_workflow_run(row) if row else None


def request_workflow_run_signal(run_id: str, kind: str) -> bool:
    """Record a pause/abort signal for `run_id`.

    Idempotent: repeated requests for the same (run_id, kind) keep a single
    row courtesy of the UNIQUE constraint + `INSERT OR IGNORE`. Returns True
    iff the target run exists (regardless of whether the row was new or a
    duplicate); callers use this to distinguish "queued" from "no such run".
    """
    if kind not in {"pause", "abort"}:
        raise ValueError("Unsupported workflow run signal.")
    now = utc_now()
    with get_connection() as db:
        exists = db.execute("SELECT 1 FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
        if exists is None:
            return False
        db.execute(
            "INSERT OR IGNORE INTO workflow_run_signals (run_id, kind, created_at) VALUES (?, ?, ?)",
            (run_id, kind, now),
        )
    return True


def has_workflow_run_signal(run_id: str, kind: str) -> bool:
    with get_connection() as db:
        row = db.execute(
            "SELECT 1 FROM workflow_run_signals WHERE run_id = ? AND kind = ? LIMIT 1", (run_id, kind)
        ).fetchone()
    return row is not None


def clear_workflow_run_signal(run_id: str, kind: str) -> int:
    with get_connection() as db:
        result = db.execute("DELETE FROM workflow_run_signals WHERE run_id = ? AND kind = ?", (run_id, kind))
    return int(result.rowcount or 0)
