import {
  CANVAS_PAD,
  NODE_GRID_X,
  NODE_GRID_Y,
  NODE_TILE_HEIGHT,
  NODE_TILE_WIDTH,
  canvasConnectionPath,
  canvasPortPoint,
} from "../workflow-builder.js";
import { escapeHtml } from "../helpers.js";
import { edgeKey } from "./reducer.js";

/**
 * Lightweight read-only renderer used by the run inspector.
 *
 * Intentionally separate from the builder's `createWorkflowCanvas`: the
 * builder owns drag, port-click, edge-rule popovers, dirty tracking and a
 * 950-line bridge to mutate state. The inspector needs none of that — it
 * renders a static graph whose node tiles re-paint when status changes.
 */

const SVG_NS = "http://www.w3.org/2000/svg";

export function createInspectorCanvas({ host }) {
  if (!host) throw new Error("createInspectorCanvas: host element required");
  host.classList.add("inspector-canvas");
  host.innerHTML = `
    <svg class="inspector-canvas-edges" aria-hidden="true">
      <defs>
        <marker id="inspector-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 Z" />
        </marker>
      </defs>
      <g class="inspector-canvas-edge-layer"></g>
    </svg>
    <div class="inspector-canvas-nodes"></div>
  `;

  const svg = host.querySelector("svg");
  const edgeLayer = host.querySelector(".inspector-canvas-edge-layer");
  const nodesHost = host.querySelector(".inspector-canvas-nodes");

  let onNodeClick = null;
  let selectedNodeId = null;
  let currentWorkflow = null;
  let currentRunState = null;

  function setOnNodeClick(handler) {
    onNodeClick = handler;
  }

  function setSelectedNode(nodeId) {
    selectedNodeId = nodeId;
    nodesHost.querySelectorAll(".inspector-node").forEach((tile) => {
      tile.classList.toggle("is-selected", tile.dataset.nodeId === selectedNodeId);
    });
  }

  function render(workflow, runState) {
    currentWorkflow = workflow;
    currentRunState = runState;
    const nodes = autoLayout(workflow);
    drawNodes(nodes, runState);
    drawEdges(nodes, workflow.edges || [], runState);
    sizeCanvas(nodes);
  }

  function update(runState) {
    if (!currentWorkflow) return;
    currentRunState = runState;
    // Re-apply node statuses (cheap; tiles already in DOM)
    nodesHost.querySelectorAll(".inspector-node").forEach((tile) => {
      const status = runState.nodeStates[tile.dataset.nodeId] || "idle";
      tile.dataset.status = status;
    });
    // Re-paint edges (small N; just re-build)
    drawEdges(autoLayout(currentWorkflow), currentWorkflow.edges || [], runState);
  }

  function autoLayout(workflow) {
    const rawNodes = (workflow.nodes || []).map((node) => ({ ...node }));
    // If every node has explicit position (non-zero), respect it; else BFS layout.
    const hasExplicit = rawNodes.some(
      (node) => Number(node.position?.x) || Number(node.position?.y),
    );
    if (hasExplicit) {
      return rawNodes.map((node) => ({
        ...node,
        position: {
          x: Number(node.position?.x || 0) + CANVAS_PAD,
          y: Number(node.position?.y || 0) + CANVAS_PAD,
        },
      }));
    }
    return bfsLayout(rawNodes, workflow.edges || []);
  }

  function bfsLayout(nodes, edges) {
    const incoming = new Map(nodes.map((node) => [node.id, 0]));
    const outgoing = new Map(nodes.map((node) => [node.id, []]));
    for (const edge of edges) {
      if (!incoming.has(edge.to) || !outgoing.has(edge.from)) continue;
      if (String(edge.when || "").toLowerCase() === "error") continue;
      outgoing.get(edge.from).push(edge.to);
      incoming.set(edge.to, (incoming.get(edge.to) || 0) + 1);
    }
    const depth = new Map(nodes.map((node) => [node.id, 0]));
    const queue = nodes.filter((node) => (incoming.get(node.id) || 0) === 0).map((node) => node.id);
    const seen = new Set();
    while (queue.length) {
      const id = queue.shift();
      if (seen.has(id)) continue;
      seen.add(id);
      for (const target of outgoing.get(id) || []) {
        depth.set(target, Math.max(depth.get(target) || 0, (depth.get(id) || 0) + 1));
        incoming.set(target, Math.max(0, (incoming.get(target) || 0) - 1));
        if ((incoming.get(target) || 0) === 0) queue.push(target);
      }
    }
    const rowCounts = new Map();
    return nodes.map((node) => {
      const col = depth.get(node.id) || 0;
      const row = rowCounts.get(col) || 0;
      rowCounts.set(col, row + 1);
      return {
        ...node,
        position: {
          x: CANVAS_PAD + col * NODE_GRID_X,
          y: CANVAS_PAD + row * NODE_GRID_Y,
        },
      };
    });
  }

  function drawNodes(nodes, runState) {
    nodesHost.innerHTML = nodes
      .map((node) => {
        const status = runState.nodeStates[node.id] || "idle";
        const x = Number(node.position?.x || 0);
        const y = Number(node.position?.y || 0);
        const subtitle = node.role ? `${node.type} · ${node.role}` : node.type;
        return `
          <button
            type="button"
            class="inspector-node"
            data-node-id="${escapeHtml(node.id)}"
            data-status="${escapeHtml(status)}"
            style="left:${x}px;top:${y}px;width:${NODE_TILE_WIDTH}px;height:${NODE_TILE_HEIGHT}px"
          >
            <span class="inspector-node-title">${escapeHtml(node.title || node.id)}</span>
            <span class="inspector-node-subtitle">${escapeHtml(subtitle)}</span>
          </button>
        `;
      })
      .join("");
    nodesHost.querySelectorAll(".inspector-node").forEach((tile) => {
      tile.addEventListener("click", () => {
        const id = tile.dataset.nodeId;
        if (onNodeClick) onNodeClick(id);
      });
    });
    if (selectedNodeId) setSelectedNode(selectedNodeId);
  }

  function drawEdges(nodes, edges, runState) {
    edgeLayer.innerHTML = "";
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    for (const edge of edges) {
      const source = nodeById.get(edge.from);
      const target = nodeById.get(edge.to);
      if (!source || !target) continue;
      const isLoop = (target.position?.x || 0) <= (source.position?.x || 0);
      const path = canvasConnectionPath(
        canvasPortPoint(source, "output"),
        canvasPortPoint(target, "input"),
        isLoop,
      );
      const status = runState.edgeStates[edgeKey(edge.from, edge.to)];
      const traversed = status === "traversed";
      const isError = String(edge.when || "").toLowerCase() === "error";
      const el = document.createElementNS(SVG_NS, "path");
      el.setAttribute("d", path);
      el.setAttribute("class", [
        "inspector-edge",
        traversed ? "is-traversed" : "",
        isError ? "is-error-edge" : "",
      ].filter(Boolean).join(" "));
      el.setAttribute("marker-end", "url(#inspector-arrow)");
      edgeLayer.appendChild(el);
    }
  }

  function sizeCanvas(nodes) {
    let width = NODE_TILE_WIDTH + CANVAS_PAD * 2;
    let height = NODE_TILE_HEIGHT + CANVAS_PAD * 2;
    for (const node of nodes) {
      width = Math.max(width, (node.position?.x || 0) + NODE_TILE_WIDTH + CANVAS_PAD);
      height = Math.max(height, (node.position?.y || 0) + NODE_TILE_HEIGHT + CANVAS_PAD);
    }
    host.style.minWidth = "";
    host.style.minHeight = "";
    nodesHost.style.minWidth = `${width}px`;
    nodesHost.style.minHeight = `${height}px`;
    svg.setAttribute("width", String(width));
    svg.setAttribute("height", String(height));
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  }

  return { render, update, setOnNodeClick, setSelectedNode };
}
