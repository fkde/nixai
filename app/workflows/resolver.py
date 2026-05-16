from __future__ import annotations

from typing import Any

from app.workflows.models import WorkflowNode
from app.workflows.state import WorkflowState


class NodeInputResolver:
    """Resolve node inputs from the shared workflow state without raising on gaps."""

    _KNOWN_DEFAULTS = {
        "plan": None,
        "worker_reports": [],
        "review": None,
        "decision": None,
        "agentic_context": "",
        "code_context": "",
        "history": [],
        "memory": "",
    }

    def resolve(self, node: WorkflowNode, state: WorkflowState) -> dict[str, Any]:
        inputs = node.input if node.input else ([node.output] if node.output else [])
        resolved: dict[str, Any] = {}
        for key in inputs:
            resolved[key] = self.resolve_key(str(key), state)
        return resolved

    def resolve_key(self, key: str, state: WorkflowState) -> Any:
        if not key:
            return None
        if key in state:
            return state.get(key)
        if key in self._KNOWN_DEFAULTS:
            return self._KNOWN_DEFAULTS[key]

        node_results = state.get("node_results")
        if isinstance(node_results, dict):
            if key in node_results:
                return node_results.get(key)
            if "." in key:
                first, rest = key.split(".", 1)
                if first in node_results:
                    return self._dig(node_results.get(first), rest)

        if "." in key:
            first, rest = key.split(".", 1)
            if first in state:
                return self._dig(state.get(first), rest)
            if first in self._KNOWN_DEFAULTS:
                return self._dig(self._KNOWN_DEFAULTS[first], rest)
        return None

    def _dig(self, value: Any, path: str) -> Any:
        current = value
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list) and part.isdigit():
                index = int(part)
                current = current[index] if 0 <= index < len(current) else None
            else:
                return None
        return current
