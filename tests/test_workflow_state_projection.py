"""Tests for the runtime-state read-model built from trace events."""
from __future__ import annotations

from app.workflows.runtime_trace import SqliteTracePersistence, TraceEmitter


def _setup_run(db, run_id: str = "proj-1"):
    chat = db.create_chat(title="t", workspace_path="")
    db.create_workflow_run(run_id, workflow_id="wf", chat_id=chat.id, mode="chat")
    return TraceEmitter(run_id=run_id, workflow_id="wf", persistence=SqliteTracePersistence())


def test_node_started_creates_node_state_row(db) -> None:
    em = _setup_run(db)
    em.emit(
        "node_started",
        node_id="role",
        payload={
            "node_type": "role",
            "input_snapshot": {"x": 1},
            "input_snapshot_truncated": False,
            "prompt_snapshot": "hi",
            "prompt_snapshot_truncated": False,
        },
    )

    states = [db.node_state_row_to_dict(row) for row in db.list_node_states("proj-1")]
    assert len(states) == 1
    row = states[0]
    assert row["node_id"] == "role"
    assert row["status"] == "running"
    assert row["node_type"] == "role"
    assert row["input_snapshot"] == {"x": 1}
    assert row["prompt_snapshot"] == "hi"


def test_node_finished_updates_status_and_output(db) -> None:
    em = _setup_run(db)
    em.emit("node_started", node_id="role", payload={"node_type": "role"})
    em.emit(
        "node_finished",
        node_id="role",
        payload={"status": "done", "output_snapshot": {"answer": 42}, "duration_ms": 80},
    )
    row = db.node_state_row_to_dict(db.list_node_states("proj-1")[0])
    assert row["status"] == "done"
    assert row["output_snapshot"] == {"answer": 42}
    assert row["duration_ms"] == 80
    assert row["finished_at"] is not None


def test_node_failed_sets_failed_status_and_appends_error(db) -> None:
    em = _setup_run(db)
    em.emit("node_started", node_id="role")
    em.emit("node_failed", node_id="role", payload={"error": "boom", "duration_ms": 10})

    row = db.node_state_row_to_dict(db.list_node_states("proj-1")[0])
    assert row["status"] == "failed"
    assert row["errors"][0]["error"] == "boom"
    assert row["duration_ms"] == 10


def test_llm_call_updates_model_and_token_usage(db) -> None:
    em = _setup_run(db)
    em.emit("node_started", node_id="role")
    em.emit_llm_call(
        node_id="role",
        model="fake-llm",
        prompt="p",
        response="r",
        duration_ms=33,
        tokens_in=12,
        tokens_out=34,
    )

    row = db.node_state_row_to_dict(db.list_node_states("proj-1")[0])
    assert row["model_used"] == "fake-llm"
    assert row["token_usage"] == {"tokens_in": 12, "tokens_out": 34}


def test_tool_call_inserts_into_tool_calls_table_and_node_summary(db) -> None:
    em = _setup_run(db)
    parent = em.emit("node_started", node_id="role")
    with em.scope(parent):
        em.emit_tool_call(
            node_id="role",
            tool_name="search",
            arguments={"q": "x"},
            result={"hits": 3},
            duration_ms=42,
        )

    tool_rows = [db.tool_call_row_to_dict(row) for row in db.list_tool_calls("proj-1")]
    assert len(tool_rows) == 1
    tool = tool_rows[0]
    assert tool["tool_name"] == "search"
    assert tool["arguments_snapshot"] == {"q": "x"}
    assert tool["result_snapshot"] == {"hits": 3}
    assert tool["status"] == "done"

    # Also denormalised into the node's tool_calls summary
    node_row = db.node_state_row_to_dict(db.list_node_states("proj-1")[0])
    assert node_row["tool_calls"][0]["tool_name"] == "search"
    assert node_row["tool_calls"][0]["duration_ms"] == 42


def test_tool_call_with_error_records_failed_status(db) -> None:
    em = _setup_run(db)
    parent = em.emit("node_started", node_id="role")
    with em.scope(parent):
        em.emit_tool_call(
            node_id="role",
            tool_name="search",
            arguments={"q": "x"},
            error="rate limited",
            duration_ms=5,
        )
    tool = db.tool_call_row_to_dict(db.list_tool_calls("proj-1")[0])
    assert tool["status"] == "failed"
    assert tool["error_snapshot"] == "rate limited"


def test_projection_uses_existing_db_connection_when_provided(db) -> None:
    """Atomic-insert path: when called with an explicit db, both writes are
    visible inside the same transaction (smoke test, not a rollback test)."""
    from app.db.connection import get_connection
    from app.db.workflow_state import apply_trace_event_to_runtime_state
    from app.workflows.runtime_trace import TraceEvent

    chat = db.create_chat(title="t", workspace_path="")
    db.create_workflow_run("proj-conn", workflow_id="wf", chat_id=chat.id, mode="chat")

    event = TraceEvent(
        run_id="proj-conn", workflow_id="wf", node_id="x", type="node_started", payload={"node_type": "role"}
    )
    with get_connection() as conn:
        apply_trace_event_to_runtime_state(event, seq=1, db=conn)
        # Same connection sees the insert before commit
        row = conn.execute(
            "SELECT status FROM workflow_node_states WHERE step_id = ?",
            (event.step_id,),
        ).fetchone()
    assert row is not None and row["status"] == "running"
