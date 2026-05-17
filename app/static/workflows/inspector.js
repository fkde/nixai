import { clampInt, clampLength, escapeHtml, slugifyWorkflowId } from "../helpers.js";
import { state } from "../state.js";
import { dedupeList, parseCsvList } from "../workflow-editor.js";
import {
  CANVAS_PAD,
  NODE_GRID_X,
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
const NODE_TYPE_DEFINITIONS = [
  {
    type: "role",
    label: "Agent",
    description: "Single role-prompt node for planning, synthesis, or custom work.",
    defaults: { id: "agent", title: "Agent", role: "orchestrator", output: "agent_result" },
  },
  {
    type: "worker_pool",
    label: "Worker Pool",
    description: "Parallel workers over a list input; worker count is capped by the UI.",
    defaults: { id: "workers", title: "Workers", role: "worker", input: ["plan.work_items"], output: "worker_reports", max_items: 4, worker_instances: 2, max_parallel: 2 },
  },
  {
    type: "reviewer",
    label: "Reviewer",
    description: "Critiques or consolidates prior outputs before a decision.",
    defaults: { id: "reviewer", title: "Review", role: "reviewer", input: ["plan", "worker_reports"], output: "review", expects_json: true },
  },
  {
    type: "judge",
    label: "Judge",
    description: "Returns decision.status values used by connection rules.",
    defaults: { id: "judge", title: "Judge", role: "judge", input: ["plan", "worker_reports", "review"], output: "decision", expects_json: true },
  },
  {
    type: "pause",
    label: "Ask User",
    description: "Pauses the run and waits for user feedback before continuing.",
    defaults: { id: "ask_user", title: "Ask User", role: "", input: ["decision"], output: "pause", prompt: "" },
  },
  {
    type: "answer",
    label: "Answer",
    description: "Synthesizes the final user-facing response.",
    defaults: { id: "answer", title: "Answer", role: "orchestrator", input: ["plan", "worker_reports", "review", "decision"], output: "final_answer" },
  },
  {
    type: "tool_agent",
    label: "Tool Agent",
    description: "Runs the Agentic runner with approved web/code/MCP-style tools.",
    defaults: { id: "research", title: "Research", role: "orchestrator", input: [], output: "research_result", prompt: "Research the task and return grounded findings." },
  },
  {
    type: "for_each",
    label: "For Each",
    description: "Iterates over an input list using body nodes configured in JSON.",
    defaults: { id: "for_each", title: "For Each", role: "", input: ["plan.work_items"], output: "iteration_results", config: { body: [] } },
  },
  {
    type: "while",
    label: "While",
    description: "Repeats body nodes until a safe break condition becomes true.",
    defaults: { id: "while_loop", title: "While", role: "", input: [], output: "while_result", break_when: "decision.status == 'done'", config: { body: [] } },
  },
  {
    type: "workflow",
    label: "Sub Workflow",
    description: "Runs another saved workflow by id as a reusable block.",
    defaults: { id: "sub_workflow", title: "Sub Workflow", role: "", input: [], output: "workflow_result", ref: "deep_orchestra" },
  },
];

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
  nodeEditType,
  nodeEditRef,
  nodeEditPrompt,
  nodeEditBody,
  nodeEditRetryMax,
  nodeEditRetryBackoff,
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
  function nodeTypeDefinition(type) {
    const clean = String(type || "role").trim().toLowerCase();
    return NODE_TYPE_DEFINITIONS.find((item) => item.type === clean) || NODE_TYPE_DEFINITIONS[0];
  }

  function nodeTypeOptionsHtml(selectedType) {
    const selected = String(selectedType || "role").trim().toLowerCase();
    return NODE_TYPE_DEFINITIONS
      .map((item) => `<option value="${escapeHtml(item.type)}"${item.type === selected ? " selected" : ""}>${escapeHtml(item.label)}</option>`)
      .join("");
  }

  function nodeTypeLabel(type) {
    return nodeTypeDefinition(type).label;
  }

  function nodeTypeDefaults(type) {
    const defaults = nodeTypeDefinition(type).defaults;
    return {
      ...defaults,
      input: Array.isArray(defaults.input) ? [...defaults.input] : [],
      config: typeof defaults.config === "object" && defaults.config ? JSON.parse(JSON.stringify(defaults.config)) : {},
    };
  }

  function nextNodeId(draft, baseId) {
    const taken = new Set((draft?.nodes || []).map((node) => node.id));
    const cleanBase = slugifyWorkflowId(baseId || "node") || "node";
    if (!taken.has(cleanBase)) return cleanBase;
    let n = 2;
    let candidate = `${cleanBase}_${n}`;
    while (taken.has(candidate)) {
      n += 1;
      candidate = `${cleanBase}_${n}`;
    }
    return candidate;
  }

  function nextNodePosition(draft) {
    const existingNodes = realWorkflowNodes(draft?.nodes || []);
    const lastPos = existingNodes[existingNodes.length - 1]?.position || { x: CANVAS_PAD + NODE_GRID_X, y: CANVAS_PAD };
    return { x: lastPos.x + NODE_GRID_X, y: lastPos.y };
  }

  function createNodeForType(draft, type) {
    const defaults = nodeTypeDefaults(type);
    const cleanType = nodeTypeDefinition(type).type;
    const id = nextNodeId(draft, defaults.id || cleanType);
    return {
      id,
      type: cleanType,
      role: defaults.role || "",
      title: defaults.title || nodeTypeLabel(cleanType),
      prompt: defaults.prompt || "",
      input: Array.isArray(defaults.input) ? [...defaults.input] : [],
      output: defaults.output || id,
      max_parallel: Math.min(8, Math.max(1, Number(defaults.max_parallel || 1))),
      max_items: Math.min(12, Math.max(1, Number(defaults.max_items || 4))),
      expects_json: Boolean(defaults.expects_json),
      receive_from: [],
      reports_to: [],
      worker_instances: Math.min(8, Math.max(1, Number(defaults.worker_instances || defaults.max_parallel || 1))),
      position: nextNodePosition(draft),
      config: typeof defaults.config === "object" && defaults.config ? { ...defaults.config } : {},
      retry: { max: 0, backoff: 0 },
      break_when: defaults.break_when || "",
      ref: defaults.ref || "",
    };
  }

  function addWorkflowNode(type = "role") {
    const draft = activeWorkflowDraft();
    if (!draft) return null;
    const node = createNodeForType(draft, type);
    draft.nodes.push(node);
    state.workflowEditorDraft = {
      ...draft,
      nodes: ensureWorkflowBoundaryNodes(draft.nodes),
    };
    canvas.renderWorkflowCanvas();
    selectWorkflowNode(node.id);
    return node;
  }

  function closeNodeTypeMenu() {
    document.querySelector(".workflow-node-type-menu")?.remove();
    document.removeEventListener("pointerdown", handleNodeTypeMenuOutside);
  }

  function handleNodeTypeMenuOutside(event) {
    const menu = document.querySelector(".workflow-node-type-menu");
    if (!menu) return;
    if (menu.contains(event.target)) return;
    closeNodeTypeMenu();
  }

  function openNodeTypeMenu(anchor) {
    const draft = activeWorkflowDraft();
    if (!draft || !anchor) return;
    closeNodeTypeMenu();
    const rect = anchor.getBoundingClientRect();
    const menu = document.createElement("div");
    menu.className = "workflow-node-type-menu";
    menu.style.top = `${rect.bottom + 8}px`;
    menu.style.left = `${Math.max(12, Math.min(window.innerWidth - 372, rect.right - 360))}px`;
    menu.innerHTML = `
      <strong>Add Node</strong>
      <div class="workflow-node-type-grid">
        ${NODE_TYPE_DEFINITIONS.map((item) => `
          <button type="button" class="workflow-node-type-option" data-node-type="${escapeHtml(item.type)}">
            <span>${escapeHtml(item.label)}</span>
            <small>${escapeHtml(item.description)}</small>
          </button>
        `).join("")}
      </div>
    `;
    menu.addEventListener("click", (event) => {
      const option = event.target.closest?.(".workflow-node-type-option");
      if (!option) return;
      addWorkflowNode(option.dataset.nodeType || "role");
      closeNodeTypeMenu();
    });
    document.body.append(menu);
    const menuRect = menu.getBoundingClientRect();
    menu.style.top = `${Math.max(12, Math.min(rect.bottom + 8, window.innerHeight - menuRect.height - 12))}px`;
    setTimeout(() => document.addEventListener("pointerdown", handleNodeTypeMenuOutside), 0);
  }

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
          prompt: "",
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
    const retry = typeof node.retry === "object" && node.retry ? node.retry : {};
    nodeEditId.value = node.id;
    nodeEditTitleInput.value = node.title || "";
    nodeEditType.innerHTML = nodeTypeOptionsHtml(node.type);
    nodeEditType.value = nodeTypeDefinition(node.type).type;
    nodeEditRef.value = String(node.type || "").toLowerCase() === "while" ? (node.break_when || "") : (node.ref || "");
    nodeEditPrompt.value = node.prompt || "";
    nodeEditBody.value = Array.isArray(node.config?.body) ? node.config.body.join(", ") : "";
    nodeEditRetryMax.value = String(Math.max(0, Number(retry.max || 0)));
    nodeEditRetryBackoff.value = String(Math.max(0, Number(retry.backoff || 0)));
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
    const previousTitle = node.title || "";
    node.id = safeId;
    node.title = clampLength(nodeEditTitleInput.value.trim(), WORKFLOW_NAME_MAX);
    const previousType = String(node.type || "").toLowerCase();
    const selectedType = nodeTypeDefinition(nodeEditType?.value || previousType).type;
    if (selectedType !== previousType) {
      const defaults = nodeTypeDefaults(selectedType);
      const previousDefaults = nodeTypeDefaults(previousType);
      node.type = selectedType;
      node.role = defaults.role || node.role || "";
      if (!node.title || previousTitle === previousDefaults.title || previousTitle === nodeTypeLabel(previousType)) {
        node.title = defaults.title || nodeTypeLabel(selectedType);
        nodeEditTitleInput.value = node.title;
      }
      node.output = defaults.output || node.output || safeId;
      node.input = Array.isArray(defaults.input) ? [...defaults.input] : [];
      node.prompt = defaults.prompt || "";
      node.expects_json = Boolean(defaults.expects_json);
      node.worker_instances = Math.min(8, Math.max(1, Number(defaults.worker_instances || defaults.max_parallel || 1)));
      node.max_parallel = Math.min(8, Math.max(1, Number(defaults.max_parallel || node.worker_instances || 1)));
      node.max_items = Math.min(12, Math.max(1, Number(defaults.max_items || node.max_items || 4)));
      node.config = typeof defaults.config === "object" && defaults.config ? { ...defaults.config } : {};
      node.break_when = defaults.break_when || "";
      node.ref = defaults.ref || "";
      nodeEditRole.innerHTML = nodeRoleSelectOptionsHtml(node.role);
      nodeEditInput.value = (node.input || []).join(", ");
      nodeEditOutput.value = node.output || "";
      nodeEditWorkers.value = String(Math.max(1, Number(node.worker_instances || node.max_parallel || 1)));
      nodeEditMaxItems.value = String(Math.max(1, Number(node.max_items || 4)));
      nodeEditJson.checked = Boolean(node.expects_json);
      nodeEditPrompt.value = node.prompt || "";
      nodeEditRef.value = selectedType === "while" ? node.break_when : node.ref;
      nodeEditBody.value = Array.isArray(node.config?.body) ? node.config.body.join(", ") : "";
    } else {
      node.type = selectedType;
    }
    const chosenRole = String(nodeEditRole.value || "").trim();
    node.role = clampLength(chosenRole || nodeTypeDefaults(node.type).role || "", WORKFLOW_FIELD_MAX);
    const workers = clampInt(nodeEditWorkers.value, 1, 8);
    node.prompt = clampLength(nodeEditPrompt?.value || "", WORKFLOW_DESCRIPTION_MAX);
    const refValue = clampLength(nodeEditRef?.value || "", WORKFLOW_FIELD_MAX);
    node.break_when = node.type === "while" ? refValue : "";
    node.ref = node.type === "workflow" ? refValue : "";
    node.config = typeof node.config === "object" && node.config ? node.config : {};
    const bodyNodes = parseCsvList(nodeEditBody?.value || "");
    if (node.type === "for_each" || node.type === "while") {
      node.config.body = bodyNodes;
    } else {
      delete node.config.body;
    }
    node.retry = {
      max: clampInt(nodeEditRetryMax?.value || 0, 0, 5),
      backoff: Math.min(60, Math.max(0, Number(nodeEditRetryBackoff?.value || 0))),
    };
    node.receive_from = dedupeList(parseCsvList(nodeEditReceive.value));
    node.reports_to = dedupeList(parseCsvList(nodeEditReports.value));
    node.input = parseCsvList(nodeEditInput.value);
    node.output = clampLength(nodeEditOutput.value.trim(), WORKFLOW_FIELD_MAX);
    node.worker_instances = node.type === "worker_pool" ? workers : 1;
    node.max_parallel = node.type === "worker_pool" ? workers : 1;
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
    openNodeTypeMenu,
    addWorkflowNode,
    applyNodeEditChanges,
  };
}
