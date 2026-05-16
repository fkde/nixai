from __future__ import annotations

import json
import re
from typing import Any


def parse_json_object(content: object, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse a JSON object from raw model output.

    Models sometimes wrap JSON in Markdown fences or add a short preamble.
    Keep this parser conservative: return only JSON objects, otherwise the
    caller-provided fallback.
    """
    fallback_value = fallback if fallback is not None else {}
    clean = str(content or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?", "", clean, flags=re.IGNORECASE).strip()
        clean = re.sub(r"```$", "", clean).strip()

    parsed = _load_json_object(clean)
    if parsed is not None:
        return parsed

    match = re.search(r"\{[\s\S]*\}", clean)
    if not match:
        return fallback_value
    parsed = _load_json_object(match.group(0))
    return parsed if parsed is not None else fallback_value


def _load_json_object(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
