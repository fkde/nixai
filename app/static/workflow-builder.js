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
export const DECISION_BRANCHES = [
  { label: "Done", when: "decision.status == 'done'", target: "" },
  { label: "Retry", when: "decision.status == 'retry'", target: "" },
  { label: "Needs user", when: "decision.status == 'needs_user'", target: "" },
];

export function canonicalNodeType(type) {
  const clean = String(type || "role").trim().toLowerCase();
  if (clean === "final") return "answer";
  if (clean === "judge") return "decision";
  if (clean === "reviewer") return "report";
  return clean || "role";
}

export function defaultDecisionBranches() {
  return DECISION_BRANCHES.map((branch) => ({ ...branch }));
}

export function normalizeDecisionBranches(config = {}) {
  const rawBranches = Array.isArray(config.branches) ? config.branches : [];
  const byWhen = new Map();
  [...DECISION_BRANCHES, ...rawBranches].forEach((branch) => {
    const label = String(branch?.label || "").trim();
    const when = String(branch?.when || "").trim();
    if (!label || !when) return;
    byWhen.set(when, {
      label,
      when,
      target: String(branch?.target || "").trim(),
    });
  });
  return [...byWhen.values()];
}

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

  const shouldShiftForNewInput = !hadInput
    && !normalized.some((node) => Boolean(node?._boundaryShifted))
    && realNodes.some((node) => Number(node.position?.x || 0) < CANVAS_PAD + NODE_GRID_X);
  if (shouldShiftForNewInput) {
    realNodes.forEach((node) => {
      const x = Number(node.position?.x || 0);
      const y = Number(node.position?.y || 0);
      if (Number.isFinite(x) && Number.isFinite(y) && (x !== 0 || y !== 0)) {
        node.position = { x: x + NODE_GRID_X, y };
        node._boundaryShifted = true;
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
    const type = canonicalNodeType(node.type || deriveNodeTypeFromRole(node.role, node.worker_instances || node.max_parallel));
    const rawId = migrateNodeId(node.id || `node_${index + 1}`);
    const rawConfig = typeof node.config === "object" && node.config ? { ...node.config } : {};
    const config = type === "decision"
      ? { ...rawConfig, branches: normalizeDecisionBranches(rawConfig) }
      : rawConfig;
    return {
      id: rawId || `node_${index + 1}`,
      type,
      role: String(node.role || (type === "decision" ? "judge" : type === "report" ? "reviewer" : "")),
      title: String(node.title || ""),
      prompt: String(node.prompt || ""),
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
      config,
      retry: typeof node.retry === "object" && node.retry ? node.retry : { max: 0, backoff: 0 },
      break_when: String(node.break_when || ""),
      ref: String(node.ref || ""),
    };
  });

  const nodeIds = new Set(nodes.map((node) => node.id));
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
    edges: syncDerivedEdges({ ...(workflow || {}), nodes }, nodes),
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
  if (role === "judge") return "decision";
  if (role === "reviewer") return "report";
  if (role === "worker") return "worker_pool";
  return "role";
}

export function deriveWorkflowEdgesFromNodes(nodes, existingEdges = [], includeBoundaryEdges = false) {
  const available = new Set((nodes || []).map((node) => node.id));
  const dedupe = new Set();
  const edges = [];
  (existingEdges || []).forEach((edge) => {
    const source = String(edge.from || edge.from_node || "").trim();
    const target = String(edge.to || "").trim();
    const when = String(edge.when || "").trim();
    if (!source || !target || !available.has(source) || !available.has(target)) return;
    const key = `${source}->${target}->${when}`;
    if (dedupe.has(key)) return;
    dedupe.add(key);
    edges.push({ from: source, to: target, when });
  });
  if (includeBoundaryEdges && available.has(WORKFLOW_INPUT_ID) && available.has(WORKFLOW_OUTPUT_ID)) {
    const realNodes = (nodes || []).filter((node) => !isBoundaryNode(node));
    const nodeById = new Map(realNodes.map((node) => [node.id, node]));
    const isMainFlowEdge = (edge) => {
      const source = nodeById.get(edge.from);
      const when = String(edge.when || "");
      return source && !when.includes("retry") && when !== "error" && String(source.type || "").toLowerCase() !== "pause";
    };
    const flowEdges = edges.filter(isMainFlowEdge);
    const targets = new Set(flowEdges.map((edge) => edge.to));
    const sources = new Set(flowEdges.map((edge) => edge.from));
    const answerNodes = realNodes.filter((node) => String(node.type || "").toLowerCase() === "answer");
    const outputNodes = answerNodes.length > 0
      ? answerNodes
      : realNodes.filter((node) => !sources.has(node.id) && String(node.type || "").toLowerCase() !== "pause");
    realNodes
      .filter((node) => !targets.has(node.id))
      .forEach((node) => {
        const key = `${WORKFLOW_INPUT_ID}->${node.id}`;
        if (isAutoBoundaryEdgeSuppressed(node, WORKFLOW_INPUT_ID, node.id)) return;
        if (!dedupe.has(key)) {
          dedupe.add(key);
          edges.unshift({ from: WORKFLOW_INPUT_ID, to: node.id, when: "" });
        }
      });
    outputNodes.forEach((node) => {
      const key = `${node.id}->${WORKFLOW_OUTPUT_ID}`;
      if (isAutoBoundaryEdgeSuppressed(node, node.id, WORKFLOW_OUTPUT_ID)) return;
      if (!dedupe.has(key)) {
        dedupe.add(key);
        edges.push({ from: node.id, to: WORKFLOW_OUTPUT_ID, when: "" });
      }
    });
  }
  return edges;
}

export function mutateWorkflowEdges(draft, op) {
  if (!draft || !op) return [];
  const edges = deriveWorkflowEdgesFromNodes(draft.nodes || [], draft.edges || []);
  const dedupe = (items) => {
    const seen = new Set();
    return items.filter((edge) => {
      const from = String(edge.from || edge.from_node || "").trim();
      const to = String(edge.to || "").trim();
      const when = String(edge.when || "").trim();
      const key = `${from}->${to}->${when}`;
      if (!from || !to || seen.has(key)) return false;
      seen.add(key);
      return true;
    }).map((edge) => ({ from: edge.from || edge.from_node, to: edge.to, when: String(edge.when || "").trim() }));
  };
  if (op.type === "add") {
    draft.edges = dedupe([...edges, { from: op.from, to: op.to, when: op.when || "" }]);
    return draft.edges;
  }
  if (op.type === "remove") {
    draft.edges = edges.filter((edge) => {
      const matchesFrom = op.from === undefined || edge.from === op.from;
      const matchesTo = op.to === undefined || edge.to === op.to;
      const matchesWhen = op.when === undefined || String(edge.when || "") === String(op.when || "");
      return !(matchesFrom && matchesTo && matchesWhen);
    });
    return draft.edges;
  }
  if (op.type === "update") {
    draft.edges = dedupe(edges.map((edge) => {
      const matchesPair = edge.from === op.from && edge.to === op.to;
      const matchesWhen = op.fromWhen === undefined || String(edge.when || "") === String(op.fromWhen || "");
      return matchesPair && matchesWhen ? { ...edge, when: String(op.when || "").trim() } : edge;
    }));
    return draft.edges;
  }
  if (op.type === "renameNode") {
    draft.edges = dedupe(edges.map((edge) => ({
      ...edge,
      from: edge.from === op.fromId ? op.toId : edge.from,
      to: edge.to === op.fromId ? op.toId : edge.to,
    })));
    return draft.edges;
  }
  draft.edges = dedupe(edges);
  return draft.edges;
}

export function syncDerivedEdges(workflow, nodes = workflow?.nodes || []) {
  const normalizedEdges = normalizeWorkflowEdges(workflow || {}, nodes);
  if (normalizedEdges.length > 0) return normalizedEdges;
  const available = new Set((nodes || []).map((node) => node.id));
  const dedupe = new Set();
  const migrated = [];
  (nodes || []).forEach((node) => {
    const source = String(node.id || "").trim();
    if (!source) return;
    const reports = dedupeList(Array.isArray(node.reports_to) ? node.reports_to : parseCsvList(node.reports_to || ""));
    reports.forEach((target) => {
      const to = String(target || "").trim();
      const key = `${source}->${to}->`;
      if (!to || !available.has(to) || dedupe.has(key)) return;
      dedupe.add(key);
      migrated.push({ from: source, to, when: "" });
    });
    const incoming = dedupeList(Array.isArray(node.receive_from) ? node.receive_from : parseCsvList(node.receive_from || ""));
    incoming.forEach((from) => {
      const cleanFrom = String(from || "").trim();
      const key = `${cleanFrom}->${source}->`;
      if (!cleanFrom || !available.has(cleanFrom) || dedupe.has(key)) return;
      dedupe.add(key);
      migrated.push({ from: cleanFrom, to: source, when: "" });
    });
  });
  return migrated;
}

export function autoBoundaryEdgeKey(from, to) {
  return `${String(from || "").trim()}->${String(to || "").trim()}`;
}

export function isAutoBoundaryEdgeSuppressed(node, from, to) {
  const removed = Array.isArray(node?.config?._removed_auto_edges) ? node.config._removed_auto_edges : [];
  return removed.includes(autoBoundaryEdgeKey(from, to));
}

export function suppressAutoBoundaryEdge(node, from, to) {
  if (!node || !from || !to) return false;
  node.config = typeof node.config === "object" && node.config ? node.config : {};
  const key = autoBoundaryEdgeKey(from, to);
  const removed = Array.isArray(node.config._removed_auto_edges) ? node.config._removed_auto_edges : [];
  if (removed.includes(key)) return false;
  node.config._removed_auto_edges = dedupeList([...removed, key]);
  return true;
}

export function restoreAutoBoundaryEdge(node, from, to) {
  if (!node || !from || !to || !Array.isArray(node.config?._removed_auto_edges)) return false;
  const key = autoBoundaryEdgeKey(from, to);
  const next = node.config._removed_auto_edges.filter((item) => item !== key);
  const changed = next.length !== node.config._removed_auto_edges.length;
  node.config._removed_auto_edges = next;
  return changed;
}

export function derivedNodeConnections(draft, nodeId) {
  const edges = deriveWorkflowEdgesFromNodes(draft?.nodes || [], draft?.edges || []);
  return {
    incoming: dedupeList(edges.filter((edge) => edge.to === nodeId).map((edge) => edge.from)),
    outgoing: dedupeList(edges.filter((edge) => edge.from === nodeId).map((edge) => edge.to)),
  };
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
  return derivedNodeConnections(draft, targetId).incoming;
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
    const receivesFromSource = (draft.edges || []).some((edge) => (edge.from || edge.from_node) === sourceId && edge.to === node.id);
    if (!receivesFromSource) return;
    node.input = dedupeList(node.input.map((field) => (field === previousKey ? nextKey : field)));
  });
}

export function incomingEdgeForNode(draft, targetId, includeBoundaryEdges = false) {
  if (!draft || !targetId) return null;
  const incoming = deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || [], includeBoundaryEdges)
    .filter((edge) => edge.to === targetId);
  if (incoming.length === 0) return null;
  return incoming[incoming.length - 1];
}

export function validateWorkflowHealth(draft, workflowPresets = []) {
  const nodes = realWorkflowNodes(draft?.nodes || []);
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const edges = deriveWorkflowEdgesFromNodes(draft?.nodes || [], draft?.edges || []);
  const realEdges = edges.filter((edge) => nodeMap.has(edge.from) && nodeMap.has(edge.to));
  const incoming = new Map(nodes.map((node) => [node.id, 0]));
  const outgoing = new Map(nodes.map((node) => [node.id, 0]));
  realEdges.forEach((edge) => {
    incoming.set(edge.to, (incoming.get(edge.to) || 0) + 1);
    outgoing.set(edge.from, (outgoing.get(edge.from) || 0) + 1);
  });
  const issues = [];
  const addIssue = ({ nodeId = "", severity = "warning", title, detail = "", action = "", debug = false }) => {
    issues.push({
      nodeId,
      severity,
      title,
      detail,
      action,
      debug,
      message: [title, action || detail].filter(Boolean).join(" "),
    });
  };
  nodes.forEach((node) => {
    const type = canonicalNodeType(node.type);
    const nodeName = node.title || node.id;
    if ((incoming.get(node.id) || 0) === 0 && (outgoing.get(node.id) || 0) === 0) {
      addIssue({
        nodeId: node.id,
        severity: "warning",
        title: `${nodeName} is not connected`,
        action: "Connect it to another step, or remove it if it is unused.",
      });
    }
    if (type === "decision") {
      normalizeDecisionBranches(node.config || {}).forEach((branch) => {
        const hasEdge = realEdges.some((edge) => edge.from === node.id && edge.when === branch.when);
        if (!hasEdge) {
          addIssue({
            nodeId: node.id,
            severity: "warning",
            title: `Decision path "${branch.label}" has nowhere to go`,
            action: "Draw an edge from this decision to the next step for that outcome.",
          });
        }
      });
    }
    if (node.expects_json && !String(node.prompt || "").toLowerCase().includes("json")) {
      addIssue({
        nodeId: node.id,
        severity: "info",
        title: `${nodeName} returns structured data`,
        detail: "This is usually fine. The runner adds the JSON instruction automatically.",
        action: "Only edit the prompt if the model keeps returning plain text.",
        debug: true,
      });
    }
    if (type === "workflow") {
      const ref = String(node.ref || "").trim();
      if (ref && ref === String(draft?.id || "").trim()) {
        addIssue({
          nodeId: node.id,
          severity: "warning",
          title: `${nodeName} starts this same workflow again`,
          action: "Choose a different sub-workflow to avoid recursion.",
        });
      }
      const validRef = ref && workflowPresets.some((workflow) => workflow.id === ref);
      if (!validRef) {
        addIssue({
          nodeId: node.id,
          severity: "warning",
          title: `${nodeName} has no valid sub-workflow`,
          action: "Pick an existing workflow in the node settings.",
        });
      }
    }
  });
  if (!nodes.some((node) => canonicalNodeType(node.type) === "answer")) {
    addIssue({
      severity: "warning",
      title: "No final answer step",
      action: "Add an Answer node so the workflow can respond to the user.",
    });
  }
  const outgoingByNode = new Map(nodes.map((node) => [node.id, []]));
  realEdges.forEach((edge) => {
    outgoingByNode.get(edge.from)?.push(edge);
  });
  const isCycleGate = (edge) => {
    const source = nodeMap.get(edge.from);
    const target = nodeMap.get(edge.to);
    return String(edge.when || "").includes("retry")
      || canonicalNodeType(source?.type) === "pause"
      || canonicalNodeType(target?.type) === "pause";
  };
  const hasUngatedCyclePath = (from, to, initialHasRetry, blockedEdge) => {
    const queue = [{ id: from, hasRetry: initialHasRetry }];
    const seen = new Set();
    while (queue.length) {
      const current = queue.shift();
      if (!current?.id) continue;
      const key = `${current.id}:${current.hasRetry ? "retry" : "plain"}`;
      if (seen.has(key)) continue;
      if (current.id === to) return !current.hasRetry;
      seen.add(key);
      (outgoingByNode.get(current.id) || []).forEach((nextEdge) => {
        if (blockedEdge && blockedEdge.from === nextEdge.from && blockedEdge.to === nextEdge.to && blockedEdge.when === nextEdge.when) return;
        const nextHasRetry = current.hasRetry || isCycleGate(nextEdge);
        queue.push({ id: nextEdge.to, hasRetry: nextHasRetry });
      });
    }
    return false;
  };
  realEdges.forEach((edge) => {
    const createsUngatedCycle = hasUngatedCyclePath(edge.to, edge.from, isCycleGate(edge), edge);
    if (createsUngatedCycle) {
      addIssue({
        nodeId: edge.from,
        severity: "warning",
        title: `Possible endless loop: ${edge.from} → ${edge.to}`,
        detail: "This path can loop without being tied to a retry decision.",
        action: "Add a condition such as retry, or remove one of the loop edges.",
      });
    }
  });
  return issues;
}

export function nodeTileMarkup(node) {
  const nodeType = canonicalNodeType(node.type);
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
