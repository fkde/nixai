import { api } from "../api.js";

export function listRuns({ workflowId, status, limit = 50, offset = 0 } = {}) {
  const params = new URLSearchParams();
  if (workflowId) params.set("workflow_id", workflowId);
  if (status) params.set("status", status);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return api(`/api/runs?${params.toString()}`);
}

export function getRun(runId) {
  return api(`/api/runs/${encodeURIComponent(runId)}`);
}

export function getRunEvents(runId, { since = 0, limit = 500 } = {}) {
  const params = new URLSearchParams();
  if (since) params.set("since", String(since));
  if (limit) params.set("limit", String(limit));
  const qs = params.toString();
  return api(`/api/runs/${encodeURIComponent(runId)}/events${qs ? `?${qs}` : ""}`);
}

export function pauseRun(runId) {
  return api(`/api/runs/${encodeURIComponent(runId)}/pause`, { method: "POST" });
}

export function resumeRun(runId, { feedback = "" } = {}) {
  return api(`/api/runs/${encodeURIComponent(runId)}/resume`, {
    method: "POST",
    body: JSON.stringify({ feedback }),
  });
}

export function forkRun(runId, { fromStepId, editedOutput, label = "" }) {
  return api(`/api/runs/${encodeURIComponent(runId)}/fork`, {
    method: "POST",
    body: JSON.stringify({ from_step_id: fromStepId, edited_output: editedOutput, label }),
  });
}

export function planReplay(runId, { startNodeId, scope = "downstream" }) {
  return api(`/api/runs/${encodeURIComponent(runId)}/replay-plan`, {
    method: "POST",
    body: JSON.stringify({ start_node_id: startNodeId, scope }),
  });
}

export function replayRun(runId, { startNodeId, scope = "downstream", label = "" }) {
  return api(`/api/runs/${encodeURIComponent(runId)}/replay`, {
    method: "POST",
    body: JSON.stringify({ start_node_id: startNodeId, scope, label }),
  });
}
