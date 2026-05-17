import { dom } from "./dom.js";
import { state } from "./state.js";
import {
  DRAG_THRESHOLD,
  PORT_INPUT,
  PORT_OUTPUT,
  deriveWorkflowEdgesFromNodes,
  mutateWorkflowEdges,
  newWorkflowDraftFrom,
} from "./workflow-builder.js";
import { createWorkflowCanvas } from "./workflows/canvas.js";
import { createWorkflowInspector } from "./workflows/inspector.js";
import { createWorkflowPersistence } from "./workflows/persistence.js";

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
  workflowEditorUndo,
  workflowEditorRedo,
  workflowSaveIndicator,
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
  workflowEditorRelayout,
  workflowHealthPanel,
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
  workflowNodeEditDuplicate,
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
} = dom;

export function createWorkflowsUi({ setStatus, getSettingsUi }) {
  const bridge = {};
  const HISTORY_LIMIT = 30;
  const TEXT_EDIT_BURST_MS = 600;
  let undoStack = [];
  let redoStack = [];
  let draftBaseline = "";
  let pendingBurstSnapshot = null;
  let pendingBurstTimer = null;

  function draftSignature(draft = inspector?.activeWorkflowDraft?.()) {
    return draft ? JSON.stringify(draft) : "";
  }

  function updateEditorComfortState() {
    const signature = draftSignature();
    const dirty = Boolean(signature && signature !== draftBaseline);
    if (workflowEditorUndo) workflowEditorUndo.disabled = undoStack.length === 0;
    if (workflowEditorRedo) workflowEditorRedo.disabled = redoStack.length === 0;
    if (workflowSaveIndicator) {
      workflowSaveIndicator.textContent = dirty ? "Unsaved changes" : "Saved";
      workflowSaveIndicator.dataset.state = dirty ? "dirty" : "saved";
    }
  }

  function clearBurstTimer() {
    if (pendingBurstTimer) {
      clearTimeout(pendingBurstTimer);
      pendingBurstTimer = null;
    }
  }

  function flushBurstSnapshot() {
    clearBurstTimer();
    if (pendingBurstSnapshot !== null) {
      pushUndoSnapshot(pendingBurstSnapshot);
      pendingBurstSnapshot = null;
    }
  }

  // Capture the pre-edit draft state once per burst of text/typing input.
  // Call BEFORE applying the mutation. Subsequent calls within the debounce
  // window only reset the timer; the snapshot is pushed once after idle or
  // immediately when flushBurstSnapshot() runs on commit/structural op.
  function beginTextEditBurst() {
    if (pendingBurstSnapshot === null) {
      pendingBurstSnapshot = draftSignature();
    }
    clearBurstTimer();
    pendingBurstTimer = setTimeout(flushBurstSnapshot, TEXT_EDIT_BURST_MS);
  }

  function resetEditorHistory() {
    undoStack = [];
    redoStack = [];
    clearBurstTimer();
    pendingBurstSnapshot = null;
    draftBaseline = draftSignature();
    updateEditorComfortState();
  }

  function captureUndoSnapshot() {
    flushBurstSnapshot();
    pushUndoSnapshot(draftSignature());
  }

  function pushUndoSnapshot(serialized) {
    if (!serialized) return;
    if (undoStack[undoStack.length - 1] === serialized) return;
    undoStack.push(serialized);
    if (undoStack.length > HISTORY_LIMIT) undoStack.shift();
    redoStack = [];
    updateEditorComfortState();
  }

  function markDraftChanged(options) {
    if (options && options.structural) flushBurstSnapshot();
    updateEditorComfortState();
  }

  function renderRestoredDraft(selectedNodeId = state.workflowEditorSelectedNodeId) {
    inspector.renderWorkflowEditor();
    if (selectedNodeId && state.workflowEditorDraft?.nodes?.some((node) => node.id === selectedNodeId)) {
      inspector.selectWorkflowNode(selectedNodeId);
    } else {
      inspector.closeNodeEditPanel();
    }
    canvas.renderWorkflowHealthPanel(workflowHealthPanel);
    updateEditorComfortState();
  }

  function undoWorkflowEdit() {
    if (undoStack.length === 0) return false;
    const current = draftSignature();
    if (current) redoStack.push(current);
    const previous = undoStack.pop();
    state.workflowEditorDraft = JSON.parse(previous);
    renderRestoredDraft();
    setStatus("Undone");
    return true;
  }

  function redoWorkflowEdit() {
    if (redoStack.length === 0) return false;
    const current = draftSignature();
    if (current) undoStack.push(current);
    const next = redoStack.pop();
    state.workflowEditorDraft = JSON.parse(next);
    renderRestoredDraft();
    setStatus("Redone");
    return true;
  }

  const canvas = createWorkflowCanvas({
    workflowCanvas,
    workflowCanvasNodes,
    workflowCanvasLabels,
    workflowCanvasEdges,
    workflowCanvasEdgeLayer,
    workflowEdgeRulesList,
    setStatus,
    bridge,
  });

  const inspector = createWorkflowInspector({
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
  });

  bridge.activeWorkflowDraft = inspector.activeWorkflowDraft;
  bridge.selectWorkflowNode = inspector.selectWorkflowNode;
  bridge.renderWorkflowHealthPanel = () => canvas.renderWorkflowHealthPanel(workflowHealthPanel);
  bridge.beforeWorkflowMutation = captureUndoSnapshot;
  bridge.afterWorkflowMutation = () => markDraftChanged({ structural: true });

  const persistence = createWorkflowPersistence({
    workflowEditorAssignChat,
    workflowEditorAssignCode,
    workflowEditorAssignAgentic,
    setStatus,
    getSettingsUi,
    inspector,
  });

  function init() {
    workflowEditorNew?.addEventListener("click", () => {
      inspector.showWorkflowBuilderView(null);
      resetEditorHistory();
    });

    workflowBuilderBack?.addEventListener("click", () => {
      inspector.showWorkflowListView();
    });

    workflowEditorSave?.addEventListener("click", () => {
      persistence.saveWorkflowEditorDraft()
        .then(() => {
          draftBaseline = draftSignature();
          updateEditorComfortState();
          inspector.showWorkflowListView();
        })
        .catch((error) => setStatus(error.message, true));
    });

    workflowEditorSaveAssign?.addEventListener("click", () => {
      persistence.saveWorkflowEditorDraftWithAssignment(true)
        .then(() => {
          draftBaseline = draftSignature();
          updateEditorComfortState();
          inspector.showWorkflowListView();
        })
        .catch((error) => setStatus(error.message, true));
    });

    workflowEditorDelete?.addEventListener("click", () => {
      persistence.deleteWorkflowEditorDraft()
        .then(() => inspector.showWorkflowListView())
        .catch((error) => setStatus(error.message, true));
    });

    workflowPresetList?.addEventListener("click", (event) => {
      const editButton = event.target.closest(".workflow-preset-edit");
      if (!editButton) return;
      const card = editButton.closest(".workflow-preset-item");
      const workflowId = card?.dataset.workflowId;
      if (!workflowId) return;
      inspector.showWorkflowBuilderView(workflowId);
      resetEditorHistory();
    });

    workflowEdgeRulesList?.addEventListener("change", (event) => {
      const target = event.target;
      if (target?.classList?.contains("workflow-edge-rule-preset")) {
        captureUndoSnapshot();
        canvas.applyEdgeRuleChange(target);
        canvas.renderEdgeRules(inspector.activeWorkflowDraft());
        markDraftChanged({ structural: true });
      } else if (target?.classList?.contains("workflow-edge-rule-expression")) {
        beginTextEditBurst();
        canvas.applyEdgeRuleChange(target);
        flushBurstSnapshot();
        markDraftChanged();
      }
    });

    workflowEdgeRulesList?.addEventListener("input", (event) => {
      const target = event.target;
      if (target?.classList?.contains("workflow-edge-rule-expression")) {
        beginTextEditBurst();
        canvas.applyEdgeRuleChange(target);
        markDraftChanged();
      }
    });

    workflowEditorAddNode?.addEventListener("click", () => {
      inspector.openNodeTypeMenu(workflowEditorAddNode);
    });

    workflowEditorRelayout?.addEventListener("click", () => {
      captureUndoSnapshot();
      canvas.relayoutCanvasNodes();
      canvas.renderWorkflowHealthPanel(workflowHealthPanel);
      markDraftChanged({ structural: true });
    });

    workflowEditorUndo?.addEventListener("click", undoWorkflowEdit);
    workflowEditorRedo?.addEventListener("click", redoWorkflowEdit);

    workflowHealthPanel?.addEventListener("click", (event) => {
      const issue = event.target.closest?.(".workflow-health-issue");
      const nodeId = issue?.dataset.nodeId || "";
      if (!nodeId) return;
      inspector.selectWorkflowNode(nodeId);
      workflowCanvas?.focus();
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
        beginTextEditBurst();
        inspector.collectWorkflowDraftFromEditor();
        markDraftChanged();
      });
      element?.addEventListener("change", () => {
        beginTextEditBurst();
        inspector.collectWorkflowDraftFromEditor();
        flushBurstSnapshot();
        markDraftChanged();
      });
    });

    const { canvasDrag, linkDrag } = canvas;

    workflowCanvas?.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const portTarget = event.target.closest?.(".workflow-canvas-port");
      if (portTarget) {
        captureUndoSnapshot();
        if (portTarget.dataset.portType === PORT_OUTPUT) {
          canvas.startCanvasLinkDrag(event, portTarget);
        } else if (portTarget.dataset.portType === PORT_INPUT) {
          canvas.startCanvasRelinkDrag(event, portTarget);
        }
        return;
      }
      const editTarget = event.target.closest?.(".workflow-canvas-node-edit");
      const labelTarget = event.target.closest?.(".workflow-canvas-edge-label");
      if (labelTarget) {
        event.preventDefault();
        event.stopPropagation();
        canvas.selectCanvasEdge({
          from: labelTarget.dataset.edgeFrom,
          to: labelTarget.dataset.edgeTo,
          when: labelTarget.dataset.edgeWhen || "",
        }, labelTarget);
        return;
      }
      const tile = event.target.closest?.(".workflow-canvas-node");
      if (!tile) return;
      const id = tile.dataset.nodeId;
      if (editTarget) {
        event.preventDefault();
        event.stopPropagation();
        inspector.selectWorkflowNode(id);
        return;
      }
      canvasDrag.id = id;
      canvasDrag.tile = tile;
      canvasDrag.originX = parseFloat(tile.style.left) || 0;
      canvasDrag.originY = parseFloat(tile.style.top) || 0;
      canvasDrag.pointerX = event.clientX;
      canvasDrag.pointerY = event.clientY;
      canvasDrag.moved = false;
      flushBurstSnapshot();
      canvasDrag.undoSnapshot = draftSignature();
      tile.setPointerCapture?.(event.pointerId);
      tile.classList.add("is-dragging");
    });

    workflowCanvas?.addEventListener("pointermove", (event) => {
      if (linkDrag.sourceId) {
        canvas.updateCanvasLinkPreview(event);
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
      const draft = inspector.activeWorkflowDraft();
      const node = draft?.nodes.find((n) => n.id === canvasDrag.id);
      if (node) node.position = { x, y };
      canvas.renderCanvasEdges(draft);
    });

    workflowCanvas?.addEventListener("pointerup", (event) => {
      if (linkDrag.sourceId) {
        canvas.finishCanvasLinkDrag(event);
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
      if (wasClick && id) inspector.selectWorkflowNode(id);
      if (!wasClick) {
        pushUndoSnapshot(canvasDrag.undoSnapshot);
        markDraftChanged({ structural: true });
      }
      canvasDrag.undoSnapshot = "";
      canvas.renderWorkflowHealthPanel(workflowHealthPanel);
    });

    workflowCanvas?.addEventListener("pointercancel", () => {
      if (linkDrag.sourceId) {
        const removedConnection = Boolean(linkDrag.detached);
        canvas.cleanupCanvasLinkDrag();
        if (removedConnection) {
          canvas.refreshWorkflowCanvasAfterLinkChange();
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
      inspector.closeNodeEditPanel();
    });

    workflowNodeEditRemove?.addEventListener("click", () => {
      const draft = inspector.activeWorkflowDraft();
      const id = state.workflowEditorSelectedNodeId;
      if (!draft || !id) return;
      const index = draft.nodes.findIndex((n) => n.id === id);
      if (index < 0) return;
      captureUndoSnapshot();
      deriveWorkflowEdgesFromNodes(draft.nodes, draft.edges || [])
        .filter((edge) => edge.from === id || edge.to === id)
        .forEach((edge) => {
          canvas.removeCanvasConnection(edge.from, edge.to);
        });
      draft.nodes.splice(index, 1);
      mutateWorkflowEdges(draft, { type: "remove", from: id });
      mutateWorkflowEdges(draft, { type: "remove", to: id });
      inspector.closeNodeEditPanel();
      canvas.renderWorkflowCanvas();
      canvas.renderWorkflowHealthPanel(workflowHealthPanel);
      markDraftChanged({ structural: true });
    });

    workflowNodeEditDuplicate?.addEventListener("click", () => {
      captureUndoSnapshot();
      inspector.duplicateSelectedNode();
      canvas.renderWorkflowHealthPanel(workflowHealthPanel);
      markDraftChanged({ structural: true });
      setStatus("Node duplicated");
    });

    [
      nodeEditTitleInput,
      nodeEditType,
      nodeEditSubWorkflowRef,
      nodeEditBreakWhen,
      nodeEditPrompt,
      nodeEditBody,
      nodeEditRetryMax,
      nodeEditRetryBackoff,
      nodeEditRole,
      nodeEditInput,
      nodeEditOutput,
      nodeEditWorkers,
      nodeEditMaxItems,
      nodeEditJson,
    ].forEach((element) => {
      element?.addEventListener("input", () => {
        beginTextEditBurst();
        inspector.applyNodeEditChanges();
        markDraftChanged();
      });
      element?.addEventListener("change", () => {
        beginTextEditBurst();
        inspector.applyNodeEditChanges();
        flushBurstSnapshot();
        markDraftChanged();
      });
    });

    nodeEditId?.addEventListener("change", () => {
      beginTextEditBurst();
      inspector.applyNodeEditChanges();
      flushBurstSnapshot();
      markDraftChanged();
    });
    nodeEditId?.addEventListener("blur", () => {
      flushBurstSnapshot();
    });

    document.addEventListener("keydown", (event) => {
      const inBuilder = state.workflowEditorView === "builder" && !workflowBuilderView?.hidden;
      if (!inBuilder) return;
      const key = event.key.toLowerCase();
      if ((event.metaKey || event.ctrlKey) && key === "z") {
        event.preventDefault();
        if (event.shiftKey) redoWorkflowEdit();
        else undoWorkflowEdit();
        return;
      }
      if ((event.metaKey || event.ctrlKey) && key === "d") {
        captureUndoSnapshot();
        inspector.duplicateSelectedNode();
        canvas.renderWorkflowHealthPanel(workflowHealthPanel);
        markDraftChanged({ structural: true });
        event.preventDefault();
        return;
      }
      if (event.key === "Delete" || event.key === "Backspace") {
        if (event.target.matches?.("input, textarea, select")) return;
        if (workflowNodeEditPanel?.contains(document.activeElement)) return;
        if (state.workflowEditorSelectedEdge) captureUndoSnapshot();
        if (canvas.deleteSelectedEdge()) {
          event.preventDefault();
          canvas.renderWorkflowHealthPanel(workflowHealthPanel);
          markDraftChanged({ structural: true });
          return;
        }
        if (state.workflowEditorSelectedNodeId) {
          workflowNodeEditRemove?.click();
          event.preventDefault();
        }
      }
    });

    workflowCanvasLabels?.addEventListener("click", (event) => {
      const label = event.target.closest?.(".workflow-canvas-edge-label");
      if (!label) return;
      canvas.selectCanvasEdge({
        from: label.dataset.edgeFrom,
        to: label.dataset.edgeTo,
        when: label.dataset.edgeWhen || "",
      }, label);
    });
  }

  return {
    activeWorkflowDraft: inspector.activeWorkflowDraft,
    collectWorkflowDraftFromEditor: inspector.collectWorkflowDraftFromEditor,
    deriveWorkflowEdgesFromNodes,
    init,
    loadWorkflowPresets: persistence.loadWorkflowPresets,
    newWorkflowDraftFrom,
    nodeRoleSelectOptionsHtml: inspector.nodeRoleSelectOptionsHtml,
    renderWorkflowEditor: inspector.renderWorkflowEditor,
    renderWorkflowSettings: inspector.renderWorkflowSettings,
    showWorkflowBuilderView: inspector.showWorkflowBuilderView,
    showWorkflowListView: inspector.showWorkflowListView,
    syncSelectedNodeRoleOptions: inspector.syncSelectedNodeRoleOptions,
    workflowById: inspector.workflowById,
  };
}
