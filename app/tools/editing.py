from __future__ import annotations

import difflib
import hashlib
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.tools.workspace import resolve_workspace_path, workspace_root


BACKUP_DIR = ".nixai-edit-backups"


def preview_edit_file(args: dict[str, Any], workspace_path: str = "") -> dict[str, Any]:
    target = _target_path(args, workspace_path)
    before = _read_existing_text(target)
    after = _content(args)
    before_sha256 = _sha256(before)
    after_sha256 = _sha256(after)
    relative = _relative(target, workspace_path)

    return {
        "success": True,
        "operation": "workspace_edit_file",
        "path": relative,
        "exists": target.exists(),
        "before_sha256": before_sha256,
        "after_sha256": after_sha256,
        "diff": _unified_diff(before, after, f"a/{relative}", f"b/{relative}"),
        "inverse_diff": _unified_diff(after, before, f"b/{relative}", f"a/{relative}"),
        "commit_arguments": {**args, "expected_sha256": before_sha256},
    }


def edit_file(args: dict[str, Any], workspace_path: str = "") -> dict[str, Any]:
    target = _target_path(args, workspace_path)
    before = _read_existing_text(target)
    expected = str(args.get("expected_sha256") or "")
    before_sha256 = _sha256(before)
    if expected and expected != before_sha256:
        raise ValueError("File changed after preview; refresh the diff before writing.")

    after = _content(args)
    relative = _relative(target, workspace_path)
    backup_path = _write_backup(target, before.encode("utf-8"), workspace_path) if target.exists() else ""
    _atomic_write_text(target, after)

    return {
        "success": True,
        "operation": "workspace_edit_file",
        "path": relative,
        "backup_path": backup_path,
        "before_sha256": before_sha256,
        "after_sha256": _sha256(after),
        "diff": _unified_diff(before, after, f"a/{relative}", f"b/{relative}"),
        "inverse_diff": _unified_diff(after, before, f"b/{relative}", f"a/{relative}"),
    }


def _target_path(args: dict[str, Any], workspace_path: str) -> Path:
    path = str(args.get("path") or "").strip()
    if not path:
        raise ValueError("Path is required.")
    target = resolve_workspace_path(path, workspace_path)
    if target.exists() and not target.is_file():
        raise ValueError(f"Path is not a file: {path}")
    if not target.parent.exists() or not target.parent.is_dir():
        raise ValueError(f"Parent directory does not exist: {path}")
    return target


def _content(args: dict[str, Any]) -> str:
    if "content" not in args:
        raise ValueError("Content is required.")
    content = args.get("content")
    if not isinstance(content, str):
        raise ValueError("Content must be a string.")
    return content


def _read_existing_text(path: Path) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Only UTF-8 text files can be edited.") from exc


def _atomic_write_text(path: Path, content: str) -> None:
    data = content.encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp_name).replace(path)
    except Exception:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass
        raise


def _write_backup(target: Path, data: bytes, workspace_path: str) -> str:
    root = workspace_root(workspace_path)
    backup_root = resolve_workspace_path(BACKUP_DIR, workspace_path)
    backup_root.mkdir(mode=0o700, exist_ok=True)
    stem = target.name.replace(os.sep, "_")
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    digest = hashlib.sha256(data).hexdigest()[:12]
    backup = backup_root / f"{stamp}-{digest}-{stem}.bak"
    fd, tmp_name = tempfile.mkstemp(prefix=".backup.", suffix=".tmp", dir=str(backup_root))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp_name).replace(backup)
    except Exception:
        try:
            Path(tmp_name).unlink()
        except FileNotFoundError:
            pass
        raise
    return str(backup.relative_to(root))


def _relative(path: Path, workspace_path: str) -> str:
    return str(path.relative_to(workspace_root(workspace_path)))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _unified_diff(before: str, after: str, fromfile: str, tofile: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )
