from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from app.config import config_dir
from app.models import utc_now


DEFAULT_MEMORY = """# MEMORY

Accepted NixAI operating reminders.

## Purpose
- Store reviewed lessons that should influence future model behavior.
- Keep instructions concrete, reusable, and short.
- Only add entries after human approval.

## Entries
"""


class MemoryDocument(BaseModel):
    filename: str
    content: str
    updated_at: str


def memory_path() -> Path:
    return config_dir() / "MEMORY.md"


def ensure_memory() -> None:
    path = memory_path()
    if not path.exists():
        path.write_text(DEFAULT_MEMORY.rstrip() + "\n", encoding="utf-8")


def load_memory() -> MemoryDocument:
    ensure_memory()
    path = memory_path()
    stat = path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    return MemoryDocument(filename=path.name, content=path.read_text(encoding="utf-8"), updated_at=updated_at)


def save_memory(content: str) -> MemoryDocument:
    path = memory_path()
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return load_memory()


def append_memory_entry(title: str, instruction: str, source: str = "") -> MemoryDocument:
    document = load_memory()
    source_line = f"\n- Source: {source.strip()}" if source.strip() else ""
    entry = (
        f"### {utc_now()} - {title.strip() or 'Reviewed lesson'}\n"
        f"- Instruction: {instruction.strip()}{source_line}\n"
    )
    return save_memory(f"{document.content.rstrip()}\n\n{entry}")


def memory_context() -> str:
    return load_memory().content
