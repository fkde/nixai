from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from app.config import database_path
from app.models import Chat, Message, MessageRole, new_id, utc_now


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path or database_path())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
              id TEXT PRIMARY KEY,
              chat_id TEXT NOT NULL,
              role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
              content TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_chat_created
              ON messages(chat_id, created_at);

            CREATE INDEX IF NOT EXISTS idx_chats_updated
              ON chats(updated_at);
            """
        )


def row_to_chat(row: sqlite3.Row) -> Chat:
    return Chat(**dict(row))


def row_to_message(row: sqlite3.Row) -> Message:
    return Message(**dict(row))


def list_chats() -> list[Chat]:
    with get_connection() as db:
        rows = db.execute(
            "SELECT id, title, created_at, updated_at FROM chats ORDER BY updated_at DESC"
        ).fetchall()
    return [row_to_chat(row) for row in rows]


def create_chat(title: Optional[str] = None) -> Chat:
    now = utc_now()
    chat = Chat(id=new_id(), title=title or "Neuer Chat", created_at=now, updated_at=now)
    with get_connection() as db:
        db.execute(
            "INSERT INTO chats (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (chat.id, chat.title, chat.created_at, chat.updated_at),
        )
    return chat


def get_chat(chat_id: str) -> Optional[Chat]:
    with get_connection() as db:
        row = db.execute(
            "SELECT id, title, created_at, updated_at FROM chats WHERE id = ?",
            (chat_id,),
        ).fetchone()
    return row_to_chat(row) if row else None


def delete_chat(chat_id: str) -> bool:
    with get_connection() as db:
        result = db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    return result.rowcount > 0


def list_messages(chat_id: str) -> list[Message]:
    with get_connection() as db:
        rows = db.execute(
            """
            SELECT id, chat_id, role, content, created_at
            FROM messages
            WHERE chat_id = ?
            ORDER BY created_at ASC
            """,
            (chat_id,),
        ).fetchall()
    return [row_to_message(row) for row in rows]


def add_message(chat_id: str, role: MessageRole, content: str) -> Message:
    message = Message(id=new_id(), chat_id=chat_id, role=role, content=content, created_at=utc_now())
    with get_connection() as db:
        db.execute(
            """
            INSERT INTO messages (id, chat_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (message.id, message.chat_id, message.role, message.content, message.created_at),
        )
        db.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (message.created_at, chat_id))
    return message


def update_chat_title_if_default(chat_id: str, title: str) -> None:
    clean_title = " ".join(title.strip().split())[:80] or "Neuer Chat"
    with get_connection() as db:
        db.execute(
            """
            UPDATE chats
            SET title = ?
            WHERE id = ? AND title = 'Neuer Chat'
            """,
            (clean_title, chat_id),
        )
