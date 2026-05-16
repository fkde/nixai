from __future__ import annotations

import pytest

from app.json_utils import parse_json_object, parse_json_object_strict


def test_parse_json_object_accepts_plain_json() -> None:
    assert parse_json_object('{"action": "run", "ok": true}') == {"action": "run", "ok": True}


def test_parse_json_object_accepts_markdown_fence() -> None:
    content = """```json
{"status": "done", "count": 2}
```"""

    assert parse_json_object(content) == {"status": "done", "count": 2}


def test_parse_json_object_extracts_object_from_text() -> None:
    content = 'Sure: {"reason": "fallback", "items": []} done.'

    assert parse_json_object(content) == {"reason": "fallback", "items": []}


def test_parse_json_object_returns_fallback_for_non_object() -> None:
    fallback = {"status": "fallback"}

    assert parse_json_object("[1, 2, 3]", fallback=fallback) == fallback
    assert parse_json_object("no json here", fallback=fallback) == fallback


def test_parse_json_object_strict_accepts_fenced_object() -> None:
    assert parse_json_object_strict('```json\n{"ok": true}\n```') == {"ok": True}


def test_parse_json_object_strict_raises_when_no_object() -> None:
    with pytest.raises(ValueError, match="not contain"):
        parse_json_object_strict("no json here")


def test_parse_json_object_strict_raises_when_not_object() -> None:
    with pytest.raises(ValueError, match="not an object"):
        parse_json_object_strict("[1, 2, 3]")


def test_parse_json_object_strict_uses_custom_error_factory() -> None:
    class _Boom(RuntimeError):
        pass

    with pytest.raises(_Boom, match="custom"):
        parse_json_object_strict(
            "still no json",
            error_factory=_Boom,
            not_found_message="custom not found",
        )
