from __future__ import annotations

from typing import Any

import platform
import subprocess


MAX_TITLE_CHARS = 80
MAX_MESSAGE_CHARS = 240


def notify_desktop(title: str, message: str, subtitle: str = "") -> dict[str, Any]:
    clean_title = _clean(title, MAX_TITLE_CHARS) or "NixAI"
    clean_message = _clean(message, MAX_MESSAGE_CHARS)
    clean_subtitle = _clean(subtitle, MAX_TITLE_CHARS)
    if not clean_message:
        raise ValueError("Notification message is required.")

    system = platform.system().lower()
    if system != "darwin":
        raise ValueError("Desktop notifications are currently implemented for macOS only.")

    script = 'display notification "{message}" with title "{title}"'.format(
        message=_escape_osascript(clean_message),
        title=_escape_osascript(clean_title),
    )
    if clean_subtitle:
        script += ' subtitle "{subtitle}"'.format(subtitle=_escape_osascript(clean_subtitle))

    subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True, timeout=10)
    return {"success": True, "title": clean_title, "message": clean_message, "subtitle": clean_subtitle}


def _clean(value: str, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _escape_osascript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
