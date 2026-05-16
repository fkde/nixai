from __future__ import annotations

import pytest

from app.validation import clean_single_line, clean_text, validate_http_url, validate_slug, validate_workspace_path


def test_clean_text_strips_control_chars_and_enforces_length() -> None:
    assert clean_text(" \x00hello\x07\nworld  ", max_length=20, field_name="body") == "hello\nworld"

    with pytest.raises(ValueError, match="body must be at most 3 characters"):
        clean_text("toolong", max_length=3, field_name="body")


def test_clean_single_line_collapses_whitespace() -> None:
    assert clean_single_line(" hello\n  local\tagent ", max_length=40) == "hello local agent"


def test_validate_slug_rejects_unsafe_names() -> None:
    assert validate_slug("Task_1-ok") == "Task_1-ok"

    for value in ["", "../x", "-starts-with-dash", "has space"]:
        with pytest.raises(ValueError):
            validate_slug(value)


def test_validate_workspace_path_rejects_traversal() -> None:
    assert validate_workspace_path("~/project").endswith("project")

    with pytest.raises(ValueError, match="must not contain '..'"):
        validate_workspace_path("../secret")


def test_validate_http_url_allows_only_http_hosts() -> None:
    assert validate_http_url("https://example.com/path") == "https://example.com/path"

    for value in ["ftp://example.com", "file:///tmp/x", "https:///missing-host"]:
        with pytest.raises(ValueError):
            validate_http_url(value)
