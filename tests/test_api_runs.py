from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.runs import router as runs_router
from app.workflows.run_bus import RunEventBus, get_run_bus, reset_run_bus
from app.workflows.runtime_trace import SqliteTracePersistence, TraceEmitter


def _make_app() -> TestClient:
    app = FastAPI()
    app.include_router(runs_router)
    return TestClient(app)


def _seed_run(db, run_id: str = "run-1", workflow_id: str = "wf-1", status: str = "running") -> str:
    chat = db.create_chat(title="t", workspace_path="")
    db.create_workflow_run(run_id, workflow_id=workflow_id, chat_id=chat.id, mode="chat", initial_input="hi")
    if status != "running":
        db.update_workflow_run(run_id, status=status, state_json="{}", events_json="[]", finished=True)
    return run_id


def test_list_runs_filters_by_workflow_and_status(db) -> None:
    chat = db.create_chat(title="t", workspace_path="")
    db.create_workflow_run("r1", workflow_id="wf-a", chat_id=chat.id, mode="chat")
    db.create_workflow_run("r2", workflow_id="wf-b", chat_id=chat.id, mode="chat")
    db.update_workflow_run("r2", status="done", state_json="{}", events_json="[]", finished=True)

    client = _make_app()
    all_runs = client.get("/api/runs").json()["runs"]
    assert {run["id"] for run in all_runs} == {"r1", "r2"}

    only_a = client.get("/api/runs", params={"workflow_id": "wf-a"}).json()["runs"]
    assert [run["id"] for run in only_a] == ["r1"]

    only_done = client.get("/api/runs", params={"status": "done"}).json()["runs"]
    assert [run["id"] for run in only_done] == ["r2"]


def test_get_run_returns_metadata_and_events(db) -> None:
    run_id = _seed_run(db)
    emitter = TraceEmitter(run_id=run_id, workflow_id="wf-1", persistence=SqliteTracePersistence())
    emitter.emit("run_started", node_id="workflow", payload={"initial_input": "hi"})
    emitter.emit("node_started", node_id="role")
    emitter.emit("node_finished", node_id="role", payload={"status": "done"})

    client = _make_app()
    body = client.get(f"/api/runs/{run_id}").json()
    assert body["run"]["id"] == run_id
    assert body["run"]["initial_input"] == "hi"
    assert [event["type"] for event in body["events"]] == ["run_started", "node_started", "node_finished"]


def test_get_run_returns_fork_metadata(db) -> None:
    chat = db.create_chat(title="t", workspace_path="")
    db.create_workflow_run(
        "child",
        workflow_id="wf-1",
        chat_id=chat.id,
        mode="chat",
        fork_of_run_id="parent",
        fork_at_step_id="reviewer",
    )

    client = _make_app()
    body = client.get("/api/runs/child").json()
    assert body["run"]["fork_of_run_id"] == "parent"
    assert body["run"]["fork_at_step_id"] == "reviewer"


def test_get_run_404_when_missing(db) -> None:
    client = _make_app()
    assert client.get("/api/runs/does-not-exist").status_code == 404


def test_pause_endpoint_records_pause_signal(db) -> None:
    run_id = _seed_run(db, status="running")
    client = _make_app()

    response = client.post(f"/api/runs/{run_id}/pause")

    assert response.status_code == 200
    assert response.json()["status"] == "pause_requested"
    assert db.has_workflow_run_signal(run_id, "pause")


def test_pause_endpoint_rejects_finished_run(db) -> None:
    run_id = _seed_run(db, status="done")
    client = _make_app()

    assert client.post(f"/api/runs/{run_id}/pause").status_code == 409


def test_get_run_events_since_returns_only_new(db) -> None:
    run_id = _seed_run(db)
    emitter = TraceEmitter(run_id=run_id, workflow_id="wf-1", persistence=SqliteTracePersistence())
    emitter.emit("node_started", node_id="a")
    emitter.emit("node_finished", node_id="a")
    client = _make_app()
    first_seq = client.get(f"/api/runs/{run_id}/events").json()["events"][0]["seq"]
    emitter.emit("node_started", node_id="b")
    new_events = client.get(f"/api/runs/{run_id}/events", params={"since": first_seq}).json()["events"]
    assert [event["node_id"] for event in new_events] == ["a", "b"]


def test_stream_for_finished_run_replays_and_closes(db) -> None:
    run_id = _seed_run(db, status="done")
    emitter = TraceEmitter(run_id=run_id, workflow_id="wf-1", persistence=SqliteTracePersistence())
    emitter.emit("run_started", node_id="workflow")
    emitter.emit("run_finished", node_id="workflow")

    client = _make_app()
    with client.stream("GET", f"/api/runs/{run_id}/stream") as response:
        body = b"".join(response.iter_bytes())
    lines = [line for line in body.decode("utf-8").split("\n\n") if line.strip()]
    parsed = [json.loads(line.removeprefix("data: ")) for line in lines]
    assert [item.get("type") for item in parsed[:2]] == ["run_started", "run_finished"]
    assert parsed[-1] == {"type": "stream_closed", "reason": "done"}


def test_stream_for_running_run_pushes_live_event(db) -> None:
    reset_run_bus()
    bus = get_run_bus()
    run_id = _seed_run(db, status="running")
    emitter = TraceEmitter(run_id=run_id, workflow_id="wf-1", persistence=SqliteTracePersistence(), bus=bus)

    async def scenario() -> list[dict]:
        async def push_later() -> None:
            await asyncio.sleep(0.05)
            emitter.emit("node_started", node_id="role")
            await asyncio.sleep(0.05)
            emitter.emit("run_finished", node_id="workflow")
            bus.close(run_id)

        from app.api.runs import _event_stream

        gen = _event_stream(run_id, "running", since=0)
        push_task = asyncio.create_task(push_later())
        received: list[dict] = []
        async for item in gen:
            received.append(item)
        await push_task
        return received

    events = asyncio.run(scenario())
    types = [event.get("type") for event in events]
    assert "node_started" in types
    assert "run_finished" in types
    assert events[-1] == {"type": "stream_closed", "reason": "run_finished"}
    reset_run_bus()
