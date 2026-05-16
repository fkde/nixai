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
