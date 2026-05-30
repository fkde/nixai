import test from "node:test";
import assert from "node:assert/strict";

import {
  forkRun,
  getRun,
  getRunEvents,
  listRuns,
  pauseRun,
  planReplay,
  replayRun,
  resumeRun,
} from "../../app/static/runs/api.js";

const originalFetch = globalThis.fetch;

function mockJsonFetch(calls) {
  globalThis.fetch = async (path, options = {}) => {
    calls.push({ path, options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    };
  };
}

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("listRuns builds query strings with defaults and filters", async () => {
  const calls = [];
  mockJsonFetch(calls);

  await listRuns();
  await listRuns({ workflowId: "wf 1", status: "paused", limit: 10, offset: 20 });

  assert.equal(calls[0].path, "/api/runs?limit=50&offset=0");
  assert.equal(calls[1].path, "/api/runs?workflow_id=wf+1&status=paused&limit=10&offset=20");
});

test("run fetch helpers encode run ids in path segments", async () => {
  const calls = [];
  mockJsonFetch(calls);

  await getRun("run/one");
  await getRunEvents("run/one", { since: 7, limit: 25 });

  assert.equal(calls[0].path, "/api/runs/run%2Fone");
  assert.equal(calls[1].path, "/api/runs/run%2Fone/events?since=7&limit=25");
});

test("getRunEvents omits empty query params", async () => {
  const calls = [];
  mockJsonFetch(calls);

  await getRunEvents("r1", { since: 0, limit: 0 });

  assert.equal(calls[0].path, "/api/runs/r1/events");
});

test("pauseRun and resumeRun post to the expected endpoints", async () => {
  const calls = [];
  mockJsonFetch(calls);

  await pauseRun("r1");
  await resumeRun("r1", { feedback: "continue from here" });

  assert.equal(calls[0].path, "/api/runs/r1/pause");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[1].path, "/api/runs/r1/resume");
  assert.equal(calls[1].options.method, "POST");
  assert.equal(calls[1].options.body, JSON.stringify({ feedback: "continue from here" }));
});

test("fork and replay helpers post structured payloads", async () => {
  const calls = [];
  mockJsonFetch(calls);

  await forkRun("r1", { fromStepId: "s1", editedOutput: { answer: "new" }, label: "Try again" });
  await planReplay("r1", { startNodeId: "judge", scope: "node" });
  await replayRun("r1", { startNodeId: "judge", scope: "downstream", label: "Replay" });

  assert.equal(calls[0].path, "/api/runs/r1/fork");
  assert.equal(calls[0].options.body, JSON.stringify({
    from_step_id: "s1",
    edited_output: { answer: "new" },
    label: "Try again",
  }));
  assert.equal(calls[1].path, "/api/runs/r1/replay-plan");
  assert.equal(calls[1].options.body, JSON.stringify({ start_node_id: "judge", scope: "node" }));
  assert.equal(calls[2].path, "/api/runs/r1/replay");
  assert.equal(calls[2].options.body, JSON.stringify({
    start_node_id: "judge",
    scope: "downstream",
    label: "Replay",
  }));
});
