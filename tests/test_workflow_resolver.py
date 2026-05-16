from __future__ import annotations

from app.workflows.models import WorkflowNode
from app.workflows.resolver import NodeInputResolver


def test_resolver_reads_known_state_values() -> None:
    resolver = NodeInputResolver()
    state = {
        "plan": {"summary": "Plan", "work_items": [{"id": "main"}]},
        "worker_reports": [{"id": "main", "content": "done"}],
        "agentic_context": "tools",
        "code_context": "files",
        "history": [{"role": "user", "content": "hello"}],
        "memory": "remember",
    }
    node = WorkflowNode(id="reviewer", type="reviewer", input=["plan", "plan.work_items.0.id", "memory"])

    assert resolver.resolve(node, state) == {
        "plan": {"summary": "Plan", "work_items": [{"id": "main"}]},
        "plan.work_items.0.id": "main",
        "memory": "remember",
    }


def test_resolver_reads_node_results() -> None:
    resolver = NodeInputResolver()
    state = {
        "node_results": {
            "workers": {
                "status": "done",
                "output": [{"id": "main", "content": "report"}],
            }
        }
    }

    assert resolver.resolve_key("workers.output.0.content", state) == "report"


def test_missing_inputs_do_not_crash() -> None:
    resolver = NodeInputResolver()
    node = WorkflowNode(id="worker", type="worker_pool", input=["missing", "worker_reports", "history"])

    assert resolver.resolve(node, {}) == {"missing": None, "worker_reports": [], "history": []}
