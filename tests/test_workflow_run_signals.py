"""Tests for the workflow_run_signals table (pause/abort signalling)."""
from __future__ import annotations

import pytest


def _seed(db, run_id: str = "sig-1") -> str:
    chat = db.create_chat(title="t", workspace_path="")
    db.create_workflow_run(run_id, workflow_id="wf", chat_id=chat.id, mode="chat")
    return run_id


def test_request_pause_signal_returns_true_when_run_exists(db) -> None:
    run_id = _seed(db)
    assert db.request_workflow_run_signal(run_id, "pause") is True
    assert db.has_workflow_run_signal(run_id, "pause") is True


def test_request_signal_returns_false_when_run_missing(db) -> None:
    assert db.request_workflow_run_signal("ghost", "pause") is False
    assert db.has_workflow_run_signal("ghost", "pause") is False


def test_unsupported_signal_kind_raises(db) -> None:
    run_id = _seed(db)
    with pytest.raises(ValueError):
        db.request_workflow_run_signal(run_id, "bogus")


def test_clear_signal_removes_row_and_returns_count(db) -> None:
    run_id = _seed(db)
    db.request_workflow_run_signal(run_id, "pause")
    db.request_workflow_run_signal(run_id, "pause")  # duplicate requests are idempotent
    removed = db.clear_workflow_run_signal(run_id, "pause")
    assert removed == 1
    assert db.has_workflow_run_signal(run_id, "pause") is False


def test_pause_and_abort_signals_are_independent(db) -> None:
    run_id = _seed(db)
    db.request_workflow_run_signal(run_id, "pause")
    db.request_workflow_run_signal(run_id, "abort")
    assert db.has_workflow_run_signal(run_id, "pause") is True
    assert db.has_workflow_run_signal(run_id, "abort") is True
    db.clear_workflow_run_signal(run_id, "pause")
    assert db.has_workflow_run_signal(run_id, "abort") is True


def test_signals_cascade_when_run_is_deleted(db) -> None:
    chat = db.create_chat(title="t", workspace_path="")
    db.create_workflow_run("sig-cascade", workflow_id="wf", chat_id=chat.id, mode="chat")
    db.request_workflow_run_signal("sig-cascade", "pause")
    assert db.has_workflow_run_signal("sig-cascade", "pause") is True
    db.delete_chat(chat.id)
    assert db.has_workflow_run_signal("sig-cascade", "pause") is False
