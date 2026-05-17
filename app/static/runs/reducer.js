/**
 * Pure reducer over trace events. Applied incrementally as events arrive (live
 * SSE) or in bulk after fetching the full event list. The state shape is the
 * single source of truth the canvas + step-detail panel render from.
 *
 * Keep this file dependency-free so it can be unit-tested cheaply.
 */

export function createRunState() {
  return {
    runStatus: "idle",
    finalOutput: null,
    error: null,
    nodeStates: {}, // nodeId -> "idle" | "running" | "done" | "failed" | "needs_user"
    nodeLastFinishedAt: {}, // nodeId -> ISO ts of last completion (for live-pulse heuristics)
    edgeStates: {}, // "from→to" -> "traversed"
    eventsByNode: {}, // nodeId -> event[] (chronological)
    eventsByStep: {}, // step_id -> child event[] (parent_step_id == step_id)
    nodeStarts: {}, // node_id -> step_id of latest node_started (for grouping child events)
    lastSeq: 0,
  };
}

export function edgeKey(from, to) {
  return `${from}→${to}`;
}

function pushBy(map, key, event) {
  if (!map[key]) map[key] = [];
  map[key].push(event);
}

export function applyEvent(state, event) {
  if (!event || typeof event !== "object") return state;
  if (typeof event.seq === "number" && event.seq <= state.lastSeq) {
    // duplicate from replay/race — ignore
    return state;
  }

  const nodeId = event.node_id;
  if (nodeId) {
    pushBy(state.eventsByNode, nodeId, event);
  }
  if (event.parent_step_id) {
    pushBy(state.eventsByStep, event.parent_step_id, event);
  }

  switch (event.type) {
    case "run_started":
      state.runStatus = "running";
      break;
    case "run_paused":
      state.runStatus = "paused";
      break;
    case "run_finished":
      state.runStatus = "done";
      state.finalOutput = event.payload?.final_output ?? state.finalOutput;
      break;
    case "run_failed":
      state.runStatus = "failed";
      state.error = event.payload?.error ?? null;
      break;
    case "node_started":
      state.nodeStates[nodeId] = "running";
      if (event.step_id) state.nodeStarts[nodeId] = event.step_id;
      break;
    case "node_finished": {
      const status = event.payload?.status;
      state.nodeStates[nodeId] = status === "needs_user" ? "needs_user" : "done";
      if (event.ts) state.nodeLastFinishedAt[nodeId] = event.ts;
      break;
    }
    case "node_failed":
      state.nodeStates[nodeId] = "failed";
      if (event.ts) state.nodeLastFinishedAt[nodeId] = event.ts;
      break;
    case "edge_traversed": {
      const from = event.payload?.from;
      const to = event.payload?.to;
      if (from && to) state.edgeStates[edgeKey(from, to)] = "traversed";
      break;
    }
    default:
      break;
  }

  if (typeof event.seq === "number") {
    state.lastSeq = event.seq;
  }
  return state;
}

export function applyEvents(state, events) {
  if (!Array.isArray(events)) return state;
  for (const event of events) {
    applyEvent(state, event);
  }
  return state;
}

export function rebuildState(events, upToIndex = null) {
  const count = upToIndex === null || upToIndex === undefined ? events?.length : upToIndex;
  return applyEvents(createRunState(), Array.isArray(events) ? events.slice(0, count) : []);
}

/**
 * Returns the per-node breakdown the step-detail panel needs.
 * Groups runs by `node_started.step_id` so multi-execution nodes (for_each
 * body, retries) show up as distinct steps.
 */
export function stepsForNode(state, nodeId) {
  const events = state.eventsByNode[nodeId] || [];
  const steps = [];
  let current = null;
  for (const event of events) {
    if (event.type === "node_started") {
      current = {
        stepId: event.step_id,
        startedAt: event.ts,
        nodeType: event.payload?.node_type,
        inputSnapshot: event.payload?.input_snapshot,
        prompt: event.payload?.prompt,
        status: "running",
        finishedAt: null,
        outputSnapshot: null,
        summary: null,
        error: null,
        durationMs: null,
        childEvents: state.eventsByStep[event.step_id] || [],
      };
      steps.push(current);
    } else if (current && event.type === "node_finished") {
      current.status = event.payload?.status || "done";
      current.outputSnapshot = event.payload?.output_snapshot ?? null;
      current.summary = event.payload?.summary ?? null;
      current.durationMs = event.payload?.duration_ms ?? null;
      current.finishedAt = event.ts;
      current = null;
    } else if (current && event.type === "node_failed") {
      current.status = "failed";
      current.error = event.payload?.error ?? null;
      current.durationMs = event.payload?.duration_ms ?? null;
      current.finishedAt = event.ts;
      current = null;
    }
  }
  return steps;
}
