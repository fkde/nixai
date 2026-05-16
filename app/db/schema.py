from __future__ import annotations

from app.db.connection import get_connection
from app.models import utc_now


SCHEMA_VERSION = 2


def init_db() -> None:
    with get_connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              workspace_path TEXT NOT NULL DEFAULT '',
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

            CREATE TABLE IF NOT EXISTS workflow_runs (
              id TEXT PRIMARY KEY,
              workflow_id TEXT NOT NULL,
              chat_id TEXT NOT NULL,
              mode TEXT NOT NULL CHECK(mode IN ('chat', 'code', 'agentic')),
              status TEXT NOT NULL CHECK(status IN ('running', 'done', 'failed', 'needs_user')),
              current_node TEXT NOT NULL DEFAULT '',
              state_json TEXT NOT NULL DEFAULT '{}',
              events_json TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              finished_at TEXT,
              FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
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

            CREATE INDEX IF NOT EXISTS idx_workflow_runs_chat_updated
              ON workflow_runs(chat_id, updated_at);

            CREATE TABLE IF NOT EXISTS schema_version (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              version INTEGER NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        message_columns = {row["name"] for row in db.execute("PRAGMA table_info(messages)").fetchall()}
        chat_columns = {row["name"] for row in db.execute("PRAGMA table_info(chats)").fetchall()}
        if "workspace_path" not in chat_columns:
            db.execute("ALTER TABLE chats ADD COLUMN workspace_path TEXT NOT NULL DEFAULT ''")
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
        _set_schema_version(db, SCHEMA_VERSION)


def get_schema_version() -> int:
    with get_connection() as db:
        row = db.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    return int(row["version"]) if row else 0


def set_schema_version(version: int) -> None:
    with get_connection() as db:
        _set_schema_version(db, version)


def _set_schema_version(db, version: int) -> None:
    db.execute(
        """
        INSERT INTO schema_version (id, version, updated_at)
        VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET version = excluded.version, updated_at = excluded.updated_at
        """,
        (version, utc_now()),
    )
