import { clampInt, clampLength, escapeHtml, slugifyWorkflowId } from "../helpers.js";
import { state } from "../state.js";
import { dedupeList, parseCsvList } from "../workflow-editor.js";
import {
  CANVAS_PAD,
  NODE_GRID_X,
  deriveNodeTypeFromRole,
  deriveWorkflowEdgesFromNodes,
  ensureWorkflowBoundaryNodes,
  isBoundaryNode,
  newWorkflowDraftFrom,
  nodeOutputIdentifier,
  normalizeWorkflowDraft,
  normalizeWorkflowNodes,
  realWorkflowNodes,
  updateDownstreamInputReferences,
} from "../workflow-builder.js";

const WORKFLOW_NAME_MAX = 200;
const WORKFLOW_DESCRIPTION_MAX = 1000;
const WORKFLOW_FIELD_MAX = 120;

export function createWorkflowInspector({
  workflowSection,
  workflowListView,
  workflowBuilderView,
  workflowBuilderTitle,
  workflowChat,
  workflowCode,
  workflowAgentic,
  workflowPresetList,
  workflowEditorDelete,
  workflowEditorId,
  workflowEditorName,
  workflowEditorDescription,
  workflowEditorExecution,
  workflowEditorMaxIterations,
  workflowEditorModeChat,
  workflowEditorModeCode,
  workflowEditorModeAgentic,
  workflowEditorAssignChat,
  workflowEditorAssignCode,
  workflowEditorAssignAgentic,
  workflowCanvasNodes,
  workflowNodeEditPanel,
  workflowNodeEditTitle,
  nodeEditId,
  nodeEditTitleInput,
  nodeEditRole,
  nodeEditReceive,
  nodeEditReports,
  nodeEditInput,
  nodeEditOutput,
  nodeEditWorkers,
  nodeEditMaxItems,
  nodeEditJson,
  getSettingsUi,
  canvas,
}) {
  function workflowPresetsForMode(mode) {
    return state.workflowPresets.filter((workflow) => {
      const modes = Array.isArray(workflow.modes) && workflow.modes.length > 0 ? workflow.modes : [workflow.mode];
      return modes.includes(mode);
    });
  }

  function workflowById(workflowId) {
    return state.workflowPresets.find((workflow) => workflow.id === workflowId) || null;
  }

  function isCustomWorkflow(workflowId) {
    return state.customWorkflowIds.includes(workflowId);
  }

  function nodeRoleSelectOptionsHtml(selectedRole) {
    const roles = Array.isArray(state.roles) ? state.roles : [];
    const matchKey = String(selectedRole || "").trim().toLowerCase();
    const options = roles
      .map((role) => {
        const display = String(role.name || "").toLowerCase();
        const isSelected = display === matchKey ? " selected" : "";
        return `<option value="${escapeHtml(display)}"${isSelected}>${escapeHtml(display)}</option>`;
      })
      .join("");
    const known = new Set(roles.map((role) => String(role.name || "").toLowerCase()));
    const orphanOption = matchKey && !known.has(matchKey)
      ? `<option value="${escapeHtml(matchKey)}" selected>${escapeHtml(matchKey)} (missing)</option>`
      : "";
    const placeholderSelected = matchKey ? "" : " selected";
    return `<option value=""${placeholderSelected}>Select role…</option>${orphanOption}${options}`;
  }

  function workflowOptionsHtml(mode, selected) {
    const workflows = workflowPresetsForMode(mode);
    const options = workflows
      .map((workflow) => `<option value="${escapeHtml(workflow.id)}"${workflow.id === selected ? " selected" : ""}>${escapeHtml(workflow.name)}</option>`)
      .join("");
    const selectedExists = workflows.some((workflow) => workflow.id === selected);
    const customOption = selected && !selectedExists
      ? `<option value="${escapeHtml(selected)}" selected>${escapeHtml(selected)}</option>`
      : "";
    return `${customOption}${options}`;
  }

  function renderWorkflowSettings() {
    if (!state.settings || !workflowChat || !workflowCode || !workflowAgentic) return;
    const selected = state.settings.workflow_presets || {};
    workflowChat.innerHTML = workflowOptionsHtml("chat", selected.chat || "simple");
    workflowCode.innerHTML = workflowOptionsHtml("code", selected.code || "simple");
    workflowAgentic.innerHTML = workflowOptionsHtml("agentic", selected.agentic || "simple");
    renderWorkflowPresetList();
    renderWorkflowEditor();
    getSettingsUi()?.updateSettingsDirtyState();
  }

  function renderWorkflowPresetList() {
    if (!workflowPresetList) return;
    workflowPresetList.innerHTML = "";
    if (state.workflowPresets.length === 0) {
      workflowPresetList.innerHTML = '<p class="settings-empty">No workflow presets found.</p>';
      return;
    }
    state.workflowPresets.forEach((workflow) => {
      const item = document.createElement("article");
      item.className = "workflow-preset-item";
      item.dataset.workflowId = workflow.id;
      const nodes = normalizeWorkflowNodes(workflow);
      const listedNodes = realWorkflowNodes(nodes);
      const modes = Array.isArray(workflow.modes) && workflow.modes.length > 0 ? workflow.modes : [workflow.mode];
      const customBadge = isCustomWorkflow(workflow.id) ? " · custom" : "";
      item.innerHTML = `
        <div class="workflow-preset-head">
          <div>
            <strong>${escapeHtml(workflow.name)}</strong>
            <small>${escapeHtml(modes.join(", "))} · ${escapeHtml(workflow.execution)} · ${escapeHtml(workflow.max_iterations || 1)} iteration(s)${customBadge}</small>
          </div>
          <button class="icon-button workflow-preset-edit" type="button" aria-label="Edit workflow" title="Edit">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 20l4-1 11-11-3-3-11 11-1 4z" />
              <path d="M14 6l3 3" />
            </svg>
          </button>
        </div>
        <p>${escapeHtml(workflow.description || "")}</p>
        <div class="workflow-node-list">
          ${listedNodes.map((node) => `<span>${escapeHtml(node.title || node.role || node.type || node.id)}</span>`).join("")}
        </div>
        <div class="workflow-graph-preview">
          ${canvas.workflowGraphMarkup(normalizeWorkflowDraft(workflow), true)}
        </div>
      `;
      workflowPresetList.append(item);
    });
  }

  function activeWorkflowDraft() {
    if (state.workflowEditorDraft) return state.workflowEditorDraft;
    const first = state.workflowPresets[0] || null;
    state.workflowEditorDraft = first ? newWorkflowDraftFrom(first) : null;
    return state.workflowEditorDraft;
  }

  function renderWorkflowEditor() {
    const draft = activeWorkflowDraft();
    if (!draft) return;
    if (workflowEditorDelete) workflowEditorDelete.disabled = !isCustomWorkflow(draft.id);
    workflowEditorId.value = draft.id || "";
    workflowEditorName.value = draft.name || "";
    workflowEditorDescription.value = draft.description || "";
    workflowEditorExecution.value = draft.execution || "loop";
    workflowEditorMaxIterations.value = String(Math.max(1, Number(draft.max_iterations || 1)));
    workflowEditorModeChat.checked = draft.modes.includes("chat");
    workflowEditorModeCode.checked = draft.modes.includes("code");
    workflowEditorModeAgentic.checked = draft.modes.includes("agentic");
    const selected = state.settings?.workflow_presets || {};
    workflowEditorAssignChat.checked = selected.chat === draft.id;
    workflowEditorAssignCode.checked = selected.code === draft.id;
    workflowEditorAssignAgentic.checked = selected.agentic === draft.id;
    if (workflowBuilderTitle) {
      workflowBuilderTitle.textContent = draft.name || draft.id || "Edit Workflow";
    }
    canvas.renderWorkflowCanvas();
  }

  function showWorkflowListView() {
    state.workflowEditorView = "list";
    state.workflowEditorSelectedNodeId = null;
    workflowSection?.setAttribute("data-workflow-view", "list");
    if (workflowListView) workflowListView.hidden = false;
    if (workflowBuilderView) workflowBuilderView.hidden = true;
    closeNodeEditPanel();
  }

  function showWorkflowBuilderView(workflowId = null) {
    const source = workflowId ? workflowById(workflowId) : null;
    if (workflowId && !source) return;
    state.workflowEditorDraft = source ? newWorkflowDraftFrom(source) : blankCustomWorkflowDraft();
    state.workflowEditorView = "builder";
    state.workflowEditorSelectedNodeId = null;
    workflowSection?.setAttribute("data-workflow-view", "builder");
    if (workflowListView) workflowListView.hidden = true;
    if (workflowBuilderView) workflowBuilderView.hidden = false;
    closeNodeEditPanel();
    renderWorkflowEditor();
  }

  function blankCustomWorkflowDraft() {
    return {
      id: nextAvailableCustomId(),
      name: "My Workflow",
      description: "",
      mode: "chat",
      modes: ["chat", "code", "agentic"],
      execution: "loop",
      max_iterations: 1,
      edges: [],
      nodes: ensureWorkflowBoundaryNodes([
        {
          id: "orchestrator",
          type: "role",
          role: "orchestrator",
          title: "Orchestrator",
          input: [],
          output: "",
          max_parallel: 1,
          max_items: 4,
          expects_json: false,
          receive_from: [],
          reports_to: [],
          worker_instances: 1,
          position: { x: CANVAS_PAD + NODE_GRID_X, y: CANVAS_PAD },
          config: {},
        },
      ]),
    };
  }

  function nextAvailableCustomId() {
    const taken = new Set(state.workflowPresets.map((wf) => wf.id));
    let candidate = "custom_workflow";
    let n = 1;
    while (taken.has(candidate)) {
      n += 1;
      candidate = `custom_workflow_${n}`;
    }
    return candidate;
  }

  function selectWorkflowNode(nodeId) {
    if (!workflowNodeEditPanel) return;
    const draft = activeWorkflowDraft();
    const node = draft?.nodes.find((n) => n.id === nodeId);
    if (node && isBoundaryNode(node)) {
      closeNodeEditPanel();
      return;
    }
    if (!node) {
      closeNodeEditPanel();
      return;
    }
    state.workflowEditorSelectedNodeId = node.id;
    workflowNodeEditPanel.hidden = false;
    workflowNodeEditPanel.setAttribute("aria-hidden", "false");
    if (workflowNodeEditTitle) workflowNodeEditTitle.textContent = node.title || node.id;
    nodeEditId.value = node.id;
    nodeEditTitleInput.value = node.title || "";
    nodeEditRole.innerHTML = nodeRoleSelectOptionsHtml(node.role);
    nodeEditReceive.value = (node.receive_from || []).join(", ");
    nodeEditReports.value = (node.reports_to || []).join(", ");
    nodeEditInput.value = (node.input || []).join(", ");
    nodeEditOutput.value = node.output || "";
    const workerCount = Math.max(1, Number(node.worker_instances || node.max_parallel || 1));
    nodeEditWorkers.value = String(workerCount);
    nodeEditMaxItems.value = String(Math.max(1, Number(node.max_items || 4)));
    nodeEditJson.checked = Boolean(node.expects_json);
    workflowCanvasNodes
      ?.querySelectorAll(".workflow-canvas-node.is-selected")
      .forEach((el) => el.classList.remove("is-selected"));
    workflowCanvasNodes
      ?.querySelector(`.workflow-canvas-node[data-node-id="${canvas.cssEscape(node.id)}"]`)
      ?.classList.add("is-selected");
  }

  function closeNodeEditPanel() {
    state.workflowEditorSelectedNodeId = null;
    if (workflowNodeEditPanel) {
      workflowNodeEditPanel.hidden = true;
      workflowNodeEditPanel.setAttribute("aria-hidden", "true");
    }
    workflowCanvasNodes
      ?.querySelectorAll(".workflow-canvas-node.is-selected")
      .forEach((el) => el.classList.remove("is-selected"));
  }

  function collectWorkflowDraftFromEditor() {
    const previous = activeWorkflowDraft();
    if (!previous) return null;
    const modes = [];
    if (workflowEditorModeChat.checked) modes.push("chat");
    if (workflowEditorModeCode.checked) modes.push("code");
    if (workflowEditorModeAgentic.checked) modes.push("agentic");
    const normalizedModes = modes.length > 0 ? modes : ["chat"];
    const rawId = workflowEditorId.value || previous.id || workflowEditorName.value;
    previous.id = slugifyWorkflowId(rawId) || previous.id || "custom_workflow";
    previous.name = clampLength(workflowEditorName.value.trim() || "Custom Workflow", WORKFLOW_NAME_MAX);
    previous.description = clampLength(workflowEditorDescription.value.trim(), WORKFLOW_DESCRIPTION_MAX);
    previous.mode = normalizedModes[0];
    previous.modes = normalizedModes;
    previous.execution = workflowEditorExecution.value === "direct" ? "direct" : "loop";
    previous.max_iterations = clampInt(workflowEditorMaxIterations.value, 1, 8);
    workflowEditorId.value = previous.id;
    if (workflowBuilderTitle) workflowBuilderTitle.textContent = previous.name || previous.id;
    return previous;
  }

  function syncSelectedNodeRoleOptions() {
    if (!state.workflowEditorSelectedNodeId) return;
    const node = activeWorkflowDraft()?.nodes.find((n) => n.id === state.workflowEditorSelectedNodeId);
    if (node && nodeEditRole) nodeEditRole.innerHTML = nodeRoleSelectOptionsHtml(node.role);
  }

  function applyNodeEditChanges() {
    const draft = activeWorkflowDraft();
    const selectedId = state.workflowEditorSelectedNodeId;
    if (!draft || !selectedId) return;
    const node = draft.nodes.find((n) => n.id === selectedId);
    if (!node) return;
    const otherIds = new Set(draft.nodes.filter((n) => n !== node).map((n) => n.id));
    const desiredId = slugifyWorkflowId(nodeEditId.value) || node.id;
    const safeId = otherIds.has(desiredId) ? node.id : desiredId;
    const oldId = node.id;
    const previousOutputIdentifier = nodeOutputIdentifier(node);
    node.id = safeId;
    node.title = clampLength(nodeEditTitleInput.value.trim(), WORKFLOW_NAME_MAX);
    const chosenRole = String(nodeEditRole.value || "").trim();
    node.role = clampLength(chosenRole || "orchestrator", WORKFLOW_FIELD_MAX);
    const workers = clampInt(nodeEditWorkers.value, 1, 8);
    const previousType = String(node.type || "").toLowerCase();
    node.type = previousType === "answer" ? "answer" : deriveNodeTypeFromRole(node.role, workers);
    node.receive_from = dedupeList(parseCsvList(nodeEditReceive.value));
    node.reports_to = dedupeList(parseCsvList(nodeEditReports.value));
    node.input = parseCsvList(nodeEditInput.value);
    node.output = clampLength(nodeEditOutput.value.trim(), WORKFLOW_FIELD_MAX);
    node.worker_instances = node.type === "worker_pool" ? workers : 1;
    node.max_parallel = workers;
    node.max_items = clampInt(nodeEditMaxItems.value, 1, 12);
    node.expects_json = Boolean(nodeEditJson.checked);
    const nextOutputIdentifier = nodeOutputIdentifier(node);
    if (safeId !== oldId) {
      draft.nodes.forEach((other) => {
        if (other === node) return;
        other.receive_from = (other.receive_from || []).map((r) => (r === oldId ? safeId : r));
        other.reports_to = (other.reports_to || []).map((r) => (r === oldId ? safeId : r));
      });
      draft.edges = (draft.edges || []).map((edge) => ({
        ...edge,
        from: (edge.from || edge.from_node) === oldId ? safeId : (edge.from || edge.from_node),
        to: edge.to === oldId ? safeId : edge.to,
      }));
      state.workflowEditorSelectedNodeId = safeId;
    }
    updateDownstreamInputReferences(draft, safeId, previousOutputIdentifier, nextOutputIdentifier);
    if (workflowNodeEditTitle) workflowNodeEditTitle.textContent = node.title || node.id;
    canvas.renderWorkflowCanvas();
  }

  return {
    activeWorkflowDraft,
    workflowById,
    isCustomWorkflow,
    nodeRoleSelectOptionsHtml,
    renderWorkflowSettings,
    renderWorkflowPresetList,
    renderWorkflowEditor,
    showWorkflowListView,
    showWorkflowBuilderView,
    selectWorkflowNode,
    closeNodeEditPanel,
    collectWorkflowDraftFromEditor,
    syncSelectedNodeRoleOptions,
    applyNodeEditChanges,
  };
}
