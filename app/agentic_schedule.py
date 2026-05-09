from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


def utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def compute_next_run(schedule: str, after: datetime | None = None) -> str:
    base = after or utc_now_dt()
    lower = schedule.strip().casefold()
    time_value = _extract_time(lower) or (9, 0)

    if lower.startswith("weekly"):
        candidate = _next_weekly(lower, time_value, base)
    elif lower.startswith("monthly"):
        candidate = _next_monthly(lower, time_value, base)
    else:
        candidate = _next_daily(time_value, base)
    return candidate.astimezone(timezone.utc).isoformat()


def is_due(next_run_at: str | None, now: datetime | None = None) -> bool:
    due_at = parse_iso(next_run_at)
    return due_at is None or due_at <= (now or utc_now_dt())


def _extract_time(value: str) -> tuple[int, int] | None:
    match = re.search(r"\b([01]?\d|2[0-3])(?::([0-5]\d))\b", value)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _next_daily(time_value: tuple[int, int], base: datetime) -> datetime:
    hour, minute = time_value
    candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= base:
        candidate += timedelta(days=1)
    return candidate


def _next_weekly(value: str, time_value: tuple[int, int], base: datetime) -> datetime:
    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    target = next((index for name, index in weekdays.items() if name in value), base.weekday())
    days = (target - base.weekday()) % 7
    hour, minute = time_value
    candidate_base = base + timedelta(days=days)
    candidate = candidate_base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= base:
        candidate += timedelta(days=7)
    return candidate


def _next_monthly(value: str, time_value: tuple[int, int], base: datetime) -> datetime:
    day_match = re.search(r"\bday\s+([1-9]|[12]\d|3[01])\b", value)
    day = int(day_match.group(1)) if day_match else 1
    hour, minute = time_value
    year = base.year
    month = base.month
    while True:
        max_day = _month_days(year, month)
        candidate = base.replace(
            year=year,
            month=month,
            day=min(day, max_day),
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if candidate > base:
            return candidate
        month += 1
        if month > 12:
            month = 1
            year += 1


def _month_days(year: int, month: int) -> int:
    if month == 12:
        next_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    current = datetime(year, month, 1, tzinfo=timezone.utc)
    return (next_month - current).days
