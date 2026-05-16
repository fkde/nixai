from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.workflows.models import NodePosition, WorkflowDefinition


def test_workflow_definition_derives_edges_from_node_links() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf1",
            "name": "Demo Workflow",
            "nodes": [
                {"id": "planner", "type": "role", "reports_to": ["worker", "worker", "missing"]},
                {"id": "worker", "type": "worker_pool", "receive_from": ["planner"]},
            ],
        }
    )

    assert [(edge.from_node, edge.to) for edge in workflow.edges] == [("planner", "worker")]


def test_workflow_definition_uses_explicit_edges_as_canonical_links() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf2",
            "name": "Explicit Edges",
            "nodes": [
                {"id": "start", "type": "role", "reports_to": ["ignored"]},
                {"id": "review", "type": "reviewer"},
            ],
            "edges": [{"from": "start", "to": "review"}, {"from": "ghost", "to": "start"}],
        }
    )

    start = workflow.node("start")
    review = workflow.node("review")
    assert start is not None
    assert review is not None
    assert start.reports_to == ["review"]
    assert review.receive_from == ["start"]


def test_workflow_model_normalizes_modes_and_positions() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf3",
            "name": "Modes",
            "mode": "chat",
            "modes": ["chat", "code", "code", "invalid"],
            "nodes": [{"id": "node1", "type": "role", "position": {"x": 20000, "y": "bad"}}],
        }
    )

    assert workflow.supported_modes() == ["chat", "code"]
    assert workflow.nodes[0].position == NodePosition(x=10000.0, y=0.0)


def test_workflow_definition_rejects_invalid_id() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate({"id": "../bad", "name": "Bad"})
