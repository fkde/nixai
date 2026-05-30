from __future__ import annotations

import shlex
import subprocess

from app.tools.workspace import workspace_root


ALLOWED_COMMANDS: dict[tuple[str, ...], list[str]] = {
    ("git", "status"): ["git", "status"],
    ("git", "diff"): ["git", "diff", "--"],
    ("composer", "test"): ["composer", "test"],
    ("composer", "phpunit"): ["composer", "phpunit"],
    ("vendor/bin/phpunit",): ["vendor/bin/phpunit"],
    ("npm", "test"): ["npm", "test"],
    ("npm", "run", "build"): ["npm", "run", "build"],
}


def run_command(command: str) -> str:
    parts = tuple(shlex.split(command))
    if parts not in ALLOWED_COMMANDS:
        allowed = ", ".join(" ".join(cmd) for cmd in ALLOWED_COMMANDS)
        raise ValueError(f"Command not allowed. Allowed commands: {allowed}")

    result = subprocess.run(
        ALLOWED_COMMANDS[parts], cwd=workspace_root(), check=False, capture_output=True, text=True, timeout=120
    )
    return (result.stdout + result.stderr).strip()
