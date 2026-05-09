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


class MistakeEntry(BaseModel):
    id: str
    title: str
    timestamp: str
    content: str


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


def append_mistake_entry(entry: str) -> MistakesDocument:
    document = load_mistakes()
    content = document.content.rstrip()
    return save_mistakes(f"{content}\n\n{entry.strip()}\n")


def list_mistake_entries() -> list[MistakeEntry]:
    content = load_mistakes().content
    entries: list[MistakeEntry] = []
    current_title = ""
    current_timestamp = ""
    current_lines: list[str] = []
    current_id = 0

    for line in content.splitlines():
        if line.startswith("### "):
            if current_lines:
                entries.append(
                    MistakeEntry(
                        id=str(current_id),
                        title=current_title,
                        timestamp=current_timestamp,
                        content="\n".join(current_lines).strip(),
                    )
                )
            current_id += 1
            heading = line[4:].strip()
            timestamp, title = _split_heading(heading)
            current_timestamp = timestamp
            current_title = title
            current_lines = [line]
        elif current_lines:
            current_lines.append(line)

    if current_lines:
        entries.append(
            MistakeEntry(
                id=str(current_id),
                title=current_title,
                timestamp=current_timestamp,
                content="\n".join(current_lines).strip(),
            )
        )
    return entries


def get_mistake_entry(entry_id: str) -> MistakeEntry | None:
    for entry in list_mistake_entries():
        if entry.id == entry_id:
            return entry
    return None


def _split_heading(heading: str) -> tuple[str, str]:
    if " - " not in heading:
        return "", heading
    timestamp, title = heading.split(" - ", 1)
    return timestamp.strip(), title.strip()
