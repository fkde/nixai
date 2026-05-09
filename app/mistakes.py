from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from app.config import config_dir


DEFAULT_MISTAKES = """# MISTAKES

Central NixAI learning notes.

## Purpose
- Record recurring mistakes, false assumptions, unsafe behavior, and failed workflows.
- Keep entries concise and actionable.
- Prefer concrete examples and the corrected behavior.

## Entries

<!--
Example:

### 2026-05-09 - Claimed tests ran without evidence
- Mistake: The assistant said tests passed without a recorded tool result.
- Correction: Only claim verification when a run log or tool output exists.
-->
"""


class MistakesDocument(BaseModel):
    filename: str
    content: str
    updated_at: str


def mistakes_path() -> Path:
    return config_dir() / "MISTAKES.md"


def ensure_mistakes() -> None:
    path = mistakes_path()
    if not path.exists():
        path.write_text(DEFAULT_MISTAKES.rstrip() + "\n", encoding="utf-8")


def load_mistakes() -> MistakesDocument:
    ensure_mistakes()
    path = mistakes_path()
    stat = path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    return MistakesDocument(filename=path.name, content=path.read_text(encoding="utf-8"), updated_at=updated_at)


def save_mistakes(content: str) -> MistakesDocument:
    path = mistakes_path()
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return load_mistakes()


def mistakes_context() -> str:
    return load_mistakes().content
