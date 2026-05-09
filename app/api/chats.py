from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from app import database
from app.agent import Agent
from app.models import Chat, CreateChatRequest, CreateMessageRequest, CreateMessageResponse, Message


router = APIRouter(prefix="/api/chats", tags=["chats"])


@router.get("", response_model=list[Chat])
def get_chats() -> list[Chat]:
    return database.list_chats()


@router.post("", response_model=Chat)
def post_chat(request: Optional[CreateChatRequest] = None) -> Chat:
    return database.create_chat(request.title if request else None)


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


@router.get("/{chat_id}/messages", response_model=list[Message])
def get_messages(chat_id: str) -> list[Message]:
    if database.get_chat(chat_id) is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    return database.list_messages(chat_id)


@router.post("/{chat_id}/messages", response_model=CreateMessageResponse)
async def post_message(chat_id: str, request: CreateMessageRequest) -> CreateMessageResponse:
    try:
        return await Agent().run(chat_id, request.content, mode=request.mode)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
