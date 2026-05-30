import test from "node:test";
import assert from "node:assert/strict";

import { api } from "../../app/static/api.js";
import { parseFrameEvent, startMessageStream } from "../../app/static/stream.js";

const originalFetch = globalThis.fetch;

test.afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("api sends JSON headers, preserves custom headers, and parses response JSON", async () => {
  const calls = [];
  globalThis.fetch = async (path, options) => {
    calls.push({ path, options });
    return {
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    };
  };

  const result = await api("/api/example", { method: "POST", headers: { "X-Test": "yes" } });

  assert.deepEqual(result, { ok: true });
  assert.equal(calls[0].path, "/api/example");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers["Content-Type"], "application/json");
  assert.equal(calls[0].options.headers["X-Test"], "yes");
});

test("api returns null for 204 responses", async () => {
  globalThis.fetch = async () => ({
    ok: true,
    status: 204,
    json: async () => {
      throw new Error("should not parse");
    },
  });

  assert.equal(await api("/api/empty"), null);
});

test("api surfaces backend detail and falls back to HTTP status", async () => {
  globalThis.fetch = async () => ({
    ok: false,
    status: 400,
    json: async () => ({ detail: "bad input" }),
  });
  await assert.rejects(() => api("/api/fail"), /bad input/);

  globalThis.fetch = async () => ({
    ok: false,
    status: 503,
    json: async () => {
      throw new Error("invalid json");
    },
  });
  await assert.rejects(() => api("/api/fail"), /HTTP 503/);
});

test("parseFrameEvent parses single and multi-line SSE data payloads", () => {
  assert.deepEqual(parseFrameEvent('event: message\ndata: {"type":"token","content":"hi"}\n'), {
    type: "token",
    content: "hi",
  });

  assert.deepEqual(parseFrameEvent('data: {"a":\ndata: 1}\n'), { a: 1 });
});

test("parseFrameEvent ignores frames without valid JSON data", () => {
  assert.equal(parseFrameEvent("event: ping\n\n"), null);
  assert.equal(parseFrameEvent("data: not json\n\n"), null);
});

test("startMessageStream posts to the chat stream endpoint and dispatches chunked events", async () => {
  const encoder = new TextEncoder();
  const chunks = [
    'data: {"type":"token","content":"he',
    'llo"}\n\n',
    'data: {"type":"done"}',
  ];
  const dispatched = [];
  const calls = [];
  globalThis.fetch = async (path, options) => {
    calls.push({ path, options });
    return {
      ok: true,
      status: 200,
      body: new ReadableStream({
        start(controller) {
          chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
          controller.close();
        },
      }),
    };
  };

  await startMessageStream({
    chatId: "chat 1",
    body: { message: "hello" },
    onEvent: (event) => dispatched.push(event),
  });

  assert.equal(calls[0].path, "/api/chats/chat 1/messages/stream");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.body, JSON.stringify({ message: "hello" }));
  assert.deepEqual(dispatched, [
    { type: "token", content: "hello" },
    { type: "done" },
  ]);
});

test("startMessageStream reports HTTP failures with backend detail", async () => {
  globalThis.fetch = async () => ({
    ok: false,
    status: 409,
    body: null,
    json: async () => ({ detail: "chat busy" }),
  });

  await assert.rejects(
    () => startMessageStream({ chatId: "c1", body: {}, onEvent: () => {} }),
    /chat busy/,
  );
});
