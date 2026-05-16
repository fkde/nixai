"""Shared input validators.

Centralised so API models, settings, and workflow definitions reject the
same malformed input the same way. Keep these functions pure: take raw
input, return a normalised value, or raise ``ValueError``.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse


MAX_TITLE_LENGTH = 200
MAX_NAME_LENGTH = 120
MAX_DESCRIPTION_LENGTH = 1000
MAX_PROMPT_LENGTH = 20000
MAX_SCHEDULE_LENGTH = 200
MAX_URL_LENGTH = 500
MAX_PATH_LENGTH = 1024

_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(value: object, *, max_length: int, field_name: str = "value") -> str:
    """Strip control chars, collapse whitespace, enforce length."""
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n")
    text = _CONTROL_CHARS_RE.sub("", text)
    text = text.strip()
    if len(text) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters")
    return text


def clean_single_line(value: object, *, max_length: int, field_name: str = "value") -> str:
    """Like ``clean_text`` but also rejects line breaks."""
    text = clean_text(value, max_length=max_length, field_name=field_name)
    return " ".join(text.split())


def validate_slug(value: object, *, field_name: str = "id") -> str:
    """Identifier safe for use in filenames and URL paths (preserves case)."""
    text = clean_single_line(value, max_length=80, field_name=field_name)
    if not text:
        raise ValueError(f"{field_name} is required")
    if not _SLUG_RE.match(text):
        raise ValueError(
            f"{field_name} must start with a letter or digit and contain only "
            "letters, digits, '-', or '_' (max 80 chars)"
        )
    return text


def validate_workspace_path(value: object, *, field_name: str = "workspace_path") -> str:
    """Reject empty paths and obvious traversal attempts."""
    if value is None:
        return ""
    text = clean_single_line(value, max_length=MAX_PATH_LENGTH, field_name=field_name)
    if not text:
        return ""
    if "\x00" in text:
        raise ValueError(f"{field_name} contains a null byte")
    try:
        path = Path(text).expanduser()
    except (OSError, ValueError) as exc:
        raise ValueError(f"{field_name} is not a valid filesystem path") from exc
    if ".." in path.parts:
        raise ValueError(f"{field_name} must not contain '..' segments")
    return str(path)


def validate_http_url(value: object, *, field_name: str = "url") -> str:
    """Restrict URLs to http(s) so we never call mailto:/file:/javascript: targets."""
    text = clean_single_line(value, max_length=MAX_URL_LENGTH, field_name=field_name)
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{field_name} must use http or https")
    if not parsed.netloc:
        raise ValueError(f"{field_name} must include a host")
    return text


__all__ = [
    "MAX_DESCRIPTION_LENGTH",
    "MAX_NAME_LENGTH",
    "MAX_PATH_LENGTH",
    "MAX_PROMPT_LENGTH",
    "MAX_SCHEDULE_LENGTH",
    "MAX_TITLE_LENGTH",
    "MAX_URL_LENGTH",
    "clean_single_line",
    "clean_text",
    "validate_http_url",
    "validate_slug",
    "validate_workspace_path",
]
