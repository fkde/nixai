"""Prompt composition helpers.

Small composer for the repeating role + runtime-meta + effort + (optional)
memory blocks. The intent is to reduce copy/paste in ``context_builder``,
``agentic_runner``, ``task_discovery`` and similar callers without changing
the rendered prompt text.
"""

from __future__ import annotations

from app.effort import effort_context
from app.memory import memory_context
from app.roles import role_prompt
from app.runtime_context import runtime_meta_context


def compose_role_block(
    role: str, *, language_source: str = "", effort: str = "medium", include_memory: bool = False
) -> str:
    """Return the standard ``role + runtime + effort [+ memory]`` system block.

    The block is the prefix used by chat, code, agentic, and scheduled-task
    prompts. Returning a single string keeps callers free to append their
    mode-specific instructions.
    """
    parts = [role_prompt(role), runtime_meta_context(language_source), effort_context(effort)]
    if include_memory:
        parts.append("Shared reviewed memory:\n" + memory_context())
    return "\n\n".join(part for part in parts if part)
