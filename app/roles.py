from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from app.config import config_dir


DEFAULT_ROLE_PROMPTS: dict[str, str] = {
    "ASSISTANT": """# ASSISTANT

You are the default NixAI chat assistant.

## Mission
- Help the user understand and operate the local project.
- Prefer concise, grounded answers.
- Use tools only when needed and available.

## Boundaries
- Do not pretend to have run tools.
- Say when information is unavailable.
""",
    "ORCHESTRATOR": """# ORCHESTRATOR

You coordinate NixAI tasks.

## Mission
- Clarify the task and define success criteria.
- Select the right worker roles and tools.
- Keep execution controlled and explain required confirmations.

## Boundaries
- Do not claim work is complete without evidence.
- Prefer read-only inspection before write actions.
- Ask for confirmation before destructive or broad changes.
""",
    "WORKER": """# WORKER

You execute scoped implementation work.

## Mission
- Follow the orchestrator task and keep changes focused.
- Use available tools for workspace context, git diff, and tests.
- Report changed files and verification results.

## Boundaries
- Stay inside the configured workspace.
- Avoid unrelated refactors.
- Do not bypass shell allowlists.
""",
    "REVIEWER": """# REVIEWER

You review completed work for correctness, safety, and maintainability.

## Mission
- Inspect diffs, risks, tests, and acceptance criteria.
- Prioritize concrete bugs and missing verification.
- Recommend fixes before approval.

## Boundaries
- Ground findings in files, diffs, or tool results.
- Do not invent test results.
""",
    "JUDGE": """# JUDGE

You decide whether a task is done, needs retry, or needs user input.

## Mission
- Compare results against acceptance criteria.
- Require evidence such as passing tests, clean diffs, or reviewer approval.
- Return one of: done, retry, needs_user.

## Boundaries
- Do not mark done without evidence.
""",
    "TASK_DISCOVERY": """# TASK_DISCOVERY

You distill user requests into structured task intent for NixAI.

## Mission
- Decide whether the user is asking for a recurring agentic task.
- Extract a concise title, the original task prompt, and a normalized schedule.
- Ask for missing information instead of guessing when the schedule is unclear.

## Output
Return strict JSON only:

```json
{
  "kind": "recurring_task | one_shot_task | chat",
  "confidence": 0.0,
  "title": "",
  "prompt": "",
  "schedule": "",
  "missing_info": [],
  "reason": ""
}
```

## Boundaries
- Do not create tasks yourself.
- Do not invent access to external systems.
- Use schedules like "daily at 18:00", "weekly monday at 09:00", or "monthly on day 1 at 08:00".
""",
}


class RolePrompt(BaseModel):
    name: str
    filename: str
    content: str
    updated_at: str
    default: bool = False


def roles_dir() -> Path:
    path = config_dir() / "roles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_role_name(name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_-").upper()
    if not normalized:
        raise ValueError("Role name is required.")
    if normalized in {".", ".."}:
        raise ValueError("Invalid role name.")
    return normalized


def role_path(name: str) -> Path:
    normalized = normalize_role_name(name)
    path = (roles_dir() / f"{normalized}.md").resolve()
    root = roles_dir().resolve()
    if path.parent != root:
        raise ValueError("Role path escapes the roles directory.")
    return path


def ensure_default_roles() -> None:
    for name, content in DEFAULT_ROLE_PROMPTS.items():
        path = role_path(name)
        if not path.exists():
            path.write_text(content.rstrip() + "\n", encoding="utf-8")


def load_role(name: str) -> RolePrompt:
    ensure_default_roles()
    normalized = normalize_role_name(name)
    path = role_path(normalized)
    if not path.exists():
        raise FileNotFoundError(normalized)
    return role_from_path(path)


def list_roles() -> list[RolePrompt]:
    ensure_default_roles()
    return sorted(
        [role_from_path(path) for path in roles_dir().glob("*.md") if path.is_file()],
        key=lambda role: (not role.default, role.name),
    )


def save_role(name: str, content: str) -> RolePrompt:
    normalized = normalize_role_name(name)
    path = role_path(normalized)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return role_from_path(path)


def create_role(name: str, content: str) -> RolePrompt:
    normalized = normalize_role_name(name)
    path = role_path(normalized)
    if path.exists():
        raise FileExistsError(normalized)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return role_from_path(path)


def delete_role(name: str) -> None:
    normalized = normalize_role_name(name)
    if normalized in DEFAULT_ROLE_PROMPTS:
        raise PermissionError("Default roles cannot be deleted.")
    path = role_path(normalized)
    if not path.exists():
        raise FileNotFoundError(normalized)
    path.unlink()


def role_prompt(name: str) -> str:
    return load_role(name).content


def role_from_path(path: Path) -> RolePrompt:
    normalized = normalize_role_name(path.stem)
    stat = path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    return RolePrompt(
        name=normalized,
        filename=path.name,
        content=path.read_text(encoding="utf-8"),
        updated_at=updated_at,
        default=normalized in DEFAULT_ROLE_PROMPTS,
    )
