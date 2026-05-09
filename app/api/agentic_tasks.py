from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import database
from app.agentic_scheduler import scheduler
from app.agentic_schedule import compute_next_run, utc_now_dt
from app.models import AgenticTask, AgenticTaskRun, CreateAgenticTaskRequest, RunAgenticTaskResponse, UpdateAgenticTaskRequest


router = APIRouter(prefix="/api/agentic-tasks", tags=["agentic-tasks"])


@router.get("", response_model=list[AgenticTask])
def get_agentic_tasks() -> list[AgenticTask]:
    return database.list_agentic_tasks()


@router.post("", response_model=AgenticTask)
def post_agentic_task(request: CreateAgenticTaskRequest) -> AgenticTask:
    task = database.create_agentic_task(
        title=request.title,
        prompt=request.prompt,
        schedule=request.schedule,
        status=request.status,
    )
    return database.update_agentic_task_schedule_state(task.id, next_run_at=compute_next_run(task.schedule, utc_now_dt())) or task


@router.get("/scheduler/status")
def get_scheduler_status() -> dict[str, object]:
    return scheduler.status()


@router.put("/{task_id}", response_model=AgenticTask)
def put_agentic_task(task_id: str, request: UpdateAgenticTaskRequest) -> AgenticTask:
    task = database.update_agentic_task(
        task_id,
        title=request.title,
        prompt=request.prompt,
        schedule=request.schedule,
        status=request.status,
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Agentic task not found")
    return database.update_agentic_task_schedule_state(task.id, next_run_at=compute_next_run(task.schedule, utc_now_dt())) or task


@router.delete("/{task_id}", status_code=204)
def delete_agentic_task(task_id: str) -> None:
    if not database.delete_agentic_task(task_id):
        raise HTTPException(status_code=404, detail="Agentic task not found")


@router.get("/{task_id}/runs", response_model=list[AgenticTaskRun])
def get_agentic_task_runs(task_id: str) -> list[AgenticTaskRun]:
    if database.get_agentic_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Agentic task not found")
    return database.list_agentic_task_runs(task_id)


@router.post("/{task_id}/run-now", response_model=RunAgenticTaskResponse)
async def post_agentic_task_run_now(task_id: str) -> RunAgenticTaskResponse:
    try:
        run = await scheduler.run_task_now(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RunAgenticTaskResponse(run=run)
