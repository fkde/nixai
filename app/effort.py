from __future__ import annotations


EFFORT_LEVELS = ("minimum", "medium", "high", "max")

EFFORT_ALIASES = {
    "min": "minimum",
    "minimal": "minimum",
    "low": "minimum",
    "normal": "medium",
    "default": "medium",
    "med": "medium",
    "maximum": "max",
    "deep": "max",
}


def normalize_effort(value: str | None) -> str:
    clean = str(value or "").strip().casefold()
    clean = EFFORT_ALIASES.get(clean, clean)
    return clean if clean in EFFORT_LEVELS else "medium"


def effort_label(value: str | None) -> str:
    return {"minimum": "Minimum", "medium": "Medium", "high": "High", "max": "Max"}[normalize_effort(value)]


def effort_context(value: str | None) -> str:
    effort = normalize_effort(value)
    rules = {
        "minimum": [
            "Prefer the shortest reliable path.",
            "Do not broaden the task beyond the user's wording.",
            "Use tools only when the answer would otherwise be clearly unreliable.",
            "Keep final answers compact and skip optional alternatives unless they are essential.",
        ],
        "medium": [
            "Use balanced reasoning and practical verification.",
            "Gather tool or workspace evidence when it materially improves accuracy.",
            "Mention uncertainty and important tradeoffs without over-expanding the answer.",
            "Keep final answers concise but complete enough to be useful.",
        ],
        "high": [
            "Reason through edge cases, alternatives, and failure modes before finalizing.",
            "Use available tools proactively for current facts, workspace evidence, or verification.",
            "Cross-check important claims when practical and call out remaining uncertainty.",
            "Provide a structured answer when it helps the user act on the result.",
        ],
        "max": [
            "Run the deepest useful analysis within the available workflow and tool limits.",
            "Actively gather evidence, compare sources or files, and verify assumptions when tools are available.",
            "Break complex work into independent subtasks where the active workflow supports it.",
            "Be explicit about evidence quality, missing access, and residual risks.",
            "Still keep the final answer user-facing and avoid exposing internal deliberation.",
        ],
    }[effort]
    return "\n".join(
        [
            "Effort instructions:",
            f"- Effort level: {effort_label(effort)}",
            *[f"- {rule}" for rule in rules],
            "- For simple reminders or direct confirmations, do exactly the requested action and do not add unnecessary analysis.",
        ]
    )


def effort_max_items(configured_limit: int, value: str | None) -> int:
    configured = max(1, int(configured_limit or 1))
    effort = normalize_effort(value)
    if effort == "minimum":
        return 1
    if effort == "medium":
        return min(configured, 2)
    if effort == "high":
        return configured
    return min(6, max(configured, 4))


def effort_max_parallel(configured_limit: int, value: str | None) -> int:
    configured = max(1, int(configured_limit or 1))
    effort = normalize_effort(value)
    if effort == "minimum":
        return 1
    if effort == "medium":
        return min(configured, 2)
    if effort == "high":
        return configured
    return min(4, max(configured, 3))


def effort_tool_steps(value: str | None) -> int:
    return {"minimum": 1, "medium": 2, "high": 3, "max": 4}[normalize_effort(value)]


def effort_tool_calls(value: str | None) -> int:
    return {"minimum": 2, "medium": 3, "high": 4, "max": 5}[normalize_effort(value)]
