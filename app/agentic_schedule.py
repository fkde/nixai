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
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    lower = schedule.strip().casefold()
    once_at = parse_one_shot_schedule(schedule)
    if is_one_shot_schedule(schedule):
        return (once_at or base).astimezone(timezone.utc).isoformat()
    time_value = _extract_time(lower) or (9, 0)
    local_base = base.astimezone()

    if lower.startswith("weekly"):
        candidate = _next_weekly(lower, time_value, local_base)
    elif lower.startswith("monthly"):
        candidate = _next_monthly(lower, time_value, local_base)
    else:
        candidate = _next_daily(time_value, local_base)
    return candidate.astimezone(timezone.utc).isoformat()


def is_due(next_run_at: str | None, now: datetime | None = None) -> bool:
    due_at = parse_iso(next_run_at)
    return due_at is None or due_at <= (now or utc_now_dt())


def is_one_shot_schedule(schedule: str) -> bool:
    return schedule.strip().casefold().startswith("once at ")


def parse_one_shot_schedule(schedule: str) -> datetime | None:
    if not is_one_shot_schedule(schedule):
        return None
    value = schedule.strip()[len("once at ") :].strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc)


def normalize_one_shot_schedule(schedule: str) -> str:
    clean = schedule.strip()
    value = clean[len("once at ") :].strip() if is_one_shot_schedule(clean) else clean
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return clean
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return f"once at {parsed.isoformat()}"


def _extract_time(value: str) -> tuple[int, int] | None:
    match = re.search(r"\b([01]?\d|2[0-3])(?::([0-5]\d))\b", value)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _next_daily(time_value: tuple[int, int], base: datetime) -> datetime:
    hour, minute = time_value
    candidate = _local_candidate(base.year, base.month, base.day, hour, minute)
    if candidate <= base:
        tomorrow = base + timedelta(days=1)
        candidate = _local_candidate(tomorrow.year, tomorrow.month, tomorrow.day, hour, minute)
    return candidate


def _next_weekly(value: str, time_value: tuple[int, int], base: datetime) -> datetime:
    weekdays = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
    target = next((index for name, index in weekdays.items() if name in value), base.weekday())
    days = (target - base.weekday()) % 7
    hour, minute = time_value
    candidate_base = base + timedelta(days=days)
    candidate = _local_candidate(candidate_base.year, candidate_base.month, candidate_base.day, hour, minute)
    if candidate <= base:
        next_week = candidate_base + timedelta(days=7)
        candidate = _local_candidate(next_week.year, next_week.month, next_week.day, hour, minute)
    return candidate


def _next_monthly(value: str, time_value: tuple[int, int], base: datetime) -> datetime:
    day_match = re.search(r"\bday\s+([1-9]|[12]\d|3[01])\b", value)
    day = int(day_match.group(1)) if day_match else 1
    hour, minute = time_value
    year = base.year
    month = base.month
    while True:
        max_day = _month_days(year, month)
        candidate = _local_candidate(year, month, min(day, max_day), hour, minute)
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


def _local_candidate(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, second=0, microsecond=0).astimezone()
