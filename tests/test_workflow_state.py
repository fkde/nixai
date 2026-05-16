from __future__ import annotations

from app.config import Settings
from app.workflows.state import (
    compact_workflow_reports,
    compact_workflow_rounds,
    compact_workflow_state,
    final_answer_payload,
    initial_workflow_state,
    record_workflow_round,
    workflow_state_payload,
)


def test_initial_workflow_state_collects_history_and_code_context(db, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "main.py").write_text("print('ok')\n", encoding="utf-8")
    chat = db.create_chat("Workflow", workspace_path=str(workspace))
    db.add_message(chat.id, "user", "Hello", mode="code")
    db.add_message(chat.id, "assistant", "Hi", mode="code")

    state = initial_workflow_state(Settings(effort="minimum"), chat.id, "Projekt struktur", "code")

    assert state["chat_id"] == chat.id
    assert state["mode"] == "code"
    assert state["workspace"] == str(workspace)
    assert state["history"] == [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}]
    assert "main.py" in state["code_context"]


def test_workflow_payloads_compact_context_and_rounds() -> None:
    state = {
        "mode": "code",
        "effort": "medium",
        "user_message": "Do work",
        "workspace": "/tmp/project",
        "history": [],
        "workflow_rounds": [],
        "worker_reports": [{"id": "w1", "title": "Worker", "content": "x" * 5000}],
        "code_context": "code" * 5000,
        "agentic_context": "tools" * 5000,
        "workflow_run_id": "missing",
        "final_answer_streamed": True,
    }
    state["iteration"] = 1
    state["plan"] = {"summary": "Plan"}
    record_workflow_round(state, state["worker_reports"], {"status": "approved"}, {"status": "done"})

    payload = workflow_state_payload(state)
    final_payload = final_answer_payload(state)
    compact = compact_workflow_state(state)

    assert len(payload["code_context"]) == 12000
    assert len(payload["agentic_context"]) == 16000
    assert "code_context" not in final_payload
    assert len(final_payload["worker_reports"][0]["content"]) == 1800
    assert compact["code_context"] == "[omitted]"
    assert compact["agentic_context"] == "[omitted]"
    assert compact["answer_streamed"] is True


def test_compact_workflow_helpers_ignore_bad_items() -> None:
    reports = compact_workflow_reports([{"id": "ok", "title": "Title", "content": "abc"}, "bad"])
    rounds = compact_workflow_rounds([{"iteration": 1, "plan": {"summary": "S"}, "worker_reports": reports}, "bad"])

    assert reports == [{"id": "ok", "title": "Title", "content": "abc"}]
    assert rounds[0]["plan_summary"] == "S"
