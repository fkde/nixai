from __future__ import annotations

from datetime import datetime, timezone

from app.agentic_schedule import compute_next_run, is_due, normalize_one_shot_schedule, parse_iso, parse_one_shot_schedule


def test_parse_iso_normalizes_to_utc() -> None:
    assert parse_iso("2026-05-16T12:00:00+02:00") == datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc)
    assert parse_iso("2026-05-16T12:00:00") == datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    assert parse_iso("not-a-date") is None


def test_compute_next_run_for_daily_weekly_and_monthly(utc_local_timezone) -> None:
    base = datetime(2026, 5, 16, 8, 0, tzinfo=timezone.utc)

    assert compute_next_run("daily at 09:30", base) == "2026-05-16T09:30:00+00:00"
    assert compute_next_run("daily at 07:30", base) == "2026-05-17T07:30:00+00:00"
    assert compute_next_run("weekly monday at 06:15", base) == "2026-05-18T06:15:00+00:00"
    assert compute_next_run("monthly day 31 at 10:00", datetime(2026, 1, 31, 11, 0, tzinfo=timezone.utc)) == (
        "2026-02-28T10:00:00+00:00"
    )


def test_one_shot_schedules_round_trip_to_utc() -> None:
    schedule = "once at 2026-05-16T12:00:00+02:00"

    assert parse_one_shot_schedule(schedule) == datetime(2026, 5, 16, 10, 0, tzinfo=timezone.utc)
    assert compute_next_run(schedule, datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc)) == (
        "2026-05-16T10:00:00+00:00"
    )
    assert normalize_one_shot_schedule("2026-05-16T12:00:00+02:00") == "once at 2026-05-16T12:00:00+02:00"


def test_is_due_treats_missing_or_past_as_due() -> None:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)

    assert is_due(None, now)
    assert is_due("2026-05-16T11:59:00+00:00", now)
    assert not is_due("2026-05-16T12:01:00+00:00", now)
