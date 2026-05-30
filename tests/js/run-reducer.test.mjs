import test from "node:test";
import assert from "node:assert/strict";

import {
  applyEvent,
  applyEvents,
  createRunState,
  edgeKey,
  rebuildState,
  stepsForNode,
} from "../../app/static/runs/reducer.js";

test("createRunState returns the expected empty trace state", () => {
  assert.deepEqual(createRunState(), {
    runStatus: "idle",
    finalOutput: null,
    error: null,
    nodeStates: {},
    nodeLastFinishedAt: {},
    edgeStates: {},
    eventsByNode: {},
    eventsByStep: {},
    nodeStarts: {},
    lastSeq: 0,
  });
});

test("applyEvent tracks run status, final output, errors, nodes, and edges", () => {
  const state = createRunState();
  applyEvents(state, [
    { seq: 1, type: "run_started" },
    { seq: 2, type: "node_started", node_id: "plan", step_id: "s1", payload: { node_type: "role" } },
    { seq: 3, type: "edge_traversed", payload: { from: "plan", to: "answer" } },
    { seq: 4, type: "node_finished", node_id: "plan", ts: "2026-01-01T00:00:00Z", payload: { status: "done" } },
    { seq: 5, type: "run_finished", payload: { final_output: "done" } },
  ]);

  assert.equal(state.runStatus, "done");
  assert.equal(state.finalOutput, "done");
  assert.equal(state.nodeStates.plan, "done");
  assert.equal(state.nodeStarts.plan, "s1");
  assert.equal(state.nodeLastFinishedAt.plan, "2026-01-01T00:00:00Z");
  assert.equal(state.edgeStates[edgeKey("plan", "answer")], "traversed");
  assert.equal(state.lastSeq, 5);
});

test("applyEvent ignores duplicate or out-of-order sequenced events", () => {
  const state = createRunState();
  applyEvent(state, { seq: 2, type: "run_started" });
  applyEvent(state, { seq: 2, type: "run_failed", payload: { error: "duplicate" } });
  applyEvent(state, { seq: 1, type: "run_finished", payload: { final_output: "old" } });

  assert.equal(state.runStatus, "running");
  assert.equal(state.error, null);
  assert.equal(state.finalOutput, null);
  assert.equal(state.lastSeq, 2);
});

test("applyEvent records node failures and needs_user completions", () => {
  const state = createRunState();
  applyEvent(state, {
    seq: 1,
    type: "node_finished",
    node_id: "ask",
    ts: "2026-01-01T00:00:00Z",
    payload: { status: "needs_user" },
  });
  applyEvent(state, {
    seq: 2,
    type: "node_failed",
    node_id: "work",
    ts: "2026-01-01T00:00:01Z",
    payload: { error: "boom" },
  });
  applyEvent(state, { seq: 3, type: "run_failed", payload: { error: "run boom" } });

  assert.equal(state.nodeStates.ask, "needs_user");
  assert.equal(state.nodeStates.work, "failed");
  assert.equal(state.runStatus, "failed");
  assert.equal(state.error, "run boom");
});

test("stepsForNode groups child events under their parent node step", () => {
  const state = createRunState();
  applyEvents(state, [
    {
      seq: 1,
      type: "node_started",
      node_id: "worker",
      step_id: "step-1",
      ts: "start",
      payload: { node_type: "role", input_snapshot: { a: 1 }, prompt: "Do work" },
    },
    { seq: 2, type: "tool_called", node_id: "tool", parent_step_id: "step-1", payload: { name: "search" } },
    {
      seq: 3,
      type: "node_finished",
      node_id: "worker",
      ts: "finish",
      payload: { status: "done", output_snapshot: { b: 2 }, summary: "ok", duration_ms: 42 },
    },
  ]);

  assert.deepEqual(stepsForNode(state, "worker"), [{
    stepId: "step-1",
    startedAt: "start",
    nodeType: "role",
    inputSnapshot: { a: 1 },
    prompt: "Do work",
    status: "done",
    finishedAt: "finish",
    outputSnapshot: { b: 2 },
    summary: "ok",
    error: null,
    durationMs: 42,
    childEvents: [{ seq: 2, type: "tool_called", node_id: "tool", parent_step_id: "step-1", payload: { name: "search" } }],
  }]);
});

test("stepsForNode reports failed steps", () => {
  const state = rebuildState([
    { seq: 1, type: "node_started", node_id: "worker", step_id: "step-1", ts: "start", payload: {} },
    { seq: 2, type: "node_failed", node_id: "worker", ts: "finish", payload: { error: "bad", duration_ms: 5 } },
  ]);

  assert.equal(stepsForNode(state, "worker")[0].status, "failed");
  assert.equal(stepsForNode(state, "worker")[0].error, "bad");
  assert.equal(stepsForNode(state, "worker")[0].durationMs, 5);
});

test("rebuildState can replay only a prefix of events", () => {
  const state = rebuildState([
    { seq: 1, type: "run_started" },
    { seq: 2, type: "run_finished", payload: { final_output: "done" } },
  ], 1);

  assert.equal(state.runStatus, "running");
  assert.equal(state.finalOutput, null);
  assert.equal(state.lastSeq, 1);
});
