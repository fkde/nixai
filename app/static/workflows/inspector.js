import { clampInt, clampLength, escapeHtml, slugifyWorkflowId } from "../helpers.js";
import { state } from "../state.js";
import { dedupeList, parseCsvList } from "../workflow-editor.js";
import {
  CANVAS_PAD,
  NODE_GRID_X,
  canonicalNodeType,
  defaultDecisionBranches,
  derivedNodeConnections,
  deriveWorkflowEdgesFromNodes,
  ensureWorkflowBoundaryNodes,
  isBoundaryNode,
  mutateWorkflowEdges,
  newWorkflowDraftFrom,
  nodeOutputIdentifier,
  normalizeDecisionBranches,
  normalizeWorkflowDraft,
  normalizeWorkflowNodes,
  realWorkflowNodes,
  updateDownstreamInputReferences,
} from "../workflow-builder.js";

const WORKFLOW_NAME_MAX = 200;
const WORKFLOW_DESCRIPTION_MAX = 1000;
const WORKFLOW_FIELD_MAX = 120;

const NODE_PROPERTY_TYPES = {
  identity: { kind: "identity" },
  type: { kind: "select" },
  role: { kind: "select" },
  json: { kind: "boolean" },
  input: { kind: "csv" },
  output: { kind: "state_key" },
  prompt: { kind: "textarea" },
  retry: { kind: "retry" },
  workers: { kind: "number" },
  max_items: { kind: "number" },
  branches: { kind: "branch_list" },
  body: { kind: "node_list" },
  break_when: { kind: "expression" },
  sub_workflow: { kind: "workflow_ref" },
};

function nodeProperties(keys, overrides = {}) {
  return Object.fromEntries(keys.map((key) => [key, { key, ...(NODE_PROPERTY_TYPES[key] || { kind: "text" }), ...(overrides[key] || {}) }]));
}

const NODE_TYPE_DEFINITIONS = [
  {
    type: "role",
    label: "Agent",
    description: "Single role-prompt node for planning, synthesis, or custom work.",
    properties: nodeProperties(["identity", "type", "role", "json", "input", "output", "prompt", "retry"], {
      role: { label: "Role", tip: "Markdown role prompt that defines this agent's behavior." },
      prompt: {
        label: "Node Instruction",
        placeholder: "Describe what this agent should do in this workflow step.",
        tip: "Applies only to this node in this workflow. The selected role prompt still defines the agent's general behavior.",
      },
      input: { label: "Input Fields", placeholder: "input, plan" },
      output: { label: "Output Field", placeholder: "agent_result" },
    }),
    defaults: { id: "agent", title: "Agent", role: "orchestrator", output: "agent_result" },
  },
  {
    type: "worker_pool",
    label: "Worker Pool",
    description: "Parallel workers over a list input; worker count is capped by the UI.",
    properties: nodeProperties(["identity", "type", "role", "json", "input", "output", "workers", "max_items", "prompt", "retry"], {
      role: { label: "Worker Role", tip: "Markdown role prompt used for every worker instance." },
      prompt: {
        label: "Worker Instruction",
        placeholder: "Describe how every worker should handle its assigned work item.",
        tip: "Applies only to this worker pool in this workflow. The selected role prompt still defines each worker's general behavior.",
      },
      input: { label: "Work Items Input", placeholder: "plan.work_items" },
      output: { label: "Reports Field", placeholder: "worker_reports" },
      workers: { label: "Max Worker Instances" },
      max_items: { label: "Max Work Items" },
    }),
    defaults: { id: "workers", title: "Workers", role: "worker", input: ["plan.work_items"], output: "worker_reports", max_items: 4, worker_instances: 2, max_parallel: 2 },
  },
  {
    type: "vision",
    label: "Vision",
    description: "Analyzes image inputs with a vision-capable model.",
    properties: nodeProperties(["identity", "type", "role", "json", "input", "output", "prompt", "retry"], {
      role: { label: "Vision Role", tip: "Markdown role prompt and model mapping used for image analysis." },
      prompt: {
        label: "Vision Instruction",
        placeholder: "Extract the text from this document and preserve paragraphs.",
        tip: "Applies only to this vision node. The selected vision role still defines the model's general behavior.",
      },
      input: { label: "Image Input", placeholder: "attachments" },
      output: { label: "Vision Result Field", placeholder: "vision_result" },
    }),
    defaults: {
      id: "vision",
      title: "Vision",
      role: "vision",
      input: ["attachments"],
      output: "vision_result",
      prompt: "Extract the text from this document and preserve paragraphs.",
    },
  },
  {
    type: "report",
    label: "Report",
    description: "Consolidates predecessor outputs into a structured non-terminal report.",
    properties: nodeProperties(["identity", "type", "role", "json", "input", "output", "prompt", "retry"], {
      role: { label: "Report Role", tip: "Markdown role prompt that consolidates or reviews previous outputs." },
      prompt: {
        label: "Report Instruction",
        placeholder: "Define the report or review criteria for this node only.",
        tip: "Applies only to this report node in this workflow. The selected role prompt still defines the agent's general behavior.",
      },
      input: { label: "Inputs To Review", placeholder: "plan, worker_reports" },
      output: { label: "Report Field", placeholder: "review" },
    }),
    defaults: { id: "report", title: "Report", role: "reviewer", input: ["plan", "worker_reports"], output: "review", expects_json: true },
  },
  {
    type: "decision",
    label: "Decision",
    description: "Returns decision.status and routes the workflow through structured branches.",
    properties: nodeProperties(["identity", "type", "role", "json", "input", "output", "branches", "prompt", "retry"], {
      role: { label: "Decision Role", tip: "Markdown role prompt that judges state and returns branchable JSON." },
      prompt: {
        label: "Decision Instruction",
        placeholder: "Define when this node should choose done, retry, or needs_user.",
        tip: "Applies only to this decision node in this workflow. The selected role prompt still defines the agent's general behavior.",
      },
      input: { label: "Decision Inputs", placeholder: "plan, worker_reports, review" },
      output: { label: "Decision Field", placeholder: "decision" },
      branches: { label: "Branches" },
    }),
    defaults: { id: "decision", title: "Decision", role: "judge", input: ["plan", "worker_reports", "review"], output: "decision", expects_json: true, config: { branches: defaultDecisionBranches() } },
  },
  {
    type: "pause",
    label: "Ask User",
    description: "Pauses the run and waits for user feedback before continuing.",
    properties: nodeProperties(["identity", "type", "input", "output", "prompt"], {
      prompt: {
        label: "Question",
        placeholder: "Ask the user for the missing requirement.",
        tip: "Shown to the user when this pause node runs. It is not a role prompt.",
      },
      input: { label: "Question Context", placeholder: "decision, review" },
      output: { label: "Feedback Field", placeholder: "pause" },
    }),
    defaults: { id: "ask_user", title: "Ask User", role: "", input: ["decision"], output: "pause", prompt: "" },
  },
  {
    type: "answer",
    label: "Answer",
    description: "Synthesizes the final user-facing response.",
    properties: nodeProperties(["identity", "type", "role", "input", "output", "prompt"], {
      role: { label: "Answer Role", tip: "Markdown role prompt used to write the final user-facing response." },
      prompt: {
        label: "Answer Instruction",
        placeholder: "Describe how the final user-facing answer should be synthesized.",
        tip: "Applies only to this answer node in this workflow. The selected role prompt still defines the agent's general behavior.",
      },
      input: { label: "Answer Inputs", placeholder: "plan, worker_reports, review" },
      output: { label: "Final Answer Field", placeholder: "final_answer" },
    }),
    defaults: { id: "answer", title: "Answer", role: "orchestrator", input: ["plan", "worker_reports", "review", "decision"], output: "final_answer" },
  },
  {
    type: "tool_agent",
    label: "Tool Agent",
    description: "Runs the Agentic runner with approved web/code/MCP-style tools.",
    properties: nodeProperties(["identity", "type", "input", "output", "prompt", "retry"], {
      prompt: {
        label: "Tool Instruction",
        placeholder: "Describe the concrete tool task for this node.",
        tip: "Applies only to this tool-agent node in this workflow. Input fields are added as tool context.",
      },
      input: { label: "Tool Context", placeholder: "input, plan" },
      output: { label: "Tool Result Field", placeholder: "research_result" },
    }),
    defaults: { id: "research", title: "Research", role: "orchestrator", input: [], output: "research_result", prompt: "Research the task and return grounded findings." },
  },
  {
    type: "for_each",
    label: "For Each",
    description: "Iterates over an input list using body nodes configured in JSON.",
    properties: nodeProperties(["identity", "type", "input", "output", "prompt", "body", "max_items"], {
      input: { label: "List Input", placeholder: "plan.work_items" },
      output: { label: "Results Field", placeholder: "iteration_results" },
      prompt: {
        label: "Iteration Instruction",
        placeholder: "Describe how each item should be processed by the loop body.",
        tip: "Applies only while this loop node runs. Body nodes still keep their own role prompts and node instructions.",
      },
      body: { label: "Body Nodes" },
      max_items: { label: "Max Iterations" },
    }),
    defaults: { id: "for_each", title: "For Each", role: "", input: ["plan.work_items"], output: "iteration_results", config: { body: [] } },
  },
  {
    type: "while",
    label: "While",
    description: "Repeats body nodes until a safe break condition becomes true.",
    properties: nodeProperties(["identity", "type", "input", "output", "prompt", "body", "break_when"], {
      break_when: { label: "Break Condition", placeholder: "decision.status == 'done'" },
      input: { label: "Loop Inputs", placeholder: "decision, review" },
      output: { label: "Loop Result Field", placeholder: "while_result" },
      prompt: {
        label: "Loop Instruction",
        placeholder: "Describe the loop goal and what each pass should improve.",
        tip: "Applies only while this loop node runs. Body nodes still keep their own role prompts and node instructions.",
      },
      body: { label: "Body Nodes" },
    }),
    defaults: { id: "while_loop", title: "While", role: "", input: [], output: "while_result", break_when: "decision.status == 'done'", config: { body: [] } },
  },
  {
    type: "workflow",
    label: "Sub Workflow",
    description: "Runs another saved workflow by id as a reusable block.",
    properties: nodeProperties(["identity", "type", "input", "output", "prompt", "sub_workflow", "retry"], {
      sub_workflow: { label: "Sub Workflow" },
      input: { label: "Workflow Inputs", placeholder: "input, plan" },
      output: { label: "Workflow Result Field", placeholder: "workflow_result" },
      prompt: {
        label: "Subworkflow Instruction",
        placeholder: "Add context the child workflow should consider for this invocation.",
        tip: "Applies only to this subworkflow call. The child workflow's own nodes keep their role prompts and node instructions.",
      },
    }),
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
  workflowCanvas,
  workflowCanvasNodes,
  workflowNodeEditPanel,
  workflowNodeEditTitle,
  nodeEditId,
  nodeEditTitleInput,
  nodeEditType,
  nodeEditSubWorkflowRef,
  nodeEditBreakWhen,
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
    const clean = canonicalNodeType(type);
    return NODE_TYPE_DEFINITIONS.find((item) => item.type === clean) || NODE_TYPE_DEFINITIONS[0];
  }

  function nodeTypeProperties(type) {
    const definition = nodeTypeDefinition(type);
    if (definition.properties && typeof definition.properties === "object") return definition.properties;
    return nodeProperties(definition.fields || []);
  }

  function nodeTypePropertyKeys(type) {
    return new Set(Object.keys(nodeTypeProperties(type)));
  }

  function nodeTypeProperty(type, property) {
    return nodeTypeProperties(type)[property] || {};
  }

  function applyFieldCopy(control, copy) {
    const label = control?.closest("label");
    if (!label || !copy) return;
    const fieldLabel = label.querySelector(".field-label");
    if (fieldLabel && copy.label) {
      fieldLabel.childNodes[0].textContent = `${copy.label} `;
    }
    const tip = fieldLabel?.querySelector(".info-tip");
    if (tip && copy.tip) {
      tip.dataset.tip = copy.tip;
      tip.setAttribute("aria-label", copy.tip);
    }
    if (copy.placeholder !== undefined && "placeholder" in control) {
      control.placeholder = copy.placeholder || "";
    }
  }

  function normalizeNodeForType(node) {
    const fields = nodeTypePropertyKeys(node.type);
    if (!fields.has("role")) node.role = "";
    if (!fields.has("json")) node.expects_json = false;
    if (!fields.has("retry")) node.retry = { max: 0, backoff: 0 };
    if (!fields.has("workers")) {
      node.worker_instances = 1;
      node.max_parallel = 1;
    }
    if (!fields.has("max_items") && node.type !== "worker_pool") node.max_items = 4;
    if (!fields.has("body") && node.config) delete node.config.body;
    if (!fields.has("branches") && node.config) delete node.config.branches;
    if (!fields.has("break_when")) node.break_when = "";
    if (!fields.has("sub_workflow")) node.ref = "";
  }

  function nodeTypeOptionsHtml(selectedType) {
    const selected = canonicalNodeType(selectedType);
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
    const node = {
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
      config: typeof defaults.config === "object" && defaults.config ? JSON.parse(JSON.stringify(defaults.config)) : {},
      retry: { max: 0, backoff: 0 },
      break_when: defaults.break_when || "",
      ref: defaults.ref || "",
    };
    normalizeNodeForType(node);
    return node;
  }

  function ensureInspectorDynamicControls() {
    if (nodeEditId && !nodeEditId.parentElement.querySelector(".node-edit-id-error")) {
      const hint = document.createElement("small");
      hint.className = "field-hint node-edit-id-error";
      hint.hidden = true;
      nodeEditId.after(hint);
    }
    if (nodeEditBody && !nodeEditBody.parentElement.querySelector(".node-edit-body-chips")) {
      const chips = document.createElement("div");
      chips.className = "node-edit-body-chips";
      chips.addEventListener("change", applyNodeEditChanges);
      nodeEditBody.after(chips);
    }
    if (nodeEditBody && !nodeEditBody.parentElement.querySelector(".node-edit-branch-list")) {
      const branches = document.createElement("div");
      branches.className = "node-edit-branch-list";
      branches.hidden = true;
      branches.addEventListener("input", () => {
        applyNodeEditChanges();
        canvas.bridge?.afterWorkflowMutation?.();
      });
      branches.addEventListener("click", (event) => {
        const button = event.target.closest?.(".node-edit-add-retry-branch");
        if (!button) return;
        const draft = activeWorkflowDraft();
        const node = draft?.nodes.find((candidate) => candidate.id === state.workflowEditorSelectedNodeId);
        if (!node) return;
        canvas.bridge?.beforeWorkflowMutation?.();
        node.config = { ...(node.config || {}), branches: normalizeDecisionBranches(node.config || {}) };
        renderDecisionBranches(node);
        applyNodeEditChanges();
        canvas.bridge?.afterWorkflowMutation?.();
      });
      nodeEditBody.after(branches);
    }
    if (nodeEditReceive && !nodeEditReceive.parentElement.querySelector(".node-edit-connection-chips.incoming")) {
      const chips = document.createElement("div");
      chips.className = "node-edit-connection-chips incoming";
      nodeEditReceive.after(chips);
    }
    if (nodeEditReports && !nodeEditReports.parentElement.querySelector(".node-edit-connection-chips.outgoing")) {
      const chips = document.createElement("div");
      chips.className = "node-edit-connection-chips outgoing";
      nodeEditReports.after(chips);
    }
  }

  function setInspectorFieldVisibility(node) {
    const fields = nodeTypePropertyKeys(node.type);
    const controls = [
      [nodeEditRole?.closest(".node-edit-role-row"), fields.has("role") || fields.has("json")],
      [nodeEditRole?.closest("label"), fields.has("role")],
      [nodeEditJson?.closest("label"), fields.has("json")],
      [nodeEditSubWorkflowRef?.closest("label"), fields.has("sub_workflow") || fields.has("break_when")],
      [nodeEditPrompt?.closest("label"), fields.has("prompt")],
      [nodeEditBody?.closest("label"), fields.has("body") || fields.has("branches")],
      [nodeEditRetryMax?.closest("label"), fields.has("retry")],
      [nodeEditRetryBackoff?.closest("label"), fields.has("retry")],
      [nodeEditWorkers?.closest("label"), fields.has("workers")],
      [nodeEditMaxItems?.closest("label"), fields.has("max_items")],
      [nodeEditInput?.closest("label"), fields.has("input")],
      [nodeEditOutput?.closest("label"), fields.has("output")],
      [nodeEditReceive?.closest(".settings-grid"), true],
    ];
    controls.forEach(([element, visible]) => {
      if (element) element.hidden = !visible;
    });
    applyFieldCopy(nodeEditRole, nodeTypeProperty(node.type, "role"));
    applyFieldCopy(nodeEditPrompt, nodeTypeProperty(node.type, "prompt"));
    applyFieldCopy(nodeEditBody, nodeTypeProperty(node.type, fields.has("branches") ? "branches" : "body"));
    applyFieldCopy(nodeEditInput, nodeTypeProperty(node.type, "input"));
    applyFieldCopy(nodeEditOutput, nodeTypeProperty(node.type, "output"));
    applyFieldCopy(nodeEditWorkers, nodeTypeProperty(node.type, "workers"));
    applyFieldCopy(nodeEditMaxItems, nodeTypeProperty(node.type, "max_items"));
    applyFieldCopy(nodeEditSubWorkflowRef, nodeTypeProperty(node.type, fields.has("break_when") ? "break_when" : "sub_workflow"));
    if (nodeEditBreakWhen) applyFieldCopy(nodeEditBreakWhen, nodeTypeProperty(node.type, "break_when"));
    if (nodeEditSubWorkflowRef) nodeEditSubWorkflowRef.hidden = !fields.has("sub_workflow");
    if (nodeEditBreakWhen) nodeEditBreakWhen.hidden = !fields.has("break_when");
  }

  function subWorkflowOptionsHtml(selected, currentWorkflowId) {
    const selectedValue = String(selected || "").trim();
    const workflows = (state.workflowPresets || []).filter((workflow) => workflow.id !== currentWorkflowId);
    const hasSelected = workflows.some((workflow) => workflow.id === selectedValue);
    const missing = selectedValue && !hasSelected
      ? `<option value="${escapeHtml(selectedValue)}" selected>${escapeHtml(selectedValue)} (missing)</option>`
      : "";
    const placeholder = selectedValue ? "" : '<option value="" selected>Select workflow…</option>';
    return `${placeholder}${missing}${workflows
      .map((workflow) => `<option value="${escapeHtml(workflow.id)}"${workflow.id === selectedValue ? " selected" : ""}>${escapeHtml(workflow.name || workflow.id)}</option>`)
      .join("")}`;
  }

  function renderBodyNodeChips(node) {
    const chips = nodeEditBody?.parentElement?.querySelector(".node-edit-body-chips");
    const branchList = nodeEditBody?.parentElement?.querySelector(".node-edit-branch-list");
    if (!chips) return;
    const isLoop = node.type === "for_each" || node.type === "while";
    chips.hidden = !isLoop;
    if (nodeEditBody) nodeEditBody.hidden = true;
    if (!isLoop) {
      chips.innerHTML = "";
    } else {
      const body = Array.isArray(node.config?.body) ? node.config.body : [];
      const candidates = realWorkflowNodes(activeWorkflowDraft()?.nodes || [])
        .filter((candidate) => candidate.id !== node.id);
      chips.innerHTML = candidates.map((candidate) => {
        const checked = body.includes(candidate.id) ? " checked" : "";
        return `<label><input type="checkbox" value="${escapeHtml(candidate.id)}"${checked}> <span>${escapeHtml(candidate.title || candidate.id)}</span></label>`;
      }).join("");
    }
    if (branchList) branchList.hidden = node.type !== "decision";
  }

  function renderDecisionBranches(node) {
    const list = nodeEditBody?.parentElement?.querySelector(".node-edit-branch-list");
    if (!list) return;
    if (node.type !== "decision") {
      list.hidden = true;
      list.innerHTML = "";
      return;
    }
    const branches = normalizeDecisionBranches(node.config || {});
    list.hidden = false;
    list.innerHTML = `
      ${branches.map((branch, index) => `
        <div class="node-edit-branch" data-branch-index="${index}">
          <input type="text" data-branch-field="label" value="${escapeHtml(branch.label)}" aria-label="Branch label" />
          <input type="text" data-branch-field="when" value="${escapeHtml(branch.when)}" aria-label="Branch condition" />
          <small class="field-hint node-edit-branch-error" hidden></small>
        </div>
      `).join("")}
      <button type="button" class="secondary-button node-edit-add-retry-branch">+ Retry branch</button>
    `;
  }

  function renderConnectionChips(node) {
    const connections = derivedNodeConnections(activeWorkflowDraft(), node.id);
    nodeEditReceive.value = connections.incoming.join(", ");
    nodeEditReports.value = connections.outgoing.join(", ");
    nodeEditReceive.readOnly = true;
    nodeEditReports.readOnly = true;
    const incoming = nodeEditReceive.parentElement.querySelector(".node-edit-connection-chips.incoming");
    const outgoing = nodeEditReports.parentElement.querySelector(".node-edit-connection-chips.outgoing");
    incoming.innerHTML = connections.incoming.length
      ? connections.incoming.map((id) => `<span>${escapeHtml(id)}</span>`).join("")
      : "<small>No incoming edges.</small>";
    outgoing.innerHTML = connections.outgoing.length
      ? connections.outgoing.map((id) => `<span>${escapeHtml(id)}</span>`).join("")
      : "<small>No outgoing edges.</small>";
  }

  function addWorkflowNode(type = "role") {
    const draft = activeWorkflowDraft();
    if (!draft) return null;
    canvas.bridge?.beforeWorkflowMutation?.();
    const node = createNodeForType(draft, type);
    draft.nodes.push(node);
    state.workflowEditorDraft = {
      ...draft,
      nodes: ensureWorkflowBoundaryNodes(draft.nodes),
    };
    canvas.renderWorkflowCanvas();
    selectWorkflowNode(node.id);
    canvas.bridge?.afterWorkflowMutation?.();
    return node;
  }

  function closeNodeTypeMenu() {
    document.querySelector(".workflow-node-type-menu")?.remove();
    document.removeEventListener("pointerdown", handleNodeTypeMenuOutside);
    window.removeEventListener("resize", repositionNodeTypeMenu);
    window.removeEventListener("scroll", repositionNodeTypeMenu, true);
    workflowCanvas?.removeEventListener("scroll", repositionNodeTypeMenu);
  }

  function handleNodeTypeMenuOutside(event) {
    const menu = document.querySelector(".workflow-node-type-menu");
    if (!menu) return;
    if (menu.contains(event.target)) return;
    closeNodeTypeMenu();
  }

  function repositionNodeTypeMenu() {
    const menu = document.querySelector(".workflow-node-type-menu");
    const anchor = menu?._workflowAnchor;
    if (!menu || !anchor) return;
    const rect = anchor.getBoundingClientRect();
    const menuRect = menu.getBoundingClientRect();
    menu.style.left = `${Math.max(12, Math.min(window.innerWidth - menuRect.width - 12, rect.right - menuRect.width))}px`;
    menu.style.top = `${Math.max(12, Math.min(rect.bottom + 8, window.innerHeight - menuRect.height - 12))}px`;
  }

  function openNodeTypeMenu(anchor) {
    const draft = activeWorkflowDraft();
    if (!draft || !anchor) return;
    closeNodeTypeMenu();
    const rect = anchor.getBoundingClientRect();
    const menu = document.createElement("div");
    menu.className = "workflow-node-type-menu";
    menu._workflowAnchor = anchor;
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
    repositionNodeTypeMenu();
    requestAnimationFrame(() => document.addEventListener("pointerdown", handleNodeTypeMenuOutside));
    window.addEventListener("resize", repositionNodeTypeMenu);
    window.addEventListener("scroll", repositionNodeTypeMenu, true);
    workflowCanvas?.addEventListener("scroll", repositionNodeTypeMenu, { passive: true });
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
    ensureInspectorDynamicControls();
    workflowNodeEditPanel.hidden = false;
    workflowNodeEditPanel.setAttribute("aria-hidden", "false");
    if (workflowNodeEditTitle) workflowNodeEditTitle.textContent = node.title || node.id;
    const retry = typeof node.retry === "object" && node.retry ? node.retry : {};
    nodeEditId.value = node.id;
    nodeEditTitleInput.value = node.title || "";
    node.type = canonicalNodeType(node.type);
    normalizeNodeForType(node);
    if (node.type === "decision") node.config = { ...(node.config || {}), branches: normalizeDecisionBranches(node.config || {}) };
    nodeEditType.innerHTML = nodeTypeOptionsHtml(node.type);
    nodeEditType.value = nodeTypeDefinition(node.type).type;
    if (nodeEditSubWorkflowRef) {
      nodeEditSubWorkflowRef.innerHTML = subWorkflowOptionsHtml(node.ref || "", draft.id);
      nodeEditSubWorkflowRef.value = node.ref || "";
    }
    if (nodeEditBreakWhen) nodeEditBreakWhen.value = node.break_when || "";
    nodeEditPrompt.value = node.prompt || "";
    nodeEditBody.value = Array.isArray(node.config?.body) ? node.config.body.join(", ") : "";
    nodeEditRetryMax.value = String(Math.max(0, Number(retry.max || 0)));
    nodeEditRetryBackoff.value = String(Math.max(0, Number(retry.backoff || 0)));
    nodeEditRole.innerHTML = nodeRoleSelectOptionsHtml(node.role);
    renderConnectionChips(node);
    nodeEditInput.value = (node.input || []).join(", ");
    nodeEditOutput.value = node.output || "";
    const workerCount = Math.max(1, Number(node.worker_instances || node.max_parallel || 1));
    nodeEditWorkers.value = String(workerCount);
    nodeEditMaxItems.value = String(Math.max(1, Number(node.max_items || 4)));
    nodeEditJson.checked = Boolean(node.expects_json);
    setInspectorFieldVisibility(node);
    renderBodyNodeChips(node);
    renderDecisionBranches(node);
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
    const idError = nodeEditId.parentElement.querySelector(".node-edit-id-error");
    const hasConflict = otherIds.has(desiredId);
    if (idError) {
      idError.hidden = !hasConflict;
      idError.textContent = hasConflict ? `ID "${desiredId}" is already used.` : "";
    }
    const safeId = hasConflict ? node.id : desiredId;
    const oldId = node.id;
    const previousOutputIdentifier = nodeOutputIdentifier(node);
    const previousTitle = node.title || "";
    node.id = safeId;
    node.title = clampLength(nodeEditTitleInput.value.trim(), WORKFLOW_NAME_MAX);
    const previousType = String(node.type || "").toLowerCase();
    const selectedType = nodeTypeDefinition(nodeEditType?.value || previousType).type;
    const selectedFields = nodeTypePropertyKeys(selectedType);
    if (selectedType !== previousType) {
      const defaults = nodeTypeDefaults(selectedType);
      const previousDefaults = nodeTypeDefaults(previousType);
      node.type = selectedType;
      node.role = selectedFields.has("role") ? (defaults.role || node.role || "") : "";
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
      node.config = typeof defaults.config === "object" && defaults.config ? JSON.parse(JSON.stringify(defaults.config)) : {};
      node.break_when = defaults.break_when || "";
      node.ref = defaults.ref || "";
      normalizeNodeForType(node);
      nodeEditRole.innerHTML = nodeRoleSelectOptionsHtml(node.role);
      nodeEditInput.value = (node.input || []).join(", ");
      nodeEditOutput.value = node.output || "";
      nodeEditWorkers.value = String(Math.max(1, Number(node.worker_instances || node.max_parallel || 1)));
      nodeEditMaxItems.value = String(Math.max(1, Number(node.max_items || 4)));
      nodeEditJson.checked = Boolean(node.expects_json);
      nodeEditPrompt.value = node.prompt || "";
      if (nodeEditSubWorkflowRef) {
        nodeEditSubWorkflowRef.innerHTML = subWorkflowOptionsHtml(node.ref || "", draft.id);
        nodeEditSubWorkflowRef.value = node.ref || "";
      }
      if (nodeEditBreakWhen) nodeEditBreakWhen.value = node.break_when || "";
      nodeEditBody.value = Array.isArray(node.config?.body) ? node.config.body.join(", ") : "";
      setInspectorFieldVisibility(node);
    } else {
      node.type = selectedType;
    }
    const chosenRole = String(nodeEditRole.value || "").trim();
    const activeFields = nodeTypePropertyKeys(node.type);
    node.role = activeFields.has("role") ? clampLength(chosenRole || nodeTypeDefaults(node.type).role || "", WORKFLOW_FIELD_MAX) : "";
    const workers = clampInt(nodeEditWorkers.value, 1, 8);
    node.prompt = activeFields.has("prompt") ? clampLength(nodeEditPrompt?.value || "", WORKFLOW_DESCRIPTION_MAX) : "";
    const breakWhenValue = clampLength(nodeEditBreakWhen?.value || "", WORKFLOW_FIELD_MAX);
    const subWorkflowValue = clampLength(nodeEditSubWorkflowRef?.value || "", WORKFLOW_FIELD_MAX);
    node.break_when = activeFields.has("break_when") ? breakWhenValue : "";
    node.ref = activeFields.has("sub_workflow") ? subWorkflowValue : "";
    node.config = typeof node.config === "object" && node.config ? node.config : {};
    const checkedBodyNodes = [...(nodeEditBody?.parentElement?.querySelectorAll(".node-edit-body-chips input:checked") || [])]
      .map((input) => String(input.value || "").trim())
      .filter(Boolean);
    const bodyNodes = checkedBodyNodes.length ? checkedBodyNodes : parseCsvList(nodeEditBody?.value || "");
    if (node.type === "for_each" || node.type === "while") {
      node.config.body = bodyNodes;
    } else {
      delete node.config.body;
    }
    if (node.type === "decision") {
      const branchRows = nodeEditBody?.parentElement?.querySelectorAll(".node-edit-branch") || [];
      const branches = normalizeDecisionBranches(node.config || {});
      branchRows.forEach((row) => {
        const index = Number(row.dataset.branchIndex);
        const branch = branches[index];
        const label = row.querySelector('[data-branch-field="label"]')?.value;
        const whenInput = row.querySelector('[data-branch-field="when"]');
        const when = String(whenInput?.value || "").trim();
        const error = row.querySelector(".node-edit-branch-error");
        if (error) {
          error.hidden = Boolean(when);
          error.textContent = when ? "" : "Condition is required.";
        }
        whenInput?.classList?.toggle("is-invalid", !when);
        if (branch && label) branch.label = clampLength(label, WORKFLOW_FIELD_MAX);
        if (branch && when) branch.when = clampLength(when, WORKFLOW_FIELD_MAX);
      });
      node.config.branches = branches;
    }
    node.retry = activeFields.has("retry")
      ? {
          max: clampInt(nodeEditRetryMax?.value || 0, 0, 5),
          backoff: Math.min(60, Math.max(0, Number(nodeEditRetryBackoff?.value || 0))),
        }
      : { max: 0, backoff: 0 };
    node.receive_from = [];
    node.reports_to = [];
    const previousInput = Array.isArray(node.input) ? [...node.input] : [];
    const nextInput = parseCsvList(nodeEditInput.value);
    const removedAutoInputs = Array.isArray(node.config?._removed_auto_inputs) ? node.config._removed_auto_inputs : [];
    const removedFields = previousInput.filter((field) => !nextInput.includes(field));
    const incomingSources = derivedNodeConnections(draft, node.id).incoming
      .map((sourceId) => draft.nodes.find((candidate) => candidate.id === sourceId))
      .filter(Boolean);
    const newlyRemovedAutoInputs = incomingSources
      .filter((source) => removedFields.includes(nodeOutputIdentifier(source)))
      .map((source) => `${source.id}:${nodeOutputIdentifier(source)}`);
    if (node.config) {
      node.config._removed_auto_inputs = dedupeList([...removedAutoInputs, ...newlyRemovedAutoInputs]);
    }
    node.input = activeFields.has("input") ? nextInput : [];
    node.output = activeFields.has("output") ? clampLength(nodeEditOutput.value.trim(), WORKFLOW_FIELD_MAX) : "";
    node.worker_instances = activeFields.has("workers") ? workers : 1;
    node.max_parallel = activeFields.has("workers") ? workers : 1;
    node.max_items = activeFields.has("max_items") ? clampInt(nodeEditMaxItems.value, 1, 12) : 4;
    node.expects_json = activeFields.has("json") ? Boolean(nodeEditJson.checked) : false;
    normalizeNodeForType(node);
    const nextOutputIdentifier = nodeOutputIdentifier(node);
    if (safeId !== oldId) {
      draft.nodes.forEach((other) => {
        if (other === node) return;
        other.receive_from = [];
        other.reports_to = [];
      });
      mutateWorkflowEdges(draft, { type: "renameNode", fromId: oldId, toId: safeId });
      state.workflowEditorSelectedNodeId = safeId;
    }
    updateDownstreamInputReferences(draft, safeId, previousOutputIdentifier, nextOutputIdentifier);
    if (workflowNodeEditTitle) workflowNodeEditTitle.textContent = node.title || node.id;
    canvas.renderWorkflowCanvas();
  }

  function duplicateSelectedNode() {
    const draft = activeWorkflowDraft();
    const selectedId = state.workflowEditorSelectedNodeId;
    const source = draft?.nodes.find((node) => node.id === selectedId);
    if (!draft || !source || isBoundaryNode(source)) return null;
    canvas.bridge?.beforeWorkflowMutation?.();
    const copy = JSON.parse(JSON.stringify(source));
    copy.id = nextNodeId(draft, `${source.id}_copy`);
    copy.title = `${source.title || source.id} Copy`;
    copy.position = {
      x: Number(source.position?.x || 0) + NODE_GRID_X,
      y: Number(source.position?.y || 0),
    };
    copy.receive_from = [];
    copy.reports_to = [];
    draft.nodes.push(copy);
    state.workflowEditorDraft = { ...draft, nodes: ensureWorkflowBoundaryNodes(draft.nodes) };
    canvas.renderWorkflowCanvas();
    selectWorkflowNode(copy.id);
    canvas.bridge?.afterWorkflowMutation?.();
    return copy;
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
    duplicateSelectedNode,
  };
}
