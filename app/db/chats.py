from __future__ import annotations

import sqlite3
from typing import Optional

from app.db.connection import get_connection
from app.models import Chat, new_id, utc_now


def row_to_chat(row: sqlite3.Row) -> Chat:
    return Chat(**dict(row))


def list_chats() -> list[Chat]:
    with get_connection() as db:
        rows = db.execute(
            "SELECT id, title, workspace_path, created_at, updated_at FROM chats ORDER BY updated_at DESC"
        ).fetchall()
    return [row_to_chat(row) for row in rows]


def create_chat(title: Optional[str] = None, workspace_path: str = "") -> Chat:
    now = utc_now()
    chat = Chat(id=new_id(), title=title or "New Chat", workspace_path=workspace_path.strip(), created_at=now, updated_at=now)
    with get_connection() as db:
        db.execute(
            "INSERT INTO chats (id, title, workspace_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (chat.id, chat.title, chat.workspace_path, chat.created_at, chat.updated_at),
        )
    return chat


def get_chat(chat_id: str) -> Optional[Chat]:
    with get_connection() as db:
        row = db.execute(
            "SELECT id, title, workspace_path, created_at, updated_at FROM chats WHERE id = ?",
            (chat_id,),
        ).fetchone()
    return row_to_chat(row) if row else None


def update_chat(chat_id: str, title: Optional[str] = None, workspace_path: Optional[str] = None) -> Optional[Chat]:
    assignments = []
    values = []
    if title is not None:
        assignments.append("title = ?")
        values.append(" ".join(title.strip().split())[:80] or "New Chat")
    if workspace_path is not None:
        assignments.append("workspace_path = ?")
        values.append(workspace_path.strip())
    if not assignments:
        return get_chat(chat_id)
    now = utc_now()
    assignments.append("updated_at = ?")
    values.append(now)
    values.append(chat_id)
    with get_connection() as db:
        result = db.execute(
            f"UPDATE chats SET {', '.join(assignments)} WHERE id = ?",
            values,
        )
    return get_chat(chat_id) if result.rowcount else None


def delete_chat(chat_id: str) -> bool:
    with get_connection() as db:
        result = db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    return result.rowcount > 0


def update_chat_title_if_default(chat_id: str, title: str) -> None:
    clean_title = " ".join(title.strip().split())[:80] or "New Chat"
    with get_connection() as db:
        db.execute(
            """
            UPDATE chats
            SET title = ?
            WHERE id = ? AND title IN ('Neuer Chat', 'New Chat')
            """,
            (clean_title, chat_id),
        )
