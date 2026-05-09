from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import database
from app.models import AgenticTask, CreateAgenticTaskRequest, UpdateAgenticTaskRequest


router = APIRouter(prefix="/api/agentic-tasks", tags=["agentic-tasks"])


@router.get("", response_model=list[AgenticTask])
def get_agentic_tasks() -> list[AgenticTask]:
    return database.list_agentic_tasks()


@router.post("", response_model=AgenticTask)
def post_agentic_task(request: CreateAgenticTaskRequest) -> AgenticTask:
    return database.create_agentic_task(
        title=request.title,
        prompt=request.prompt,
        schedule=request.schedule,
        status=request.status,
    )


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
    return task


@router.delete("/{task_id}", status_code=204)
def delete_agentic_task(task_id: str) -> None:
    if not database.delete_agentic_task(task_id):
        raise HTTPException(status_code=404, detail="Agentic task not found")
