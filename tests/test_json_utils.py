from __future__ import annotations

from app.json_utils import parse_json_object


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
