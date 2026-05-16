import { api } from "./api.js";
import { dom } from "./dom.js";
import { clampInt, clampLength, escapeHtml, slugifyWorkflowId } from "./helpers.js";
import { state } from "./state.js";
import { dedupeList, parseCsvList } from "./workflow-editor.js";
import {
  BOUNDARY_NODE_TYPE,
  CANVAS_PAD,
  DRAG_THRESHOLD,
  NODE_GRID_X,
  NODE_GRID_Y,
  NODE_TILE_HEIGHT,
  NODE_TILE_WIDTH,
  PORT_INPUT,
  PORT_OUTPUT,
  WORKFLOW_INPUT_ID,
  WORKFLOW_OUTPUT_ID,
  addUniqueNodeListValue,
  boundaryKind,
  canvasConnectionPath,
  canvasPortPoint,
  deriveNodeTypeFromRole,
  deriveWorkflowEdgesFromNodes,
  ensureWorkflowBoundaryNodes,
  hasInputPort,
  hasOutputPort,
  incomingEdgeForNode,
  isBoundaryNode,
  newWorkflowDraftFrom,
  nodeOutputIdentifier,
  nodeTileMarkup,
  normalizeWorkflowDraft,
  normalizeWorkflowNodes,
  realWorkflowNodes,
  removeAutoInputReference,
  removeNodeListValue,
  updateDownstreamInputReferences,
} from "./workflow-builder.js";
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
  workflowCanvasLabels,
  workflowCanvasEdges,
  workflowCanvasEdgeLayer,
  workflowEdgeRulesList,
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
const CANVAS_LAYOUT_X = NODE_TILE_WIDTH + 36;
const EDGE_CONDITION_PRESETS = [
  { label: "Always", value: "" },
  { label: "Run another pass", value: "decision.status == 'retry'" },
  { label: "Ready to answer", value: "decision.status == 'done'" },
  { label: "Ask user", value: "decision.status == 'needs_user'" },
  { label: "Error", value: "error" },
  { label: "Low confidence", value: "plan.confidence < 0.7" },
  { label: "Enough reports", value: "worker_reports.length >= 3" },
];

export function createWorkflowsUi({ setStatus, getSettingsUi }) {
  const canvasDrag = { id: null, tile: null, originX: 0, originY: 0, pointerX: 0, pointerY: 0, moved: false };
  const linkDrag = {
    sourceId: null,
    pointerId: null,
    path: null,
    validTargetId: null,
    detached: null,
  };

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
          ${workflowGraphMarkup(normalizeWorkflowDraft(workflow), true)}
        </div>
      `;
      workflowPresetList.append(item);
    });
  }

  function edgeLabel(condition) {
    const clean = String(condition || "").trim();
    if (!clean) return "";
    const preset = EDGE_CONDITION_PRESETS.find((item) => item.value === clean);
    if (preset && preset.value) return preset.label;
    return clean.length > 28 ? `${clean.slice(0, 25)}...` : clean;
  }

  function nodeById(draft, nodeId) {
    return draft?.nodes?.find((node) => node.id === nodeId) || null;
  }

  function isAnswerNode(node) {
    return String(node?.type || "").toLowerCase() === "answer" || String(node?.id || "").toLowerCase() === "answer";
  }

  function edgeConditionPresets(edge, draft) {
    const source = nodeById(draft, edge.from);
    const target = nodeById(draft, edge.to);
    const sourceType = String(source?.type || "").toLowerCase();
    const targetType = String(target?.type || "").toLowerCase();
    const presets = [{ label: "Always", value: "" }];

    if (sourceType === "judge") {
      if (targetType === "pause") {
        presets.push({ label: "Ask user", value: "decision.status == 'needs_user'" });
      } else if (isAnswerNode(target)) {
        presets.push(
          { label: "Ready to answer", value: "decision.status == 'done'" },
        );
      } else {
        presets.push({ label: "Run another pass", value: "decision.status == 'retry'" });
      }
    }
    if (sourceType === "role" || sourceType === "orchestrator") {
      presets.push({ label: "Low confidence", value: "plan.confidence < 0.7" });
    }
    if (targetType === "reviewer") {
      presets.push({ label: "Enough reports", value: "worker_reports.length >= 3" });
    }
    presets.push({ label: "Error", value: "error" });
    return dedupeConditionPresets(presets);
  }

  function dedupeConditionPresets(presets) {
    const seen = new Set();
    return presets.filter((preset) => {
      if (seen.has(preset.value)) return false;
      seen.add(preset.value);
      return true;
    });
  }

  function edgeDisplayName(edge, draft) {
    const source = nodeById(draft, edge.from);
    const target = nodeById(draft, edge.to);
    return `${source?.title || source?.id || edge.from} -> ${target?.title || target?.id || edge.to}`;
  }

  function graphLayers(nodes, edges) {
    const ids = new Set(nodes.map((node) => node.id));
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const incoming = new Map(nodes.map((node) => [node.id, 0]));
    const outgoing = new Map(nodes.map((node) => [node.id, []]));
    const layoutEdges = edges.filter((edge) => isMainFlowEdge(edge, nodeById));
    layoutEdges.forEach((edge) => {
      if (!ids.has(edge.from) || !ids.has(edge.to)) return;
      outgoing.get(edge.from)?.push(edge.to);
      incoming.set(edge.to, (incoming.get(edge.to) || 0) + 1);
    });

    const queue = nodes.filter((node) => (incoming.get(node.id) || 0) === 0).map((node) => node.id);
    const depth = new Map(nodes.map((node) => [node.id, 0]));
    const seen = new Set();
    while (queue.length) {
      const id = queue.shift();
      if (!id || seen.has(id)) continue;
      seen.add(id);
      (outgoing.get(id) || []).forEach((target) => {
        depth.set(target, Math.max(depth.get(target) || 0, (depth.get(id) || 0) + 1));
        incoming.set(target, Math.max(0, (incoming.get(target) || 0) - 1));
        if ((incoming.get(target) || 0) === 0) queue.push(target);
      });
    }

    const layerCounts = new Map();
    const layered = nodes.map((node) => {
      const col = depth.get(node.id) || 0;
      const row = layerCounts.get(col) || 0;
      layerCounts.set(col, row + 1);
      return { ...node, _graphCol: col, _graphRow: row };
    });
    return {
      nodes: layered,
      cols: Math.max(1, ...layered.map((node) => node._graphCol + 1)),
      rows: Math.max(1, ...layerCounts.values()),
    };
  }

  function workflowGraphMarkup(workflow, compact = false) {
    const nodes = Array.isArray(workflow?.nodes) ? workflow.nodes : [];
    if (nodes.length === 0) {
      return '<p class="settings-empty">No nodes to display.</p>';
    }
    const nodeWidth = compact ? 126 : 176;
    const nodeHeight = compact ? 56 : 68;
    const gapX = compact ? 32 : 44;
    const gapY = compact ? 36 : 30;
    const pad = compact ? 22 : 18;
    const graphEdges = deriveWorkflowEdgesFromNodes(nodes, workflow.edges || [], true);
    const layers = graphLayers(nodes, graphEdges);
    const hasBackEdges = graphEdges.some((edge) => {
      const sourceNode = layers.nodes.find((node) => node.id === edge.from);
      const targetNode = layers.nodes.find((node) => node.id === edge.to);
      return sourceNode && targetNode && targetNode._graphCol <= sourceNode._graphCol;
    });
    const width = pad * 2 + (layers.cols * nodeWidth) + ((layers.cols - 1) * gapX);
    const baseHeight = pad * 2 + (layers.rows * nodeHeight) + ((layers.rows - 1) * gapY);
    const loopLaneY = baseHeight + (hasBackEdges ? (compact ? 42 : 50) : 0);
    const height = baseHeight + (hasBackEdges ? (compact ? 68 : 78) : 0);
    const positions = {};
    layers.nodes.forEach((node) => {
      const col = node._graphCol;
      const row = node._graphRow;
      positions[node.id] = {
        x: pad + col * (nodeWidth + gapX),
        y: pad + row * (nodeHeight + gapY),
      };
    });

    const edgeSvg = graphEdges
      .map((edge, index) => {
        const source = positions[edge.from];
        const target = positions[edge.to];
        if (!source || !target) return "";
        const labelText = edgeLabel(edge.when);
        if (target.x > source.x) {
          const sx = source.x + nodeWidth;
          const sy = source.y + nodeHeight / 2;
          const tx = target.x;
          const ty = target.y + nodeHeight / 2;
          const label = labelText ? graphEdgeLabel(labelText, (sx + tx) / 2, (sy + ty) / 2 - 14 - ((index % 2) * 14)) : "";
          return `<path class="workflow-graph-edge${edge.when === "error" ? " error" : ""}" d="M ${sx} ${sy} C ${sx + 30} ${sy}, ${tx - 30} ${ty}, ${tx} ${ty}" />${label}`;
        }
        const sx = source.x + nodeWidth / 2;
        const sy = source.y + nodeHeight;
        const tx = target.x + nodeWidth / 2;
        const ty = target.y + nodeHeight;
        const laneY = loopLaneY + (index % 2) * 10;
        const label = labelText ? graphEdgeLabel(labelText, (sx + tx) / 2, laneY - 14) : "";
        return `<path class="workflow-graph-edge loop${edge.when === "error" ? " error" : ""}" d="M ${sx} ${sy} C ${sx} ${laneY - 20}, ${sx} ${laneY}, ${sx - 24} ${laneY} L ${tx + 24} ${laneY} C ${tx} ${laneY}, ${tx} ${laneY - 20}, ${tx} ${ty}" />${label}`;
      })
      .join("");

    const nodeSvg = layers.nodes
      .map((node) => {
        const pos = positions[node.id];
        const nodeType = String(node.type || "").toLowerCase();
        const isWorker = nodeType === "worker_pool";
        const isAnswer = nodeType === "answer";
        const isIteration = ["for_each", "while"].includes(nodeType);
        const boundary = boundaryKind(node);
        const rawTitle = String(node.title || node.role || node.id || "node");
        const title = escapeHtml(isAnswer && rawTitle.toLowerCase() === "answer" ? "Answer" : rawTitle);
        const metaParts = [isAnswer ? "assistant response" : String(node.type || "role")];
        if (isWorker) {
          metaParts.push(`<=${Math.max(1, Number(node.worker_instances || node.max_parallel || 1))}`);
        }
        if (boundary === PORT_INPUT) metaParts.splice(0, metaParts.length, "assistant input");
        if (boundary === PORT_OUTPUT) metaParts.splice(0, metaParts.length, "assistant output");
        const meta = escapeHtml(metaParts.join(" · "));
        return `
          <g class="workflow-graph-node${isWorker ? " worker" : ""}${isIteration ? " iteration" : ""}${boundary ? " boundary" : ""}">
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

  function graphEdgeLabel(label, x, y) {
    const width = Math.min(170, Math.max(54, label.length * 7 + 18));
    return `
      <g class="workflow-graph-edge-label">
        <rect x="${x - width / 2}" y="${y - 13}" width="${width}" height="20"></rect>
        <text x="${x}" y="${y + 1}">${escapeHtml(label)}</text>
      </g>
    `;
  }

  function activeWorkflowDraft() {
    if (state.workflowEditorDraft) return state.workflowEditorDraft;
    const first = state.workflowPresets[0] || null;
    state.workflowEditorDraft = first ? newWorkflowDraftFrom(first) : null;
    return state.workflowEditorDraft;
  }

  function ensureNodePositions(draft) {
    if (!draft?.nodes?.length) return;
    draft.nodes = ensureWorkflowBoundaryNodes(draft.nodes);
    const positionedNodes = realWorkflowNodes(draft.nodes);
    const nodesToCheck = positionedNodes.length > 0 ? positionedNodes : draft.nodes;
    const allMissing = nodesToCheck.every((node) => {
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
      alignBoundaryNodes(draft);
      return;
    }
    layoutCanvasNodes(realWorkflowNodes(draft.nodes), deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || []));
    alignBoundaryNodes(draft);
  }

  function layoutCanvasNodes(realNodes, edges) {
    const ordered = mainFlowOrder(realNodes, edges);
    const topRowCount = ordered.length > 4 ? 3 : Math.min(ordered.length, 4);
    ordered.forEach((node, index) => {
      const bottom = index >= topRowCount;
      const col = bottom ? index - topRowCount + Math.max(0, topRowCount - 2) : index;
      const row = bottom ? 1 : 0;
      node.position = {
        x: CANVAS_PAD + CANVAS_LAYOUT_X + col * CANVAS_LAYOUT_X,
        y: CANVAS_PAD + row * NODE_GRID_Y,
      };
    });
  }

  function mainFlowOrder(realNodes, edges) {
    const byId = new Map(realNodes.map((node) => [node.id, node]));
    const flowEdges = edges.filter((edge) => byId.has(edge.from) && byId.has(edge.to) && isMainFlowEdge(edge, byId));
    const incoming = new Set(flowEdges.map((edge) => edge.to));
    const outgoing = new Map();
    flowEdges.forEach((edge) => {
      if (!outgoing.has(edge.from)) outgoing.set(edge.from, []);
      outgoing.get(edge.from).push(edge.to);
    });
    const start = realNodes.find((node) => !incoming.has(node.id)) || realNodes[0];
    const ordered = [];
    const seen = new Set();
    let current = start?.id || "";
    while (current && byId.has(current) && !seen.has(current)) {
      seen.add(current);
      ordered.push(byId.get(current));
      current = (outgoing.get(current) || []).find((id) => !seen.has(id)) || "";
    }
    realNodes.forEach((node) => {
      if (!seen.has(node.id)) ordered.push(node);
    });
    return ordered;
  }

  function isMainFlowEdge(edge, nodeById) {
    const source = nodeById.get(edge.from);
    const when = String(edge.when || "");
    return Boolean(
      source
        && !when.includes("retry")
        && when !== "error"
        && String(source.type || "").toLowerCase() !== "pause",
    );
  }

  function alignBoundaryNodes(draft) {
    const inputNode = draft.nodes.find((node) => boundaryKind(node) === PORT_INPUT);
    const outputNode = draft.nodes.find((node) => boundaryKind(node) === PORT_OUTPUT);
    const realNodes = realWorkflowNodes(draft.nodes);
    if (!realNodes.length) return;

    const realEdges = deriveWorkflowEdgesFromNodes(realNodes, draft.edges || []).filter(
      (edge) => !String(edge.when || "").includes("retry"),
    );
    const incoming = new Set(realEdges.map((edge) => edge.to));
    const outgoing = new Set(realEdges.map((edge) => edge.from));
    const starts = realNodes.filter((node) => !incoming.has(node.id));
    const terminals = realNodes.filter((node) => !outgoing.has(node.id));
    const firstStart = starts[0] || realNodes[0];
    const firstTerminal = terminals[0] || realNodes[realNodes.length - 1];

    if (inputNode && firstStart?.position) {
      inputNode.position = {
        x: Math.max(CANVAS_PAD, Number(firstStart.position.x) - CANVAS_LAYOUT_X),
        y: Number(firstStart.position.y),
      };
    }
    if (outputNode && firstTerminal?.position) {
      outputNode.position = {
        x: Number(firstTerminal.position.x),
        y: Number(firstTerminal.position.y) + NODE_GRID_Y,
      };
    }
  }

  function pointerPointInCanvas(event) {
    const rect = workflowCanvas?.getBoundingClientRect();
    if (!rect || !workflowCanvas) return { x: 0, y: 0 };
    return {
      x: event.clientX - rect.left + workflowCanvas.scrollLeft,
      y: event.clientY - rect.top + workflowCanvas.scrollTop,
    };
  }

  function canvasPortFromPoint(event) {
    const element = document.elementFromPoint(event.clientX, event.clientY);
    const port = element?.closest?.(".workflow-canvas-port");
    if (!port || !workflowCanvas?.contains(port)) return null;
    return port;
  }

  function canvasLinkTargetIdFromPointer(event) {
    const port = canvasPortFromPoint(event);
    if (!port || port.dataset.portType !== PORT_INPUT) return null;
    const targetId = port.closest(".workflow-canvas-node")?.dataset.nodeId || "";
    if (!targetId || targetId === linkDrag.sourceId) return null;
    const draft = activeWorkflowDraft();
    const target = draft?.nodes.find((node) => node.id === targetId);
    if (!target || !hasInputPort(target)) return null;
    return targetId;
  }

  function clearCanvasLinkHighlights() {
    workflowCanvasNodes
      ?.querySelectorAll(".is-link-target, .is-linking-source")
      .forEach((el) => el.classList.remove("is-link-target", "is-linking-source"));
  }

  function ensureLinkPreviewPath() {
    if (linkDrag.path?.isConnected) return linkDrag.path;
    const ns = "http://www.w3.org/2000/svg";
    const path = document.createElementNS(ns, "path");
    path.setAttribute("class", "workflow-canvas-edge preview");
    path.setAttribute("marker-end", "url(#wf-canvas-arrow)");
    workflowCanvasEdgeLayer?.append(path);
    linkDrag.path = path;
    return path;
  }

  function updateCanvasLinkPreview(event) {
    const draft = activeWorkflowDraft();
    const source = draft?.nodes.find((node) => node.id === linkDrag.sourceId);
    if (!source) return;
    const targetId = canvasLinkTargetIdFromPointer(event);
    linkDrag.validTargetId = targetId;
    clearCanvasLinkHighlights();
    workflowCanvasNodes
      ?.querySelector(`.workflow-canvas-node[data-node-id="${cssEscape(source.id)}"]`)
      ?.classList.add("is-linking-source");
    if (targetId) {
      workflowCanvasNodes
        ?.querySelector(`.workflow-canvas-node[data-node-id="${cssEscape(targetId)}"]`)
        ?.classList.add("is-link-target");
    }
    const target = targetId ? draft.nodes.find((node) => node.id === targetId) : null;
    const start = canvasPortPoint(source, PORT_OUTPUT);
    const end = target ? canvasPortPoint(target, PORT_INPUT) : pointerPointInCanvas(event);
    const path = ensureLinkPreviewPath();
    path.setAttribute("d", canvasConnectionPath(start, end));
    path.setAttribute("class", `workflow-canvas-edge preview${target ? " is-valid" : ""}`);
  }

  function startCanvasLinkDrag(event, port) {
    const sourceId = port.closest(".workflow-canvas-node")?.dataset.nodeId || "";
    if (!sourceId) return false;
    event.preventDefault();
    event.stopPropagation();
    linkDrag.sourceId = sourceId;
    linkDrag.pointerId = event.pointerId;
    linkDrag.validTargetId = null;
    workflowCanvas?.classList.add("is-linking");
    try {
      workflowCanvas?.setPointerCapture?.(event.pointerId);
    } catch (_error) {
      /* ignore */
    }
    updateCanvasLinkPreview(event);
    return true;
  }

  function startCanvasRelinkDrag(event, port) {
    const targetId = port.closest(".workflow-canvas-node")?.dataset.nodeId || "";
    const draft = activeWorkflowDraft();
    const target = draft?.nodes.find((node) => node.id === targetId);
    if (!draft || !target || !hasInputPort(target)) return false;
    const edge = incomingEdgeForNode(draft, targetId);
    if (!edge) return false;
    const source = draft.nodes.find((node) => node.id === edge.from);
    if (!source || !hasOutputPort(source)) return false;
    event.preventDefault();
    event.stopPropagation();
    linkDrag.sourceId = source.id;
    linkDrag.pointerId = event.pointerId;
    linkDrag.validTargetId = null;
    linkDrag.detached = { from: source.id, to: target.id };
    workflowCanvas?.classList.add("is-linking");
    try {
      workflowCanvas?.setPointerCapture?.(event.pointerId);
    } catch (_error) {
      /* ignore */
    }
    removeCanvasConnection(source.id, target.id);
    refreshWorkflowCanvasAfterLinkChange();
    updateCanvasLinkPreview(event);
    return true;
  }

  function connectCanvasNodes(sourceId, targetId) {
    const draft = activeWorkflowDraft();
    if (!draft || !sourceId || !targetId || sourceId === targetId) return false;
    const source = draft.nodes.find((node) => node.id === sourceId);
    const target = draft.nodes.find((node) => node.id === targetId);
    if (!source || !target) return false;
    if (!hasOutputPort(source) || !hasInputPort(target)) return false;
    const outputIdentifier = nodeOutputIdentifier(source);
    const changed = [
      addUniqueNodeListValue(source, "reports_to", target.id),
      addUniqueNodeListValue(target, "receive_from", source.id),
      outputIdentifier ? addUniqueNodeListValue(target, "input", outputIdentifier) : false,
    ].some(Boolean);
    draft.edges = deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || []);
    renderWorkflowCanvas();
    if (state.workflowEditorSelectedNodeId) {
      selectWorkflowNode(state.workflowEditorSelectedNodeId);
    }
    setStatus(changed ? "Nodes linked" : "Nodes already linked");
    return true;
  }

  function removeCanvasConnection(sourceId, targetId) {
    const draft = activeWorkflowDraft();
    if (!draft || !sourceId || !targetId) return false;
    const source = draft.nodes.find((node) => node.id === sourceId);
    const target = draft.nodes.find((node) => node.id === targetId);
    if (!source || !target) return false;
    const inputIdentifier = nodeOutputIdentifier(source);
    const changed = [
      removeNodeListValue(source, "reports_to", target.id),
      removeNodeListValue(target, "receive_from", source.id),
    ].some(Boolean);
    const inputChanged = removeAutoInputReference(draft, target, inputIdentifier);
    draft.edges = (draft.edges || []).filter((edge) => (edge.from || edge.from_node) !== sourceId || edge.to !== targetId);
    return changed || inputChanged;
  }

  function refreshWorkflowCanvasAfterLinkChange() {
    renderWorkflowCanvas();
    if (state.workflowEditorSelectedNodeId) {
      selectWorkflowNode(state.workflowEditorSelectedNodeId);
    }
  }

  function finishCanvasLinkDrag(event) {
    if (!linkDrag.sourceId) return false;
    const targetId = linkDrag.validTargetId || canvasLinkTargetIdFromPointer(event);
    if (targetId) {
      connectCanvasNodes(linkDrag.sourceId, targetId);
    } else if (linkDrag.detached) {
      refreshWorkflowCanvasAfterLinkChange();
      setStatus("Nodes unlinked");
    }
    cleanupCanvasLinkDrag();
    return true;
  }

  function cleanupCanvasLinkDrag() {
    if (linkDrag.pointerId !== null) {
      try {
        workflowCanvas?.releasePointerCapture?.(linkDrag.pointerId);
      } catch (_error) {
        /* ignore */
      }
    }
    linkDrag.path?.remove();
    linkDrag.sourceId = null;
    linkDrag.pointerId = null;
    linkDrag.path = null;
    linkDrag.validTargetId = null;
    linkDrag.detached = null;
    workflowCanvas?.classList.remove("is-linking");
    clearCanvasLinkHighlights();
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
      const isIteration = ["for_each", "while"].includes(String(node.type || "").toLowerCase());
      const tile = document.createElement("article");
      tile.className = "workflow-canvas-node"
        + (isWorker ? " worker" : "")
        + (isIteration ? " iteration" : "")
        + (isBoundaryNode(node) ? " boundary" : "");
      if (state.workflowEditorSelectedNodeId === node.id) tile.classList.add("is-selected");
      tile.dataset.nodeId = node.id;
      tile.style.left = `${node.position.x}px`;
      tile.style.top = `${node.position.y}px`;
      tile.innerHTML = nodeTileMarkup(node);
      workflowCanvasNodes.append(tile);
      maxRight = Math.max(maxRight, node.position.x + NODE_TILE_WIDTH + CANVAS_PAD);
      maxBottom = Math.max(maxBottom, node.position.y + NODE_TILE_HEIGHT + CANVAS_PAD);
    });
    const canvasEdges = deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || [], true);
    const loopCount = canvasEdges.filter((edge) => isLoopCanvasEdge(edge, draft)).length;
    if (loopCount > 0) {
      maxBottom += 56 + (loopCount - 1) * 28;
    }
    workflowCanvasNodes.style.minWidth = `${maxRight}px`;
    workflowCanvasNodes.style.minHeight = `${maxBottom}px`;
    if (workflowCanvasLabels) {
      workflowCanvasLabels.style.minWidth = `${maxRight}px`;
      workflowCanvasLabels.style.minHeight = `${maxBottom}px`;
    }
    workflowCanvasEdges?.setAttribute("viewBox", `0 0 ${maxRight} ${maxBottom}`);
    workflowCanvasEdges?.setAttribute("width", String(maxRight));
    workflowCanvasEdges?.setAttribute("height", String(maxBottom));
    renderCanvasEdges(draft);
    renderEdgeRules(draft);
  }

  function isLoopCanvasEdge(edge, draft) {
    const source = draft.nodes.find((node) => node.id === edge.from)?.position;
    const target = draft.nodes.find((node) => node.id === edge.to)?.position;
    if (!source || !target) return false;
    const sourcePoint = canvasPortPoint({ position: source }, PORT_OUTPUT);
    const targetPoint = canvasPortPoint({ position: target }, PORT_INPUT);
    return String(edge.when || "").includes("retry") || targetPoint.x <= sourcePoint.x && targetPoint.y <= sourcePoint.y;
  }

  function renderCanvasEdges(draft) {
    if (!workflowCanvasEdgeLayer || !draft) return;
    workflowCanvasEdgeLayer.innerHTML = "";
    if (workflowCanvasLabels) workflowCanvasLabels.innerHTML = "";
    const edges = deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || [], true);
    const ns = "http://www.w3.org/2000/svg";
    const positions = {};
    draft.nodes.forEach((node) => {
      if (node.position) positions[node.id] = node.position;
    });
    let loopLane = 0;
    let crossingLane = 0;
    edges.forEach((edge) => {
      const source = positions[edge.from];
      const target = positions[edge.to];
      if (!source || !target) return;
      const sourcePoint = canvasPortPoint({ position: source }, PORT_OUTPUT);
      const targetPoint = canvasPortPoint({ position: target }, PORT_INPUT);
      let cls = "workflow-canvas-edge";
      const isLoop = String(edge.when || "").includes("retry") || targetPoint.x <= sourcePoint.x && targetPoint.y <= sourcePoint.y;
      const laneOffset = isLoop ? loopLane++ * 28 : edge.when ? (crossingLane++ % 3 - 1) * 18 : 0;
      if (isLoop) {
        cls += " loop";
      }
      if (edge.when === "error") {
        cls += " error";
      }
      const path = document.createElementNS(ns, "path");
      path.setAttribute("class", cls);
      path.setAttribute("d", canvasConnectionPath(sourcePoint, targetPoint, isLoop, laneOffset));
      path.setAttribute("marker-end", "url(#wf-canvas-arrow)");
      workflowCanvasEdgeLayer.append(path);
      if (edge.when) renderCanvasEdgeLabel(edge, sourcePoint, targetPoint, isLoop, laneOffset);
    });
  }

  function renderCanvasEdgeLabel(edge, sourcePoint, targetPoint, isLoop = false, laneOffset = 0) {
    if (!workflowCanvasLabels) return;
    const label = edgeLabel(edge.when);
    const x = (sourcePoint.x + targetPoint.x) / 2;
    const y = isLoop
      ? Math.max(sourcePoint.y, targetPoint.y) + 38 + laneOffset
      : (sourcePoint.y + targetPoint.y) / 2 - 18 + laneOffset * 0.35;
    const badge = document.createElement("span");
    badge.className = `workflow-canvas-edge-label${edge.when === "error" ? " error" : ""}`;
    badge.textContent = label;
    badge.style.left = `${x}px`;
    badge.style.top = `${y}px`;
    workflowCanvasLabels.append(badge);
  }

  function renderEdgeRules(draft) {
    if (!workflowEdgeRulesList || !draft) return;
    const edges = deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || []);
    draft.edges = edges;
    if (edges.length === 0) {
      workflowEdgeRulesList.innerHTML = '<p class="settings-empty">No connections yet.</p>';
      return;
    }
    workflowEdgeRulesList.innerHTML = edges
      .map((edge, index) => {
        const current = String(edge.when || "");
        const presets = edgeConditionPresets(edge, draft);
        const presetValue = presets.some((item) => item.value === current) ? current : "__custom";
        const customHidden = presetValue !== "__custom" ? " hidden" : "";
        const path = edgeDisplayName(edge, draft);
        return `
          <div class="workflow-edge-rule" data-edge-index="${index}">
            <span class="workflow-edge-rule-path">${escapeHtml(path)}</span>
            <select class="workflow-edge-rule-preset" aria-label="Condition preset for ${escapeHtml(path)}">
              ${presets.map((item) => `<option value="${escapeHtml(item.value)}"${presetValue === item.value ? " selected" : ""}>${escapeHtml(item.label)}</option>`).join("")}
              <option value="__custom"${presetValue === "__custom" ? " selected" : ""}>Custom expression</option>
            </select>
            <input class="workflow-edge-rule-expression"${customHidden} type="text" value="${escapeHtml(current)}" placeholder="plan.confidence < 0.7" aria-label="Custom condition expression" />
          </div>
        `;
      })
      .join("");
  }

  function applyEdgeRuleChange(target) {
    const row = target.closest?.(".workflow-edge-rule");
    const draft = activeWorkflowDraft();
    if (!row || !draft) return;
    const index = Number(row.dataset.edgeIndex);
    const edges = deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || []);
    const edge = edges[index];
    if (!edge) return;
    const preset = row.querySelector(".workflow-edge-rule-preset");
    const expression = row.querySelector(".workflow-edge-rule-expression");
    let when = String(preset?.value || "");
    if (when === "__custom") {
      expression.hidden = false;
      when = String(expression?.value || "").trim();
    } else {
      expression.hidden = true;
      if (expression) expression.value = when;
    }
    edges[index] = { ...edge, when };
    draft.edges = edges;
    renderCanvasEdges(draft);
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
    if (!Array.isArray(draft.nodes) || realWorkflowNodes(draft.nodes).length === 0) {
      setStatus("At least one node is required.", true);
      return;
    }
    const edges = deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || []);
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

    workflowEdgeRulesList?.addEventListener("change", (event) => {
      const target = event.target;
      if (target?.classList?.contains("workflow-edge-rule-preset")) {
        applyEdgeRuleChange(target);
        renderEdgeRules(activeWorkflowDraft());
      }
    });

    workflowEdgeRulesList?.addEventListener("input", (event) => {
      const target = event.target;
      if (target?.classList?.contains("workflow-edge-rule-expression")) {
        applyEdgeRuleChange(target);
      }
    });

    workflowEditorAddNode?.addEventListener("click", () => {
      const draft = activeWorkflowDraft();
      if (!draft) return;
      const baseId = "node";
      const taken = new Set(draft.nodes.map((node) => node.id));
      const existingNodes = realWorkflowNodes(draft.nodes);
      let id = `${baseId}_${existingNodes.length + 1}`;
      let i = existingNodes.length + 1;
      while (taken.has(id)) {
        i += 1;
        id = `${baseId}_${i}`;
      }
      const lastPos = existingNodes[existingNodes.length - 1]?.position || { x: CANVAS_PAD + NODE_GRID_X, y: CANVAS_PAD };
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
      state.workflowEditorDraft = {
        ...draft,
        nodes: ensureWorkflowBoundaryNodes(draft.nodes),
      };
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
      const portTarget = event.target.closest?.(".workflow-canvas-port");
      if (portTarget) {
        if (portTarget.dataset.portType === PORT_OUTPUT) {
          startCanvasLinkDrag(event, portTarget);
        } else if (portTarget.dataset.portType === PORT_INPUT) {
          startCanvasRelinkDrag(event, portTarget);
        }
        return;
      }
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
      if (linkDrag.sourceId) {
        updateCanvasLinkPreview(event);
        return;
      }
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
      if (linkDrag.sourceId) {
        finishCanvasLinkDrag(event);
        return;
      }
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
      if (linkDrag.sourceId) {
        const removedConnection = Boolean(linkDrag.detached);
        cleanupCanvasLinkDrag();
        if (removedConnection) {
          refreshWorkflowCanvasAfterLinkChange();
          setStatus("Nodes unlinked");
        }
        return;
      }
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
      deriveWorkflowEdgesFromNodes(draft.nodes)
        .filter((edge) => edge.from === id || edge.to === id)
        .forEach((edge) => {
          removeCanvasConnection(edge.from, edge.to);
        });
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
