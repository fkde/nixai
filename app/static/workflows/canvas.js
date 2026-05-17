import { escapeHtml } from "../helpers.js";
import { state } from "../state.js";
import {
  CANVAS_PAD,
  DRAG_THRESHOLD,
  NODE_GRID_Y,
  NODE_TILE_HEIGHT,
  NODE_TILE_WIDTH,
  PORT_INPUT,
  PORT_OUTPUT,
  addUniqueNodeListValue,
  boundaryKind,
  canonicalNodeType,
  canvasConnectionPath,
  canvasPortPoint,
  derivedNodeConnections,
  deriveWorkflowEdgesFromNodes,
  ensureWorkflowBoundaryNodes,
  hasInputPort,
  hasOutputPort,
  incomingEdgeForNode,
  isBoundaryNode,
  mutateWorkflowEdges,
  normalizeDecisionBranches,
  nodeOutputIdentifier,
  nodeTileMarkup,
  realWorkflowNodes,
  removeAutoInputReference,
  restoreAutoBoundaryEdge,
  syncDerivedEdges,
  suppressAutoBoundaryEdge,
  validateWorkflowHealth,
  WORKFLOW_INPUT_ID,
  WORKFLOW_OUTPUT_ID,
} from "../workflow-builder.js";

const EDGE_CONDITION_PRESETS_DEFAULT = [
  { label: "Always", value: "" },
  { label: "Run another pass", value: "decision.status == 'retry'" },
  { label: "Ready to answer", value: "decision.status == 'done'" },
  { label: "Ask user", value: "decision.status == 'needs_user'" },
  { label: "Error", value: "error" },
  { label: "Low confidence", value: "plan.confidence < 0.7" },
  { label: "Enough reports", value: "worker_reports.length >= 3" },
];

const CANVAS_LAYOUT_X = NODE_TILE_WIDTH + 36;

export function createWorkflowCanvas({
  workflowCanvas,
  workflowCanvasNodes,
  workflowCanvasLabels,
  workflowCanvasEdges,
  workflowCanvasEdgeLayer,
  workflowEdgeRulesList,
  setStatus,
  bridge,
}) {
  const canvasDrag = { id: null, tile: null, originX: 0, originY: 0, pointerX: 0, pointerY: 0, moved: false };
  const linkDrag = {
    sourceId: null,
    pointerId: null,
    path: null,
    validTargetId: null,
    detached: null,
  };
  let edgeRulePopover = null;

  function cssEscape(value) {
    if (typeof CSS !== "undefined" && typeof CSS.escape === "function") return CSS.escape(value);
    return String(value).replace(/(["\\\]])/g, "\\$1");
  }

  function nodeById(draft, nodeId) {
    return draft?.nodes?.find((node) => node.id === nodeId) || null;
  }

  function isAnswerNode(node) {
    return String(node?.type || "").toLowerCase() === "answer" || String(node?.id || "").toLowerCase() === "answer";
  }

  function edgeLabel(condition) {
    const clean = String(condition || "").trim();
    if (!clean) return "";
    const preset = EDGE_CONDITION_PRESETS_DEFAULT.find((item) => item.value === clean);
    if (preset && preset.value) return preset.label;
    return clean.length > 28 ? `${clean.slice(0, 25)}...` : clean;
  }

  function routeLabel(condition) {
    const clean = String(condition || "").trim();
    if (!clean) return "always";
    const label = edgeLabel(clean);
    return label.toLowerCase();
  }

  function edgeRouteLabel(edge, draft) {
    const condition = String(edge?.when || "").trim();
    if (!condition) return "";
    const source = nodeById(draft, edge.from);
    if (canonicalNodeType(source?.type) === "decision") {
      const branch = normalizeDecisionBranches(source.config || {}).find((item) => item.when === condition);
      if (branch?.label) return String(branch.label).toLowerCase();
    }
    return routeLabel(condition);
  }

  function nodeDisplayName(node, fallback = "") {
    return node?.title || node?.id || fallback;
  }

  function routeSummary(edge, draft) {
    const source = nodeById(draft, edge.from);
    const target = nodeById(draft, edge.to);
    const sourceName = nodeDisplayName(source, edge.from);
    const targetName = nodeDisplayName(target, edge.to);
    const condition = String(edge.when || "").trim();
    const label = edgeRouteLabel(edge, draft) || "always";
    if (!condition) {
      return {
        badge: "always",
        path: `${sourceName} -- always --> ${targetName}`,
        sentence: `After ${sourceName} finishes, go to ${targetName}.`,
      };
    }
    if (condition === "error") {
      return {
        badge: "error",
        path: `${sourceName} -- error --> ${targetName}`,
        sentence: `If ${sourceName} fails, go to ${targetName}.`,
      };
    }
    if (canonicalNodeType(source?.type) === "decision") {
      return {
        badge: label,
        path: `${sourceName} -- ${label} --> ${targetName}`,
        sentence: `If ${sourceName} returns ${label}, go to ${targetName}.`,
      };
    }
    return {
      badge: label,
      path: `${sourceName} -- ${label} --> ${targetName}`,
      sentence: `When ${condition} is true, go to ${targetName}.`,
    };
  }

  function edgeConditionPresets(edge, draft) {
    const source = nodeById(draft, edge.from);
    const target = nodeById(draft, edge.to);
    const sourceType = canonicalNodeType(source?.type);
    const targetType = canonicalNodeType(target?.type);
    const sourceName = nodeDisplayName(source, edge.from);
    const presets = [{ label: "Always after this step", value: "" }];

    if (sourceType === "decision") {
      normalizeDecisionBranches(source.config || {}).forEach((branch) => {
        presets.push({ label: `${sourceName} returns ${branch.label}`, value: branch.when });
      });
    }
    if (sourceType === "role" || sourceType === "orchestrator") {
      presets.push({ label: "Plan confidence is low", value: "plan.confidence < 0.7" });
    }
    if (targetType === "report") {
      presets.push({ label: "Enough worker reports exist", value: "worker_reports.length >= 3" });
    }
    presets.push({ label: "If this step errors", value: "error" });
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

  function isMainFlowEdge(edge, nodeById) {
    const source = nodeById.get(edge.from);
    const when = String(edge.when || "");
    return Boolean(
      source
        && !when.includes("retry")
        && when !== "error"
        && canonicalNodeType(source.type) !== "pause",
    );
  }

  function graphLayers(nodes, edges) {
    const ids = new Set(nodes.map((node) => node.id));
    const nodeMap = new Map(nodes.map((node) => [node.id, node]));
    const incoming = new Map(nodes.map((node) => [node.id, 0]));
    const outgoing = new Map(nodes.map((node) => [node.id, []]));
    const layoutEdges = edges.filter((edge) => isMainFlowEdge(edge, nodeMap));
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

  function compactGraphLayers(nodes, edges) {
    const nodeMap = new Map(nodes.map((node) => [node.id, node]));
    const primaryEdges = edges.filter((edge) => {
      const target = nodeMap.get(edge.to);
      return isMainFlowEdge(edge, nodeMap) && String(target?.type || "").toLowerCase() !== "pause";
    });
    const incoming = new Set(primaryEdges.map((edge) => edge.to));
    const outgoing = new Map();
    primaryEdges.forEach((edge) => {
      if (!outgoing.has(edge.from)) outgoing.set(edge.from, []);
      outgoing.get(edge.from).push(edge.to);
    });

    const ordered = [];
    const seen = new Set();
    const start = nodes.find((node) => boundaryKind(node) === PORT_INPUT)
      || nodes.find((node) => !incoming.has(node.id))
      || nodes[0];
    let current = start?.id || "";
    while (current && nodeMap.has(current) && !seen.has(current)) {
      seen.add(current);
      ordered.push(nodeMap.get(current));
      current = (outgoing.get(current) || []).find((id) => !seen.has(id)) || "";
    }

    nodes.forEach((node) => {
      if (!seen.has(node.id) && canonicalNodeType(node.type) !== "pause") ordered.push(node);
    });

    const topRowCount = ordered.length > 5 ? Math.ceil(ordered.length / 2) : Math.min(ordered.length, 4);
    const topOffset = Math.max(0, topRowCount - 2);
    const layered = ordered.map((node, index) => {
      const bottom = index >= topRowCount;
      return {
        ...node,
        _graphCol: bottom ? index - topRowCount + topOffset : index,
        _graphRow: bottom ? 1 : 0,
      };
    });
    const layeredById = new Map(layered.map((node) => [node.id, node]));
    const topCols = new Set(layered.filter((node) => node._graphRow === 0).map((node) => node._graphCol));
    const pauseEdges = edges.filter((edge) => {
      const target = nodeMap.get(edge.to);
      return isMainFlowEdge(edge, nodeMap) && String(target?.type || "").toLowerCase() === "pause";
    });
    nodes
      .filter((node) => canonicalNodeType(node.type) === "pause")
      .forEach((node) => {
        const sourceEdge = pauseEdges.find((edge) => edge.to === node.id);
        const sourceLayer = sourceEdge ? layeredById.get(sourceEdge.from) : null;
        let col = sourceLayer ? sourceLayer._graphCol + 2 : topRowCount;
        while (topCols.has(col)) col += 1;
        topCols.add(col);
        layered.push({ ...node, _graphCol: col, _graphRow: 0 });
      });
    return {
      nodes: layered,
      cols: Math.max(1, ...layered.map((node) => node._graphCol + 1)),
      rows: Math.max(1, ...layered.map((node) => node._graphRow + 1)),
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
    const layers = compact ? compactGraphLayers(nodes, graphEdges) : graphLayers(nodes, graphEdges);
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
        const labelText = edgeRouteLabel(edge, workflow);
        if (target.x > source.x) {
          const sx = source.x + nodeWidth;
          const sy = source.y + nodeHeight / 2;
          const tx = target.x;
          const ty = target.y + nodeHeight / 2;
          const curve = Math.max(12, Math.min(48, (tx - sx) * 0.5));
          const label = labelText ? graphEdgeLabel(labelText, (sx + tx) / 2, (sy + ty) / 2 - 14 - ((index % 2) * 14)) : "";
          return `<path class="workflow-graph-edge${edge.when === "error" ? " error" : ""}" d="M ${sx} ${sy} C ${sx + curve} ${sy}, ${tx - curve} ${ty}, ${tx} ${ty}" />${label}`;
        }
        if (target.y > source.y) {
          const sx = source.x + nodeWidth / 2;
          const sy = source.y + nodeHeight;
          const tx = target.x + nodeWidth / 2;
          const ty = target.y;
          const label = labelText ? graphEdgeLabel(labelText, (sx + tx) / 2, (sy + ty) / 2 - 12 - ((index % 2) * 12)) : "";
          return `<path class="workflow-graph-edge${edge.when === "error" ? " error" : ""}" d="M ${sx} ${sy} C ${sx} ${sy + 26}, ${tx} ${ty - 26}, ${tx} ${ty}" />${label}`;
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
        const nodeType = canonicalNodeType(node.type);
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
      <svg class="workflow-graph-svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Workflow graph">
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

  function alignBoundaryNodes(draft) {
    const inputNode = draft.nodes.find((node) => boundaryKind(node) === PORT_INPUT);
    const outputNode = draft.nodes.find((node) => boundaryKind(node) === PORT_OUTPUT);
    const realNodes = realWorkflowNodes(draft.nodes);
    if (!realNodes.length) return;

    const realNodeById = new Map(realNodes.map((node) => [node.id, node]));
    const realEdges = deriveWorkflowEdgesFromNodes(realNodes, draft.edges || []).filter(
      (edge) => isMainFlowEdge(edge, realNodeById),
    );
    const incoming = new Set(realEdges.map((edge) => edge.to));
    const outgoing = new Set(realEdges.map((edge) => edge.from));
    const starts = realNodes.filter((node) => !incoming.has(node.id));
    const terminals = realNodes.filter((node) => !outgoing.has(node.id));
    const firstStart = starts[0] || realNodes[0];
    const answerTerminal = terminals.find((node) => canonicalNodeType(node.type) === "answer");
    const firstTerminal = answerTerminal || terminals[0] || realNodes[realNodes.length - 1];

    if (inputNode && firstStart?.position) {
      inputNode.position = {
        x: Math.max(CANVAS_PAD, Number(firstStart.position.x) - CANVAS_LAYOUT_X),
        y: Number(firstStart.position.y),
      };
    }
    if (outputNode && firstTerminal?.position) {
      outputNode.position = {
        x: Number(firstTerminal.position.x) + CANVAS_LAYOUT_X,
        y: Number(firstTerminal.position.y),
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
    if (port && workflowCanvas?.contains(port)) return port;
    return nearestCanvasPort(event, 18);
  }

  function nearestCanvasPort(event, radius = 18) {
    let best = null;
    let bestDistance = radius;
    workflowCanvasNodes?.querySelectorAll(".workflow-canvas-port").forEach((port) => {
      const rect = port.getBoundingClientRect();
      const cx = rect.left + rect.width / 2;
      const cy = rect.top + rect.height / 2;
      const distance = Math.hypot(event.clientX - cx, event.clientY - cy);
      if (distance <= bestDistance) {
        best = port;
        bestDistance = distance;
      }
    });
    return best;
  }

  function canvasLinkTargetIdFromPointer(event) {
    const port = canvasPortFromPoint(event);
    if (!port || port.dataset.portType !== PORT_INPUT) return null;
    const targetId = port.closest(".workflow-canvas-node")?.dataset.nodeId || "";
    if (!targetId || targetId === linkDrag.sourceId) return null;
    const draft = bridge.activeWorkflowDraft();
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
    const draft = bridge.activeWorkflowDraft();
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
    const draft = bridge.activeWorkflowDraft();
    const target = draft?.nodes.find((node) => node.id === targetId);
    if (!draft || !target || !hasInputPort(target)) return false;
    const edge = incomingEdgeForNode(draft, targetId, true);
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
    const draft = bridge.activeWorkflowDraft();
    if (!draft || !sourceId || !targetId || sourceId === targetId) return false;
    const source = draft.nodes.find((node) => node.id === sourceId);
    const target = draft.nodes.find((node) => node.id === targetId);
    if (!source || !target) return false;
    if (!hasOutputPort(source) || !hasInputPort(target)) return false;
    restoreAutoBoundaryEdge(target, WORKFLOW_INPUT_ID, target.id);
    restoreAutoBoundaryEdge(source, source.id, WORKFLOW_OUTPUT_ID);
    const outputIdentifier = nodeOutputIdentifier(source);
    const previousEdges = deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || []);
    const exists = previousEdges.some((edge) => edge.from === source.id && edge.to === target.id);
    const sourceType = canonicalNodeType(source.type);
    const branches = sourceType === "decision" ? normalizeDecisionBranches(source.config || {}) : [];
    const when = branches[0]?.when || "";
    if (!exists) mutateWorkflowEdges(draft, { type: "add", from: source.id, to: target.id, when });
    const changed = !exists;
    if (outputIdentifier) {
      target.config = typeof target.config === "object" && target.config ? target.config : {};
      const key = `${source.id}:${outputIdentifier}`;
      const removedAutoInputs = Array.isArray(target.config._removed_auto_inputs) ? target.config._removed_auto_inputs : [];
      if (removedAutoInputs.includes(key)) {
        renderWorkflowCanvas();
        if (changed) bridge.afterWorkflowMutation?.();
        setStatus(changed ? "Nodes linked" : "Nodes already linked");
        return true;
      }
      // Canvas links suggest the source output once; manual removals are remembered by _removed_auto_inputs.
      addUniqueNodeListValue(target, "input", outputIdentifier);
    }
    renderWorkflowCanvas();
    if (changed) bridge.afterWorkflowMutation?.();
    if (state.workflowEditorSelectedNodeId) {
      bridge.selectWorkflowNode(state.workflowEditorSelectedNodeId);
    }
    setStatus(changed ? "Nodes linked" : "Nodes already linked");
    return true;
  }

  function removeCanvasConnection(sourceId, targetId) {
    const draft = bridge.activeWorkflowDraft();
    if (!draft || !sourceId || !targetId) return false;
    const source = draft.nodes.find((node) => node.id === sourceId);
    const target = draft.nodes.find((node) => node.id === targetId);
    if (!source || !target) return false;
    const inputIdentifier = nodeOutputIdentifier(source);
    const before = deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || []).length;
    mutateWorkflowEdges(draft, { type: "remove", from: sourceId, to: targetId });
    const changed = deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || []).length !== before;
    let suppressedAutoEdge = false;
    if (!changed && sourceId === WORKFLOW_INPUT_ID) {
      suppressedAutoEdge = suppressAutoBoundaryEdge(target, sourceId, targetId);
    }
    if (!changed && targetId === WORKFLOW_OUTPUT_ID) {
      suppressedAutoEdge = suppressAutoBoundaryEdge(source, sourceId, targetId);
    }
    const inputChanged = removeAutoInputReference(draft, target, inputIdentifier);
    if (changed || inputChanged || suppressedAutoEdge) bridge.afterWorkflowMutation?.();
    return changed || inputChanged || suppressedAutoEdge;
  }

  function refreshWorkflowCanvasAfterLinkChange() {
    renderWorkflowCanvas();
    if (state.workflowEditorSelectedNodeId) {
      bridge.selectWorkflowNode(state.workflowEditorSelectedNodeId);
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
    const draft = bridge.activeWorkflowDraft();
    if (!workflowCanvasNodes || !workflowCanvasEdgeLayer || !draft) return;
    closeEdgeRulePopover();
    ensureNodePositions(draft);
    workflowCanvasNodes.innerHTML = "";
    let maxRight = CANVAS_PAD + NODE_TILE_WIDTH + CANVAS_PAD;
    let maxBottom = CANVAS_PAD + NODE_TILE_HEIGHT + CANVAS_PAD;
    draft.nodes.forEach((node) => {
      const isWorker = canonicalNodeType(node.type) === "worker_pool";
      const isIteration = ["for_each", "while"].includes(canonicalNodeType(node.type));
      const connections = derivedNodeConnections(draft, node.id);
      const visualNode = { ...node, receive_from: connections.incoming, reports_to: connections.outgoing };
      const tile = document.createElement("article");
      tile.className = "workflow-canvas-node"
        + (isWorker ? " worker" : "")
        + (isIteration ? " iteration" : "")
        + (isBoundaryNode(node) ? " boundary" : "");
      if (state.workflowEditorSelectedNodeId === node.id) tile.classList.add("is-selected");
      tile.dataset.nodeId = node.id;
      tile.style.left = `${node.position.x}px`;
      tile.style.top = `${node.position.y}px`;
      tile.innerHTML = nodeTileMarkup(visualNode);
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
    bridge.renderWorkflowHealthPanel?.();
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
      path.dataset.edgeFrom = edge.from;
      path.dataset.edgeTo = edge.to;
      path.dataset.edgeWhen = edge.when || "";
      path.setAttribute("d", canvasConnectionPath(sourcePoint, targetPoint, isLoop, laneOffset));
      path.setAttribute("marker-end", "url(#wf-canvas-arrow)");
      workflowCanvasEdgeLayer.append(path);
      if (edge.when) renderCanvasEdgeLabel(edge, sourcePoint, targetPoint, isLoop, laneOffset);
    });
  }

  function renderCanvasEdgeLabel(edge, sourcePoint, targetPoint, isLoop = false, laneOffset = 0) {
    if (!workflowCanvasLabels) return;
    const label = edgeRouteLabel(edge, bridge.activeWorkflowDraft()) || edgeLabel(edge.when);
    const x = (sourcePoint.x + targetPoint.x) / 2;
    const y = isLoop
      ? Math.max(sourcePoint.y, targetPoint.y) + 38 + laneOffset
      : (sourcePoint.y + targetPoint.y) / 2 - 18 + laneOffset * 0.35;
    const badge = document.createElement("span");
    badge.className = `workflow-canvas-edge-label${edge.when === "error" ? " error" : ""}`;
    badge.textContent = label;
    badge.title = String(edge.when || "");
    badge.dataset.edgeFrom = edge.from;
    badge.dataset.edgeTo = edge.to;
    badge.dataset.edgeWhen = edge.when || "";
    badge.setAttribute("role", "button");
    badge.tabIndex = 0;
    badge.style.left = `${x}px`;
    badge.style.top = `${y}px`;
    workflowCanvasLabels.append(badge);
  }

  function renderEdgeRules(draft) {
    if (!workflowEdgeRulesList || !draft) return;
    const edges = deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || []);
    if (edges.length === 0) {
      workflowEdgeRulesList.innerHTML = '<p class="settings-empty">No connections yet.</p>';
      return;
    }
    workflowEdgeRulesList.innerHTML = edges
      .map((edge, index) => {
        const current = String(edge.when || "");
        const presets = edgeConditionPresets(edge, draft);
        const presetValue = presets.some((item) => item.value === current) ? current : "__custom";
        const route = routeSummary(edge, draft);
        const path = edgeDisplayName(edge, draft);
        return `
          <div class="workflow-edge-rule" data-edge-index="${index}">
            <div class="workflow-edge-rule-route">
              <span class="workflow-edge-rule-path">${escapeHtml(route.path)}</span>
              <span class="workflow-edge-rule-sentence">${escapeHtml(route.sentence)}</span>
            </div>
            <span class="workflow-edge-rule-badge ${escapeHtml(route.badge === "error" ? "error" : "")}">${escapeHtml(route.badge)}</span>
            <select class="workflow-edge-rule-preset" aria-label="Condition preset for ${escapeHtml(path)}">
              ${presets.map((item) => `<option value="${escapeHtml(item.value)}"${presetValue === item.value ? " selected" : ""}>${escapeHtml(item.label)}</option>`).join("")}
            </select>
          </div>
        `;
      })
      .join("");
  }

  function applyEdgeRuleChange(target) {
    const row = target.closest?.(".workflow-edge-rule");
    const draft = bridge.activeWorkflowDraft();
    if (!row || !draft) return;
    const index = Number(row.dataset.edgeIndex);
    const edges = deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || []);
    const edge = edges[index];
    if (!edge) return;
    const preset = row.querySelector(".workflow-edge-rule-preset");
    let when = String(preset?.value || "");
    mutateWorkflowEdges(draft, { type: "update", from: edge.from, to: edge.to, fromWhen: edge.when, when });
    renderCanvasEdges(draft);
    bridge.afterWorkflowMutation?.();
  }

  function applyEdgeRule(edge, when) {
    const draft = bridge.activeWorkflowDraft();
    if (!draft || !edge) return false;
    const edges = deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || []);
    const index = edges.findIndex((candidate) => (
      candidate.from === edge.from
      && candidate.to === edge.to
      && String(candidate.when || "") === String(edge.when || "")
    ));
    if (index < 0) return false;
    bridge.beforeWorkflowMutation?.();
    mutateWorkflowEdges(draft, { type: "update", from: edge.from, to: edge.to, fromWhen: edge.when, when });
    state.workflowEditorSelectedEdge = { from: edge.from, to: edge.to, when: String(when || "") };
    renderWorkflowCanvas();
    selectCanvasEdge(state.workflowEditorSelectedEdge);
    bridge.afterWorkflowMutation?.();
    return true;
  }

  function deleteSelectedEdge() {
    const selected = state.workflowEditorSelectedEdge;
    const draft = bridge.activeWorkflowDraft();
    if (!draft || !selected) return false;
    const before = deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || []).length;
    mutateWorkflowEdges(draft, { type: "remove", from: selected.from, to: selected.to, when: selected.when });
    state.workflowEditorSelectedEdge = null;
    if (deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || []).length === before) return false;
    renderWorkflowCanvas();
    bridge.afterWorkflowMutation?.();
    setStatus("Connection removed");
    return true;
  }

  function closeEdgeRulePopover() {
    edgeRulePopover?.remove();
    edgeRulePopover = null;
    document.removeEventListener("pointerdown", handleEdgePopoverOutside);
  }

  function handleEdgePopoverOutside(event) {
    if (!edgeRulePopover || edgeRulePopover.contains(event.target)) return;
    if (event.target.closest?.(".workflow-canvas-edge-label")) return;
    closeEdgeRulePopover();
  }

  function openEdgeRulePopover(edge, anchor) {
    closeEdgeRulePopover();
    const draft = bridge.activeWorkflowDraft();
    if (!draft || !edge || !anchor) return;
    const presets = edgeConditionPresets(edge, draft);
    const popover = document.createElement("div");
    popover.className = "workflow-edge-popover";
    popover.innerHTML = `
      <strong>${escapeHtml(edgeDisplayName(edge, draft))}</strong>
      <select class="workflow-edge-popover-select" aria-label="Connection branch">
        ${presets.map((item) => `<option value="${escapeHtml(item.value)}"${String(edge.when || "") === item.value ? " selected" : ""}>${escapeHtml(item.label)}</option>`).join("")}
      </select>
      <button type="button" class="danger-button workflow-edge-popover-delete">Delete Edge</button>
    `;
    popover.querySelector(".workflow-edge-popover-select")?.addEventListener("change", (event) => {
      applyEdgeRule(edge, event.target.value);
    });
    popover.querySelector(".workflow-edge-popover-delete")?.addEventListener("click", () => {
      bridge.beforeWorkflowMutation?.();
      state.workflowEditorSelectedEdge = { from: edge.from, to: edge.to, when: edge.when || "" };
      deleteSelectedEdge();
      closeEdgeRulePopover();
    });
    workflowCanvas?.append(popover);
    edgeRulePopover = popover;
    const canvasRect = workflowCanvas.getBoundingClientRect();
    const anchorRect = anchor.getBoundingClientRect();
    const popRect = popover.getBoundingClientRect();
    const x = anchorRect.left - canvasRect.left + workflowCanvas.scrollLeft + anchorRect.width / 2 - popRect.width / 2;
    const y = anchorRect.bottom - canvasRect.top + workflowCanvas.scrollTop + 8;
    popover.style.left = `${Math.max(8, Math.min(x, workflowCanvas.scrollWidth - popRect.width - 8))}px`;
    popover.style.top = `${Math.max(8, y)}px`;
    requestAnimationFrame(() => document.addEventListener("pointerdown", handleEdgePopoverOutside));
  }

  function selectCanvasEdge(edge, anchor = null) {
    state.workflowEditorSelectedEdge = edge ? { from: edge.from, to: edge.to, when: edge.when || "" } : null;
    workflowCanvasEdgeLayer?.querySelectorAll(".workflow-canvas-edge.is-selected").forEach((item) => item.classList.remove("is-selected"));
    workflowCanvasLabels?.querySelectorAll(".workflow-canvas-edge-label.is-selected").forEach((item) => item.classList.remove("is-selected"));
    if (!edge) return;
    const selector = `[data-edge-from="${cssEscape(edge.from)}"][data-edge-to="${cssEscape(edge.to)}"][data-edge-when="${cssEscape(edge.when || "")}"]`;
    workflowCanvasEdgeLayer?.querySelector(selector)?.classList.add("is-selected");
    workflowCanvasLabels?.querySelector(selector)?.classList.add("is-selected");
    if (anchor) openEdgeRulePopover(edge, anchor);
  }

  function relayoutCanvasNodes() {
    const draft = bridge.activeWorkflowDraft();
    if (!draft) return;
    layoutCanvasNodes(realWorkflowNodes(draft.nodes), deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || []));
    alignBoundaryNodes(draft);
    renderWorkflowCanvas();
    bridge.afterWorkflowMutation?.();
    setStatus("Workflow layout refreshed");
  }

  function renderWorkflowHealthPanel(container) {
    if (!container) return;
    const draft = bridge.activeWorkflowDraft();
    const issues = validateWorkflowHealth(draft, state.workflowPresets || []);
    const debugMode = Boolean(state.workflowDebugMode);
    const visibleIssues = issues.filter((issue) => debugMode || !issue.debug);
    const hiddenDebugCount = issues.length - visibleIssues.length;
    if (!draft || visibleIssues.length === 0) {
      container.innerHTML = '<span class="workflow-health-ok">Looks good. No workflow issues found.</span>';
      if (hiddenDebugCount > 0) {
        container.innerHTML += `<span class="workflow-health-debug-note">${hiddenDebugCount} debug hint${hiddenDebugCount === 1 ? "" : "s"} hidden.</span>`;
      }
      return;
    }
    container.innerHTML = `
      <div class="workflow-health-heading">
        <strong>Workflow Health</strong>
        <span>${visibleIssues.length} thing${visibleIssues.length === 1 ? "" : "s"} to check${hiddenDebugCount > 0 ? ` · ${hiddenDebugCount} debug hidden` : ""}</span>
      </div>
      <div class="workflow-health-issues">
        ${visibleIssues.map((issue) => `
          <button type="button" class="workflow-health-issue ${escapeHtml(issue.severity)}${issue.debug ? " debug" : ""}" data-node-id="${escapeHtml(issue.nodeId || "")}" aria-label="${escapeHtml(issue.message || issue.title || "")}">
            <span class="workflow-health-title">${escapeHtml(issue.title || issue.message || "Check this step")}</span>
            ${issue.action ? `<span class="workflow-health-action"><span>To do:</span> ${escapeHtml(issue.action)}</span>` : ""}
            ${issue.detail ? `<span class="workflow-health-detail"><span>Why:</span> ${escapeHtml(issue.detail)}</span>` : ""}
          </button>
        `).join("")}
      </div>
    `;
  }

  return {
    bridge,
    canvasDrag,
    linkDrag,
    cssEscape,
    edgeLabel,
    workflowGraphMarkup,
    renderWorkflowCanvas,
    renderCanvasEdges,
    renderEdgeRules,
    applyEdgeRuleChange,
    deleteSelectedEdge,
    selectCanvasEdge,
    closeEdgeRulePopover,
    relayoutCanvasNodes,
    renderWorkflowHealthPanel,
    syncDerivedEdges,
    startCanvasLinkDrag,
    startCanvasRelinkDrag,
    finishCanvasLinkDrag,
    cleanupCanvasLinkDrag,
    updateCanvasLinkPreview,
    removeCanvasConnection,
    refreshWorkflowCanvasAfterLinkChange,
  };
}
