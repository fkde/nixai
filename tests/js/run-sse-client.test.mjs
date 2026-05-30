import test from "node:test";
import assert from "node:assert/strict";

import { openRunStream } from "../../app/static/runs/sse-client.js";

const originalEventSource = globalThis.EventSource;
const originalFetch = globalThis.fetch;
const originalSetTimeout = globalThis.setTimeout;
const originalClearTimeout = globalThis.clearTimeout;

class FakeEventSource {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.closed = false;
    this.onmessage = null;
    this.onerror = null;
    FakeEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }

  message(data) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  rawMessage(data) {
    this.onmessage?.({ data });
  }

  error() {
    this.onerror?.();
  }
}

test.beforeEach(() => {
  FakeEventSource.instances = [];
  globalThis.EventSource = FakeEventSource;
});

test.afterEach(() => {
  globalThis.EventSource = originalEventSource;
  globalThis.fetch = originalFetch;
  globalThis.setTimeout = originalSetTimeout;
  globalThis.clearTimeout = originalClearTimeout;
});

test("openRunStream opens SSE with encoded run id and since value", () => {
  const handle = openRunStream("run/one", { since: 4 });

  assert.equal(handle.mode, "sse");
  assert.equal(FakeEventSource.instances[0].url, "/api/runs/run%2Fone/stream?since=4");

  handle.close();
});

test("openRunStream forwards new events and suppresses duplicate sequence numbers", () => {
  const events = [];
  const handle = openRunStream("r1", {
    since: 10,
    onEvent: (event) => events.push(event),
  });
  const source = FakeEventSource.instances[0];

  source.message({ seq: 10, type: "duplicate" });
  source.message({ seq: 11, type: "node_started" });
  source.message({ seq: 11, type: "duplicate-again" });
  source.message({ type: "unsequenced" });

  assert.deepEqual(events, [
    { seq: 11, type: "node_started" },
    { type: "unsequenced" },
  ]);
  assert.equal(handle.lastSeq, 11);

  handle.close();
});

test("openRunStream closes exactly once when server sends stream_closed", () => {
  let closeCount = 0;
  const handle = openRunStream("r1", { onClose: () => closeCount += 1 });
  const source = FakeEventSource.instances[0];

  source.message({ type: "stream_closed" });
  handle.close();

  assert.equal(closeCount, 1);
  assert.equal(handle.mode, "closed");
  assert.equal(source.closed, true);
});

test("openRunStream ignores malformed SSE payloads", () => {
  const events = [];
  const handle = openRunStream("r1", { onEvent: (event) => events.push(event) });

  FakeEventSource.instances[0].rawMessage("{not-json");

  assert.deepEqual(events, []);
  handle.close();
});

test("openRunStream retries SSE once and then falls back to polling", async () => {
  const timers = [];
  const errors = [];
  const events = [];
  const fetchCalls = [];
  globalThis.setTimeout = (fn, ms) => {
    timers.push({ fn, ms });
    return timers.length;
  };
  globalThis.clearTimeout = () => {};
  globalThis.fetch = async (path) => {
    fetchCalls.push(path);
    return {
      ok: true,
      status: 200,
      json: async () => ({ events: [{ seq: 2, type: "polled" }] }),
    };
  };

  const handle = openRunStream("r1", {
    since: 1,
    onEvent: (event) => events.push(event),
    onError: (error) => errors.push(error),
  });

  FakeEventSource.instances[0].error();
  assert.equal(errors[0].phase, "sse");
  assert.equal(timers[0].ms, 2000);

  timers[0].fn();
  FakeEventSource.instances[1].error();
  await new Promise((resolve) => originalSetTimeout(resolve, 0));

  assert.equal(handle.mode, "polling");
  assert.deepEqual(events, [{ seq: 2, type: "polled" }]);
  assert.equal(fetchCalls[0], "/api/runs/r1/events?since=1&limit=500");

  handle.close();
});

test("openRunStream catches up on gap hints without closing SSE", async () => {
  const events = [];
  const fetchCalls = [];
  globalThis.fetch = async (path) => {
    fetchCalls.push(path);
    return {
      ok: true,
      status: 200,
      json: async () => ({ events: [{ seq: 6, type: "caught_up" }] }),
    };
  };

  const handle = openRunStream("r1", {
    since: 5,
    onEvent: (event) => events.push(event),
  });
  FakeEventSource.instances[0].message({ type: "gap" });
  await new Promise((resolve) => originalSetTimeout(resolve, 0));

  assert.equal(handle.mode, "sse");
  assert.deepEqual(events, [{ seq: 6, type: "caught_up" }]);
  assert.equal(fetchCalls[0], "/api/runs/r1/events?since=5&limit=500");

  handle.close();
});
