from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.config import config_dir
from app.runtime_context import local_now


MAX_SCRATCH_CHARS = 120_000


def new_workflow_run_id() -> str:
    stamp = local_now().strftime("%H%M%S")
    return f"{stamp}-{uuid4().hex[:8]}"


def workflow_scratch_path() -> Path:
    date = local_now().date().isoformat()
    return config_dir() / f"WORKFLOW_{date}.md"


def append_workflow_note(run_id: str, title: str, body: str = "") -> Path:
    path = workflow_scratch_path()
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


def read_workflow_notes(run_id: str = "", max_chars: int = 24_000) -> str:
    path = workflow_scratch_path()
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
