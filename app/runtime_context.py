from __future__ import annotations

import locale
import os
import platform
from datetime import datetime, timezone


def local_now() -> datetime:
    return datetime.now().astimezone()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def runtime_meta_context(user_message: str = "") -> str:
    local_dt = local_now()
    utc_dt = utc_now()
    locale_name = locale.getlocale()[0] or os.environ.get("LANG", "").split(".")[0]
    message_hint = "infer from latest user message"
    if user_message.strip():
        message_hint = "match the latest user message unless the user explicitly asks for another language"

    return "\n".join(
        [
            "Runtime meta context:",
            f"- Current local datetime: {local_dt.isoformat()}",
            f"- Current UTC datetime: {utc_dt.isoformat()}",
            f"- Local timezone: {_timezone_label(local_dt)}",
            f"- System locale: {locale_name or 'unknown'}",
            "- UI language: English",
            f"- User-facing response language: {message_hint}.",
            "- Interpret relative dates and clock-only times in the local timezone above unless the user specifies another timezone.",
            "- For user-facing schedules, preserve the user's local wall-clock time and include the local timezone offset.",
            f"- Platform: {platform.system() or 'unknown'}",
        ]
    )


def _timezone_label(local_dt: datetime) -> str:
    env_tz = os.environ.get("TZ", "").strip()
    offset = local_dt.strftime("%z")
    offset = f"{offset[:3]}:{offset[3:]}" if offset else "unknown"
    name = local_dt.tzname() or "local"
    if env_tz:
        return f"{env_tz} ({name}, UTC{offset})"
    return f"{name} (UTC{offset})"
