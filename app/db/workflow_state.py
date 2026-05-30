from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from app.db.connection import get_connection
from app.models import utc_now


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _load_json(text: str | None, fallback: Any) -> Any:
    if not text:
        return fallback
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return fallback


def apply_trace_event_to_runtime_state(event: Any, seq: int, db: sqlite3.Connection | None = None) -> None:
    """Project a trace event into the runtime read-model tables.

    If `db` is provided, the projection runs inside the caller's transaction
    — this keeps the trace insert and its projections atomic. Otherwise the
    function opens its own short-lived connection.
    """
    payload = event.payload if isinstance(event.payload, dict) else {}
    now = utc_now()
    if db is not None:
        _apply_event(db, event, payload, now)
        return
    with get_connection() as own_db:
        _apply_event(own_db, event, payload, now)


def _apply_event(db: sqlite3.Connection, event: Any, payload: dict[str, Any], now: str) -> None:
    if event.type == "node_started":
        db.execute(
            """
            INSERT OR REPLACE INTO workflow_node_states
              (run_id, workflow_id, node_id, step_id, parent_step_id, status, node_type,
               input_snapshot_json, input_snapshot_truncated, prompt_snapshot_json, prompt_snapshot_truncated,
               retries, started_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.run_id,
                event.workflow_id,
                event.node_id,
                event.step_id,
                event.parent_step_id,
                "running",
                str(payload.get("node_type") or ""),
                _json(payload.get("input_snapshot")) if "input_snapshot" in payload else None,
                1 if payload.get("input_snapshot_truncated") else 0,
                _json(payload.get("prompt_snapshot")) if "prompt_snapshot" in payload else None,
                1 if payload.get("prompt_snapshot_truncated") else 0,
                int(payload.get("retry") or 0),
                event.ts,
                now,
                now,
            ),
        )
        return
    if event.type == "node_finished":
        node_step_id = _node_step_id(db, event)
        db.execute(
            """
            UPDATE workflow_node_states
            SET status = ?, output_snapshot_json = ?, output_snapshot_truncated = ?,
                finished_at = ?, duration_ms = ?, updated_at = ?
            WHERE step_id = ?
            """,
            (
                str(payload.get("status") or "done"),
                _json(payload.get("output_snapshot")) if "output_snapshot" in payload else None,
                1 if payload.get("output_snapshot_truncated") else 0,
                event.ts,
                _int_or_none(payload.get("duration_ms")),
                now,
                node_step_id,
            ),
        )
        return
    if event.type == "node_failed":
        node_step_id = _node_step_id(db, event)
        _append_node_error(db, node_step_id, payload.get("error") or payload, event.ts)
        db.execute(
            """
            UPDATE workflow_node_states
            SET status = 'failed', finished_at = ?, duration_ms = ?, updated_at = ?
            WHERE step_id = ?
            """,
            (event.ts, _int_or_none(payload.get("duration_ms")), now, node_step_id),
        )
        return
    if event.type == "llm_call":
        _apply_llm_call(db, event, payload, now)
        return
    if event.type == "tool_call":
        _insert_tool_call(db, event, payload, now)


def list_node_states(run_id: str) -> list[sqlite3.Row]:
    with get_connection() as db:
        return list(
            db.execute(
                """
                SELECT id, run_id, workflow_id, node_id, step_id, parent_step_id, status, node_type,
                       input_snapshot_json, input_snapshot_truncated, output_snapshot_json, output_snapshot_truncated,
                       prompt_snapshot_json, prompt_snapshot_truncated, tool_calls_json, retries, errors_json,
                       started_at, finished_at, duration_ms, model_used, token_usage_json, created_at, updated_at
                FROM workflow_node_states
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        )


def list_tool_calls(run_id: str) -> list[sqlite3.Row]:
    with get_connection() as db:
        return list(
            db.execute(
                """
                SELECT id, run_id, workflow_id, node_id, step_id, parent_step_id, tool_name, status,
                       arguments_snapshot_json, arguments_snapshot_truncated,
                       result_snapshot_json, result_snapshot_truncated,
                       error_snapshot_json, error_snapshot_truncated,
                       approval_context_json, security_context_json,
                       started_at, finished_at, duration_ms, replayable, created_at, updated_at
                FROM workflow_tool_calls
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        )


def node_state_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "workflow_id": row["workflow_id"],
        "node_id": row["node_id"],
        "step_id": row["step_id"],
        "parent_step_id": row["parent_step_id"],
        "status": row["status"],
        "node_type": row["node_type"],
        "input_snapshot": _load_json(row["input_snapshot_json"], None),
        "input_snapshot_truncated": bool(row["input_snapshot_truncated"]),
        "output_snapshot": _load_json(row["output_snapshot_json"], None),
        "output_snapshot_truncated": bool(row["output_snapshot_truncated"]),
        "prompt_snapshot": _load_json(row["prompt_snapshot_json"], None),
        "prompt_snapshot_truncated": bool(row["prompt_snapshot_truncated"]),
        "tool_calls": _load_json(row["tool_calls_json"], []),
        "retries": row["retries"],
        "errors": _load_json(row["errors_json"], []),
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "duration_ms": row["duration_ms"],
        "model_used": row["model_used"],
        "token_usage": _load_json(row["token_usage_json"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def tool_call_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "workflow_id": row["workflow_id"],
        "node_id": row["node_id"],
        "step_id": row["step_id"],
        "parent_step_id": row["parent_step_id"],
        "tool_name": row["tool_name"],
        "status": row["status"],
        "arguments_snapshot": _load_json(row["arguments_snapshot_json"], None),
        "arguments_snapshot_truncated": bool(row["arguments_snapshot_truncated"]),
        "result_snapshot": _load_json(row["result_snapshot_json"], None),
        "result_snapshot_truncated": bool(row["result_snapshot_truncated"]),
        "error_snapshot": _load_json(row["error_snapshot_json"], None),
        "error_snapshot_truncated": bool(row["error_snapshot_truncated"]),
        "approval_context": _load_json(row["approval_context_json"], {}),
        "security_context": _load_json(row["security_context_json"], {}),
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "duration_ms": row["duration_ms"],
        "replayable": bool(row["replayable"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _apply_llm_call(db: sqlite3.Connection, event: Any, payload: dict[str, Any], now: str) -> None:
    token_usage = {"tokens_in": payload.get("tokens_in"), "tokens_out": payload.get("tokens_out")}
    db.execute(
        """
        UPDATE workflow_node_states
        SET model_used = ?, token_usage_json = ?, updated_at = ?
        WHERE step_id = ?
        """,
        (str(payload.get("model") or ""), _json(token_usage), now, _node_step_id(db, event)),
    )


def _insert_tool_call(db: sqlite3.Connection, event: Any, payload: dict[str, Any], now: str) -> None:
    status = str(payload.get("status") or ("failed" if payload.get("error") else "done"))
    node_step_id = _node_step_id(db, event)
    db.execute(
        """
        INSERT OR REPLACE INTO workflow_tool_calls
          (run_id, workflow_id, node_id, step_id, parent_step_id, tool_name, status,
           arguments_snapshot_json, arguments_snapshot_truncated,
           result_snapshot_json, result_snapshot_truncated,
           error_snapshot_json, error_snapshot_truncated,
           approval_context_json, security_context_json,
           started_at, finished_at, duration_ms, replayable, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.run_id,
            event.workflow_id,
            event.node_id,
            event.step_id,
            node_step_id,
            str(payload.get("tool_name") or payload.get("tool") or ""),
            status,
            _json(payload.get("arguments_snapshot")) if "arguments_snapshot" in payload else None,
            1 if payload.get("arguments_snapshot_truncated") else 0,
            _json(payload.get("result_snapshot")) if "result_snapshot" in payload else None,
            1 if payload.get("result_snapshot_truncated") else 0,
            _json(payload.get("error_snapshot")) if "error_snapshot" in payload else None,
            1 if payload.get("error_snapshot_truncated") else 0,
            _json(payload.get("approval_context") or {}),
            _json(payload.get("security_context") or {}),
            payload.get("started_at") or event.ts,
            payload.get("finished_at") or event.ts,
            _int_or_none(payload.get("duration_ms")),
            1 if payload.get("replayable") else 0,
            now,
            now,
        ),
    )
    _append_node_tool_call(
        db,
        node_step_id,
        {
            "step_id": event.step_id,
            "tool_name": str(payload.get("tool_name") or payload.get("tool") or ""),
            "status": status,
            "duration_ms": _int_or_none(payload.get("duration_ms")),
        },
        now,
    )


def _append_node_tool_call(db: sqlite3.Connection, node_step_id: Optional[str], item: dict[str, Any], now: str) -> None:
    if not node_step_id:
        return
    row = db.execute("SELECT tool_calls_json FROM workflow_node_states WHERE step_id = ?", (node_step_id,)).fetchone()
    if row is None:
        return
    tool_calls = _load_json(row["tool_calls_json"], [])
    if not isinstance(tool_calls, list):
        tool_calls = []
    tool_calls.append(item)
    db.execute(
        "UPDATE workflow_node_states SET tool_calls_json = ?, updated_at = ? WHERE step_id = ?",
        (_json(tool_calls), now, node_step_id),
    )


def _append_node_error(db: sqlite3.Connection, node_step_id: Optional[str], error: Any, ts: str) -> None:
    if not node_step_id:
        return
    row = db.execute("SELECT errors_json FROM workflow_node_states WHERE step_id = ?", (node_step_id,)).fetchone()
    if row is None:
        return
    errors = _load_json(row["errors_json"], [])
    if not isinstance(errors, list):
        errors = []
    errors.append({"ts": ts, "error": error})
    db.execute(
        "UPDATE workflow_node_states SET errors_json = ?, updated_at = ? WHERE step_id = ?",
        (_json(errors), utc_now(), node_step_id),
    )


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _node_step_id(db: sqlite3.Connection, event: Any) -> str | None:
    if event.parent_step_id:
        return event.parent_step_id
    row = db.execute(
        """
        SELECT step_id FROM workflow_node_states
        WHERE run_id = ? AND node_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (event.run_id, event.node_id),
    ).fetchone()
    return str(row["step_id"]) if row else None
