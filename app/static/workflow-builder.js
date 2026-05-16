import { escapeHtml } from "./helpers.js";
import { dedupeList, parseCsvList } from "./workflow-editor.js";
import { modeOrder } from "./ui.js";

export const NODE_TILE_WIDTH = 168;
export const NODE_TILE_HEIGHT = 78;
export const NODE_GRID_X = 220;
export const NODE_GRID_Y = 130;
export const CANVAS_PAD = 24;
export const DRAG_THRESHOLD = 4;
export const PORT_INPUT = "input";
export const PORT_OUTPUT = "output";
export const BOUNDARY_NODE_TYPE = "io";
export const WORKFLOW_INPUT_ID = "input";
export const WORKFLOW_OUTPUT_ID = "output";

export function boundaryKind(node) {
  const id = String(node?.id || "").trim().toLowerCase();
  const type = String(node?.type || "").trim().toLowerCase();
  if (type === BOUNDARY_NODE_TYPE && id === WORKFLOW_INPUT_ID) return PORT_INPUT;
  if (type === BOUNDARY_NODE_TYPE && id === WORKFLOW_OUTPUT_ID) return PORT_OUTPUT;
  return "";
}

export function isBoundaryNode(node) {
  return Boolean(boundaryKind(node));
}

export function hasInputPort(node) {
  return boundaryKind(node) !== PORT_INPUT;
}

export function hasOutputPort(node) {
  return boundaryKind(node) !== PORT_OUTPUT;
}

export function realWorkflowNodes(nodes) {
  return (nodes || []).filter((node) => !isBoundaryNode(node));
}

export function boundaryNodeTemplate(kind) {
  const isInput = kind === PORT_INPUT;
  return {
    id: isInput ? WORKFLOW_INPUT_ID : WORKFLOW_OUTPUT_ID,
    type: BOUNDARY_NODE_TYPE,
    role: "",
    title: isInput ? "Input" : "Output",
    input: [],
    output: isInput ? "user_message" : "",
    max_parallel: 1,
    max_items: 1,
    expects_json: false,
    receive_from: [],
    reports_to: [],
    worker_instances: 1,
    position: {
      x: isInput ? CANVAS_PAD : CANVAS_PAD + NODE_GRID_X * 2,
      y: CANVAS_PAD,
    },
    config: { boundary: kind },
  };
}

export function ensureWorkflowBoundaryNodes(nodes) {
  const normalized = Array.isArray(nodes) ? nodes : [];
  const hadInput = normalized.some((node) => String(node.id || "") === WORKFLOW_INPUT_ID);
  const hadOutput = normalized.some((node) => String(node.id || "") === WORKFLOW_OUTPUT_ID);
  const realNodes = normalized.filter((node) => {
    const id = String(node.id || "");
    return id !== WORKFLOW_INPUT_ID && id !== WORKFLOW_OUTPUT_ID;
  });

  if (!hadInput && realNodes.some((node) => Number(node.position?.x || 0) < CANVAS_PAD + NODE_GRID_X)) {
    realNodes.forEach((node) => {
      const x = Number(node.position?.x || 0);
      const y = Number(node.position?.y || 0);
      if (Number.isFinite(x) && Number.isFinite(y) && (x !== 0 || y !== 0)) {
        node.position = { x: x + NODE_GRID_X, y };
      }
    });
  }

  let inputNode = normalized.find((node) => String(node.id || "") === WORKFLOW_INPUT_ID) || boundaryNodeTemplate(PORT_INPUT);
  let outputNode = normalized.find((node) => String(node.id || "") === WORKFLOW_OUTPUT_ID) || boundaryNodeTemplate(PORT_OUTPUT);
  inputNode = {
    ...boundaryNodeTemplate(PORT_INPUT),
    ...inputNode,
    id: WORKFLOW_INPUT_ID,
    type: BOUNDARY_NODE_TYPE,
    role: "",
    title: "Input",
    input: [],
    output: "user_message",
    receive_from: [],
    config: { ...(inputNode.config || {}), boundary: PORT_INPUT },
  };
  outputNode = {
    ...boundaryNodeTemplate(PORT_OUTPUT),
    ...outputNode,
    id: WORKFLOW_OUTPUT_ID,
    type: BOUNDARY_NODE_TYPE,
    role: "",
    title: "Output",
    output: "",
    reports_to: [],
    config: { ...(outputNode.config || {}), boundary: PORT_OUTPUT },
  };

  if (realNodes.length > 0) {
    const maxX = Math.max(...realNodes.map((node) => Number(node.position?.x || 0)));
    const minY = Math.min(...realNodes.map((node) => Number(node.position?.y || CANVAS_PAD)));
    const outputX = Number(outputNode.position?.x || 0);
    if (Number.isFinite(maxX) && maxX > 0 && (!hadOutput || outputX <= maxX)) {
      outputNode.position = { x: maxX + NODE_GRID_X, y: Number.isFinite(minY) ? minY : CANVAS_PAD };
    }
  }

  return [inputNode, ...realNodes, outputNode];
}

export function normalizeWorkflowNodes(workflow) {
  const rawNodes = Array.isArray(workflow?.nodes) ? workflow.nodes : [];
  const hasAnswerNode = rawNodes.some((node) => String(node.id || "").trim().toLowerCase() === "answer");
  const migrateNodeId = (id) => {
    const clean = String(id || "").trim();
    return !hasAnswerNode && clean.toLowerCase() === "final" ? "answer" : clean;
  };
  const migrateNodeRefs = (items) => dedupeList(items.map((item) => migrateNodeId(item)).filter(Boolean));
  const nodes = rawNodes.map((node, index) => {
    const inputValues = Array.isArray(node.input)
      ? node.input.map((item) => String(item).trim()).filter(Boolean)
      : String(node.input || "").trim()
        ? [String(node.input || "").trim()]
        : [];
    const rawPos = node.position && typeof node.position === "object" ? node.position : {};
    const px = Number(rawPos.x);
    const py = Number(rawPos.y);
    const rawType = String(node.type || "role").trim().toLowerCase();
    const type = rawType === "final" ? "answer" : rawType || "role";
    const rawId = migrateNodeId(node.id || `node_${index + 1}`);
    return {
      id: rawId || `node_${index + 1}`,
      type,
      role: String(node.role || ""),
      title: String(node.title || ""),
      input: inputValues,
      output: String(node.output || ""),
      max_parallel: Math.min(8, Math.max(1, Number(node.max_parallel || 1))),
      max_items: Math.min(12, Math.max(1, Number(node.max_items || 4))),
      expects_json: Boolean(node.expects_json),
      receive_from: migrateNodeRefs(
        Array.isArray(node.receive_from) ? node.receive_from : parseCsvList(node.receive_from || ""),
      ),
      reports_to: migrateNodeRefs(
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
    const source = migrateNodeId(edge.from || edge.from_node || "");
    const target = migrateNodeId(edge.to || "");
    if (!source || !target || !nodeIds.has(source) || !nodeIds.has(target)) return;
    const targetNode = nodes.find((node) => node.id === target);
    const sourceNode = nodes.find((node) => node.id === source);
    if (targetNode) targetNode.receive_from = dedupeList([...targetNode.receive_from, source]);
    if (sourceNode) sourceNode.reports_to = dedupeList([...sourceNode.reports_to, target]);
  });
  return ensureWorkflowBoundaryNodes(nodes);
}

export function normalizeWorkflowEdges(workflow, nodes = normalizeWorkflowNodes(workflow || {})) {
  const available = new Set((nodes || []).map((node) => node.id));
  const edges = Array.isArray(workflow?.edges) ? workflow.edges : [];
  const shouldMigrateAnswer = available.has("answer") && !available.has("final");
  const migrateNodeId = (id) => {
    const clean = String(id || "").trim();
    return shouldMigrateAnswer && clean.toLowerCase() === "final" ? "answer" : clean;
  };
  const dedupe = new Set();
  const normalized = [];
  edges.forEach((edge) => {
    const source = migrateNodeId(edge.from || edge.from_node || "");
    const target = migrateNodeId(edge.to || "");
    if (!source || !target || !available.has(source) || !available.has(target)) return;
    const when = String(edge.when || "").trim();
    const key = `${source}->${target}->${when}`;
    if (dedupe.has(key)) return;
    dedupe.add(key);
    normalized.push({ from: source, to: target, when });
  });
  return normalized;
}

export function normalizeWorkflowDraft(workflow) {
  const modes = Array.isArray(workflow?.modes) && workflow.modes.length > 0
    ? workflow.modes
    : [workflow?.mode || "chat"];
  const uniqueModes = dedupeList(modes.map((mode) => String(mode || "").toLowerCase()))
    .filter((mode) => modeOrder.includes(mode));
  const nodes = normalizeWorkflowNodes(workflow || {});
  return {
    id: String(workflow?.id || ""),
    name: String(workflow?.name || ""),
    description: String(workflow?.description || ""),
    mode: uniqueModes[0] || "chat",
    modes: uniqueModes.length > 0 ? uniqueModes : ["chat"],
    execution: workflow?.execution === "direct" ? "direct" : "loop",
    max_iterations: Math.min(8, Math.max(1, Number(workflow?.max_iterations || 1))),
    nodes,
    edges: normalizeWorkflowEdges(workflow || {}, nodes),
  };
}

export function newWorkflowDraftFrom(workflow) {
  const draft = normalizeWorkflowDraft(workflow || {});
  if (realWorkflowNodes(draft.nodes).length > 0) return draft;
  return {
    ...draft,
    nodes: ensureWorkflowBoundaryNodes([{
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
      position: { x: CANVAS_PAD + NODE_GRID_X, y: CANVAS_PAD },
      config: {},
    }]),
  };
}

export function deriveNodeTypeFromRole(roleName, workerInstances = 1) {
  const role = String(roleName || "").trim().toLowerCase();
  if (Number(workerInstances) > 1) return "worker_pool";
  if (role === "judge") return "judge";
  if (role === "reviewer") return "reviewer";
  if (role === "worker") return "worker_pool";
  return "role";
}

export function deriveWorkflowEdgesFromNodes(nodes, existingEdges = [], includeBoundaryEdges = false) {
  const available = new Set((nodes || []).map((node) => node.id));
  const dedupe = new Set();
  const edges = [];
  const existingByPair = new Map();
  (existingEdges || []).forEach((edge) => {
    const source = String(edge.from || edge.from_node || "").trim();
    const target = String(edge.to || "").trim();
    const when = String(edge.when || "").trim();
    if (source && target && when) existingByPair.set(`${source}->${target}`, when);
  });
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
      edges.push({ from: source, to, when: existingByPair.get(key) || "" });
    });
    const incoming = dedupeList(Array.isArray(node.receive_from) ? node.receive_from : parseCsvList(node.receive_from || ""));
    incoming.forEach((from) => {
      const cleanFrom = String(from || "").trim();
      if (!cleanFrom || !available.has(cleanFrom)) return;
      const key = `${cleanFrom}->${source}`;
      if (dedupe.has(key)) return;
      dedupe.add(key);
      edges.push({ from: cleanFrom, to: source, when: existingByPair.get(key) || "" });
    });
  });
  if (includeBoundaryEdges && available.has(WORKFLOW_INPUT_ID) && available.has(WORKFLOW_OUTPUT_ID)) {
    const realNodes = (nodes || []).filter((node) => !isBoundaryNode(node));
    const flowEdges = edges.filter((edge) => !String(edge.when || "").includes("retry"));
    const targets = new Set(flowEdges.map((edge) => edge.to));
    const sources = new Set(flowEdges.map((edge) => edge.from));
    realNodes
      .filter((node) => !targets.has(node.id))
      .forEach((node) => {
        const key = `${WORKFLOW_INPUT_ID}->${node.id}`;
        if (!dedupe.has(key)) {
          dedupe.add(key);
          edges.unshift({ from: WORKFLOW_INPUT_ID, to: node.id, when: "" });
        }
      });
    realNodes
      .filter((node) => !sources.has(node.id))
      .forEach((node) => {
        const key = `${node.id}->${WORKFLOW_OUTPUT_ID}`;
        if (!dedupe.has(key)) {
          dedupe.add(key);
          edges.push({ from: node.id, to: WORKFLOW_OUTPUT_ID, when: "" });
        }
      });
  }
  return edges;
}

export function nodeOutputIdentifier(node) {
  return String(node?.output || node?.id || "").trim();
}

export function canvasPortPoint(node, portType) {
  const pos = node?.position || {};
  const x = Number.isFinite(Number(pos.x)) ? Number(pos.x) : 0;
  const y = Number.isFinite(Number(pos.y)) ? Number(pos.y) : 0;
  return {
    x: x + (portType === PORT_OUTPUT ? NODE_TILE_WIDTH : 0),
    y: y + NODE_TILE_HEIGHT / 2,
  };
}

export function canvasConnectionPath(sourcePoint, targetPoint, isLoop = false, laneOffset = 0) {
  const dx = targetPoint.x - sourcePoint.x;
  if (isLoop) {
    const stub = 24;
    const laneY = Math.max(sourcePoint.y, targetPoint.y) + 38 + laneOffset;
    const r = 14;
    return `M ${sourcePoint.x} ${sourcePoint.y} L ${sourcePoint.x + stub} ${sourcePoint.y} Q ${sourcePoint.x + stub + r} ${sourcePoint.y}, ${sourcePoint.x + stub + r} ${sourcePoint.y + r} L ${sourcePoint.x + stub + r} ${laneY - r} Q ${sourcePoint.x + stub + r} ${laneY}, ${sourcePoint.x + stub} ${laneY} L ${targetPoint.x - stub} ${laneY} Q ${targetPoint.x - stub - r} ${laneY}, ${targetPoint.x - stub - r} ${laneY - r} L ${targetPoint.x - stub - r} ${targetPoint.y + r} Q ${targetPoint.x - stub - r} ${targetPoint.y}, ${targetPoint.x - stub} ${targetPoint.y} L ${targetPoint.x} ${targetPoint.y}`;
  }
  if (dx <= 0) {
    const midY = (sourcePoint.y + targetPoint.y) / 2 + laneOffset;
    return `M ${sourcePoint.x} ${sourcePoint.y} C ${sourcePoint.x + 44} ${sourcePoint.y}, ${sourcePoint.x + 44} ${midY}, ${sourcePoint.x + 10} ${midY} L ${targetPoint.x - 10} ${midY} C ${targetPoint.x - 44} ${midY}, ${targetPoint.x - 44} ${targetPoint.y}, ${targetPoint.x} ${targetPoint.y}`;
  }
  const curve = Math.max(50, Math.min(160, Math.abs(dx) * 0.5));
  const bend = laneOffset * 0.35;
  return `M ${sourcePoint.x} ${sourcePoint.y} C ${sourcePoint.x + curve} ${sourcePoint.y + bend}, ${targetPoint.x - curve} ${targetPoint.y + bend}, ${targetPoint.x} ${targetPoint.y}`;
}

export function addUniqueNodeListValue(node, key, value) {
  const current = Array.isArray(node[key]) ? node[key] : parseCsvList(node[key] || "");
  const next = dedupeList([...current, value]);
  node[key] = next;
  return next.length !== current.length;
}

export function removeNodeListValue(node, key, value) {
  const current = Array.isArray(node[key]) ? node[key] : parseCsvList(node[key] || "");
  const next = current.filter((item) => item !== value);
  node[key] = next;
  return next.length !== current.length;
}

export function linkedSourcesForTarget(draft, targetId) {
  if (!draft || !targetId) return [];
  const target = draft.nodes.find((node) => node.id === targetId);
  const fromReceive = target?.receive_from || [];
  const fromReports = draft.nodes
    .filter((node) => (node.reports_to || []).includes(targetId))
    .map((node) => node.id);
  return dedupeList([...fromReceive, ...fromReports]);
}

export function targetStillUsesInputIdentifier(draft, targetId, inputIdentifier) {
  if (!draft || !targetId || !inputIdentifier) return false;
  return linkedSourcesForTarget(draft, targetId).some((sourceId) => {
    const source = draft.nodes.find((node) => node.id === sourceId);
    return source && nodeOutputIdentifier(source) === inputIdentifier;
  });
}

export function removeAutoInputReference(draft, target, inputIdentifier) {
  if (!target || !inputIdentifier || !Array.isArray(target.input)) return false;
  if (targetStillUsesInputIdentifier(draft, target.id, inputIdentifier)) return false;
  const next = target.input.filter((field) => field !== inputIdentifier);
  const changed = next.length !== target.input.length;
  target.input = next;
  return changed;
}

export function updateDownstreamInputReferences(draft, sourceId, previousKey, nextKey) {
  if (!draft || !previousKey || !nextKey || previousKey === nextKey) return;
  draft.nodes.forEach((node) => {
    if (node.id === sourceId || !Array.isArray(node.input)) return;
    const receivesFromSource = (node.receive_from || []).includes(sourceId);
    const sourceReportsToNode = draft.nodes
      .find((candidate) => candidate.id === sourceId)
      ?.reports_to?.includes(node.id);
    if (!receivesFromSource && !sourceReportsToNode) return;
    node.input = dedupeList(node.input.map((field) => (field === previousKey ? nextKey : field)));
  });
}

export function incomingEdgeForNode(draft, targetId) {
  if (!draft || !targetId) return null;
  const incoming = deriveWorkflowEdgesFromNodes(draft.nodes).filter((edge) => edge.to === targetId);
  if (incoming.length === 0) return null;
  const target = draft.nodes.find((node) => node.id === targetId);
  const preferredSources = [...(target?.receive_from || [])].reverse();
  for (const sourceId of preferredSources) {
    const match = incoming.find((edge) => edge.from === sourceId);
    if (match) return match;
  }
  return incoming[incoming.length - 1];
}

export function nodeTileMarkup(node) {
  const nodeType = String(node.type || "").toLowerCase();
  const isWorker = nodeType === "worker_pool";
  const isAnswer = nodeType === "answer";
  const isIteration = ["for_each", "while"].includes(nodeType);
  const boundary = boundaryKind(node);
  const rawTitle = String(node.title || node.role || node.id || "node");
  const title = isAnswer && rawTitle.toLowerCase() === "answer" ? "Answer" : rawTitle;
  const safeTitle = escapeHtml(title);
  const outputIdentifier = nodeOutputIdentifier(node);
  const role = String(node.role || "").trim();
  const metaParts = [];
  if (isAnswer) {
    metaParts.push("assistant response");
  } else if (role) {
    metaParts.push(role);
  }
  if (isWorker) {
    metaParts.push(`≤${Math.max(1, Number(node.worker_instances || node.max_parallel || 1))}`);
  }
  if (isIteration) metaParts.push("iteration");
  if (boundary === PORT_INPUT) metaParts.push("assistant input");
  if (boundary === PORT_OUTPUT) metaParts.push("assistant output");
  if (!metaParts.length) metaParts.push(String(node.type || "role"));
  const inputPort = hasInputPort(node)
    ? `<button class="workflow-canvas-port input${(node.receive_from || []).length ? " is-connected" : ""}" data-port-type="${PORT_INPUT}" type="button" aria-label="Input for ${safeTitle}" title="${(node.receive_from || []).length ? "Drag to rewire or remove" : "Input"}"></button>`
    : "";
  const outputPort = hasOutputPort(node)
    ? `<button class="workflow-canvas-port output${(node.reports_to || []).length ? " is-connected" : ""}" data-port-type="${PORT_OUTPUT}" type="button" aria-label="Output ${escapeHtml(outputIdentifier)} from ${safeTitle}" title="Output: ${escapeHtml(outputIdentifier)}"></button>`
    : "";
  const editButton = isBoundaryNode(node)
    ? ""
    : `
      <button class="workflow-canvas-node-edit" type="button" aria-label="Edit node" title="Edit">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M4 20l4-1 11-11-3-3-11 11-1 4z" />
          <path d="M14 6l3 3" />
        </svg>
      </button>
    `;
  return `
    ${inputPort}
    ${outputPort}
    ${editButton}
    <strong>${safeTitle}</strong>
    <small>${escapeHtml(metaParts.join(" · "))}</small>
    <span class="workflow-canvas-node-id">${escapeHtml(node.id)}</span>
  `;
}
