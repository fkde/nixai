from __future__ import annotations

from app.workflows.prompts import (
    append_node_instruction,
    build_node_instruction_block,
    build_final_answer_prompt,
    build_judge_prompt,
    build_plan_prompt,
    build_retry_plan_prompt,
    build_review_prompt,
    build_worker_prompt,
)
from app.workflows.models import WorkflowNode


def test_node_instruction_block_is_empty_for_blank_prompt() -> None:
    node = WorkflowNode.model_validate({"id": "agent", "type": "role", "prompt": "   "})
    prompt = "base prompt"

    assert build_node_instruction_block(node) == ""
    assert append_node_instruction(prompt, node) == prompt


def test_node_instruction_block_wraps_prompt_with_heading() -> None:
    node = WorkflowNode.model_validate({"id": "review", "type": "report", "prompt": "Check only legal risk."})

    assert build_node_instruction_block(node) == "## Node Instruction\nCheck only legal risk."


def test_plan_prompts_include_json_schema_and_limits() -> None:
    prompt = build_plan_prompt(
        role="ORCHESTRATOR", runtime_context="runtime", effort_context="effort", memory="memory", max_items=3
    )
    retry = build_retry_plan_prompt(
        role="ORCHESTRATOR", runtime_context="runtime", effort_context="effort", memory="memory", max_items=2
    )

    assert "Create a compact execution plan" in prompt
    assert "Maximum work items for this effort level: 3" in prompt
    assert '"work_items"' in prompt
    assert '"confidence"' in prompt
    assert '"recommended_workers"' in prompt
    assert "Create only as many work items" in prompt
    assert "Revise the workflow plan" in retry
    assert "Maximum work items for this effort level: 2" in retry
    assert '"confidence"' in retry
    assert '"recommended_workers"' in retry


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
        node_instruction="Prioritize source quality.",
    )

    assert "## Node Instruction\nPrioritize source quality." in prompt
    assert "Assigned item:" in prompt
    assert prompt.index("Prioritize source quality.") < prompt.index("Assigned item:")
    assert '"id": "main"' in prompt
    assert "Workspace context:\nfiles" in prompt
    assert "Agentic tool context:\ntools" in prompt
    assert "Retry feedback from Judge:\ntry again" in prompt
