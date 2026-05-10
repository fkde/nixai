from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


MessageRole = Literal["user", "assistant", "system", "tool"]
MessageMode = Literal["chat", "code", "agentic"]
FeedbackRating = Literal["up", "down"]
TaskStatus = Literal["active", "paused"]
TaskRunStatus = Literal["running", "success", "failed", "needs_review"]
OllamaModelKind = Literal["chat", "embedding", "unknown"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid4().hex


class Chat(BaseModel):
    id: str
    title: str
    workspace_path: str = ""
    created_at: str
    updated_at: str


class Message(BaseModel):
    id: str
    chat_id: str
    role: MessageRole
    content: str
    mode: MessageMode = "chat"
    feedback: Optional[FeedbackRating] = None
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
    workspace_path: str = ""


class UpdateChatRequest(BaseModel):
    title: Optional[str] = None
    workspace_path: Optional[str] = None


class CreateMessageRequest(BaseModel):
    content: str = Field(min_length=1)
    mode: MessageMode = "chat"
    effort: Optional[str] = None


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


class OllamaModelInfo(BaseModel):
    name: str
    kind: OllamaModelKind = "unknown"
    family: str = ""
    families: list[str] = Field(default_factory=list)
    parameter_size: str = ""
    quantization_level: str = ""
    format: str = ""
    size: Optional[int] = None
    digest: str = ""
    modified_at: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    model_info: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    error: str = ""


class MessageFeedbackRequest(BaseModel):
    rating: FeedbackRating


class MessageFeedbackResponse(BaseModel):
    message: Message
    mistakes_update_queued: bool = False
