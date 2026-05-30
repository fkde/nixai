import { api } from "../api.js";
import { dom } from "../dom.js";
import { escapeHtml } from "../helpers.js";
import { state } from "../state.js";
import { forkRun, getRun, listRuns, pauseRun, planReplay, replayRun, resumeRun } from "./api.js";
import { createInspectorCanvas } from "./inspector-canvas.js";
import { applyEvent, applyEvents, createRunState, rebuildState, stepsForNode } from "./reducer.js";
import { openRunStream } from "./sse-client.js";
import { createTimelineSlider } from "./timeline-slider.js";

const STATUS_LABEL = {
  running: "Running",
  paused: "Paused",
  done: "Done",
  failed: "Failed",
  needs_user: "Needs user",
};

function formatTimestamp(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

function formatDuration(startIso, endIso) {
  if (!startIso) return "—";
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return "—";
  const ms = end - start;
  if (ms < 1000) return `${ms} ms`;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rem = seconds % 60;
  return `${minutes}m ${rem.toString().padStart(2, "0")}s`;
}

function snapshotToText(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function findWorkflow(workflowId) {
  const presets = Array.isArray(state.workflowPresets) ? state.workflowPresets : [];
  return presets.find((preset) => preset.id === workflowId) || null;
}

async function ensureWorkflow(workflowId) {
  const cached = findWorkflow(workflowId);
  if (cached) return cached;
  // Fall back to a fresh fetch in case the inspector was opened before
  // workflowsUi.loadWorkflowPresets() populated state.
  try {
    const body = await api("/api/settings/workflows");
    if (Array.isArray(body?.workflows)) {
      state.workflowPresets = body.workflows;
      return findWorkflow(workflowId);
    }
  } catch {
    return null;
  }
  return null;
}

export function createRunsUi({ setStatus }) {
  const {
    runsList,
    runsDetail,
    runsDetailBack,
    runsDetailMeta,
    runsTimeline,
    runsFilterStatus,
    runsRefresh,
    runsInspectorCanvas,
    runsStepPanel,
  } = dom;

  let loaded = false;
  let currentRunId = null;
  let canvas = null;
  let currentRunState = null;
  let currentWorkflow = null;
  let currentRun = null;
  let currentStream = null;
  let currentEvents = [];
  let currentNodeStates = [];
  let currentToolCalls = [];
  let timeline = null;
  let timelineRunId = null;
  let timelinePreviewing = false;
  let selectedNodeId = null;

  function ensureCanvas() {
    if (canvas || !runsInspectorCanvas) return canvas;
    canvas = createInspectorCanvas({ host: runsInspectorCanvas });
    canvas.setOnNodeClick((nodeId) => {
      selectedNodeId = nodeId;
      canvas.setSelectedNode(nodeId);
      renderStepPanel(nodeId);
    });
    return canvas;
  }

  function closeStream() {
    if (currentStream) {
      try { currentStream.close(); } catch {}
      currentStream = null;
    }
  }

  function showList() {
    closeStream();
    currentRunId = null;
    currentRunState = null;
    currentWorkflow = null;
    currentRun = null;
    selectedNodeId = null;
    currentEvents = [];
    currentNodeStates = [];
    currentToolCalls = [];
    timelineRunId = null;
    timelinePreviewing = false;
    if (runsDetail) runsDetail.hidden = true;
    if (runsList) runsList.hidden = false;
  }

  function showDetail() {
    if (runsList) runsList.hidden = true;
    if (runsDetail) runsDetail.hidden = false;
  }

  async function loadRuns() {
    if (!runsList) return;
    const status = runsFilterStatus?.value || "";
    runsList.innerHTML = '<p class="settings-empty">Loading runs…</p>';
    try {
      const data = await listRuns({ status });
      renderRunList(data.runs || []);
      loaded = true;
    } catch (error) {
      runsList.innerHTML = `<p class="settings-empty">Failed to load runs: ${escapeHtml(error.message)}</p>`;
      setStatus(error.message, true);
    }
  }

  function renderRunList(runs) {
    if (!runsList) return;
    if (runs.length === 0) {
      runsList.innerHTML = '<p class="settings-empty">No workflow runs persisted yet.</p>';
      return;
    }
    const rows = runs
      .map((run) => {
        const status = STATUS_LABEL[run.status] || run.status;
        const duration = formatDuration(run.created_at, run.finished_at);
        const forkBadge = run.fork_of_run_id
          ? `<span class="runs-fork-badge" data-parent-run-id="${escapeHtml(run.fork_of_run_id)}" title="Open parent run">forked</span>`
          : "";
        return `
          <button class="runs-row" type="button" data-run-id="${escapeHtml(run.id)}">
            <span class="runs-row-name">${escapeHtml(run.workflow_id)} ${forkBadge}</span>
            <span class="runs-row-status runs-status-${escapeHtml(run.status)}">${escapeHtml(status)}</span>
            <span class="runs-row-time">${escapeHtml(formatTimestamp(run.created_at))}</span>
            <span class="runs-row-duration">${escapeHtml(duration)}</span>
          </button>
        `;
      })
      .join("");
    runsList.innerHTML = `
      <div class="runs-table">
        <div class="runs-row runs-row-head">
          <span>Workflow</span><span>Status</span><span>Started</span><span>Duration</span>
        </div>
        ${rows}
      </div>
    `;
  }

  async function openRun(runId) {
    if (!runsDetail) return;
    closeStream();
    currentRunId = runId;
    selectedNodeId = null;
    showDetail();
    runsDetailMeta.innerHTML = '<p class="settings-empty">Loading…</p>';
    runsStepPanel.innerHTML = '<p class="settings-empty">Loading…</p>';
    try {
      const data = await getRun(runId);
      const events = data.events || [];
      currentEvents = events;
      currentNodeStates = Array.isArray(data.node_states) ? data.node_states : [];
      currentToolCalls = Array.isArray(data.tool_calls) ? data.tool_calls : [];
      timelinePreviewing = false;
      currentRunState = applyEvents(createRunState(), events);
      currentRun = data.run;
      currentWorkflow = await ensureWorkflow(data.run.workflow_id);
      renderMeta(currentRun);
      renderTimeline();
      renderCanvas();
      renderStepPanel(null);
      if (currentRun.status === "running" || currentRun.status === "paused" || currentRun.status === "needs_user") {
        startLiveStream();
      }
    } catch (error) {
      runsDetailMeta.innerHTML = `<p class="settings-empty">Failed to load run: ${escapeHtml(error.message)}</p>`;
      setStatus(error.message, true);
    }
  }

  function startLiveStream() {
    if (!currentRunId) return;
    const sinceSeq = Math.max(0, ...currentEvents.map((event) => Number(event.seq) || 0));
    currentStream = openRunStream(currentRunId, {
      since: sinceSeq,
      onEvent: (event) => {
        if (!event || !currentRunState) return;
        currentEvents.push(event);
        if (!timelinePreviewing) {
          applyEvent(currentRunState, event);
        }
        timeline?.setEvents(currentEvents, { keepPosition: true });
        // Refresh node colours + edges + run-status pill
        if (canvas && !timelinePreviewing) canvas.update(currentRunState);
        if (!timelinePreviewing && currentRun && currentRunState.runStatus !== currentRun.status) {
          currentRun = { ...currentRun, status: currentRunState.runStatus };
          renderMeta(currentRun);
        }
        // Re-render step panel if the selected node was affected.
        if (selectedNodeId && event.node_id === selectedNodeId && !timelinePreviewing) {
          renderStepPanel(selectedNodeId);
        }
      },
      onClose: () => {
        currentStream = null;
        // Reload run metadata so finished_at / final status update from the DB.
        getRun(currentRunId).then((data) => {
          if (data?.run && currentRunId === data.run.id) {
            currentRun = data.run;
            renderMeta(currentRun);
          }
        }).catch(() => {});
      },
      onError: (info) => {
        // Soft notification — stream falls back to polling automatically.
        if (info?.phase === "polling") {
          setStatus(`Run stream lost; polling for updates: ${info.error?.message || ""}`.trim(), true);
        }
      },
    });
  }

  function renderMeta(run) {
    const status = STATUS_LABEL[run.status] || run.status;
    runsDetailMeta.innerHTML = `
      <div>
        <span class="runs-detail-title">${escapeHtml(run.workflow_id)}</span>
        <span class="runs-row-status runs-status-${escapeHtml(run.status)}">${escapeHtml(status)}</span>
      </div>
      <dl class="runs-detail-grid">
        <dt>Run ID</dt><dd><code>${escapeHtml(run.id)}</code></dd>
        ${run.fork_of_run_id ? `<dt>Forked from</dt><dd><button class="runs-parent-link" type="button" data-parent-run-id="${escapeHtml(run.fork_of_run_id)}">${escapeHtml(run.fork_of_run_id)}</button> at <code>${escapeHtml(run.fork_at_node_id || "")}</code></dd>` : ""}
        <dt>Chat</dt><dd><code>${escapeHtml(run.chat_id)}</code></dd>
        <dt>Mode</dt><dd>${escapeHtml(run.mode)}</dd>
        <dt>Started</dt><dd>${escapeHtml(formatTimestamp(run.created_at))}</dd>
        <dt>Finished</dt><dd>${escapeHtml(formatTimestamp(run.finished_at))}</dd>
        <dt>Duration</dt><dd>${escapeHtml(formatDuration(run.created_at, run.finished_at))}</dd>
        <dt>Initial input</dt><dd>${escapeHtml(run.initial_input || "—")}</dd>
      </dl>
    `;
  }

  function renderTimeline() {
    if (!runsTimeline) return;
    if (!timeline) {
      timeline = createTimelineSlider({
        host: runsTimeline,
        onChange: ({ position, live, user }) => {
          timelinePreviewing = Boolean(user && (!live || position < currentEvents.length));
          currentRunState = rebuildState(currentEvents, position);
          if (!timelinePreviewing && currentRun && currentRunState.runStatus !== "idle") {
            currentRun = { ...currentRun, status: currentRunState.runStatus };
            renderMeta(currentRun);
          }
          if (canvas) canvas.update(currentRunState);
          renderStepPanel(selectedNodeId);
        },
      });
    }
    if (timelineRunId !== currentRunId) {
      timelineRunId = currentRunId;
      timelinePreviewing = false;
      timeline.reset(currentEvents);
    } else {
      timeline.setEvents(currentEvents);
    }
  }

  function renderCanvas() {
    const canvasApi = ensureCanvas();
    if (!canvasApi) return;
    if (!currentWorkflow) {
      runsInspectorCanvas.innerHTML = `
        <p class="settings-empty">Workflow definition not available — showing event timeline only.</p>
      `;
      return;
    }
    canvasApi.render(currentWorkflow, currentRunState);
  }

  function renderStepPanel(nodeId) {
    if (!runsStepPanel) return;
    if (!nodeId) {
      runsStepPanel.innerHTML = '<p class="settings-empty">Click a node to inspect its step.</p>';
      return;
    }
    const steps = currentRunState ? stepsForNode(currentRunState, nodeId) : [];
    if (steps.length === 0) {
      const persisted = currentNodeStates.filter((item) => item.node_id === nodeId);
      if (persisted.length > 0) {
        const controls = renderRunControls(nodeId, { outputSnapshot: persisted.at(-1)?.output_snapshot });
        runsStepPanel.innerHTML = `
          <header class="runs-step-header">
            <span class="runs-step-node">${escapeHtml(nodeId)}</span>
            <span class="runs-step-count">${persisted.length} persisted state${persisted.length === 1 ? "" : "s"}</span>
          </header>
          ${controls}
          <div class="runs-step-list">${persisted.map(renderPersistedNodeState).join("")}</div>
        `;
        return;
      }
    }
    if (steps.length === 0) {
      runsStepPanel.innerHTML = `
        <header class="runs-step-header">
          <span class="runs-step-node">${escapeHtml(nodeId)}</span>
          <span class="runs-row-status runs-status-idle">Idle</span>
        </header>
        <p class="settings-empty">No execution recorded for this node yet.</p>
      `;
      return;
    }
    const controls = renderRunControls(nodeId, steps[steps.length - 1]);
    const blocks = steps.map((step, index) => renderStepBlock(step, index, steps.length)).join("");
    runsStepPanel.innerHTML = `
      <header class="runs-step-header">
        <span class="runs-step-node">${escapeHtml(nodeId)}</span>
        <span class="runs-step-count">${steps.length} execution${steps.length === 1 ? "" : "s"}</span>
      </header>
      ${controls}
      <div class="runs-step-list">${blocks}</div>
    `;
  }

  function renderRunControls(nodeId, step) {
    const canPause = currentRun?.status === "running";
    const canResume = currentRun?.status === "paused" || currentRun?.status === "needs_user";
    const canFork = Boolean(step?.outputSnapshot !== null && step?.outputSnapshot !== undefined && !isContainerNode(nodeId));
    return `
      <section class="runs-step-actions" data-selected-node="${escapeHtml(nodeId)}">
        ${canPause ? '<button type="button" class="settings-secondary-button" data-run-action="pause">Pause</button>' : ""}
        ${canResume ? `
          <textarea class="runs-resume-feedback" rows="3" placeholder="Optional feedback for resume"></textarea>
          <button type="button" class="settings-secondary-button" data-run-action="resume">Resume</button>
        ` : ""}
        <button type="button" class="settings-secondary-button" data-run-action="fork" ${canFork ? "" : "disabled"}>Fork from here</button>
        <button type="button" class="settings-secondary-button" data-run-action="replay-plan">Replay plan</button>
        <button type="button" class="settings-secondary-button" data-run-action="replay">Replay downstream</button>
      </section>
    `;
  }

  function isContainerNode(nodeId) {
    const node = currentWorkflow?.nodes?.find((item) => item.id === nodeId);
    return node?.type === "for_each" || node?.type === "while";
  }

  function renderStepBlock(step, index, total) {
    const llmCalls = step.childEvents.filter((event) => event.type === "llm_call");
    const toolCalls = step.childEvents.filter((event) => event.type === "tool_call");
    const status = step.status || (step.error ? "failed" : "running");
    const heading = total > 1 ? `Execution ${index + 1}/${total}` : "Execution";
    const durationLabel = Number.isFinite(step.durationMs) ? `${step.durationMs} ms` : "—";
    const inputText = snapshotToText(step.inputSnapshot);
    const outputText = snapshotToText(step.outputSnapshot);
    return `
      <article class="runs-step runs-step-${escapeHtml(status)}">
        <header class="runs-step-block-header">
          <span class="runs-step-heading">${escapeHtml(heading)}</span>
          <span class="runs-row-status runs-status-${escapeHtml(status)}">${escapeHtml(STATUS_LABEL[status] || status)}</span>
          <span class="runs-step-duration">${escapeHtml(durationLabel)}</span>
        </header>
        ${step.summary ? `<p class="runs-step-summary">${escapeHtml(step.summary)}</p>` : ""}
        ${step.error ? `<p class="runs-step-error">${escapeHtml(step.error)}</p>` : ""}
        ${step.prompt ? renderField("Node Instruction", step.prompt) : ""}
        ${inputText ? renderField("Input", inputText) : ""}
        ${outputText ? renderField("Output", outputText) : ""}
        ${renderLlmCalls(llmCalls)}
        ${renderToolCalls(toolCalls)}
      </article>
    `;
  }

  function renderPersistedNodeState(item) {
    const status = item.status || "done";
    const durationLabel = Number.isFinite(item.duration_ms) ? `${item.duration_ms} ms` : "—";
    const toolCalls = currentToolCalls.filter((call) => call.parent_step_id === item.step_id);
    return `
      <article class="runs-step runs-step-${escapeHtml(status)}">
        <header class="runs-step-block-header">
          <span class="runs-step-heading">${escapeHtml(item.node_type || "Node")}</span>
          <span class="runs-row-status runs-status-${escapeHtml(status)}">${escapeHtml(STATUS_LABEL[status] || status)}</span>
          <span class="runs-step-duration">${escapeHtml(durationLabel)}</span>
        </header>
        ${item.model_used ? `<p class="runs-step-summary">Model: ${escapeHtml(item.model_used)}</p>` : ""}
        ${item.prompt_snapshot ? renderField("Node Instruction", snapshotToText(item.prompt_snapshot)) : ""}
        ${item.input_snapshot ? renderField("Input", snapshotToText(item.input_snapshot)) : ""}
        ${item.output_snapshot ? renderField("Output", snapshotToText(item.output_snapshot)) : ""}
        ${renderPersistedToolCalls(toolCalls)}
      </article>
    `;
  }

  function renderField(label, value) {
    return `
      <details class="runs-step-field">
        <summary>${escapeHtml(label)}</summary>
        <pre>${escapeHtml(value)}</pre>
      </details>
    `;
  }

  function renderLlmCalls(events) {
    if (events.length === 0) return "";
    const items = events
      .map((event) => {
        const payload = event.payload || {};
        const tokens = [
          Number.isFinite(payload.tokens_in) ? `${payload.tokens_in} in` : null,
          Number.isFinite(payload.tokens_out) ? `${payload.tokens_out} out` : null,
        ].filter(Boolean).join(" · ");
        return `
          <li class="runs-llm-call">
            <header>
              <span class="runs-llm-model">${escapeHtml(payload.model || "model")}</span>
              <span class="runs-llm-meta">${escapeHtml(`${payload.duration_ms ?? "?"} ms${tokens ? " · " + tokens : ""}`)}</span>
            </header>
            ${payload.response ? renderField("Response", snapshotToText(payload.response)) : ""}
          </li>
        `;
      })
      .join("");
    return `<section class="runs-step-section"><h5>LLM calls (${events.length})</h5><ul class="runs-llm-list">${items}</ul></section>`;
  }

  function renderToolCalls(events) {
    if (events.length === 0) return "";
    const items = events
      .map((event) => {
        const payload = event.payload || {};
        return `
          <li class="runs-tool-call">
            <header>
              <span class="runs-tool-name">${escapeHtml(payload.tool_name || "tool")}</span>
              <span class="runs-llm-meta">${escapeHtml(`${payload.duration_ms ?? "?"} ms`)}</span>
            </header>
            ${payload.result ? renderField("Result", snapshotToText(payload.result)) : ""}
          </li>
        `;
      })
      .join("");
    return `<section class="runs-step-section"><h5>Tool calls (${events.length})</h5><ul class="runs-tool-list">${items}</ul></section>`;
  }

  function renderPersistedToolCalls(items) {
    if (items.length === 0) return "";
    const rendered = items
      .map((item) => `
        <li class="runs-tool-call">
          <header>
            <span class="runs-tool-name">${escapeHtml(item.tool_name || "tool")}</span>
            <span class="runs-llm-meta">${escapeHtml(`${item.duration_ms ?? "?"} ms · ${item.status || "done"}`)}</span>
          </header>
          ${item.arguments_snapshot ? renderField("Arguments", snapshotToText(item.arguments_snapshot)) : ""}
          ${item.result_snapshot ? renderField("Result", snapshotToText(item.result_snapshot)) : ""}
          ${item.error_snapshot ? renderField("Error", snapshotToText(item.error_snapshot)) : ""}
        </li>
      `)
      .join("");
    return `<section class="runs-step-section"><h5>Tool calls (${items.length})</h5><ul class="runs-tool-list">${rendered}</ul></section>`;
  }

  async function handleRunAction(action, nodeId) {
    if (!currentRunId || !action) return;
    try {
      if (action === "pause") {
        await pauseRun(currentRunId);
        setStatus("Pause requested; workflow will stop after the current step.");
        return;
      }
      if (action === "resume") {
        const feedback = runsStepPanel.querySelector(".runs-resume-feedback")?.value || "";
        await resumeRun(currentRunId, { feedback });
        await openRun(currentRunId);
        return;
      }
      if (action === "fork") {
        await openForkPrompt(nodeId);
      }
      if (action === "replay-plan") {
        const response = await planReplay(currentRunId, { startNodeId: nodeId, scope: "downstream" });
        const plan = response?.plan || {};
        if (plan.can_replay) {
          setStatus(`Replay plan ready for ${plan.replay_node_ids?.length || 0} node(s).`);
        } else {
          const firstBlocker = Array.isArray(plan.blockers) && plan.blockers.length ? `: ${plan.blockers[0]}` : "";
          setStatus(`Replay is blocked${firstBlocker}`, true);
        }
      }
      if (action === "replay") {
        const response = await replayRun(currentRunId, { startNodeId: nodeId, scope: "downstream" });
        const newRunId = response?.run_id;
        if (newRunId) await openRunInInspector(newRunId);
      }
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function openForkPrompt(nodeId) {
    const step = stepsForNode(currentRunState, nodeId).at(-1);
    if (!step) return;
    const original = snapshotToText(step.outputSnapshot);
    const edited = await openForkModal(original);
    if (edited === null) return;
    const editedOutput = parseEditedOutput(edited);
    const response = await forkRun(currentRunId, { fromStepId: nodeId, editedOutput });
    const newRunId = response?.run_id;
    if (newRunId) await openRunInInspector(newRunId);
  }

  function parseEditedOutput(text) {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }

  function openForkModal(initialText) {
    return new Promise((resolve) => {
      const backdrop = document.createElement("div");
      backdrop.className = "runs-fork-modal-backdrop";
      // Build the chrome via innerHTML, but populate the textarea via `.value`
      // so HTML entities in the initial text (e.g. `&`) are not double-encoded.
      backdrop.innerHTML = `
        <section class="runs-fork-modal" role="dialog" aria-modal="true" aria-labelledby="runs-fork-title">
          <header>
            <h3 id="runs-fork-title">Fork from here</h3>
            <button type="button" class="settings-secondary-button" data-fork-cancel>Cancel</button>
          </header>
          <textarea class="runs-fork-editor" rows="14"></textarea>
          <footer>
            <button type="button" class="settings-secondary-button" data-fork-cancel>Cancel</button>
            <button type="button" class="secondary-button" data-fork-submit>Create fork</button>
          </footer>
        </section>
      `;
      document.body.appendChild(backdrop);
      const editor = backdrop.querySelector(".runs-fork-editor");
      if (editor) editor.value = initialText ?? "";
      editor?.focus();
      editor?.select();
      function close(value) {
        backdrop.remove();
        resolve(value);
      }
      backdrop.addEventListener("click", (event) => {
        if (event.target === backdrop || event.target.closest("[data-fork-cancel]")) close(null);
        if (event.target.closest("[data-fork-submit]")) close(editor?.value || "");
      });
      backdrop.addEventListener("keydown", (event) => {
        if (event.key === "Escape") close(null);
      });
    });
  }

  function init() {
    runsList?.addEventListener("click", (event) => {
      const parent = event.target.closest("[data-parent-run-id]");
      if (parent) {
        event.preventDefault();
        openRun(parent.dataset.parentRunId);
        return;
      }
      const row = event.target.closest("[data-run-id]");
      if (!row) return;
      event.preventDefault();
      openRun(row.dataset.runId);
    });
    runsDetailMeta?.addEventListener("click", (event) => {
      const target = event.target.closest("[data-parent-run-id]");
      if (target) openRun(target.dataset.parentRunId);
    });
    runsStepPanel?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-run-action]");
      if (!button) return;
      const nodeId = event.target.closest("[data-selected-node]")?.dataset.selectedNode || selectedNodeId;
      handleRunAction(button.dataset.runAction, nodeId);
    });
    runsDetailBack?.addEventListener("click", () => {
      showList();
    });
    runsRefresh?.addEventListener("click", () => {
      loadRuns();
    });
    runsFilterStatus?.addEventListener("change", () => {
      loadRuns();
    });
    document.querySelectorAll('[data-settings-section="runs"]').forEach((button) => {
      button.addEventListener("click", () => {
        if (!loaded || currentRunId === null) {
          loadRuns();
        }
      });
    });
  }

  async function openRunInInspector(runId) {
    // Make sure the settings panel is open and the Runs section is active.
    const settingsToggle = document.querySelector("#settings-toggle");
    const navButton = document.querySelector('.settings-nav-button[data-settings-section="runs"]');
    const settingsPanel = document.querySelector("#settings-panel");
    if (settingsPanel?.getAttribute("aria-hidden") === "true") {
      settingsToggle?.click();
    }
    navButton?.click();
    await openRun(runId);
  }

  return { init, loadRuns, openRun, openRunInInspector };
}
