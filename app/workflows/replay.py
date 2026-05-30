from __future__ import annotations

from collections import deque
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.workflows.models import WorkflowDefinition


ReplayScope = Literal["node", "downstream"]


class ReplayPlan(BaseModel):
    run_id: str
    workflow_id: str
    start_node_id: str
    scope: ReplayScope = "downstream"
    replay_node_ids: list[str] = Field(default_factory=list)
    prerequisite_node_ids: list[str] = Field(default_factory=list)
    replay_until_seq: int = 0
    can_replay: bool = False
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    snapshot_requirements: dict[str, dict[str, Any]] = Field(default_factory=dict)


class WorkflowReplayPlanner:
    """Builds a conservative replay plan from persisted workflow runtime data.

    This is intentionally a planner, not an executor. It gives later selective
    replay code a stable contract and refuses plans where snapshots are missing
    or truncated enough to make deterministic reconstruction unsafe.
    """

    def build_plan(
        self,
        *,
        workflow: WorkflowDefinition,
        run_id: str,
        start_node_id: str,
        events: list[dict[str, Any]],
        node_states: list[dict[str, Any]],
        scope: ReplayScope = "downstream",
    ) -> ReplayPlan:
        start_node_id = start_node_id.strip()
        plan = ReplayPlan(
            run_id=run_id,
            workflow_id=workflow.id,
            start_node_id=start_node_id,
            scope=scope,
        )
        if workflow.node(start_node_id) is None:
            plan.blockers.append("Replay start node was not found in the workflow definition.")
            return plan
        # Note: ReplayScope is a typed Literal, so Pydantic rejects unsupported
        # values before they reach this method. No runtime check needed.

        replay_nodes = [start_node_id] if scope == "node" else self._downstream_node_ids(workflow, start_node_id)
        plan.replay_node_ids = replay_nodes
        plan.prerequisite_node_ids = self._prerequisite_node_ids(workflow, replay_nodes)
        state_by_node = self._latest_node_states(node_states)
        plan.replay_until_seq = self._seq_before_first_replay_node(events, set(replay_nodes))
        self._validate_prerequisites(plan, state_by_node)
        self._validate_replay_nodes(plan, workflow, state_by_node)
        self._validate_trace_events(plan, events, set(plan.prerequisite_node_ids), set(replay_nodes))
        plan.can_replay = not plan.blockers
        return plan

    def _downstream_node_ids(self, workflow: WorkflowDefinition, start_node_id: str) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        queue: deque[str] = deque([start_node_id])
        while queue:
            node_id = queue.popleft()
            if node_id in seen:
                continue
            seen.add(node_id)
            ordered.append(node_id)
            for edge in workflow.edges:
                if edge.from_node == node_id and edge.to not in seen:
                    queue.append(edge.to)
        return ordered

    def _prerequisite_node_ids(self, workflow: WorkflowDefinition, replay_node_ids: list[str]) -> list[str]:
        replay_set = set(replay_node_ids)
        prereqs: set[str] = set()
        for node_id in replay_node_ids:
            node = workflow.node(node_id)
            if node is None:
                continue
            for input_name in node.input:
                source = self._source_node_for_output(workflow, input_name)
                if source and source not in replay_set:
                    prereqs.add(source)
            for edge in workflow.edges:
                if edge.to == node_id and edge.from_node not in replay_set:
                    prereqs.add(edge.from_node)
        return [node.id for node in workflow.nodes if node.id in prereqs]

    def _source_node_for_output(self, workflow: WorkflowDefinition, output_name: str) -> str:
        wanted = str(output_name or "").strip()
        if not wanted:
            return ""
        for node in workflow.nodes:
            if node.output == wanted:
                return node.id
        return ""

    def _latest_node_states(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            node_id = str(row.get("node_id") or "")
            if node_id:
                latest[node_id] = row
        return latest

    def _seq_before_first_replay_node(self, events: list[dict[str, Any]], replay_nodes: set[str]) -> int:
        for event in events:
            if event.get("type") == "node_started" and event.get("node_id") in replay_nodes:
                return max(0, int(event.get("seq") or 0) - 1)
        return max((int(event.get("seq") or 0) for event in events), default=0)

    def _validate_prerequisites(self, plan: ReplayPlan, state_by_node: dict[str, dict[str, Any]]) -> None:
        for node_id in plan.prerequisite_node_ids:
            state = state_by_node.get(node_id)
            plan.snapshot_requirements[node_id] = {"role": "prerequisite", "requires_output_snapshot": True}
            if not state:
                plan.blockers.append(f"Prerequisite node has no persisted state: {node_id}")
                continue
            if state.get("status") not in {"done", "needs_user"}:
                plan.blockers.append(f"Prerequisite node did not complete safely: {node_id}")
            if state.get("output_snapshot") is None:
                plan.blockers.append(f"Prerequisite node is missing output snapshot: {node_id}")
            if state.get("output_snapshot_truncated"):
                plan.blockers.append(f"Prerequisite node output snapshot is truncated: {node_id}")

    def _validate_replay_nodes(
        self,
        plan: ReplayPlan,
        workflow: WorkflowDefinition,
        state_by_node: dict[str, dict[str, Any]],
    ) -> None:
        for node_id in plan.replay_node_ids:
            node = workflow.node(node_id)
            plan.snapshot_requirements[node_id] = {
                "role": "replay",
                "requires_input_snapshot": True,
                "requires_prompt_snapshot": bool(node and node.prompt),
            }
            state = state_by_node.get(node_id)
            if state is None:
                plan.warnings.append(f"Replay node has no prior persisted state: {node_id}")
                continue
            if state.get("input_snapshot_truncated"):
                plan.blockers.append(f"Replay node input snapshot is truncated: {node_id}")
            if state.get("prompt_snapshot_truncated"):
                plan.blockers.append(f"Replay node prompt snapshot is truncated: {node_id}")
            if node and node.type in {"for_each", "while"}:
                plan.blockers.append(f"Selective replay of container node is not supported yet: {node_id}")

    def _validate_trace_events(
        self,
        plan: ReplayPlan,
        events: list[dict[str, Any]],
        prerequisite_nodes: set[str],
        replay_nodes: set[str],
    ) -> None:
        relevant = prerequisite_nodes | replay_nodes
        for event in events:
            node_id = str(event.get("node_id") or "")
            if node_id not in relevant:
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if event.get("type") == "node_finished":
                if "output_snapshot" not in payload:
                    plan.blockers.append(f"Trace event is missing output snapshot for node: {node_id}")
                if payload.get("output_snapshot_truncated"):
                    plan.blockers.append(f"Trace event has truncated output snapshot for node: {node_id}")
            if event.get("type") == "tool_call":
                if payload.get("arguments_snapshot_truncated") or payload.get("result_snapshot_truncated"):
                    plan.blockers.append(f"Tool call snapshot is truncated for node: {node_id}")
                if payload.get("error_snapshot_truncated"):
                    plan.blockers.append(f"Tool error snapshot is truncated for node: {node_id}")
