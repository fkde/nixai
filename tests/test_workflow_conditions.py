from __future__ import annotations

from app.workflows.conditions import WorkflowConditionEvaluator


def test_allowed_decision_conditions_match_state() -> None:
    evaluator = WorkflowConditionEvaluator()
    state = {"decision": {"status": "Retry"}}

    assert evaluator.matches("decision.status == 'retry'", state) is True
    assert evaluator.matches("decision.status == 'done'", state) is False


def test_allowed_review_conditions_match_state() -> None:
    evaluator = WorkflowConditionEvaluator()
    state = {"review": {"status": "approved"}}

    assert evaluator.matches("review.status == 'approved'", state) is True
    assert evaluator.matches("review.status == 'changes_requested'", state) is False


def test_empty_condition_is_true() -> None:
    evaluator = WorkflowConditionEvaluator()

    assert evaluator.matches("", {}) is True
    assert evaluator.matches(None, {}) is True


def test_dynamic_paths_and_logical_conditions_match_state() -> None:
    evaluator = WorkflowConditionEvaluator()
    state = {
        "plan": {"confidence": 0.7, "work_items": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]},
        "worker_reports": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}],
        "review": {"status": "approved"},
    }

    assert evaluator.matches("worker_reports.length > 3 && plan.confidence < 0.8", state) is True
    assert evaluator.matches("plan.work_items.0.id == 'a'", state) is True
    assert evaluator.matches("review.status == 'approved' || worker_reports.length > 10", state) is True
    assert evaluator.matches("!(worker_reports.length < 4)", state) is True


def test_boolean_and_null_literals_match_state() -> None:
    evaluator = WorkflowConditionEvaluator()
    state = {"gate": {"ready": True, "blocked": False, "value": None}}

    assert evaluator.matches("gate.ready == true && gate.blocked == false", state) is True
    assert evaluator.matches("gate.value == null", state) is True


def test_unknown_missing_or_unparseable_condition_is_false() -> None:
    evaluator = WorkflowConditionEvaluator()
    state = {"decision": {"status": "retry"}}

    assert evaluator.matches("decision.reason == 'retry'", state) is False
    assert evaluator.matches("decision.status != 'done'", state) is True
    assert evaluator.matches("__import__('os').system('echo nope')", state) is False
    assert evaluator.matches("worker_reports.length > 0", state) is False
