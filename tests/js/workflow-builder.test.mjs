import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {
  addEventListener() {},
  setTimeout,
  clearTimeout,
};
globalThis.document = globalThis.document || {
  body: {
    append() {},
    appendChild() {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  },
  createElement() {
    return {
      className: "",
      setAttribute() {},
      append() {},
      appendChild() {},
      classList: { add() {}, remove() {}, toggle() {} },
      style: {},
    };
  },
  querySelector() {
    return null;
  },
  querySelectorAll() {
    return [];
  },
};
if (!globalThis.navigator) {
  globalThis.navigator = { platform: "node" };
}

const builder = await import("../../app/static/workflow-builder.js");

const {
  CANVAS_PAD,
  NODE_GRID_X,
  NODE_TILE_HEIGHT,
  NODE_TILE_WIDTH,
  PORT_INPUT,
  PORT_OUTPUT,
  WORKFLOW_INPUT_ID,
  WORKFLOW_OUTPUT_ID,
  addUniqueNodeListValue,
  autoBoundaryEdgeKey,
  boundaryKind,
  boundaryNodeTemplate,
  canonicalNodeType,
  canvasConnectionPath,
  canvasPortPoint,
  defaultDecisionBranches,
  deriveNodeTypeFromRole,
  deriveWorkflowEdgesFromNodes,
  ensureWorkflowBoundaryNodes,
  incomingEdgeForNode,
  isAutoBoundaryEdgeSuppressed,
  isBoundaryNode,
  mutateWorkflowEdges,
  newWorkflowDraftFrom,
  nodeOutputIdentifier,
  nodeTileMarkup,
  normalizeDecisionBranches,
  normalizeWorkflowDraft,
  normalizeWorkflowEdges,
  normalizeWorkflowNodes,
  realWorkflowNodes,
  removeAutoInputReference,
  removeNodeListValue,
  restoreAutoBoundaryEdge,
  suppressAutoBoundaryEdge,
  syncDerivedEdges,
  targetStillUsesInputIdentifier,
  updateDownstreamInputReferences,
  validateWorkflowHealth,
} = builder;

test("canonicalNodeType migrates legacy node types", () => {
  assert.equal(canonicalNodeType("final"), "answer");
  assert.equal(canonicalNodeType("judge"), "decision");
  assert.equal(canonicalNodeType("reviewer"), "report");
  assert.equal(canonicalNodeType(""), "role");
});

test("decision branch normalization keeps defaults and lets custom branches override by condition", () => {
  const branches = normalizeDecisionBranches({
    branches: [
      { label: "Custom done", when: "decision.status == 'done'", target: "answer" },
      { label: "Escalate", when: "decision.status == 'escalate'", target: "human" },
      { label: "", when: "ignored", target: "x" },
    ],
  });

  assert.equal(defaultDecisionBranches().length, 3);
  assert.equal(branches.find((branch) => branch.when === "decision.status == 'done'").label, "Custom done");
  assert.equal(branches.find((branch) => branch.when === "decision.status == 'escalate'").target, "human");
});

test("boundary helpers identify input and output nodes", () => {
  const input = boundaryNodeTemplate(PORT_INPUT);
  const output = boundaryNodeTemplate(PORT_OUTPUT);

  assert.equal(input.id, WORKFLOW_INPUT_ID);
  assert.equal(output.id, WORKFLOW_OUTPUT_ID);
  assert.equal(boundaryKind(input), PORT_INPUT);
  assert.equal(boundaryKind(output), PORT_OUTPUT);
  assert.equal(isBoundaryNode(input), true);
  assert.equal(realWorkflowNodes([input, { id: "work" }, output]).length, 1);
});

test("ensureWorkflowBoundaryNodes adds boundary nodes and shifts old real nodes away from the input", () => {
  const nodes = ensureWorkflowBoundaryNodes([
    { id: "work", type: "role", position: { x: CANVAS_PAD, y: 50 } },
  ]);

  assert.equal(nodes[0].id, WORKFLOW_INPUT_ID);
  assert.equal(nodes.at(-1).id, WORKFLOW_OUTPUT_ID);
  assert.equal(nodes[1].position.x, CANVAS_PAD + NODE_GRID_X);
  assert.equal(nodes[1]._boundaryShifted, true);
});

test("normalizeWorkflowNodes migrates legacy final references and clamps numeric settings", () => {
  const nodes = normalizeWorkflowNodes({
    nodes: [{
      id: "worker",
      role: "worker",
      input: "topic",
      reports_to: "final, missing",
      receive_from: ["final", " worker "],
      max_parallel: 20,
      max_items: 99,
      position: { x: "10", y: "bad" },
    }, {
      id: "final",
      type: "final",
    }],
  });
  const worker = nodes.find((node) => node.id === "worker");
  const answer = nodes.find((node) => node.id === "answer");

  assert.ok(answer);
  assert.deepEqual(worker.input, ["topic"]);
  assert.deepEqual(worker.reports_to, ["answer", "missing"]);
  assert.deepEqual(worker.receive_from, ["answer", "worker"]);
  assert.equal(worker.max_parallel, 8);
  assert.equal(worker.max_items, 12);
  assert.deepEqual(worker.position, { x: 10 + NODE_GRID_X, y: 0 });
});

test("normalizeWorkflowEdges drops invalid edges, dedupes, and migrates final to answer", () => {
  const nodes = normalizeWorkflowNodes({ nodes: [{ id: "plan" }, { id: "final", type: "final" }] });
  assert.deepEqual(normalizeWorkflowEdges({
    edges: [
      { from: "plan", to: "final" },
      { from: "plan", to: "answer" },
      { from: "missing", to: "answer" },
      { from: "plan", to: "answer", when: "retry" },
    ],
  }, nodes), [
    { from: "plan", to: "answer", when: "" },
    { from: "plan", to: "answer", when: "retry" },
  ]);
});

test("normalizeWorkflowDraft normalizes modes, execution, iterations, nodes, and derived edges", () => {
  const draft = normalizeWorkflowDraft({
    id: "wf",
    modes: ["code", "code", "unknown"],
    execution: "direct",
    max_iterations: 100,
    nodes: [
      { id: "a", reports_to: ["b"] },
      { id: "b", type: "answer" },
    ],
  });

  assert.equal(draft.mode, "code");
  assert.deepEqual(draft.modes, ["code"]);
  assert.equal(draft.execution, "direct");
  assert.equal(draft.max_iterations, 8);
  assert.deepEqual(draft.edges, [{ from: "a", to: "b", when: "" }]);
});

test("newWorkflowDraftFrom creates a starter orchestrator when no real nodes exist", () => {
  const draft = newWorkflowDraftFrom({ id: "new" });
  assert.ok(draft.nodes.find((node) => node.id === "orchestrator"));
  assert.ok(draft.nodes.find((node) => node.id === WORKFLOW_INPUT_ID));
  assert.ok(draft.nodes.find((node) => node.id === WORKFLOW_OUTPUT_ID));
});

test("deriveNodeTypeFromRole maps special roles and worker pools", () => {
  assert.equal(deriveNodeTypeFromRole("judge"), "decision");
  assert.equal(deriveNodeTypeFromRole("reviewer"), "report");
  assert.equal(deriveNodeTypeFromRole("worker"), "worker_pool");
  assert.equal(deriveNodeTypeFromRole("assistant", 3), "worker_pool");
  assert.equal(deriveNodeTypeFromRole("assistant", 1), "role");
});

test("deriveWorkflowEdgesFromNodes dedupes explicit edges and can add boundary edges", () => {
  const nodes = normalizeWorkflowNodes({ nodes: [{ id: "plan" }, { id: "answer", type: "answer" }] });
  const edges = deriveWorkflowEdgesFromNodes(nodes, [
    { from: "plan", to: "answer" },
    { from_node: "plan", to: "answer" },
    { from: "missing", to: "answer" },
  ], true);

  assert.deepEqual(edges, [
    { from: WORKFLOW_INPUT_ID, to: "plan", when: "" },
    { from: "plan", to: "answer", when: "" },
    { from: "answer", to: WORKFLOW_OUTPUT_ID, when: "" },
  ]);
});

test("auto boundary edge suppression removes and restores generated edges", () => {
  const node = { id: "plan", config: {} };

  assert.equal(autoBoundaryEdgeKey(WORKFLOW_INPUT_ID, "plan"), "input->plan");
  assert.equal(suppressAutoBoundaryEdge(node, WORKFLOW_INPUT_ID, "plan"), true);
  assert.equal(suppressAutoBoundaryEdge(node, WORKFLOW_INPUT_ID, "plan"), false);
  assert.equal(isAutoBoundaryEdgeSuppressed(node, WORKFLOW_INPUT_ID, "plan"), true);
  assert.equal(restoreAutoBoundaryEdge(node, WORKFLOW_INPUT_ID, "plan"), true);
  assert.equal(isAutoBoundaryEdgeSuppressed(node, WORKFLOW_INPUT_ID, "plan"), false);
});

test("mutateWorkflowEdges supports add, update, remove, rename, and normalization", () => {
  const draft = {
    nodes: [{ id: "a" }, { id: "b" }, { id: "c" }],
    edges: [],
  };

  assert.deepEqual(mutateWorkflowEdges(draft, { type: "add", from: "a", to: "b" }), [{ from: "a", to: "b", when: "" }]);
  assert.deepEqual(mutateWorkflowEdges(draft, { type: "add", from: "a", to: "b" }), [{ from: "a", to: "b", when: "" }]);
  assert.deepEqual(mutateWorkflowEdges(draft, { type: "update", from: "a", to: "b", when: "retry" }), [{ from: "a", to: "b", when: "retry" }]);
  assert.deepEqual(mutateWorkflowEdges(draft, { type: "renameNode", fromId: "b", toId: "c" }), [{ from: "a", to: "c", when: "retry" }]);
  assert.deepEqual(mutateWorkflowEdges(draft, { type: "remove", to: "c" }), []);
});

test("syncDerivedEdges migrates receive_from and reports_to when explicit edges are absent", () => {
  const nodes = [
    { id: "a", reports_to: ["b"] },
    { id: "b", receive_from: ["a"] },
  ];

  assert.deepEqual(syncDerivedEdges({ nodes }, nodes), [{ from: "a", to: "b", when: "" }]);
});

test("node connection helpers manage input references when links change", () => {
  const draft = {
    nodes: [
      { id: "source", output: "result" },
      { id: "target", input: ["result", "other"] },
      { id: "next", input: ["result"] },
    ],
    edges: [{ from: "source", to: "target" }, { from: "source", to: "next" }],
  };

  assert.equal(nodeOutputIdentifier(draft.nodes[0]), "result");
  assert.equal(targetStillUsesInputIdentifier(draft, "target", "result"), true);
  assert.equal(removeAutoInputReference(draft, draft.nodes[1], "result"), false);
  draft.edges = [];
  assert.equal(removeAutoInputReference(draft, draft.nodes[1], "result"), true);
  assert.deepEqual(draft.nodes[1].input, ["other"]);

  draft.edges = [{ from: "source", to: "next" }];
  updateDownstreamInputReferences(draft, "source", "result", "final_result");
  assert.deepEqual(draft.nodes[2].input, ["final_result"]);
});

test("list helpers add and remove unique node values", () => {
  const node = { reports_to: "a, b" };
  assert.equal(addUniqueNodeListValue(node, "reports_to", "c"), true);
  assert.deepEqual(node.reports_to, ["a", "b", "c"]);
  assert.equal(addUniqueNodeListValue(node, "reports_to", "c"), false);
  assert.equal(removeNodeListValue(node, "reports_to", "b"), true);
  assert.deepEqual(node.reports_to, ["a", "c"]);
});

test("incomingEdgeForNode returns the last matching incoming edge", () => {
  const draft = {
    nodes: [{ id: "a" }, { id: "b" }, { id: "c" }],
    edges: [{ from: "a", to: "c" }, { from: "b", to: "c", when: "retry" }],
  };

  assert.deepEqual(incomingEdgeForNode(draft, "c"), { from: "b", to: "c", when: "retry" });
  assert.equal(incomingEdgeForNode(draft, "missing"), null);
});

test("validateWorkflowHealth flags disconnected nodes, missing answer, recursion, and ungated cycles", () => {
  const issues = validateWorkflowHealth({
    id: "wf",
    nodes: [
      { id: "a", type: "role", title: "A" },
      { id: "b", type: "role", title: "B" },
      { id: "sub", type: "workflow", title: "Sub", ref: "wf" },
    ],
    edges: [{ from: "a", to: "b" }, { from: "b", to: "a" }],
  }, []);

  assert.ok(issues.some((issue) => issue.title === "Sub is not connected"));
  assert.ok(issues.some((issue) => issue.title === "Sub starts this same workflow again"));
  assert.ok(issues.some((issue) => issue.title === "Sub has no valid sub-workflow"));
  assert.ok(issues.some((issue) => issue.title === "No final answer step"));
  assert.ok(issues.some((issue) => issue.title.includes("Possible endless loop")));
});

test("validateWorkflowHealth treats retry-gated cycles as acceptable", () => {
  const issues = validateWorkflowHealth({
    nodes: [
      { id: "judge", type: "decision", config: { branches: [{ label: "Retry", when: "decision.status == 'retry'", target: "work" }] } },
      { id: "work", type: "role" },
      { id: "answer", type: "answer" },
    ],
    edges: [
      { from: "judge", to: "work", when: "decision.status == 'retry'" },
      { from: "work", to: "judge" },
      { from: "judge", to: "answer", when: "decision.status == 'done'" },
    ],
  });

  assert.equal(issues.some((issue) => issue.title.includes("Possible endless loop")), false);
});

test("canvas helpers return stable port points and SVG paths", () => {
  const node = { position: { x: 10, y: 20 } };
  assert.deepEqual(canvasPortPoint(node, PORT_INPUT), { x: 10, y: 20 + NODE_TILE_HEIGHT / 2 });
  assert.deepEqual(canvasPortPoint(node, PORT_OUTPUT), { x: 10 + NODE_TILE_WIDTH, y: 20 + NODE_TILE_HEIGHT / 2 });
  assert.match(canvasConnectionPath({ x: 0, y: 0 }, { x: 100, y: 20 }), /^M 0 0 C /);
  assert.match(canvasConnectionPath({ x: 100, y: 0 }, { x: 0, y: 20 }), / L -10 /);
  assert.match(canvasConnectionPath({ x: 100, y: 0 }, { x: 0, y: 20 }, true, 10), /^M 100 0 L /);
});

test("nodeTileMarkup escapes titles and labels while rendering expected controls", () => {
  const html = nodeTileMarkup({
    id: "node<1>",
    type: "worker_pool",
    title: "<Work>",
    role: "worker",
    output: "result<script>",
    worker_instances: 3,
    receive_from: ["input"],
    reports_to: ["answer"],
  });

  assert.match(html, /&lt;Work&gt;/);
  assert.match(html, /worker · ≤3/);
  assert.match(html, /Output result&lt;script&gt; from &lt;Work&gt;/);
  assert.match(html, /node&lt;1&gt;/);
  assert.doesNotMatch(html, /<Work>/);
});
