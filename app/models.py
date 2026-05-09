from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


MessageRole = Literal["user", "assistant", "system", "tool"]
MessageMode = Literal["chat", "code", "agentic"]
TaskStatus = Literal["active", "paused"]
TaskRunStatus = Literal["running", "success", "failed", "needs_review"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid4().hex


class Chat(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class Message(BaseModel):
    id: str
    chat_id: str
    role: MessageRole
    content: str
    mode: MessageMode = "chat"
    created_at: str


class AgenticTask(BaseModel):
    id: str
    title: str
    prompt: str
    schedule: str
    status: TaskStatus = "active"
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None
    failure_count: int = 0
    created_at: str
    updated_at: str


class AgenticTaskRun(BaseModel):
    id: str
    task_id: str
    status: TaskRunStatus
    summary: str = ""
    tool_results: str = "[]"
    error: str = ""
    attempt: int = 1
    started_at: str
    finished_at: Optional[str] = None


class CreateChatRequest(BaseModel):
    title: Optional[str] = None


class CreateMessageRequest(BaseModel):
    content: str = Field(min_length=1)
    mode: MessageMode = "chat"


class CreateMessageResponse(BaseModel):
    user_message: Message
    assistant_message: Message


class CreateAgenticTaskRequest(BaseModel):
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    schedule: str = Field(min_length=1)
    status: TaskStatus = "active"


class UpdateAgenticTaskRequest(BaseModel):
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    schedule: str = Field(min_length=1)
    status: TaskStatus = "active"


class RunAgenticTaskResponse(BaseModel):
    run: AgenticTaskRun
