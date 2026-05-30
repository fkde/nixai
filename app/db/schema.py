from __future__ import annotations

from app.db.connection import get_connection
from app.models import utc_now


SCHEMA_VERSION = 6


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
              fork_at_node_id TEXT,
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
              UNIQUE(run_id, kind),
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

            CREATE TABLE IF NOT EXISTS workflow_node_states (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id TEXT NOT NULL,
              workflow_id TEXT NOT NULL,
              node_id TEXT NOT NULL,
              step_id TEXT NOT NULL UNIQUE,
              parent_step_id TEXT,
              status TEXT NOT NULL DEFAULT 'running',
              node_type TEXT NOT NULL DEFAULT '',
              input_snapshot_json TEXT,
              input_snapshot_truncated INTEGER NOT NULL DEFAULT 0,
              output_snapshot_json TEXT,
              output_snapshot_truncated INTEGER NOT NULL DEFAULT 0,
              prompt_snapshot_json TEXT,
              prompt_snapshot_truncated INTEGER NOT NULL DEFAULT 0,
              tool_calls_json TEXT NOT NULL DEFAULT '[]',
              retries INTEGER NOT NULL DEFAULT 0,
              errors_json TEXT NOT NULL DEFAULT '[]',
              started_at TEXT,
              finished_at TEXT,
              duration_ms INTEGER,
              model_used TEXT NOT NULL DEFAULT '',
              token_usage_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS workflow_tool_calls (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id TEXT NOT NULL,
              workflow_id TEXT NOT NULL,
              node_id TEXT NOT NULL,
              step_id TEXT NOT NULL UNIQUE,
              parent_step_id TEXT,
              tool_name TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'done',
              arguments_snapshot_json TEXT,
              arguments_snapshot_truncated INTEGER NOT NULL DEFAULT 0,
              result_snapshot_json TEXT,
              result_snapshot_truncated INTEGER NOT NULL DEFAULT 0,
              error_snapshot_json TEXT,
              error_snapshot_truncated INTEGER NOT NULL DEFAULT 0,
              approval_context_json TEXT NOT NULL DEFAULT '{}',
              security_context_json TEXT NOT NULL DEFAULT '{}',
              started_at TEXT,
              finished_at TEXT,
              duration_ms INTEGER,
              replayable INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
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

            CREATE INDEX IF NOT EXISTS idx_workflow_node_states_run_node
              ON workflow_node_states(run_id, node_id);

            CREATE INDEX IF NOT EXISTS idx_workflow_tool_calls_run_node
              ON workflow_tool_calls(run_id, node_id);

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
        # v5 → v6: column rename. Schema column always stored node_id; the old
        # name "fork_at_step_id" was a misnomer.
        if "fork_at_node_id" not in run_columns and "fork_at_step_id" in run_columns:
            db.execute("ALTER TABLE workflow_runs RENAME COLUMN fork_at_step_id TO fork_at_node_id")
        elif "fork_at_node_id" not in run_columns:
            db.execute("ALTER TABLE workflow_runs ADD COLUMN fork_at_node_id TEXT")
        if _table_references_workflow_runs_old(db, "workflow_run_signals"):
            _rebuild_workflow_run_signals_table(db)
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_run_signals (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id TEXT NOT NULL,
              kind TEXT NOT NULL CHECK(kind IN ('pause', 'abort')),
              created_at TEXT NOT NULL,
              UNIQUE(run_id, kind),
              FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
            )
            """
        )
        # Pre-v6 signal rows had no UNIQUE constraint. Drop duplicates so the
        # CREATE UNIQUE INDEX below succeeds on legacy DBs.
        db.execute(
            """
            DELETE FROM workflow_run_signals
            WHERE id NOT IN (
              SELECT MIN(id) FROM workflow_run_signals GROUP BY run_id, kind
            )
            """
        )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_run_signals_unique "
            "ON workflow_run_signals(run_id, kind)"
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
        events_table = db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'workflow_run_events'"
        ).fetchone()
        if events_table and "workflow_runs_old" in str(events_table["sql"]):
            db.execute("DROP TABLE workflow_run_events")
            db.execute(
                """
                CREATE TABLE workflow_run_events (
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
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_workflow_run_events_run_seq ON workflow_run_events(run_id, seq)"
            )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_node_states (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id TEXT NOT NULL,
              workflow_id TEXT NOT NULL,
              node_id TEXT NOT NULL,
              step_id TEXT NOT NULL UNIQUE,
              parent_step_id TEXT,
              status TEXT NOT NULL DEFAULT 'running',
              node_type TEXT NOT NULL DEFAULT '',
              input_snapshot_json TEXT,
              input_snapshot_truncated INTEGER NOT NULL DEFAULT 0,
              output_snapshot_json TEXT,
              output_snapshot_truncated INTEGER NOT NULL DEFAULT 0,
              prompt_snapshot_json TEXT,
              prompt_snapshot_truncated INTEGER NOT NULL DEFAULT 0,
              tool_calls_json TEXT NOT NULL DEFAULT '[]',
              retries INTEGER NOT NULL DEFAULT 0,
              errors_json TEXT NOT NULL DEFAULT '[]',
              started_at TEXT,
              finished_at TEXT,
              duration_ms INTEGER,
              model_used TEXT NOT NULL DEFAULT '',
              token_usage_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_tool_calls (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id TEXT NOT NULL,
              workflow_id TEXT NOT NULL,
              node_id TEXT NOT NULL,
              step_id TEXT NOT NULL UNIQUE,
              parent_step_id TEXT,
              tool_name TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'done',
              arguments_snapshot_json TEXT,
              arguments_snapshot_truncated INTEGER NOT NULL DEFAULT 0,
              result_snapshot_json TEXT,
              result_snapshot_truncated INTEGER NOT NULL DEFAULT 0,
              error_snapshot_json TEXT,
              error_snapshot_truncated INTEGER NOT NULL DEFAULT 0,
              approval_context_json TEXT NOT NULL DEFAULT '{}',
              security_context_json TEXT NOT NULL DEFAULT '{}',
              started_at TEXT,
              finished_at TEXT,
              duration_ms INTEGER,
              replayable INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
            )
            """
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_workflow_node_states_run_node ON workflow_node_states(run_id, node_id)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_workflow_tool_calls_run_node ON workflow_tool_calls(run_id, node_id)"
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


def _table_references_workflow_runs_old(db, table_name: str) -> bool:
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return bool(row and "workflow_runs_old" in str(row["sql"]))


def _create_workflow_run_signals_table(db) -> None:
    db.execute(
        """
        CREATE TABLE workflow_run_signals (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id TEXT NOT NULL,
          kind TEXT NOT NULL CHECK(kind IN ('pause', 'abort')),
          created_at TEXT NOT NULL,
          UNIQUE(run_id, kind),
          FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
        )
        """
    )


def _restore_workflow_run_signals(db, rows: list) -> None:
    if not rows:
        return
    existing_run_ids = {row["id"] for row in db.execute("SELECT id FROM workflow_runs").fetchall()}
    seen: set[tuple[str, str]] = set()
    kept = []
    for row in rows:
        key = (row["run_id"], row["kind"])
        if row["run_id"] not in existing_run_ids or key in seen:
            continue
        seen.add(key)
        kept.append(row)
    if not kept:
        return
    db.executemany(
        """
        INSERT INTO workflow_run_signals (id, run_id, kind, created_at)
        VALUES (?, ?, ?, ?)
        """,
        [(row["id"], row["run_id"], row["kind"], row["created_at"]) for row in kept],
    )


def _rebuild_workflow_run_signals_table(db) -> None:
    rows = []
    table = db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'workflow_run_signals'"
    ).fetchone()
    if table:
        rows = list(
            db.execute(
                """
                SELECT id, run_id, kind, created_at
                FROM workflow_run_signals
                ORDER BY id
                """
            ).fetchall()
        )
        db.execute("DROP TABLE workflow_run_signals")
    _create_workflow_run_signals_table(db)
    _restore_workflow_run_signals(db, rows)


def _rebuild_workflow_runs_table(db) -> None:
    # Stash existing trace events before any DROP — the FK ON DELETE CASCADE
    # on workflow_run_events would otherwise wipe them when workflow_runs is
    # renamed/dropped below. We restore them after the new tables are in place.
    events_table = db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'workflow_run_events'"
    ).fetchone()
    stashed_events: list[tuple] = []
    if events_table:
        stashed_events = list(
            db.execute(
                """
                SELECT seq, step_id, run_id, parent_step_id, workflow_id, node_id, type, ts, payload_json
                FROM workflow_run_events
                """
            ).fetchall()
        )
    signals_table = db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'workflow_run_signals'"
    ).fetchone()
    stashed_signals: list = []
    if signals_table:
        stashed_signals = list(
            db.execute(
                """
                SELECT id, run_id, kind, created_at
                FROM workflow_run_signals
                ORDER BY id
                """
            ).fetchall()
        )
        db.execute("DROP TABLE workflow_run_signals")
    db.execute("DROP TABLE IF EXISTS workflow_run_events")
    has_runs = db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'workflow_runs'").fetchone()
    has_old = db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'workflow_runs_old'").fetchone()
    if has_runs and not has_old:
        db.execute("ALTER TABLE workflow_runs RENAME TO workflow_runs_old")
        has_old = True
    elif has_runs and has_old:
        db.execute("DROP TABLE workflow_runs")
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
          fork_at_node_id TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          finished_at TEXT,
          FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
        )
        """
    )
    if has_old:
        old_columns = {row["name"] for row in db.execute("PRAGMA table_info(workflow_runs_old)").fetchall()}
        initial_input_expr = "initial_input" if "initial_input" in old_columns else "''"
        fork_of_expr = "fork_of_run_id" if "fork_of_run_id" in old_columns else "NULL"
        # Tolerate the v5 column name during the rebuild path so existing data
        # carries over even if we go via _rebuild (e.g. tests forcing a v3
        # schema and then upgrading).
        if "fork_at_node_id" in old_columns:
            fork_at_expr = "fork_at_node_id"
        elif "fork_at_step_id" in old_columns:
            fork_at_expr = "fork_at_step_id"
        else:
            fork_at_expr = "NULL"
        db.execute(
            f"""
            INSERT INTO workflow_runs
              (id, workflow_id, chat_id, mode, status, current_node, state_json, events_json,
               initial_input, fork_of_run_id, fork_at_node_id, created_at, updated_at, finished_at)
            SELECT id, workflow_id, chat_id, mode, status, current_node, state_json, events_json,
                   {initial_input_expr}, {fork_of_expr}, {fork_at_expr}, created_at, updated_at, finished_at
            FROM workflow_runs_old
            """
        )
        db.execute("DROP TABLE workflow_runs_old")
    db.execute(
        """
        CREATE TABLE workflow_run_events (
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
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_workflow_run_events_run_seq ON workflow_run_events(run_id, seq)")
    _create_workflow_run_signals_table(db)
    _restore_workflow_run_signals(db, stashed_signals)
    if stashed_events:
        # Restore only events whose run still exists; orphans would FK-violate.
        existing_run_ids = {row["id"] for row in db.execute("SELECT id FROM workflow_runs").fetchall()}
        kept = [row for row in stashed_events if row["run_id"] in existing_run_ids]
        if kept:
            db.executemany(
                """
                INSERT INTO workflow_run_events
                  (seq, step_id, run_id, parent_step_id, workflow_id, node_id, type, ts, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["seq"],
                        row["step_id"],
                        row["run_id"],
                        row["parent_step_id"],
                        row["workflow_id"],
                        row["node_id"],
                        row["type"],
                        row["ts"],
                        row["payload_json"],
                    )
                    for row in kept
                ],
            )
