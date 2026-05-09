from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


MessageRole = Literal["user", "assistant", "system", "tool"]


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
    created_at: str


class CreateChatRequest(BaseModel):
    title: Optional[str] = None


class CreateMessageRequest(BaseModel):
    content: str = Field(min_length=1)


class CreateMessageResponse(BaseModel):
    user_message: Message
    assistant_message: Message
