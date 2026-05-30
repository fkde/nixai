from __future__ import annotations

import subprocess

from app.tools.workspace import workspace_root


def _run_git(args: list[str], workspace_path: str = "") -> str:
    result = subprocess.run(
        ["git", *args], cwd=workspace_root(workspace_path), check=False, capture_output=True, text=True, timeout=30
    )
    output = (result.stdout + result.stderr).strip()
    return output


def git_status(workspace_path: str = "") -> str:
    return _run_git(["status", "--short"], workspace_path)


def git_diff(workspace_path: str = "") -> str:
    return _run_git(["diff", "--"], workspace_path)
