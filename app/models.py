from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from app.validation import (
    MAX_PROMPT_LENGTH,
    MAX_SCHEDULE_LENGTH,
    MAX_TITLE_LENGTH,
    clean_single_line,
    clean_text,
    validate_workspace_path,
)


MessageRole = Literal["user", "assistant", "system", "tool"]
MessageMode = Literal["chat", "code", "agentic"]
FeedbackRating = Literal["up", "down"]
TaskStatus = Literal["active", "paused"]
TaskRunStatus = Literal["running", "success", "failed", "needs_review"]
WorkflowRunStatus = Literal["running", "paused", "done", "failed", "needs_user"]
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


class WorkflowRun(BaseModel):
    id: str
    workflow_id: str
    chat_id: str
    mode: MessageMode
    status: WorkflowRunStatus
    current_node: str = ""
    state_json: str = "{}"
    events_json: str = "[]"
    initial_input: str = ""
    fork_of_run_id: Optional[str] = None
    fork_at_step_id: Optional[str] = None
    created_at: str
    updated_at: str
    finished_at: Optional[str] = None


class CreateChatRequest(BaseModel):
    title: Optional[str] = None
    workspace_path: str = ""

    @field_validator("title", mode="before")
    @classmethod
    def _clean_title(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        cleaned = clean_single_line(value, max_length=MAX_TITLE_LENGTH, field_name="title")
        return cleaned or None

    @field_validator("workspace_path", mode="before")
    @classmethod
    def _clean_workspace(cls, value: Any) -> str:
        return validate_workspace_path(value)


class UpdateChatRequest(BaseModel):
    title: Optional[str] = None
    workspace_path: Optional[str] = None

    @field_validator("title", mode="before")
    @classmethod
    def _clean_title(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        cleaned = clean_single_line(value, max_length=MAX_TITLE_LENGTH, field_name="title")
        return cleaned or None

    @field_validator("workspace_path", mode="before")
    @classmethod
    def _clean_workspace(cls, value: Any) -> Optional[str]:
        if value is None:
            return None
        return validate_workspace_path(value)


class CreateMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    mode: MessageMode = "chat"
    effort: Optional[str] = None

    @field_validator("content", mode="before")
    @classmethod
    def _clean_content(cls, value: Any) -> str:
        cleaned = clean_text(value, max_length=MAX_PROMPT_LENGTH, field_name="content")
        if not cleaned:
            raise ValueError("content must not be empty")
        return cleaned


class CreateMessageResponse(BaseModel):
    user_message: Message
    assistant_message: Message


class CreateAgenticTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    schedule: str = Field(min_length=1, max_length=MAX_SCHEDULE_LENGTH)
    status: TaskStatus = "active"

    @field_validator("title", "schedule", mode="before")
    @classmethod
    def _clean_single_line(cls, value: Any) -> str:
        return clean_single_line(value, max_length=MAX_TITLE_LENGTH, field_name="value")

    @field_validator("prompt", mode="before")
    @classmethod
    def _clean_prompt(cls, value: Any) -> str:
        return clean_text(value, max_length=MAX_PROMPT_LENGTH, field_name="prompt")


class UpdateAgenticTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    schedule: str = Field(min_length=1, max_length=MAX_SCHEDULE_LENGTH)
    status: TaskStatus = "active"

    @field_validator("title", "schedule", mode="before")
    @classmethod
    def _clean_single_line(cls, value: Any) -> str:
        return clean_single_line(value, max_length=MAX_TITLE_LENGTH, field_name="value")

    @field_validator("prompt", mode="before")
    @classmethod
    def _clean_prompt(cls, value: Any) -> str:
        return clean_text(value, max_length=MAX_PROMPT_LENGTH, field_name="prompt")


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
