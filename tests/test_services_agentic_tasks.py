from __future__ import annotations

from app import database
from app.agentic_schedule import parse_iso, utc_now_dt
from app.services import AgenticTaskService


def _service() -> AgenticTaskService:
    return AgenticTaskService(max_failure_attempts=2)


def test_create_task_sets_next_run_at(db) -> None:
    service = _service()

    task = service.create_task(
        title="Daily ping",
        prompt="Send a notification",
        schedule="daily at 09:00",
    )

    assert task.next_run_at is not None
    assert parse_iso(task.next_run_at) is not None


def test_update_task_returns_none_for_missing(db) -> None:
    service = _service()

    result = service.update_task(
        "missing-id",
        title="x",
        prompt="y",
        schedule="daily at 09:00",
        status="active",
    )

    assert result is None


def test_record_run_result_success_recurring_clears_failures(db) -> None:
    service = _service()
    task = service.create_task(title="t", prompt="p", schedule="daily at 09:00")
    database.update_agentic_task_schedule_state(task.id, next_run_at=task.next_run_at, failure_count=1)
    reloaded = database.get_agentic_task(task.id)
    assert reloaded.failure_count == 1

    service.record_run_result(reloaded, status="success")

    after = database.get_agentic_task(task.id)
    assert after.failure_count == 0
    assert after.status == "active"
    assert after.next_run_at is not None


def test_record_run_result_failures_pause_after_max(db) -> None:
    service = _service()
    task = service.create_task(title="t", prompt="p", schedule="daily at 09:00")
    database.update_agentic_task_schedule_state(task.id, next_run_at=task.next_run_at, failure_count=1)
    reloaded = database.get_agentic_task(task.id)

    service.record_run_result(reloaded, status="needs_review")

    after = database.get_agentic_task(task.id)
    assert after.failure_count == 2
    assert after.status == "paused"


def test_record_run_result_one_shot_pauses_and_clears_next_run(db) -> None:
    service = _service()
    future = utc_now_dt().isoformat()
    task = service.create_task(title="t", prompt="p", schedule=f"once at {future}")

    service.record_run_result(task, status="success")

    after = database.get_agentic_task(task.id)
    assert after.status == "paused"
    assert after.next_run_at is None


def test_ensure_next_run_only_when_missing(db) -> None:
    service = _service()
    task = service.create_task(title="t", prompt="p", schedule="daily at 09:00")
    fixed = task.next_run_at

    same = service.ensure_next_run(task)
    assert same.next_run_at == fixed
