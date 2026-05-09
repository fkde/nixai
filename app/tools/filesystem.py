from __future__ import annotations

from pathlib import Path

from app.tools.workspace import resolve_workspace_path, workspace_root


IGNORED_DIRS = {".git", ".idea", "__pycache__", "node_modules", "vendor", ".venv", "venv"}
MAX_READ_BYTES = 250_000


def _relative(path: Path) -> str:
    return str(path.relative_to(workspace_root()))


def list_files(path: str = ".") -> list[str]:
    base = resolve_workspace_path(path)
    if not base.exists():
        return []
    if base.is_file():
        return [_relative(base)]

    files: list[str] = []
    for item in base.rglob("*"):
        if any(part in IGNORED_DIRS for part in item.parts):
            continue
        if item.is_file():
            files.append(_relative(item))
    return sorted(files)


def read_file(path: str) -> str:
    file_path = resolve_workspace_path(path)
    if not file_path.is_file():
        raise FileNotFoundError(path)
    data = file_path.read_bytes()
    if len(data) > MAX_READ_BYTES:
        raise ValueError(f"File is too large to read in POC mode: {path}")
    return data.decode("utf-8", errors="replace")


def search_files(query: str) -> list[str]:
    needle = query.casefold()
    matches: list[str] = []
    for path in list_files("."):
        if needle in path.casefold():
            matches.append(path)
            continue
        try:
            if needle in read_file(path).casefold():
                matches.append(path)
        except (OSError, UnicodeError, ValueError):
            continue
    return matches
