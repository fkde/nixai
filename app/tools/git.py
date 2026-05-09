from __future__ import annotations

import subprocess

from app.tools.workspace import workspace_root


def _run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=workspace_root(),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = (result.stdout + result.stderr).strip()
    return output


def git_status() -> str:
    return _run_git(["status", "--short"])


def git_diff() -> str:
    return _run_git(["diff", "--"])
