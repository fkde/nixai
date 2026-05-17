from __future__ import annotations

from app.db.connection import get_connection
from app.models import utc_now


SCHEMA_VERSION = 4


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
              status TEXT NOT NULL CHECK(status IN ('running', 'paused', 'done', 'failed', 'needs_user')),
              current_node TEXT NOT NULL DEFAULT '',
              state_json TEXT NOT NULL DEFAULT '{}',
              events_json TEXT NOT NULL DEFAULT '[]',
              initial_input TEXT NOT NULL DEFAULT '',
              fork_of_run_id TEXT,
              fork_at_step_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              finished_at TEXT,
              FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS workflow_run_signals (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id TEXT NOT NULL,
              kind TEXT NOT NULL CHECK(kind IN ('pause', 'abort')),
              created_at TEXT NOT NULL,
              FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS workflow_run_events (
              seq INTEGER PRIMARY KEY AUTOINCREMENT,
              step_id TEXT NOT NULL UNIQUE,
              run_id TEXT NOT NULL,
              parent_step_id TEXT,
              workflow_id TEXT NOT NULL,
              node_id TEXT NOT NULL,
              type TEXT NOT NULL,
              ts TEXT NOT NULL,
              payload_json TEXT NOT NULL DEFAULT '{}',
              FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
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

            CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow_status_updated
              ON workflow_runs(workflow_id, status, updated_at);

            CREATE INDEX IF NOT EXISTS idx_workflow_run_events_run_seq
              ON workflow_run_events(run_id, seq);

            CREATE INDEX IF NOT EXISTS idx_workflow_run_signals_run_kind
              ON workflow_run_signals(run_id, kind);

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
        run_columns = {row["name"] for row in db.execute("PRAGMA table_info(workflow_runs)").fetchall()}
        run_table = db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'workflow_runs'"
        ).fetchone()
        if run_table and "'paused'" not in str(run_table["sql"]):
            _rebuild_workflow_runs_table(db)
            run_columns = {row["name"] for row in db.execute("PRAGMA table_info(workflow_runs)").fetchall()}
        if "initial_input" not in run_columns:
            db.execute("ALTER TABLE workflow_runs ADD COLUMN initial_input TEXT NOT NULL DEFAULT ''")
        if "fork_of_run_id" not in run_columns:
            db.execute("ALTER TABLE workflow_runs ADD COLUMN fork_of_run_id TEXT")
        if "fork_at_step_id" not in run_columns:
            db.execute("ALTER TABLE workflow_runs ADD COLUMN fork_at_step_id TEXT")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_run_signals (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id TEXT NOT NULL,
              kind TEXT NOT NULL CHECK(kind IN ('pause', 'abort')),
              created_at TEXT NOT NULL,
              FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_chat_updated
              ON workflow_runs(chat_id, updated_at)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow_status_updated
              ON workflow_runs(workflow_id, status, updated_at)
            """
        )
        db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workflow_run_signals_run_kind
              ON workflow_run_signals(run_id, kind)
            """
        )
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


def _rebuild_workflow_runs_table(db) -> None:
    db.execute("ALTER TABLE workflow_runs RENAME TO workflow_runs_old")
    db.execute(
        """
        CREATE TABLE workflow_runs (
          id TEXT PRIMARY KEY,
          workflow_id TEXT NOT NULL,
          chat_id TEXT NOT NULL,
          mode TEXT NOT NULL CHECK(mode IN ('chat', 'code', 'agentic')),
          status TEXT NOT NULL CHECK(status IN ('running', 'paused', 'done', 'failed', 'needs_user')),
          current_node TEXT NOT NULL DEFAULT '',
          state_json TEXT NOT NULL DEFAULT '{}',
          events_json TEXT NOT NULL DEFAULT '[]',
          initial_input TEXT NOT NULL DEFAULT '',
          fork_of_run_id TEXT,
          fork_at_step_id TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          finished_at TEXT,
          FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
        )
        """
    )
    old_columns = {row["name"] for row in db.execute("PRAGMA table_info(workflow_runs_old)").fetchall()}
    initial_input_expr = "initial_input" if "initial_input" in old_columns else "''"
    fork_of_expr = "fork_of_run_id" if "fork_of_run_id" in old_columns else "NULL"
    fork_at_expr = "fork_at_step_id" if "fork_at_step_id" in old_columns else "NULL"
    db.execute(
        f"""
        INSERT INTO workflow_runs
          (id, workflow_id, chat_id, mode, status, current_node, state_json, events_json,
           initial_input, fork_of_run_id, fork_at_step_id, created_at, updated_at, finished_at)
        SELECT id, workflow_id, chat_id, mode, status, current_node, state_json, events_json,
               {initial_input_expr}, {fork_of_expr}, {fork_at_expr}, created_at, updated_at, finished_at
        FROM workflow_runs_old
        """
    )
    db.execute("DROP TABLE workflow_runs_old")
