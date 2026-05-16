from __future__ import annotations

from app.workflows.prompts import (
    build_final_answer_prompt,
    build_judge_prompt,
    build_plan_prompt,
    build_retry_plan_prompt,
    build_review_prompt,
    build_worker_prompt,
)


def test_plan_prompts_include_json_schema_and_limits() -> None:
    prompt = build_plan_prompt(
        role="ORCHESTRATOR",
        runtime_context="runtime",
        effort_context="effort",
        memory="memory",
        max_items=3,
    )
    retry = build_retry_plan_prompt(
        role="ORCHESTRATOR",
        runtime_context="runtime",
        effort_context="effort",
        memory="memory",
        max_items=2,
    )

    assert "Create a compact execution plan" in prompt
    assert "Maximum work items for this effort level: 3" in prompt
    assert '"work_items"' in prompt
    assert '"confidence"' in prompt
    assert "Revise the workflow plan" in retry
    assert "Maximum work items for this effort level: 2" in retry
    assert '"confidence"' in retry


def test_review_judge_and_final_prompts_keep_contracts() -> None:
    review = build_review_prompt(role="REVIEWER", runtime_context="runtime", effort_context="effort")
    judge = build_judge_prompt(role="JUDGE", runtime_context="runtime", effort_context="effort")
    final = build_final_answer_prompt(runtime_context="runtime", effort_context="effort")

    assert '"approved|changes_requested"' in review
    assert "Do not invent test results" in review
    assert '"done|retry|needs_user"' in judge
    assert "Never put internal deliberation" in judge
    assert "Write the final answer" in final
    assert "transparent about missing verification" in final


def test_worker_prompt_adds_available_context_blocks() -> None:
    prompt = build_worker_prompt(
        role="WORKER",
        runtime_context="runtime",
        effort_context="effort",
        memory="memory",
        item={"id": "main", "title": "Do it"},
        code_context="files",
        agentic_context="tools",
        retry_feedback="try again",
    )

    assert "Assigned item:" in prompt
    assert '"id": "main"' in prompt
    assert "Workspace context:\nfiles" in prompt
    assert "Agentic tool context:\ntools" in prompt
    assert "Retry feedback from Judge:\ntry again" in prompt
