from __future__ import annotations

from typing import Optional

from fastapi import BackgroundTasks
from fastapi import APIRouter, HTTPException, Query

from app import database
from app.agent import Agent
from app.mistake_distiller import MistakeDistiller
from app.models import Chat, CreateChatRequest, CreateMessageRequest, CreateMessageResponse, Message, MessageFeedbackRequest, MessageFeedbackResponse, MessageMode, UpdateChatRequest
from app.streaming import sse_response


router = APIRouter(prefix="/api/chats", tags=["chats"])


@router.get("", response_model=list[Chat])
def get_chats() -> list[Chat]:
    return database.list_chats()


@router.post("", response_model=Chat)
def post_chat(request: Optional[CreateChatRequest] = None) -> Chat:
    return database.create_chat(request.title if request else None, request.workspace_path if request else "")


@router.get("/{chat_id}", response_model=Chat)
def get_chat(chat_id: str) -> Chat:
    chat = database.get_chat(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@router.delete("/{chat_id}", status_code=204)
def delete_chat(chat_id: str) -> None:
    if not database.delete_chat(chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")


@router.put("/{chat_id}", response_model=Chat)
def put_chat(chat_id: str, request: UpdateChatRequest) -> Chat:
    chat = database.update_chat(chat_id, title=request.title, workspace_path=request.workspace_path)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat


@router.get("/{chat_id}/messages", response_model=list[Message])
def get_messages(chat_id: str, mode: Optional[MessageMode] = Query(default=None)) -> list[Message]:
    if database.get_chat(chat_id) is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return database.list_messages(chat_id, mode=mode)


@router.post("/{chat_id}/messages", response_model=CreateMessageResponse)
async def post_message(chat_id: str, request: CreateMessageRequest) -> CreateMessageResponse:
    try:
        return await Agent(effort=request.effort).run(
            chat_id,
            request.content,
            mode=request.mode,
            attachments=request.attachments,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{chat_id}/messages/stream")
async def post_message_stream(chat_id: str, request: CreateMessageRequest):
    return sse_response(
        Agent(effort=request.effort).stream(
            chat_id,
            request.content,
            mode=request.mode,
            attachments=request.attachments,
        )
    )


@router.post("/messages/{message_id}/feedback", response_model=MessageFeedbackResponse)
async def post_message_feedback(
    message_id: str,
    request: MessageFeedbackRequest,
    background_tasks: BackgroundTasks,
) -> MessageFeedbackResponse:
    message = database.set_message_feedback(message_id, request.rating)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    queued = request.rating == "down" and message.role == "assistant"
    if queued:
        background_tasks.add_task(MistakeDistiller().process_downvote, message.id)
    return MessageFeedbackResponse(message=message, mistakes_update_queued=queued)
