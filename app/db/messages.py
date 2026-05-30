from __future__ import annotations

import sqlite3
from typing import Optional

from app.db.connection import get_connection
from app.models import FeedbackRating, Message, MessageMode, MessageRole, new_id, utc_now


def row_to_message(row: sqlite3.Row) -> Message:
    return Message(**dict(row))


def list_messages(chat_id: str, mode: Optional[MessageMode] = None) -> list[Message]:
    where = "WHERE chat_id = ?"
    params: list[str] = [chat_id]
    if mode is not None:
        where += " AND mode = ?"
        params.append(mode)
    with get_connection() as db:
        rows = db.execute(
            f"""
            SELECT id, chat_id, role, content, mode, feedback, created_at
            FROM messages
            {where}
            ORDER BY created_at ASC
            """,
            params,
        ).fetchall()
    return [row_to_message(row) for row in rows]


def add_message(chat_id: str, role: MessageRole, content: str, mode: MessageMode = "chat") -> Message:
    message = Message(id=new_id(), chat_id=chat_id, role=role, content=content, mode=mode, created_at=utc_now())
    with get_connection() as db:
        db.execute(
            """
            INSERT INTO messages (id, chat_id, role, content, mode, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (message.id, message.chat_id, message.role, message.content, message.mode, message.created_at),
        )
        db.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (message.created_at, chat_id))
    return message


def get_message(message_id: str) -> Optional[Message]:
    with get_connection() as db:
        row = db.execute(
            """
            SELECT id, chat_id, role, content, mode, feedback, created_at
            FROM messages
            WHERE id = ?
            """,
            (message_id,),
        ).fetchone()
    return row_to_message(row) if row else None


def set_message_feedback(message_id: str, rating: FeedbackRating) -> Optional[Message]:
    with get_connection() as db:
        result = db.execute("UPDATE messages SET feedback = ? WHERE id = ?", (rating, message_id))
    if result.rowcount == 0:
        return None
    return get_message(message_id)
