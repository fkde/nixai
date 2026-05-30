from __future__ import annotations


def test_init_db_records_schema_version(db) -> None:
    assert db.get_schema_version() == db.SCHEMA_VERSION

    db.set_schema_version(0)
    assert db.get_schema_version() == 0

    db.init_db()
    assert db.get_schema_version() == db.SCHEMA_VERSION


def test_connect_accepts_explicit_db_path(db, tmp_path) -> None:
    custom_path = tmp_path / "custom.sqlite"
    connection = db.connect(custom_path)
    try:
        connection.execute("CREATE TABLE smoke (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO smoke (id) VALUES ('ok')")
        connection.commit()
    finally:
        connection.close()

    connection = db.connect(custom_path)
    try:
        row = connection.execute("SELECT id FROM smoke").fetchone()
    finally:
        connection.close()

    assert row["id"] == "ok"


def test_chat_and_message_crud(db) -> None:
    chat = db.create_chat("  Demo Chat  ", workspace_path=" /tmp/project ")

    assert db.get_chat(chat.id).title == "  Demo Chat  "
    assert db.list_chats()[0].id == chat.id

    updated = db.update_chat(chat.id, title=" Updated\nTitle ", workspace_path="/tmp/other")
    assert updated is not None
    assert updated.title == "Updated Title"
    assert updated.workspace_path == "/tmp/other"

    user = db.add_message(chat.id, "user", "Hello", mode="chat")
    assistant = db.add_message(chat.id, "assistant", "Hi", mode="code")
    assert [message.id for message in db.list_messages(chat.id)] == [user.id, assistant.id]
    assert [message.id for message in db.list_messages(chat.id, mode="code")] == [assistant.id]

    rated = db.set_message_feedback(assistant.id, "down")
    assert rated is not None
    assert rated.feedback == "down"

    assert db.delete_chat(chat.id)
    assert db.get_chat(chat.id) is None
    assert db.list_messages(chat.id) == []


def test_agentic_task_and_run_crud(db) -> None:
    task = db.create_agentic_task(" Daily Check ", "Look around", "daily at 09:00")

    assert db.get_agentic_task(task.id).title == "Daily Check"
    assert db.list_agentic_tasks()[0].id == task.id

    updated = db.update_agentic_task(task.id, " Weekly Check ", "Summarize", "weekly monday at 10:00", "paused")
    assert updated is not None
    assert updated.title == "Weekly Check"
    assert updated.status == "paused"

    scheduled = db.update_agentic_task_schedule_state(
        task.id,
        next_run_at="2026-05-16T10:00:00+00:00",
        last_run_at="2026-05-15T10:00:00+00:00",
        failure_count=2,
        status="active",
    )
    assert scheduled is not None
    assert scheduled.failure_count == 2
    assert [item.id for item in db.list_due_agentic_tasks("2026-05-16T10:00:01+00:00")] == [task.id]

    run = db.create_agentic_task_run(task.id, attempt=2)
    finished = db.finish_agentic_task_run(run.id, status="success", summary="Done", tool_results="[]")
    assert finished is not None
    assert finished.finished_at is not None
    assert finished.status == "success"
    assert db.list_agentic_task_runs(task.id)[0].id == run.id

    assert db.delete_agentic_task(task.id)
    assert db.get_agentic_task(task.id) is None
    assert db.list_agentic_task_runs(task.id) == []


def test_workflow_run_crud(db) -> None:
    chat = db.create_chat("Workflow Chat")
    run = db.create_workflow_run(
        "run-1",
        workflow_id="deep_orchestra",
        chat_id=chat.id,
        mode="chat",
        state_json='{"step": 1}',
        events_json="[]",
        current_node="pause",
    )

    assert run.status == "running"
    assert db.get_workflow_run("run-1").workflow_id == "deep_orchestra"

    updated = db.update_workflow_run(
        "run-1",
        status="needs_user",
        state_json='{"pause": true}',
        events_json='[{"type":"paused"}]',
        current_node="pause",
    )

    assert updated is not None
    assert updated.status == "needs_user"
    assert updated.current_node == "pause"
    assert updated.finished_at is None

    finished = db.update_workflow_run(
        "run-1",
        status="done",
        state_json="{}",
        events_json="[]",
        finished=True,
    )
    assert finished is not None
    assert finished.finished_at is not None


def test_rebuild_workflow_runs_preserves_trace_events(db) -> None:
    """Regression: legacy v3/v4 → v5 migration must not lose trace events.

    Reproduces the upgrade path by simulating an older `workflow_runs` schema
    that lacks the 'paused' status, then re-running init_db().
    """
    from app.db.connection import get_connection

    chat = db.create_chat(title="t", workspace_path="")
    run_id = "migration-keepme"
    db.create_workflow_run(run_id, workflow_id="wf-x", chat_id=chat.id, mode="chat", initial_input="hi")
    from app.workflows.runtime_trace import SqliteTracePersistence, TraceEmitter

    emitter = TraceEmitter(run_id=run_id, workflow_id="wf-x", persistence=SqliteTracePersistence())
    emitter.emit("run_started", node_id="workflow")
    emitter.emit("node_started", node_id="a")
    emitter.emit("node_finished", node_id="a", payload={"status": "done"})
    assert len(db.list_trace_events(run_id)) == 3

    # Simulate a v4 schema where workflow_runs has no 'paused' status in its CHECK.
    with get_connection() as conn:
        conn.execute("DROP TABLE workflow_run_events")
        conn.execute("DROP TABLE workflow_runs")
        conn.execute(
            """
            CREATE TABLE workflow_runs (
              id TEXT PRIMARY KEY,
              workflow_id TEXT NOT NULL,
              chat_id TEXT NOT NULL,
              mode TEXT NOT NULL CHECK(mode IN ('chat', 'code', 'agentic')),
              status TEXT NOT NULL CHECK(status IN ('running', 'done', 'failed', 'needs_user')),
              current_node TEXT NOT NULL DEFAULT '',
              state_json TEXT NOT NULL DEFAULT '{}',
              events_json TEXT NOT NULL DEFAULT '[]',
              initial_input TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              finished_at TEXT,
              FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
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
        # Insert a run + events using the legacy shape.
        conn.execute(
            """
            INSERT INTO workflow_runs (id, workflow_id, chat_id, mode, status, created_at, updated_at, initial_input)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, "wf-x", chat.id, "chat", "done", "2026-01-01", "2026-01-01", "hi"),
        )
        for step_id, type_ in (("s1", "run_started"), ("s2", "node_started"), ("s3", "node_finished")):
            conn.execute(
                "INSERT INTO workflow_run_events (step_id, run_id, workflow_id, node_id, type, ts, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (step_id, run_id, "wf-x", "a", type_, "2026-01-01", "{}"),
            )

    # Force re-migration: bump schema_version backward so init_db() rebuilds.
    db.set_schema_version(3)
    db.init_db()

    rows = db.list_trace_events(run_id)
    assert [row["step_id"] for row in rows] == ["s1", "s2", "s3"], "trace events must survive v3 → v5 upgrade"


def test_rebuild_workflow_runs_repairs_signal_foreign_key(db) -> None:
    """Regression: rebuilding workflow_runs must not leave signals pointing at
    the temporary workflow_runs_old table."""
    from app.db.connection import get_connection

    chat = db.create_chat(title="t", workspace_path="")
    run_id = "migration-signal"

    with get_connection() as conn:
        conn.execute("DROP TABLE workflow_run_signals")
        conn.execute("DROP TABLE workflow_run_events")
        conn.execute("DROP TABLE workflow_runs")
        conn.execute(
            """
            CREATE TABLE workflow_runs (
              id TEXT PRIMARY KEY,
              workflow_id TEXT NOT NULL,
              chat_id TEXT NOT NULL,
              mode TEXT NOT NULL CHECK(mode IN ('chat', 'code', 'agentic')),
              status TEXT NOT NULL CHECK(status IN ('running', 'done', 'failed', 'needs_user')),
              current_node TEXT NOT NULL DEFAULT '',
              state_json TEXT NOT NULL DEFAULT '{}',
              events_json TEXT NOT NULL DEFAULT '[]',
              initial_input TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              finished_at TEXT,
              FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE workflow_run_signals (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id TEXT NOT NULL,
              kind TEXT NOT NULL CHECK(kind IN ('pause', 'abort')),
              created_at TEXT NOT NULL,
              FOREIGN KEY (run_id) REFERENCES workflow_runs(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            INSERT INTO workflow_runs (id, workflow_id, chat_id, mode, status, created_at, updated_at, initial_input)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, "wf-x", chat.id, "chat", "done", "2026-01-01", "2026-01-01", "hi"),
        )
        conn.execute(
            "INSERT INTO workflow_run_signals (run_id, kind, created_at) VALUES (?, ?, ?)",
            (run_id, "pause", "2026-01-01"),
        )

    db.set_schema_version(3)
    db.init_db()

    with get_connection() as conn:
        table = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'workflow_run_signals'"
        ).fetchone()
        assert "workflow_runs_old" not in table["sql"]
        rows = conn.execute("SELECT run_id, kind FROM workflow_run_signals").fetchall()
        assert [(row["run_id"], row["kind"]) for row in rows] == [(run_id, "pause")]

    assert db.request_workflow_run_signal(run_id, "abort") is True


def test_rebuild_renames_fork_at_step_id_to_fork_at_node_id(db) -> None:
    """Regression P1-6: legacy v5 column `fork_at_step_id` is renamed in v6,
    preserving every row's data."""
    from app.db.connection import get_connection

    chat = db.create_chat(title="t", workspace_path="")
    # Simulate a v5 schema with the legacy column name.
    with get_connection() as conn:
        conn.execute("ALTER TABLE workflow_runs RENAME COLUMN fork_at_node_id TO fork_at_step_id")
        conn.execute(
            "INSERT INTO workflow_runs (id, workflow_id, chat_id, mode, status, "
            "created_at, updated_at, fork_of_run_id, fork_at_step_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("rename-me", "wf", chat.id, "chat", "done", "2026-01-01", "2026-01-01", "parent", "draft"),
        )

    db.set_schema_version(5)
    db.init_db()

    run = db.get_workflow_run("rename-me")
    assert run is not None
    assert run.fork_of_run_id == "parent"
    assert run.fork_at_node_id == "draft", "v5 column data must survive the rename"
