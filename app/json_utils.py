from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any


def parse_json_object(content: object, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    """Parse a JSON object from raw model output.

    Models sometimes wrap JSON in Markdown fences or add a short preamble.
    Keep this parser conservative: return only JSON objects, otherwise the
    caller-provided fallback.
    """
    fallback_value = fallback if fallback is not None else {}
    parsed = _try_parse_json_object(content)
    return parsed if parsed is not None else fallback_value


def parse_json_object_strict(
    content: object,
    *,
    error_factory: Callable[[str], BaseException] | None = None,
    not_found_message: str = "Response did not contain JSON.",
    not_object_message: str = "Response JSON was not an object.",
) -> dict[str, Any]:
    """Parse a JSON object from raw model output, raising on failure.

    Used by call sites that previously implemented private ``_parse_json``
    helpers with custom error types/messages. ``error_factory`` builds the
    raised exception (defaults to ``ValueError``).
    """
    factory = error_factory or ValueError
    clean = _strip_fences(str(content or "").strip())

    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", clean)
        if not match:
            raise factory(not_found_message) from None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise factory(not_found_message) from exc

    if not isinstance(parsed, dict):
        raise factory(not_object_message)
    return parsed


def _try_parse_json_object(content: object) -> dict[str, Any] | None:
    clean = _strip_fences(str(content or "").strip())
    parsed = _load_json_object(clean)
    if parsed is not None:
        return parsed
    match = re.search(r"\{[\s\S]*\}", clean)
    if not match:
        return None
    return _load_json_object(match.group(0))


def _strip_fences(clean: str) -> str:
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?", "", clean, flags=re.IGNORECASE).strip()
        clean = re.sub(r"```$", "", clean).strip()
    return clean


def _load_json_object(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
