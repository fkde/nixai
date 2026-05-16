import { api } from "../api.js";
import { state } from "../state.js";
import { deriveWorkflowEdgesFromNodes, newWorkflowDraftFrom, realWorkflowNodes } from "../workflow-builder.js";

export function createWorkflowPersistence({
  workflowEditorAssignChat,
  workflowEditorAssignCode,
  workflowEditorAssignAgentic,
  setStatus,
  getSettingsUi,
  inspector,
}) {
  async function loadWorkflowPresets() {
    const previousDraftId = state.workflowEditorDraft?.id || "";
    const response = await api("/api/settings/workflows");
    state.workflowPresets = response.workflows || [];
    state.customWorkflowIds = Array.isArray(response.custom_ids) ? response.custom_ids : [];
    if (response.selected && state.settings) {
      state.settings.workflow_presets = response.selected;
    }
    const candidate = inspector.workflowById(previousDraftId)
      || inspector.workflowById(state.settings?.workflow_presets?.[state.activeMode])
      || state.workflowPresets[0]
      || null;
    state.workflowEditorDraft = candidate ? newWorkflowDraftFrom(candidate) : null;
    inspector.renderWorkflowSettings();
  }

  function currentWorkflowAssignmentSelection() {
    return {
      chat: Boolean(workflowEditorAssignChat?.checked),
      code: Boolean(workflowEditorAssignCode?.checked),
      agentic: Boolean(workflowEditorAssignAgentic?.checked),
    };
  }

  async function applyWorkflowAssignment(workflowId, assignment = currentWorkflowAssignmentSelection()) {
    if (!inspector.workflowById(workflowId)) {
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
    inspector.renderWorkflowSettings();
    getSettingsUi()?.captureSettingsBaselineFromForm();
    setStatus("Workflow assigned & saved");
    return true;
  }

  async function saveWorkflowEditorDraftWithAssignment(assignAfterSave = false) {
    const draft = inspector.collectWorkflowDraftFromEditor();
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
    const saved = inspector.workflowById(draft.id);
    if (saved) {
      state.workflowEditorDraft = newWorkflowDraftFrom(saved);
      inspector.renderWorkflowEditor();
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

  async function saveWorkflowEditorDraft() {
    return saveWorkflowEditorDraftWithAssignment(false);
  }

  async function deleteWorkflowEditorDraft() {
    const draft = inspector.collectWorkflowDraftFromEditor();
    if (!draft || !draft.id) return;
    if (!inspector.isCustomWorkflow(draft.id)) {
      setStatus("Only custom workflows can be deleted.", true);
      return;
    }
    await api(`/api/settings/workflows/${encodeURIComponent(draft.id)}`, { method: "DELETE" });
    await loadWorkflowPresets();
    setStatus("Custom workflow deleted");
  }

  return {
    loadWorkflowPresets,
    saveWorkflowEditorDraft,
    saveWorkflowEditorDraftWithAssignment,
    deleteWorkflowEditorDraft,
    applyWorkflowAssignment,
    currentWorkflowAssignmentSelection,
  };
}
