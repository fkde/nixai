from __future__ import annotations

from pathlib import Path

from app.config import load_settings


class WorkspaceError(ValueError):
    pass


def workspace_root() -> Path:
    root = Path(load_settings().workspace_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise WorkspaceError(f"Workspace does not exist or is not a directory: {root}")
    return root


def resolve_workspace_path(path: str = ".") -> Path:
    root = workspace_root()
    candidate = (root / path).expanduser().resolve()
    if candidate != root and root not in candidate.parents:
        raise WorkspaceError("Path escapes configured workspace")
    return candidate
