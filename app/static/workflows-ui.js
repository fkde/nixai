import { api } from "./api.js";
import { dom } from "./dom.js";
import { clampInt, clampLength, escapeHtml, slugifyWorkflowId } from "./helpers.js";
import { state } from "./state.js";
import { dedupeList, parseCsvList } from "./workflow-editor.js";
import { modeOrder } from "./ui.js";

const {
  workflowSection,
  workflowListView,
  workflowBuilderView,
  workflowBuilderBack,
  workflowBuilderTitle,
  workflowChat,
  workflowCode,
  workflowAgentic,
  workflowPresetList,
  workflowEditorNew,
  workflowEditorDelete,
  workflowEditorSave,
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
  workflowEditorSaveAssign,
  workflowEditorAddNode,
  workflowCanvas,
  workflowCanvasNodes,
  workflowCanvasEdges,
  workflowCanvasEdgeLayer,
  workflowNodeEditPanel,
  workflowNodeEditTitle,
  workflowNodeEditClose,
  workflowNodeEditRemove,
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
} = dom;

const WORKFLOW_NAME_MAX = 200;
const WORKFLOW_DESCRIPTION_MAX = 1000;
const WORKFLOW_FIELD_MAX = 120;

const NODE_TILE_WIDTH = 168;
const NODE_TILE_HEIGHT = 78;
const NODE_GRID_X = 220;
const NODE_GRID_Y = 130;
const CANVAS_PAD = 24;
const DRAG_THRESHOLD = 4;

export function createWorkflowsUi({ setStatus, getSettingsUi }) {
  const canvasDrag = { id: null, tile: null, originX: 0, originY: 0, pointerX: 0, pointerY: 0, moved: false };

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

  function normalizeWorkflowNodes(workflow) {
    const nodes = (Array.isArray(workflow?.nodes) ? workflow.nodes : []).map((node, index) => {
      const inputValues = Array.isArray(node.input)
        ? node.input.map((item) => String(item).trim()).filter(Boolean)
        : String(node.input || "").trim()
          ? [String(node.input || "").trim()]
          : [];
      const rawPos = node.position && typeof node.position === "object" ? node.position : {};
      const px = Number(rawPos.x);
      const py = Number(rawPos.y);
      return {
        id: String(node.id || `node_${index + 1}`),
        type: String(node.type || "role"),
        role: String(node.role || ""),
        title: String(node.title || ""),
        input: inputValues,
        output: String(node.output || ""),
        max_parallel: Math.min(8, Math.max(1, Number(node.max_parallel || 1))),
        max_items: Math.min(12, Math.max(1, Number(node.max_items || 4))),
        expects_json: Boolean(node.expects_json),
        receive_from: dedupeList(
          Array.isArray(node.receive_from) ? node.receive_from : parseCsvList(node.receive_from || ""),
        ),
        reports_to: dedupeList(
          Array.isArray(node.reports_to) ? node.reports_to : parseCsvList(node.reports_to || ""),
        ),
        worker_instances: Math.min(8, Math.max(1, Number(node.worker_instances || node.max_parallel || 1))),
        position: {
          x: Number.isFinite(px) ? px : 0,
          y: Number.isFinite(py) ? py : 0,
        },
        config: typeof node.config === "object" && node.config ? node.config : {},
      };
    });

    const nodeIds = new Set(nodes.map((node) => node.id));
    const edges = Array.isArray(workflow?.edges) ? workflow.edges : [];
    edges.forEach((edge) => {
      const source = String(edge.from || edge.from_node || "").trim();
      const target = String(edge.to || "").trim();
      if (!source || !target || !nodeIds.has(source) || !nodeIds.has(target)) return;
      const targetNode = nodes.find((node) => node.id === target);
      const sourceNode = nodes.find((node) => node.id === source);
      if (targetNode) targetNode.receive_from = dedupeList([...targetNode.receive_from, source]);
      if (sourceNode) sourceNode.reports_to = dedupeList([...sourceNode.reports_to, target]);
    });
    return nodes;
  }

  function normalizeWorkflowDraft(workflow) {
    const modes = Array.isArray(workflow?.modes) && workflow.modes.length > 0
      ? workflow.modes
      : [workflow?.mode || "chat"];
    const uniqueModes = dedupeList(modes.map((mode) => String(mode || "").toLowerCase()))
      .filter((mode) => modeOrder.includes(mode));
    return {
      id: String(workflow?.id || ""),
      name: String(workflow?.name || ""),
      description: String(workflow?.description || ""),
      mode: uniqueModes[0] || "chat",
      modes: uniqueModes.length > 0 ? uniqueModes : ["chat"],
      execution: workflow?.execution === "direct" ? "direct" : "loop",
      max_iterations: Math.min(8, Math.max(1, Number(workflow?.max_iterations || 1))),
      nodes: normalizeWorkflowNodes(workflow || {}),
    };
  }

  function deriveNodeTypeFromRole(roleName, workerInstances = 1) {
    const role = String(roleName || "").trim().toLowerCase();
    if (Number(workerInstances) > 1) return "worker_pool";
    if (role === "judge") return "judge";
    if (role === "reviewer") return "reviewer";
    if (role === "worker") return "worker_pool";
    return "role";
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

  function newWorkflowDraftFrom(workflow) {
    const draft = normalizeWorkflowDraft(workflow || {});
    if (draft.nodes.length > 0) return draft;
    return {
      ...draft,
      nodes: [{
        id: "orchestrator",
        type: "role",
        role: "orchestrator",
        title: "Plan",
        input: [],
        output: "plan",
        max_parallel: 1,
        max_items: 4,
        expects_json: true,
        receive_from: [],
        reports_to: [],
        worker_instances: 1,
        config: {},
      }],
    };
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
          ${nodes.map((node) => `<span>${escapeHtml(node.title || node.role || node.type || node.id)}</span>`).join("")}
        </div>
        <div class="workflow-graph-preview">
          ${workflowGraphMarkup(normalizeWorkflowDraft(workflow), true)}
        </div>
      `;
      workflowPresetList.append(item);
    });
  }

  function workflowGraphMarkup(workflow, compact = false) {
    const nodes = Array.isArray(workflow?.nodes) ? workflow.nodes : [];
    if (nodes.length === 0) {
      return '<p class="settings-empty">No nodes to display.</p>';
    }
    const nodeWidth = compact ? 150 : 176;
    const nodeHeight = compact ? 58 : 68;
    const gapX = compact ? 34 : 44;
    const gapY = compact ? 24 : 30;
    const pad = 18;
    const cols = compact ? Math.min(3, Math.max(1, nodes.length)) : Math.min(4, Math.max(1, nodes.length));
    const rows = Math.ceil(nodes.length / cols);
    const width = pad * 2 + (cols * nodeWidth) + ((cols - 1) * gapX);
    const height = pad * 2 + (rows * nodeHeight) + ((rows - 1) * gapY);
    const positions = {};
    nodes.forEach((node, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);
      positions[node.id] = {
        x: pad + col * (nodeWidth + gapX),
        y: pad + row * (nodeHeight + gapY),
      };
    });

    const edges = deriveWorkflowEdgesFromNodes(nodes);
    const edgeSvg = edges
      .map((edge) => {
        const source = positions[edge.from];
        const target = positions[edge.to];
        if (!source || !target) return "";
        if (target.x > source.x) {
          const sx = source.x + nodeWidth;
          const sy = source.y + nodeHeight / 2;
          const tx = target.x;
          const ty = target.y + nodeHeight / 2;
          return `<path class="workflow-graph-edge" d="M ${sx} ${sy} C ${sx + 30} ${sy}, ${tx - 30} ${ty}, ${tx} ${ty}" />`;
        }
        const sx = source.x + nodeWidth / 2;
        const sy = source.y + nodeHeight;
        const tx = target.x + nodeWidth / 2;
        const ty = target.y;
        return `<path class="workflow-graph-edge loop" d="M ${sx} ${sy} C ${sx} ${sy + 30}, ${tx} ${ty - 30}, ${tx} ${ty}" />`;
      })
      .join("");

    const nodeSvg = nodes
      .map((node) => {
        const pos = positions[node.id];
        const isWorker = String(node.type || "").toLowerCase() === "worker_pool";
        const title = escapeHtml(String(node.title || node.role || node.id || "node"));
        const metaParts = [String(node.type || "role")];
        if (isWorker) {
          metaParts.push(`x${Math.max(1, Number(node.worker_instances || node.max_parallel || 1))}`);
        }
        const meta = escapeHtml(metaParts.join(" · "));
        return `
          <g class="workflow-graph-node${isWorker ? " worker" : ""}">
            <rect x="${pos.x}" y="${pos.y}" width="${nodeWidth}" height="${nodeHeight}"></rect>
            <text x="${pos.x + 10}" y="${pos.y + 24}">
              <tspan>${title}</tspan>
              <tspan x="${pos.x + 10}" dy="18">${meta}</tspan>
            </text>
          </g>
        `;
      })
      .join("");

    return `
      <svg class="workflow-graph-svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Workflow graph" style="max-width:${width}px;">
        <defs>
          <marker id="wf-arrow" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto">
            <path d="M0,0 L9,3.5 L0,7 z" fill="rgba(157, 250, 255, 0.7)"></path>
          </marker>
        </defs>
        ${edgeSvg}
        ${nodeSvg}
      </svg>
    `;
  }

  function deriveWorkflowEdgesFromNodes(nodes) {
    const available = new Set((nodes || []).map((node) => node.id));
    const dedupe = new Set();
    const edges = [];
    (nodes || []).forEach((node) => {
      const source = String(node.id || "").trim();
      if (!source) return;
      const reports = dedupeList(Array.isArray(node.reports_to) ? node.reports_to : parseCsvList(node.reports_to || ""));
      reports.forEach((target) => {
        const to = String(target || "").trim();
        if (!to || !available.has(to)) return;
        const key = `${source}->${to}`;
        if (dedupe.has(key)) return;
        dedupe.add(key);
        edges.push({ from: source, to });
      });
      const incoming = dedupeList(Array.isArray(node.receive_from) ? node.receive_from : parseCsvList(node.receive_from || ""));
      incoming.forEach((from) => {
        const cleanFrom = String(from || "").trim();
        if (!cleanFrom || !available.has(cleanFrom)) return;
        const key = `${cleanFrom}->${source}`;
        if (dedupe.has(key)) return;
        dedupe.add(key);
        edges.push({ from: cleanFrom, to: source });
      });
    });
    return edges;
  }

  function activeWorkflowDraft() {
    if (state.workflowEditorDraft) return state.workflowEditorDraft;
    const first = state.workflowPresets[0] || null;
    state.workflowEditorDraft = first ? newWorkflowDraftFrom(first) : null;
    return state.workflowEditorDraft;
  }

  function ensureNodePositions(draft) {
    if (!draft?.nodes?.length) return;
    const allMissing = draft.nodes.every((node) => {
      const pos = node.position;
      return !pos || (Number(pos.x) === 0 && Number(pos.y) === 0);
    });
    if (!allMissing) {
      draft.nodes.forEach((node) => {
        const pos = node.position || {};
        node.position = {
          x: Number.isFinite(Number(pos.x)) ? Number(pos.x) : 0,
          y: Number.isFinite(Number(pos.y)) ? Number(pos.y) : 0,
        };
      });
      return;
    }
    const cols = Math.min(3, Math.max(1, draft.nodes.length));
    draft.nodes.forEach((node, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);
      node.position = {
        x: CANVAS_PAD + col * NODE_GRID_X,
        y: CANVAS_PAD + row * NODE_GRID_Y,
      };
    });
  }

  function nodeTileMarkup(node) {
    const isWorker = String(node.type || "").toLowerCase() === "worker_pool";
    const title = String(node.title || node.role || node.id || "node");
    const role = String(node.role || "").trim();
    const metaParts = [];
    if (role) metaParts.push(role);
    if (isWorker) {
      metaParts.push(`×${Math.max(1, Number(node.worker_instances || node.max_parallel || 1))}`);
    }
    if (!metaParts.length) metaParts.push(String(node.type || "role"));
    return `
      <button class="workflow-canvas-node-edit" type="button" aria-label="Edit node" title="Edit">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4 20l4-1 11-11-3-3-11 11-1 4z" />
          <path d="M14 6l3 3" />
        </svg>
      </button>
      <strong>${escapeHtml(title)}</strong>
      <small>${escapeHtml(metaParts.join(" · "))}</small>
      <span class="workflow-canvas-node-id">${escapeHtml(node.id)}</span>
    `;
  }

  function renderWorkflowCanvas() {
    const draft = activeWorkflowDraft();
    if (!workflowCanvasNodes || !workflowCanvasEdgeLayer || !draft) return;
    ensureNodePositions(draft);
    workflowCanvasNodes.innerHTML = "";
    let maxRight = CANVAS_PAD + NODE_TILE_WIDTH + CANVAS_PAD;
    let maxBottom = CANVAS_PAD + NODE_TILE_HEIGHT + CANVAS_PAD;
    draft.nodes.forEach((node) => {
      const isWorker = String(node.type || "").toLowerCase() === "worker_pool";
      const tile = document.createElement("article");
      tile.className = "workflow-canvas-node" + (isWorker ? " worker" : "");
      if (state.workflowEditorSelectedNodeId === node.id) tile.classList.add("is-selected");
      tile.dataset.nodeId = node.id;
      tile.style.left = `${node.position.x}px`;
      tile.style.top = `${node.position.y}px`;
      tile.innerHTML = nodeTileMarkup(node);
      workflowCanvasNodes.append(tile);
      maxRight = Math.max(maxRight, node.position.x + NODE_TILE_WIDTH + CANVAS_PAD);
      maxBottom = Math.max(maxBottom, node.position.y + NODE_TILE_HEIGHT + CANVAS_PAD);
    });
    workflowCanvasNodes.style.minWidth = `${maxRight}px`;
    workflowCanvasNodes.style.minHeight = `${maxBottom}px`;
    workflowCanvasEdges?.setAttribute("viewBox", `0 0 ${maxRight} ${maxBottom}`);
    workflowCanvasEdges?.setAttribute("width", String(maxRight));
    workflowCanvasEdges?.setAttribute("height", String(maxBottom));
    renderCanvasEdges(draft);
  }

  function renderCanvasEdges(draft) {
    if (!workflowCanvasEdgeLayer || !draft) return;
    workflowCanvasEdgeLayer.innerHTML = "";
    const edges = deriveWorkflowEdgesFromNodes(draft.nodes);
    const ns = "http://www.w3.org/2000/svg";
    const positions = {};
    draft.nodes.forEach((node) => {
      if (node.position) positions[node.id] = node.position;
    });
    edges.forEach((edge) => {
      const source = positions[edge.from];
      const target = positions[edge.to];
      if (!source || !target) return;
      let d;
      let cls = "workflow-canvas-edge";
      if (target.x > source.x + NODE_TILE_WIDTH / 2) {
        const sx = source.x + NODE_TILE_WIDTH;
        const sy = source.y + NODE_TILE_HEIGHT / 2;
        const tx = target.x;
        const ty = target.y + NODE_TILE_HEIGHT / 2;
        d = `M ${sx} ${sy} C ${sx + 50} ${sy}, ${tx - 50} ${ty}, ${tx} ${ty}`;
      } else {
        const sx = source.x + NODE_TILE_WIDTH / 2;
        const sy = source.y + NODE_TILE_HEIGHT;
        const tx = target.x + NODE_TILE_WIDTH / 2;
        const ty = target.y;
        d = `M ${sx} ${sy} C ${sx} ${sy + 40}, ${tx} ${ty - 40}, ${tx} ${ty}`;
        cls += " loop";
      }
      const path = document.createElementNS(ns, "path");
      path.setAttribute("class", cls);
      path.setAttribute("d", d);
      path.setAttribute("marker-end", "url(#wf-canvas-arrow)");
      workflowCanvasEdgeLayer.append(path);
    });
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
    renderWorkflowCanvas();
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
      nodes: [
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
          position: { x: CANVAS_PAD, y: CANVAS_PAD },
          config: {},
        },
      ],
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
      ?.querySelector(`.workflow-canvas-node[data-node-id="${cssEscape(node.id)}"]`)
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

  function cssEscape(value) {
    if (typeof CSS !== "undefined" && typeof CSS.escape === "function") return CSS.escape(value);
    return String(value).replace(/(["\\\]])/g, "\\$1");
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

  async function loadWorkflowPresets() {
    const previousDraftId = state.workflowEditorDraft?.id || "";
    const response = await api("/api/settings/workflows");
    state.workflowPresets = response.workflows || [];
    state.customWorkflowIds = Array.isArray(response.custom_ids) ? response.custom_ids : [];
    if (response.selected && state.settings) {
      state.settings.workflow_presets = response.selected;
    }
    const candidate = workflowById(previousDraftId)
      || workflowById(state.settings?.workflow_presets?.[state.activeMode])
      || state.workflowPresets[0]
      || null;
    state.workflowEditorDraft = candidate ? newWorkflowDraftFrom(candidate) : null;
    renderWorkflowSettings();
  }

  async function saveWorkflowEditorDraft() {
    return saveWorkflowEditorDraftWithAssignment(false);
  }

  function currentWorkflowAssignmentSelection() {
    return {
      chat: Boolean(workflowEditorAssignChat?.checked),
      code: Boolean(workflowEditorAssignCode?.checked),
      agentic: Boolean(workflowEditorAssignAgentic?.checked),
    };
  }

  async function applyWorkflowAssignment(workflowId, assignment = currentWorkflowAssignmentSelection()) {
    if (!workflowById(workflowId)) {
      setStatus("Save the workflow first before assigning it.", true);
      return false;
    }
    const nextPresets = {
      ...(state.settings?.workflow_presets || {}),
    };
    let assigned = 0;
    if (assignment.chat) {
      nextPresets.chat = workflowId;
      assigned += 1;
    }
    if (assignment.code) {
      nextPresets.code = workflowId;
      assigned += 1;
    }
    if (assignment.agentic) {
      nextPresets.agentic = workflowId;
      assigned += 1;
    }
    if (assigned === 0) {
      return false;
    }
    const workflowPresets = {
      chat: nextPresets.chat || "simple",
      code: nextPresets.code || "simple",
      agentic: nextPresets.agentic || "simple",
    };
    state.settings = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        ...(state.settings || {}),
        workflow_presets: workflowPresets,
      }),
    });
    renderWorkflowSettings();
    getSettingsUi()?.captureSettingsBaselineFromForm();
    setStatus("Workflow assigned & saved");
    return true;
  }

  async function saveWorkflowEditorDraftWithAssignment(assignAfterSave = false) {
    const draft = collectWorkflowDraftFromEditor();
    if (!draft) return;
    const assignment = assignAfterSave ? currentWorkflowAssignmentSelection() : null;
    if (!draft.id || !draft.name) {
      setStatus("Workflow id and name are required.", true);
      return;
    }
    if (!Array.isArray(draft.nodes) || draft.nodes.length === 0) {
      setStatus("At least one node is required.", true);
      return;
    }
    const edges = deriveWorkflowEdgesFromNodes(draft.nodes);
    const payload = {
      ...draft,
      mode: draft.modes[0] || "chat",
      edges,
    };
    await api(`/api/settings/workflows/${encodeURIComponent(draft.id)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    await loadWorkflowPresets();
    const saved = workflowById(draft.id);
    if (saved) {
      state.workflowEditorDraft = newWorkflowDraftFrom(saved);
      renderWorkflowEditor();
    }
    if (assignAfterSave) {
      const assigned = await applyWorkflowAssignment(draft.id, assignment || undefined);
      if (!assigned) {
        setStatus("Custom workflow saved");
      }
      return;
    }
    setStatus("Custom workflow saved");
  }

  async function deleteWorkflowEditorDraft() {
    const draft = collectWorkflowDraftFromEditor();
    if (!draft || !draft.id) return;
    if (!isCustomWorkflow(draft.id)) {
      setStatus("Only custom workflows can be deleted.", true);
      return;
    }
    await api(`/api/settings/workflows/${encodeURIComponent(draft.id)}`, { method: "DELETE" });
    await loadWorkflowPresets();
    setStatus("Custom workflow deleted");
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
    node.id = safeId;
    node.title = clampLength(nodeEditTitleInput.value.trim(), WORKFLOW_NAME_MAX);
    const chosenRole = String(nodeEditRole.value || "").trim();
    node.role = clampLength(chosenRole || "orchestrator", WORKFLOW_FIELD_MAX);
    const workers = clampInt(nodeEditWorkers.value, 1, 8);
    node.type = deriveNodeTypeFromRole(node.role, workers);
    node.receive_from = dedupeList(parseCsvList(nodeEditReceive.value));
    node.reports_to = dedupeList(parseCsvList(nodeEditReports.value));
    node.input = parseCsvList(nodeEditInput.value);
    node.output = clampLength(nodeEditOutput.value.trim(), WORKFLOW_FIELD_MAX);
    node.worker_instances = node.type === "worker_pool" ? workers : 1;
    node.max_parallel = workers;
    node.max_items = clampInt(nodeEditMaxItems.value, 1, 12);
    node.expects_json = Boolean(nodeEditJson.checked);
    if (safeId !== oldId) {
      draft.nodes.forEach((other) => {
        if (other === node) return;
        other.receive_from = (other.receive_from || []).map((r) => (r === oldId ? safeId : r));
        other.reports_to = (other.reports_to || []).map((r) => (r === oldId ? safeId : r));
      });
      state.workflowEditorSelectedNodeId = safeId;
    }
    if (workflowNodeEditTitle) workflowNodeEditTitle.textContent = node.title || node.id;
    renderWorkflowCanvas();
  }

  function init() {
    workflowEditorNew?.addEventListener("click", () => {
      showWorkflowBuilderView(null);
    });

    workflowBuilderBack?.addEventListener("click", () => {
      showWorkflowListView();
    });

    workflowEditorSave?.addEventListener("click", () => {
      saveWorkflowEditorDraft()
        .then(() => showWorkflowListView())
        .catch((error) => setStatus(error.message, true));
    });

    workflowEditorSaveAssign?.addEventListener("click", () => {
      saveWorkflowEditorDraftWithAssignment(true)
        .then(() => showWorkflowListView())
        .catch((error) => setStatus(error.message, true));
    });

    workflowEditorDelete?.addEventListener("click", () => {
      deleteWorkflowEditorDraft()
        .then(() => showWorkflowListView())
        .catch((error) => setStatus(error.message, true));
    });

    workflowPresetList?.addEventListener("click", (event) => {
      const editButton = event.target.closest(".workflow-preset-edit");
      if (!editButton) return;
      const card = editButton.closest(".workflow-preset-item");
      const workflowId = card?.dataset.workflowId;
      if (!workflowId) return;
      showWorkflowBuilderView(workflowId);
    });

    workflowEditorAddNode?.addEventListener("click", () => {
      const draft = activeWorkflowDraft();
      if (!draft) return;
      const baseId = "node";
      const taken = new Set(draft.nodes.map((node) => node.id));
      let id = `${baseId}_${draft.nodes.length + 1}`;
      let i = draft.nodes.length + 1;
      while (taken.has(id)) {
        i += 1;
        id = `${baseId}_${i}`;
      }
      const lastPos = draft.nodes[draft.nodes.length - 1]?.position || { x: CANVAS_PAD, y: CANVAS_PAD };
      const position = { x: lastPos.x + NODE_GRID_X, y: lastPos.y };
      draft.nodes.push({
        id,
        type: "role",
        role: "orchestrator",
        title: "New Node",
        input: [],
        output: "",
        max_parallel: 1,
        max_items: 4,
        expects_json: false,
        receive_from: [],
        reports_to: [],
        worker_instances: 1,
        position,
        config: {},
      });
      state.workflowEditorDraft = draft;
      renderWorkflowCanvas();
      selectWorkflowNode(id);
    });

    [
      workflowEditorId,
      workflowEditorName,
      workflowEditorDescription,
      workflowEditorExecution,
      workflowEditorMaxIterations,
      workflowEditorModeChat,
      workflowEditorModeCode,
      workflowEditorModeAgentic,
    ].forEach((element) => {
      element?.addEventListener("input", () => {
        collectWorkflowDraftFromEditor();
      });
      element?.addEventListener("change", () => {
        collectWorkflowDraftFromEditor();
      });
    });

    workflowCanvas?.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const editTarget = event.target.closest?.(".workflow-canvas-node-edit");
      const tile = event.target.closest?.(".workflow-canvas-node");
      if (!tile) return;
      const id = tile.dataset.nodeId;
      if (editTarget) {
        event.preventDefault();
        event.stopPropagation();
        selectWorkflowNode(id);
        return;
      }
      canvasDrag.id = id;
      canvasDrag.tile = tile;
      canvasDrag.originX = parseFloat(tile.style.left) || 0;
      canvasDrag.originY = parseFloat(tile.style.top) || 0;
      canvasDrag.pointerX = event.clientX;
      canvasDrag.pointerY = event.clientY;
      canvasDrag.moved = false;
      tile.setPointerCapture?.(event.pointerId);
      tile.classList.add("is-dragging");
    });

    workflowCanvas?.addEventListener("pointermove", (event) => {
      if (!canvasDrag.tile) return;
      const dx = event.clientX - canvasDrag.pointerX;
      const dy = event.clientY - canvasDrag.pointerY;
      if (!canvasDrag.moved && Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) return;
      canvasDrag.moved = true;
      const x = Math.max(0, canvasDrag.originX + dx);
      const y = Math.max(0, canvasDrag.originY + dy);
      canvasDrag.tile.style.left = `${x}px`;
      canvasDrag.tile.style.top = `${y}px`;
      const draft = activeWorkflowDraft();
      const node = draft?.nodes.find((n) => n.id === canvasDrag.id);
      if (node) node.position = { x, y };
      renderCanvasEdges(draft);
    });

    workflowCanvas?.addEventListener("pointerup", (event) => {
      if (!canvasDrag.tile) return;
      const wasClick = !canvasDrag.moved;
      const id = canvasDrag.id;
      canvasDrag.tile.classList.remove("is-dragging");
      try {
        canvasDrag.tile.releasePointerCapture?.(event.pointerId);
      } catch (_error) {
        /* ignore */
      }
      canvasDrag.tile = null;
      canvasDrag.id = null;
      canvasDrag.moved = false;
      if (wasClick && id) selectWorkflowNode(id);
    });

    workflowCanvas?.addEventListener("pointercancel", () => {
      if (canvasDrag.tile) canvasDrag.tile.classList.remove("is-dragging");
      canvasDrag.tile = null;
      canvasDrag.id = null;
      canvasDrag.moved = false;
    });

    workflowNodeEditClose?.addEventListener("click", () => {
      closeNodeEditPanel();
    });

    workflowNodeEditRemove?.addEventListener("click", () => {
      const draft = activeWorkflowDraft();
      const id = state.workflowEditorSelectedNodeId;
      if (!draft || !id) return;
      const index = draft.nodes.findIndex((n) => n.id === id);
      if (index < 0) return;
      draft.nodes.splice(index, 1);
      draft.nodes.forEach((node) => {
        node.receive_from = (node.receive_from || []).filter((r) => r !== id);
        node.reports_to = (node.reports_to || []).filter((r) => r !== id);
      });
      closeNodeEditPanel();
      renderWorkflowCanvas();
    });

    [
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
    ].forEach((element) => {
      element?.addEventListener("input", applyNodeEditChanges);
      element?.addEventListener("change", applyNodeEditChanges);
    });
  }

  return {
    activeWorkflowDraft,
    collectWorkflowDraftFromEditor,
    deriveWorkflowEdgesFromNodes,
    init,
    loadWorkflowPresets,
    newWorkflowDraftFrom,
    nodeRoleSelectOptionsHtml,
    renderWorkflowEditor,
    renderWorkflowSettings,
    showWorkflowBuilderView,
    showWorkflowListView,
    syncSelectedNodeRoleOptions,
    workflowById,
  };
}
