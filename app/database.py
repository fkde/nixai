from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from app.config import database_path
from app.models import AgenticTask, AgenticTaskRun, Chat, FeedbackRating, Message, MessageMode, MessageRole, TaskRunStatus, TaskStatus, new_id, utc_now


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path or database_path())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
              id TEXT PRIMARY KEY,
              chat_id TEXT NOT NULL,
              role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
              content TEXT NOT NULL,
              mode TEXT NOT NULL DEFAULT 'chat' CHECK(mode IN ('chat', 'code', 'agentic')),
              feedback TEXT CHECK(feedback IN ('up', 'down')),
              created_at TEXT NOT NULL,
              FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS agentic_tasks (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              prompt TEXT NOT NULL,
              schedule TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('active', 'paused')),
              next_run_at TEXT,
              last_run_at TEXT,
              failure_count INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agentic_task_runs (
              id TEXT PRIMARY KEY,
              task_id TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('running', 'success', 'failed', 'needs_review')),
              summary TEXT NOT NULL DEFAULT '',
              tool_results TEXT NOT NULL DEFAULT '[]',
              error TEXT NOT NULL DEFAULT '',
              attempt INTEGER NOT NULL DEFAULT 1,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              FOREIGN KEY (task_id) REFERENCES agentic_tasks(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_chat_created
              ON messages(chat_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_chats_updated
              ON chats(updated_at);

            CREATE INDEX IF NOT EXISTS idx_agentic_tasks_status_updated
              ON agentic_tasks(status, updated_at);

            CREATE INDEX IF NOT EXISTS idx_agentic_tasks_due
              ON agentic_tasks(status, next_run_at);

            CREATE INDEX IF NOT EXISTS idx_agentic_task_runs_task_started
              ON agentic_task_runs(task_id, started_at);
            """
        )
        message_columns = {row["name"] for row in db.execute("PRAGMA table_info(messages)").fetchall()}
        if "mode" not in message_columns:
            db.execute(
                "ALTER TABLE messages ADD COLUMN mode TEXT NOT NULL DEFAULT 'chat' CHECK(mode IN ('chat', 'code', 'agentic'))"
            )
        if "feedback" not in message_columns:
            db.execute("ALTER TABLE messages ADD COLUMN feedback TEXT CHECK(feedback IN ('up', 'down'))")
        task_columns = {row["name"] for row in db.execute("PRAGMA table_info(agentic_tasks)").fetchall()}
        for column, ddl in {
            "next_run_at": "ALTER TABLE agentic_tasks ADD COLUMN next_run_at TEXT",
            "last_run_at": "ALTER TABLE agentic_tasks ADD COLUMN last_run_at TEXT",
            "failure_count": "ALTER TABLE agentic_tasks ADD COLUMN failure_count INTEGER NOT NULL DEFAULT 0",
        }.items():
            if column not in task_columns:
                db.execute(ddl)


def row_to_chat(row: sqlite3.Row) -> Chat:
    return Chat(**dict(row))


def row_to_message(row: sqlite3.Row) -> Message:
    return Message(**dict(row))


def row_to_agentic_task(row: sqlite3.Row) -> AgenticTask:
    return AgenticTask(**dict(row))


def row_to_agentic_task_run(row: sqlite3.Row) -> AgenticTaskRun:
    return AgenticTaskRun(**dict(row))


def list_chats() -> list[Chat]:
    with get_connection() as db:
        rows = db.execute(
            "SELECT id, title, created_at, updated_at FROM chats ORDER BY updated_at DESC"
        ).fetchall()
    return [row_to_chat(row) for row in rows]


def create_chat(title: Optional[str] = None) -> Chat:
    now = utc_now()
    chat = Chat(id=new_id(), title=title or "Neuer Chat", created_at=now, updated_at=now)
    with get_connection() as db:
        db.execute(
            "INSERT INTO chats (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (chat.id, chat.title, chat.created_at, chat.updated_at),
        )
    return chat


def get_chat(chat_id: str) -> Optional[Chat]:
    with get_connection() as db:
        row = db.execute(
            "SELECT id, title, created_at, updated_at FROM chats WHERE id = ?",
            (chat_id,),
        ).fetchone()
    return row_to_chat(row) if row else None


def delete_chat(chat_id: str) -> bool:
    with get_connection() as db:
        result = db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    return result.rowcount > 0


def list_messages(chat_id: str) -> list[Message]:
    with get_connection() as db:
        rows = db.execute(
            """
            SELECT id, chat_id, role, content, mode, feedback, created_at
            FROM messages
            WHERE chat_id = ?
            ORDER BY created_at ASC
            """,
            (chat_id,),
        ).fetchall()
    return [row_to_message(row) for row in rows]


def add_message(chat_id: str, role: MessageRole, content: str, mode: MessageMode = "chat") -> Message:
    message = Message(id=new_id(), chat_id=chat_id, role=role, content=content, mode=mode, created_at=utc_now())
    with get_connection() as db:
        db.execute(
            """
            INSERT INTO messages (id, chat_id, role, content, mode, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (message.id, message.chat_id, message.role, message.content, message.mode, message.created_at),
        )
        db.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (message.created_at, chat_id))
    return message


def get_message(message_id: str) -> Optional[Message]:
    with get_connection() as db:
        row = db.execute(
            """
            SELECT id, chat_id, role, content, mode, feedback, created_at
            FROM messages
            WHERE id = ?
            """,
            (message_id,),
        ).fetchone()
    return row_to_message(row) if row else None


def set_message_feedback(message_id: str, rating: FeedbackRating) -> Optional[Message]:
    with get_connection() as db:
        result = db.execute(
            "UPDATE messages SET feedback = ? WHERE id = ?",
            (rating, message_id),
        )
    if result.rowcount == 0:
        return None
    return get_message(message_id)


def update_chat_title_if_default(chat_id: str, title: str) -> None:
    clean_title = " ".join(title.strip().split())[:80] or "Neuer Chat"
    with get_connection() as db:
        db.execute(
            """
            UPDATE chats
            SET title = ?
            WHERE id = ? AND title = 'Neuer Chat'
            """,
            (clean_title, chat_id),
        )


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
