from __future__ import annotations

import sqlite3
from typing import Optional

from app.db.connection import get_connection


def insert_trace_event(
    *,
    step_id: str,
    run_id: str,
    workflow_id: str,
    node_id: str,
    type: str,
    ts: str,
    payload_json: str = "{}",
    parent_step_id: Optional[str] = None,
    db: sqlite3.Connection | None = None,
) -> int:
    """Insert a raw trace event row.

    When `db` is provided, the INSERT runs in the caller's transaction so
    callers can atomically combine the insert with derived projections.
    """
    if db is not None:
        cursor = db.execute(
            """
            INSERT INTO workflow_run_events
              (step_id, run_id, parent_step_id, workflow_id, node_id, type, ts, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (step_id, run_id, parent_step_id, workflow_id, node_id, type, ts, payload_json),
        )
        return int(cursor.lastrowid or 0)
    with get_connection() as own_db:
        cursor = own_db.execute(
            """
            INSERT INTO workflow_run_events
              (step_id, run_id, parent_step_id, workflow_id, node_id, type, ts, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (step_id, run_id, parent_step_id, workflow_id, node_id, type, ts, payload_json),
        )
        return int(cursor.lastrowid or 0)


def list_trace_events(run_id: str, *, since_seq: Optional[int] = None, limit: Optional[int] = None) -> list[sqlite3.Row]:
    query = (
        "SELECT seq, step_id, run_id, parent_step_id, workflow_id, node_id, type, ts, payload_json "
        "FROM workflow_run_events WHERE run_id = ?"
    )
    params: list[object] = [run_id]
    if since_seq is not None:
        query += " AND seq > ?"
        params.append(int(since_seq))
    query += " ORDER BY seq ASC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(int(limit))
    with get_connection() as db:
        return list(db.execute(query, tuple(params)).fetchall())


def list_workflow_runs(
    *,
    workflow_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[sqlite3.Row]:
    query = (
        "SELECT id, workflow_id, chat_id, mode, status, current_node, state_json, events_json, "
        "initial_input, fork_of_run_id, fork_at_node_id, created_at, updated_at, finished_at FROM workflow_runs"
    )
    where: list[str] = []
    params: list[object] = []
    if workflow_id:
        where.append("workflow_id = ?")
        params.append(workflow_id)
    if status:
        where.append("status = ?")
        params.append(status)
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([max(1, int(limit)), max(0, int(offset))])
    with get_connection() as db:
        return list(db.execute(query, tuple(params)).fetchall())


def delete_trace_events(run_id: str) -> int:
    with get_connection() as db:
        result = db.execute("DELETE FROM workflow_run_events WHERE run_id = ?", (run_id,))
        return int(result.rowcount or 0)
