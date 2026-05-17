import { getRunEvents } from "./api.js";

const RECONNECT_DELAY_MS = 2000;
const POLL_INTERVAL_MS = 1500;

/**
 * Subscribes to a run's trace events.
 *
 * Behavioural contract:
 * 1. Opens an SSE connection to /api/runs/{runId}/stream and forwards every
 *    event payload to onEvent.
 * 2. On SSE error, retries once after RECONNECT_DELAY_MS. If that also fails,
 *    falls back to polling /api/runs/{runId}/events?since=<lastSeq>.
 * 3. Calls onClose exactly once when the server closes the stream or the
 *    consumer calls .close().
 * 4. Suppresses duplicate events (seq <= lastSeq) automatically.
 *
 * The returned handle exposes .close() (idempotent) and a few read-only
 * fields useful for tests/debug (mode, lastSeq).
 */
export function openRunStream(runId, { onEvent, onClose, onError, since = 0 } = {}) {
  let lastSeq = Number(since) || 0;
  let closed = false;
  let mode = "idle"; // "sse" | "polling" | "idle" | "closed"
  let sseAttempts = 0;
  let source = null;
  let pollTimer = null;

  const handle = {
    close,
    get mode() { return mode; },
    get lastSeq() { return lastSeq; },
  };

  function emit(event) {
    if (event && typeof event.seq === "number") {
      if (event.seq <= lastSeq) return;
      lastSeq = event.seq;
    }
    try {
      onEvent && onEvent(event);
    } catch (err) {
      // Consumer-side errors must not break the stream.
      console && console.error && console.error("openRunStream onEvent threw", err);
    }
  }

  function finish() {
    if (closed) return;
    closed = true;
    mode = "closed";
    if (source) { try { source.close(); } catch {} source = null; }
    if (pollTimer !== null) { clearTimeout(pollTimer); pollTimer = null; }
    try { onClose && onClose(); } catch {}
  }

  function close() {
    finish();
  }

  function startSse() {
    if (closed) return;
    sseAttempts += 1;
    mode = "sse";
    const url = `/api/runs/${encodeURIComponent(runId)}/stream${lastSeq ? `?since=${lastSeq}` : ""}`;
    source = new EventSource(url);
    source.onmessage = (msg) => {
      let data;
      try { data = JSON.parse(msg.data); } catch { return; }
      if (data && data.type === "stream_closed") {
        finish();
        return;
      }
      if (data && data.type === "gap") {
        // Server hint: we missed some events; reconcile via polling-once.
        catchUpThenContinue();
        return;
      }
      emit(data);
    };
    source.onerror = () => {
      try { source.close(); } catch {}
      source = null;
      if (closed) return;
      try { onError && onError({ phase: "sse", attempts: sseAttempts }); } catch {}
      if (sseAttempts < 2) {
        // One retry after a short delay; keeps recovering from transient drops.
        pollTimer = setTimeout(startSse, RECONNECT_DELAY_MS);
      } else {
        // SSE keeps failing — fall back to polling.
        startPolling();
      }
    };
  }

  async function catchUpThenContinue() {
    try {
      const { events } = await getRunEvents(runId, { since: lastSeq });
      for (const event of events || []) emit(event);
    } catch (err) {
      try { onError && onError({ phase: "catch-up", error: err }); } catch {}
    }
  }

  async function pollOnce() {
    if (closed) return;
    try {
      const { events } = await getRunEvents(runId, { since: lastSeq });
      for (const event of events || []) emit(event);
    } catch (err) {
      try { onError && onError({ phase: "polling", error: err }); } catch {}
    }
    if (!closed) {
      pollTimer = setTimeout(pollOnce, POLL_INTERVAL_MS);
    }
  }

  function startPolling() {
    mode = "polling";
    pollOnce();
  }

  // Kick off
  if (typeof EventSource === "undefined") {
    startPolling();
  } else {
    startSse();
  }

  return handle;
}
