import { dom } from "./dom.js";
import { state } from "./state.js";
import {
  DRAG_THRESHOLD,
  PORT_INPUT,
  PORT_OUTPUT,
  deriveWorkflowEdgesFromNodes,
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
} = dom;

export function createWorkflowsUi({ setStatus, getSettingsUi }) {
  const bridge = {};

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
  });

  bridge.activeWorkflowDraft = inspector.activeWorkflowDraft;
  bridge.selectWorkflowNode = inspector.selectWorkflowNode;

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
    });

    workflowBuilderBack?.addEventListener("click", () => {
      inspector.showWorkflowListView();
    });

    workflowEditorSave?.addEventListener("click", () => {
      persistence.saveWorkflowEditorDraft()
        .then(() => inspector.showWorkflowListView())
        .catch((error) => setStatus(error.message, true));
    });

    workflowEditorSaveAssign?.addEventListener("click", () => {
      persistence.saveWorkflowEditorDraftWithAssignment(true)
        .then(() => inspector.showWorkflowListView())
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
    });

    workflowEdgeRulesList?.addEventListener("change", (event) => {
      const target = event.target;
      if (target?.classList?.contains("workflow-edge-rule-preset")) {
        canvas.applyEdgeRuleChange(target);
        canvas.renderEdgeRules(inspector.activeWorkflowDraft());
      }
    });

    workflowEdgeRulesList?.addEventListener("input", (event) => {
      const target = event.target;
      if (target?.classList?.contains("workflow-edge-rule-expression")) {
        canvas.applyEdgeRuleChange(target);
      }
    });

    workflowEditorAddNode?.addEventListener("click", () => {
      inspector.openNodeTypeMenu(workflowEditorAddNode);
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
        inspector.collectWorkflowDraftFromEditor();
      });
      element?.addEventListener("change", () => {
        inspector.collectWorkflowDraftFromEditor();
      });
    });

    const { canvasDrag, linkDrag } = canvas;

    workflowCanvas?.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      const portTarget = event.target.closest?.(".workflow-canvas-port");
      if (portTarget) {
        if (portTarget.dataset.portType === PORT_OUTPUT) {
          canvas.startCanvasLinkDrag(event, portTarget);
        } else if (portTarget.dataset.portType === PORT_INPUT) {
          canvas.startCanvasRelinkDrag(event, portTarget);
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
      deriveWorkflowEdgesFromNodes(draft.nodes)
        .filter((edge) => edge.from === id || edge.to === id)
        .forEach((edge) => {
          canvas.removeCanvasConnection(edge.from, edge.to);
        });
      draft.nodes.splice(index, 1);
      draft.nodes.forEach((node) => {
        node.receive_from = (node.receive_from || []).filter((r) => r !== id);
        node.reports_to = (node.reports_to || []).filter((r) => r !== id);
      });
      inspector.closeNodeEditPanel();
      canvas.renderWorkflowCanvas();
    });

    [
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
    ].forEach((element) => {
      element?.addEventListener("input", inspector.applyNodeEditChanges);
      element?.addEventListener("change", inspector.applyNodeEditChanges);
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
