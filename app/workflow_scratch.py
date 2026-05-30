from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.config import config_dir
from app.runtime_meta import local_now


MAX_SCRATCH_CHARS = 120_000


class WorkflowScratchpad(Protocol):
    def new_run_id(self) -> str: ...

    def path(self) -> Path: ...

    def append_note(self, run_id: str, title: str, body: str = "") -> Path: ...

    def read_notes(self, run_id: str = "", max_chars: int = 24_000) -> str: ...


class FileWorkflowScratchpad:
    def new_run_id(self) -> str:
        return _new_workflow_run_id()

    def path(self) -> Path:
        return _workflow_scratch_path()

    def append_note(self, run_id: str, title: str, body: str = "") -> Path:
        return _append_workflow_note(run_id, title, body)

    def read_notes(self, run_id: str = "", max_chars: int = 24_000) -> str:
        return _read_workflow_notes(run_id, max_chars=max_chars)


class InMemoryWorkflowScratchpad:
    def __init__(self, scratch_path: Path | None = None) -> None:
        self._path = scratch_path or Path("/memory/WORKFLOW.md")
        self.notes: list[tuple[str, str, str, str]] = []

    def new_run_id(self) -> str:
        return _new_workflow_run_id()

    def path(self) -> Path:
        return self._path

    def append_note(self, run_id: str, title: str, body: str = "") -> Path:
        timestamp = local_now().isoformat(timespec="seconds")
        safe_title = " ".join(str(title or "Workflow note").split())[:160]
        self.notes.append((timestamp, str(run_id), safe_title, str(body or "").strip()))
        return self._path

    def read_notes(self, run_id: str = "", max_chars: int = 24_000) -> str:
        blocks = []
        for timestamp, note_run_id, title, body in self.notes:
            if run_id and note_run_id != run_id:
                continue
            block = [f"## {timestamp} [{note_run_id}] {title}"]
            if body:
                block.extend(["", body])
            blocks.append("\n".join(block))
        return "\n\n".join(blocks)[-max_chars:]


default_workflow_scratchpad = FileWorkflowScratchpad()


def _new_workflow_run_id() -> str:
    stamp = local_now().strftime("%H%M%S")
    return f"{stamp}-{uuid4().hex[:8]}"


def _workflow_scratch_path() -> Path:
    date = local_now().date().isoformat()
    return config_dir() / f"WORKFLOW_{date}.md"


def _append_workflow_note(run_id: str, title: str, body: str = "") -> Path:
    path = _workflow_scratch_path()
    if not path.exists():
        path.write_text(f"# Workflow Scratchpad {local_now().date().isoformat()}\n\n", encoding="utf-8")

    timestamp = local_now().isoformat(timespec="seconds")
    safe_title = " ".join(str(title or "Workflow note").split())[:160]
    content = str(body or "").strip()
    block = [f"## {timestamp} [{run_id}] {safe_title}"]
    if content:
        block.extend(["", content])
    block.append("")

    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(block))
        handle.write("\n")
    _trim_scratch_file(path)
    return path


def _read_workflow_notes(run_id: str = "", max_chars: int = 24_000) -> str:
    path = _workflow_scratch_path()
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    if run_id:
        chunks = []
        current: list[str] = []
        include = False
        for line in text.splitlines():
            if line.startswith("## "):
                if include and current:
                    chunks.append("\n".join(current))
                current = [line]
                include = f"[{run_id}]" in line
            elif current:
                current.append(line)
        if include and current:
            chunks.append("\n".join(current))
        text = "\n\n".join(chunks)
    return text[-max_chars:]


def new_workflow_run_id() -> str:
    return default_workflow_scratchpad.new_run_id()


def workflow_scratch_path() -> Path:
    return default_workflow_scratchpad.path()


def append_workflow_note(run_id: str, title: str, body: str = "") -> Path:
    return default_workflow_scratchpad.append_note(run_id, title, body)


def read_workflow_notes(run_id: str = "", max_chars: int = 24_000) -> str:
    return default_workflow_scratchpad.read_notes(run_id, max_chars=max_chars)


def _trim_scratch_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if len(text) <= MAX_SCRATCH_CHARS:
        return
    marker = "\n## "
    trimmed = text[-MAX_SCRATCH_CHARS:]
    marker_index = trimmed.find(marker)
    if marker_index > 0:
        trimmed = trimmed[marker_index + 1 :]
    header = f"# Workflow Scratchpad {local_now().date().isoformat()}\n\n"
    path.write_text(header + trimmed, encoding="utf-8")
