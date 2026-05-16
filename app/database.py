from __future__ import annotations

from app.db.agentic_tasks import (
    create_agentic_task,
    create_agentic_task_run,
    delete_agentic_task,
    finish_agentic_task_run,
    get_agentic_task,
    get_agentic_task_run,
    list_agentic_task_runs,
    list_agentic_tasks,
    list_due_agentic_tasks,
    row_to_agentic_task,
    row_to_agentic_task_run,
    update_agentic_task,
    update_agentic_task_schedule_state,
)
from app.db.chats import (
    create_chat,
    delete_chat,
    get_chat,
    list_chats,
    row_to_chat,
    update_chat,
    update_chat_title_if_default,
)
from app.db.connection import connect, get_connection
from app.db.messages import (
    add_message,
    get_message,
    list_messages,
    row_to_message,
    set_message_feedback,
)
from app.db.schema import SCHEMA_VERSION, get_schema_version, init_db, set_schema_version


__all__ = [
    "add_message",
    "SCHEMA_VERSION",
    "connect",
    "create_agentic_task",
    "create_agentic_task_run",
    "create_chat",
    "delete_agentic_task",
    "delete_chat",
    "finish_agentic_task_run",
    "get_agentic_task",
    "get_agentic_task_run",
    "get_chat",
    "get_connection",
    "get_message",
    "get_schema_version",
    "init_db",
    "list_agentic_task_runs",
    "list_agentic_tasks",
    "list_chats",
    "list_due_agentic_tasks",
    "list_messages",
    "row_to_agentic_task",
    "row_to_agentic_task_run",
    "row_to_chat",
    "row_to_message",
    "set_message_feedback",
    "set_schema_version",
    "update_agentic_task",
    "update_agentic_task_schedule_state",
    "update_chat",
    "update_chat_title_if_default",
]
