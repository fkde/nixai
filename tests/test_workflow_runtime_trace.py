from __future__ import annotations

import json

import pytest

from app import database
from app.workflows.runtime_trace import (
    SNAPSHOT_INLINE_CAP,
    InMemoryTracePersistence,
    SqliteTracePersistence,
    TraceEmitter,
    cap_snapshot,
)


def _make_chat_and_run(db) -> tuple[str, str]:
    chat = db.create_chat(title="t", workspace_path="")
    run = db.create_workflow_run(
        "run-1",
        workflow_id="wf-1",
        chat_id=chat.id,
        mode="chat",
        initial_input="hello",
    )
    return chat.id, run.id


def test_create_workflow_run_persists_initial_input(db):
    _, run_id = _make_chat_and_run(db)
    fetched = db.get_workflow_run(run_id)
    assert fetched is not None
    assert fetched.initial_input == "hello"


def test_insert_and_list_trace_events_returns_in_seq_order(db):
    _, run_id = _make_chat_and_run(db)
    persistence = SqliteTracePersistence()
    emitter = TraceEmitter(run_id=run_id, workflow_id="wf-1", persistence=persistence)

    run_started = emitter.emit("run_started", node_id="start", payload={"initial_input": "hi"})
    a = emitter.emit("node_started", node_id="role")
    b = emitter.emit("node_finished", node_id="role", payload={"status": "done"})

    rows = db.list_trace_events(run_id)
    assert [row["step_id"] for row in rows] == [run_started, a, b]
    assert [row["type"] for row in rows] == ["run_started", "node_started", "node_finished"]
    assert json.loads(rows[0]["payload_json"]) == {"initial_input": "hi"}
    # seq is monotonic
    assert rows[0]["seq"] < rows[1]["seq"] < rows[2]["seq"]


def test_list_trace_events_since_seq_returns_only_new(db):
    _, run_id = _make_chat_and_run(db)
    emitter = TraceEmitter(run_id=run_id, workflow_id="wf-1", persistence=SqliteTracePersistence())
    emitter.emit("node_started", node_id="a")
    emitter.emit("node_finished", node_id="a")
    rows_all = db.list_trace_events(run_id)
    last_seq = rows_all[0]["seq"]
    emitter.emit("node_started", node_id="b")
    new_rows = db.list_trace_events(run_id, since_seq=last_seq)
    assert [row["node_id"] for row in new_rows] == ["a", "b"]


def test_scope_sets_parent_step_id(db):
    _, run_id = _make_chat_and_run(db)
    emitter = TraceEmitter(run_id=run_id, workflow_id="wf-1", persistence=SqliteTracePersistence())
    parent = emitter.emit("node_started", node_id="for_each")
    with emitter.scope(parent):
        child = emitter.emit("node_started", node_id="body")
        assert emitter.current_parent == parent
        # nested scope inherits child as parent
        with emitter.scope(child):
            grand = emitter.emit("node_started", node_id="inner")
    assert emitter.current_parent is None

    rows = {row["step_id"]: row for row in db.list_trace_events(run_id)}
    assert rows[parent]["parent_step_id"] is None
    assert rows[child]["parent_step_id"] == parent
    assert rows[grand]["parent_step_id"] == child


def test_explicit_parent_step_id_overrides_scope(db):
    _, run_id = _make_chat_and_run(db)
    emitter = TraceEmitter(run_id=run_id, workflow_id="wf-1", persistence=SqliteTracePersistence())
    other = "stub-parent"
    with emitter.scope("scope-parent"):
        step = emitter.emit("node_started", node_id="x", parent_step_id=other)
    rows = {row["step_id"]: row for row in db.list_trace_events(run_id)}
    assert rows[step]["parent_step_id"] == other


def test_persistence_failure_is_swallowed():
    class BrokenPersistence:
        def insert(self, event):  # noqa: ANN001
            raise RuntimeError("boom")

    emitter = TraceEmitter(run_id="r", workflow_id="w", persistence=BrokenPersistence())
    step_id = emitter.emit("node_started", node_id="x")
    assert step_id  # caller still gets an id back; workflow execution unaffected


def test_list_workflow_runs_filters(db):
    chat = db.create_chat(title="t", workspace_path="")
    db.create_workflow_run("r1", workflow_id="wf-a", chat_id=chat.id, mode="chat")
    db.create_workflow_run("r2", workflow_id="wf-b", chat_id=chat.id, mode="chat")
    db.update_workflow_run("r2", status="done", state_json="{}", events_json="[]", finished=True)

    all_runs = db.list_workflow_runs()
    assert {row["id"] for row in all_runs} == {"r1", "r2"}

    only_a = db.list_workflow_runs(workflow_id="wf-a")
    assert [row["id"] for row in only_a] == ["r1"]

    only_done = db.list_workflow_runs(status="done")
    assert [row["id"] for row in only_done] == ["r2"]


def test_in_memory_persistence_records_events():
    persistence = InMemoryTracePersistence()
    emitter = TraceEmitter(run_id="r", workflow_id="w", persistence=persistence)
    emitter.emit("run_started", node_id="start")
    emitter.emit("run_finished", node_id="end")
    assert [event.type for event in persistence.events] == ["run_started", "run_finished"]


@pytest.mark.parametrize(
    "value",
    [
        "a" * (SNAPSHOT_INLINE_CAP + 1),
        {"big": "a" * (SNAPSHOT_INLINE_CAP + 1)},
    ],
)
def test_cap_snapshot_truncates_when_above_cap(value):
    capped, truncated = cap_snapshot(value)
    assert truncated is True
    assert isinstance(capped, str)
    assert len(capped.encode("utf-8")) <= SNAPSHOT_INLINE_CAP


def test_cap_snapshot_passes_through_small_values():
    capped, truncated = cap_snapshot({"hello": "world"})
    assert truncated is False
    assert capped == {"hello": "world"}


def test_delete_trace_events_removes_rows(db):
    _, run_id = _make_chat_and_run(db)
    emitter = TraceEmitter(run_id=run_id, workflow_id="wf-1", persistence=SqliteTracePersistence())
    emitter.emit("node_started", node_id="x")
    emitter.emit("node_finished", node_id="x")
    removed = db.delete_trace_events(run_id)
    assert removed == 2
    assert db.list_trace_events(run_id) == []


def test_cascade_delete_on_run_removes_events(db):
    chat_id, run_id = _make_chat_and_run(db)
    emitter = TraceEmitter(run_id=run_id, workflow_id="wf-1", persistence=SqliteTracePersistence())
    emitter.emit("node_started", node_id="x")
    # cascade via chat delete (workflow_runs FK ON DELETE CASCADE, and workflow_run_events FK too)
    db.delete_chat(chat_id)
    assert db.list_trace_events(run_id) == []
