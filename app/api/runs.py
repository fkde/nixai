from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator
from typing import Any, Optional

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Query

from app import database
from app.streaming import sse_response
from app.workflows.presets import get_workflow
from app.workflows.replay import WorkflowReplayPlanner
from app.workflows.run_bus import get_run_bus
from app.workflows.runner import WorkflowRunner


router = APIRouter(prefix="/api/runs", tags=["runs"])


class WorkflowResumeRequest(BaseModel):
    feedback: str = ""


class WorkflowForkRequest(BaseModel):
    from_step_id: str
    edited_output: Any
    label: str = ""


class WorkflowReplayPlanRequest(BaseModel):
    start_node_id: str
    scope: str = "downstream"


class WorkflowReplayRequest(BaseModel):
    start_node_id: str
    scope: str = "downstream"
    label: str = ""


def _row_to_run_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workflow_id": row["workflow_id"],
        "chat_id": row["chat_id"],
        "mode": row["mode"],
        "status": row["status"],
        "current_node": row["current_node"],
        "initial_input": row["initial_input"],
        "fork_of_run_id": row["fork_of_run_id"],
        "fork_at_node_id": row["fork_at_node_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
    }


def _row_to_event_dict(row: sqlite3.Row) -> dict[str, Any]:
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError):
        payload = {}
    return {
        "seq": row["seq"],
        "step_id": row["step_id"],
        "run_id": row["run_id"],
        "parent_step_id": row["parent_step_id"],
        "workflow_id": row["workflow_id"],
        "node_id": row["node_id"],
        "type": row["type"],
        "ts": row["ts"],
        "payload": payload,
    }


@router.get("")
def list_runs(
    workflow_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    rows = database.list_workflow_runs(workflow_id=workflow_id, status=status, limit=limit, offset=offset)
    return {"runs": [_row_to_run_dict(row) for row in rows]}


@router.get("/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = database.get_workflow_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    rows = database.list_trace_events(run_id)
    node_rows = database.list_node_states(run_id)
    tool_rows = database.list_tool_calls(run_id)
    return {
        "run": {
            "id": run.id,
            "workflow_id": run.workflow_id,
            "chat_id": run.chat_id,
            "mode": run.mode,
            "status": run.status,
            "current_node": run.current_node,
            "initial_input": run.initial_input,
            "fork_of_run_id": run.fork_of_run_id,
            "fork_at_node_id": run.fork_at_node_id,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "finished_at": run.finished_at,
        },
        "events": [_row_to_event_dict(row) for row in rows],
        "node_states": [database.node_state_row_to_dict(row) for row in node_rows],
        "tool_calls": [database.tool_call_row_to_dict(row) for row in tool_rows],
    }


@router.get("/{run_id}/events")
def get_run_events(
    run_id: str,
    since: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    if database.get_workflow_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    rows = database.list_trace_events(run_id, since_seq=since or None, limit=limit)
    return {"events": [_row_to_event_dict(row) for row in rows]}


@router.post("/{run_id}/replay-plan")
def plan_replay(run_id: str, request: WorkflowReplayPlanRequest) -> dict[str, Any]:
    run = database.get_workflow_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    workflow = get_workflow(run.workflow_id, run.mode)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow definition not found")
    if request.scope not in {"node", "downstream"}:
        raise HTTPException(status_code=400, detail="Unsupported replay scope.")
    events = [_row_to_event_dict(row) for row in database.list_trace_events(run_id)]
    node_states = [database.node_state_row_to_dict(row) for row in database.list_node_states(run_id)]
    plan = WorkflowReplayPlanner().build_plan(
        workflow=workflow,
        run_id=run_id,
        start_node_id=request.start_node_id,
        scope=request.scope,  # type: ignore[arg-type]
        events=events,
        node_states=node_states,
    )
    return {"success": True, "plan": plan.model_dump()}


@router.post("/{run_id}/replay")
async def replay_run(run_id: str, request: WorkflowReplayRequest) -> dict[str, Any]:
    run = database.get_workflow_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    workflow = get_workflow(run.workflow_id, run.mode)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow definition not found")
    if request.scope not in {"downstream"}:
        raise HTTPException(status_code=400, detail="Only downstream replay execution is supported for now.")
    try:
        result = await WorkflowRunner().replay(
            workflow,
            run,
            start_node_id=request.start_node_id,
            scope=request.scope,  # type: ignore[arg-type]
            label=request.label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result.answer:
        database.add_message(run.chat_id, "assistant", result.answer, mode=run.mode)
    new_run_id = str(result.state.get("workflow_run_id") or "")
    return {"run_id": new_run_id, "result": result.model_dump()}


@router.get("/{run_id}/stream")
async def stream_run_events(run_id: str, since: int = Query(default=0, ge=0)):
    run = database.get_workflow_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return sse_response(_event_stream(run_id, run.status, since))


@router.post("/{run_id}/pause")
def pause_run(run_id: str) -> dict[str, Any]:
    run = database.get_workflow_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "running":
        raise HTTPException(status_code=409, detail="Only running workflow runs can be paused.")
    if not database.request_workflow_run_signal(run_id, "pause"):
        raise HTTPException(status_code=404, detail="Run not found")
    return {"ok": True, "run_id": run_id, "status": "pause_requested"}


@router.post("/{run_id}/resume")
async def resume_run(run_id: str, request: WorkflowResumeRequest) -> dict[str, Any]:
    run = database.get_workflow_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in {"paused", "needs_user"}:
        raise HTTPException(status_code=409, detail="Only paused workflow runs can be resumed.")
    workflow = get_workflow(run.workflow_id, run.mode)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow definition not found")
    try:
        state = json.loads(run.state_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=409, detail="Workflow run state is corrupted.") from exc
    if not isinstance(state, dict):
        raise HTTPException(status_code=409, detail="Workflow run state is invalid.")
    result = await WorkflowRunner().resume(workflow, state, feedback=request.feedback)
    if result.answer:
        database.add_message(run.chat_id, "assistant", result.answer, mode=run.mode)
    return result.model_dump()


@router.post("/{run_id}/fork")
async def fork_run(run_id: str, request: WorkflowForkRequest) -> dict[str, Any]:
    run = database.get_workflow_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    workflow = get_workflow(run.workflow_id, run.mode)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow definition not found")
    try:
        result = await WorkflowRunner().fork(
            workflow,
            run,
            from_step_id=request.from_step_id,
            edited_output=request.edited_output,
            label=request.label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result.answer:
        database.add_message(run.chat_id, "assistant", result.answer, mode=run.mode)
    new_run_id = str(result.state.get("workflow_run_id") or "")
    return {"run_id": new_run_id, "result": result.model_dump()}


async def _event_stream(run_id: str, initial_status: str, since: int) -> AsyncIterator[dict[str, Any]]:
    # Replay everything persisted since the cursor before tapping the live bus.
    replay = database.list_trace_events(run_id, since_seq=since or None)
    last_seq = since
    for row in replay:
        last_seq = row["seq"]
        yield _row_to_event_dict(row)

    # If the run already terminated, no point subscribing.
    if initial_status in {"done", "failed"}:
        yield {"type": "stream_closed", "reason": initial_status}
        return

    bus = get_run_bus()
    async for item in bus.subscribe(run_id):
        event = item["event"]
        seq = item["seq"]
        # Suppress events the consumer already received via replay (race against publish).
        if seq <= last_seq:
            continue
        # Gap detection: if the bus dropped events under backpressure, tell the
        # consumer to reconcile via /events?since=<last_seq>.
        if seq > last_seq + 1:
            yield {"type": "gap", "reconcile_since": last_seq, "next_seq": seq}
        last_seq = seq
        yield {
            "seq": seq,
            "step_id": event.step_id,
            "run_id": event.run_id,
            "parent_step_id": event.parent_step_id,
            "workflow_id": event.workflow_id,
            "node_id": event.node_id,
            "type": event.type,
            "ts": event.ts,
            "payload": event.payload,
        }
    yield {"type": "stream_closed", "reason": "run_finished"}
