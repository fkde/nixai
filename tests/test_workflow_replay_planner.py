from __future__ import annotations

from app.workflows.models import WorkflowDefinition
from app.workflows.replay import WorkflowReplayPlanner


def _wf() -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "id": "wf",
            "name": "Linear",
            "nodes": [
                {"id": "a", "type": "role", "output": "plan"},
                {"id": "b", "type": "role", "input": ["plan"], "output": "draft"},
                {"id": "c", "type": "answer", "input": ["draft"], "output": "final_answer"},
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "c"},
            ],
        }
    )


def _node_state(node_id: str, **overrides) -> dict:
    base = {
        "node_id": node_id,
        "status": "done",
        "output_snapshot": {"k": "v"},
        "output_snapshot_truncated": False,
        "input_snapshot": {"x": 1},
        "input_snapshot_truncated": False,
        "prompt_snapshot_truncated": False,
    }
    base.update(overrides)
    return base


def _event(seq: int, type_: str, node_id: str, payload: dict | None = None) -> dict:
    return {"seq": seq, "type": type_, "node_id": node_id, "payload": payload or {}}


# ---- Happy path ----

def test_downstream_plan_replays_from_start_and_lists_prerequisites() -> None:
    plan = WorkflowReplayPlanner().build_plan(
        workflow=_wf(),
        run_id="r1",
        start_node_id="b",
        events=[
            _event(1, "node_started", "a"),
            _event(2, "node_finished", "a", {"output_snapshot": {"plan": "ok"}}),
            _event(3, "node_started", "b"),
            _event(4, "node_finished", "b", {"output_snapshot": {"draft": "x"}}),
        ],
        node_states=[_node_state("a", output_snapshot={"plan": "ok"}), _node_state("b")],
    )
    assert plan.can_replay
    assert plan.replay_node_ids == ["b", "c"]  # downstream
    assert plan.prerequisite_node_ids == ["a"]
    assert plan.replay_until_seq == 2  # the seq before b's first node_started


def test_node_scope_only_replays_the_single_node() -> None:
    plan = WorkflowReplayPlanner().build_plan(
        workflow=_wf(),
        run_id="r1",
        start_node_id="b",
        events=[_event(1, "node_started", "a"), _event(2, "node_finished", "a", {"output_snapshot": {}})],
        node_states=[_node_state("a")],
        scope="node",
    )
    assert plan.replay_node_ids == ["b"]


# ---- Blocker paths ----

def test_unknown_start_node_blocks_plan() -> None:
    plan = WorkflowReplayPlanner().build_plan(
        workflow=_wf(), run_id="r1", start_node_id="ghost", events=[], node_states=[]
    )
    assert not plan.can_replay
    assert any("not found" in blocker.lower() for blocker in plan.blockers)


def test_prerequisite_without_persisted_state_blocks() -> None:
    plan = WorkflowReplayPlanner().build_plan(
        workflow=_wf(), run_id="r1", start_node_id="b", events=[], node_states=[]
    )
    assert any("no persisted state" in blocker for blocker in plan.blockers)


def test_prerequisite_not_completed_safely_blocks() -> None:
    plan = WorkflowReplayPlanner().build_plan(
        workflow=_wf(),
        run_id="r1",
        start_node_id="b",
        events=[],
        node_states=[_node_state("a", status="failed")],
    )
    assert any("did not complete safely" in blocker for blocker in plan.blockers)


def test_prerequisite_missing_output_snapshot_blocks() -> None:
    plan = WorkflowReplayPlanner().build_plan(
        workflow=_wf(),
        run_id="r1",
        start_node_id="b",
        events=[],
        node_states=[_node_state("a", output_snapshot=None)],
    )
    assert any("missing output snapshot" in blocker for blocker in plan.blockers)


def test_prerequisite_truncated_output_snapshot_blocks() -> None:
    plan = WorkflowReplayPlanner().build_plan(
        workflow=_wf(),
        run_id="r1",
        start_node_id="b",
        events=[],
        node_states=[_node_state("a", output_snapshot_truncated=True)],
    )
    assert any("truncated" in blocker for blocker in plan.blockers)


def test_truncated_replay_node_input_blocks() -> None:
    plan = WorkflowReplayPlanner().build_plan(
        workflow=_wf(),
        run_id="r1",
        start_node_id="b",
        events=[],
        node_states=[_node_state("a"), _node_state("b", input_snapshot_truncated=True)],
    )
    assert any("input snapshot is truncated" in blocker for blocker in plan.blockers)


def test_container_node_replay_blocked() -> None:
    workflow = WorkflowDefinition.model_validate(
        {
            "id": "wf",
            "name": "Loops",
            "nodes": [
                {"id": "a", "type": "role", "output": "plan"},
                {"id": "loop", "type": "for_each", "input": ["plan"], "config": {"body": ["a"]}, "output": "out"},
            ],
            "edges": [{"from": "a", "to": "loop"}],
        }
    )
    plan = WorkflowReplayPlanner().build_plan(
        workflow=workflow,
        run_id="r1",
        start_node_id="loop",
        events=[],
        node_states=[_node_state("a"), _node_state("loop")],
    )
    assert any("container node is not supported" in blocker for blocker in plan.blockers)


def test_trace_node_finished_missing_output_blocks() -> None:
    plan = WorkflowReplayPlanner().build_plan(
        workflow=_wf(),
        run_id="r1",
        start_node_id="b",
        events=[
            _event(1, "node_finished", "a", {}),  # missing output_snapshot
        ],
        node_states=[_node_state("a")],
    )
    assert any("missing output snapshot" in blocker for blocker in plan.blockers)


def test_truncated_tool_call_blocks() -> None:
    plan = WorkflowReplayPlanner().build_plan(
        workflow=_wf(),
        run_id="r1",
        start_node_id="b",
        events=[
            _event(1, "node_finished", "a", {"output_snapshot": {"plan": "ok"}}),
            _event(2, "tool_call", "a", {"result_snapshot_truncated": True}),
        ],
        node_states=[_node_state("a")],
    )
    assert any("Tool call snapshot is truncated" in blocker for blocker in plan.blockers)


def test_replay_until_seq_falls_back_to_max_when_no_replay_node_started() -> None:
    plan = WorkflowReplayPlanner().build_plan(
        workflow=_wf(),
        run_id="r1",
        start_node_id="b",
        events=[
            _event(1, "node_started", "a"),
            _event(2, "node_finished", "a", {"output_snapshot": {"plan": "ok"}}),
        ],
        node_states=[_node_state("a")],
    )
    # b never started in the trace — replay_until_seq is the last seq we saw.
    assert plan.replay_until_seq == 2
