import {
  dirtyStorageKey,
  registerDirtyTracker,
  safeLocalStorageGet,
} from "./dirty-tracker.js";
import { api } from "./api.js";
import { dom } from "./dom.js";
import { escapeHtml } from "./helpers.js";
import { state } from "./state.js";
import { effortOrder, embeddingModelMarkers, uiIcon } from "./ui.js";

const {
  shell,
  messagesEl,
  effortSelect,
  settingsClose,
  settingsPanel,
  settingsForm,
  settingsFooter,
  saveSettingsButton,
  settingsNavButtons,
  settingsSections,
  userName,
  ollamaBaseUrl,
  workspacePath,
  embeddingModel,
  requireToolConfirmation,
  alwaysAllowedTools,
  workflowChat,
  workflowCode,
  workflowAgentic,
  emailProvider,
  emailProviderStatus,
  emailProviderAccount,
  emailProviderHint,
  connectEmailProviderButton,
  disconnectEmailProviderButton,
  availableToolList,
  modelRoleList,
  addModelRoleButton,
  refreshModelsButton,
  modelsHint,
} = dom;

export function createSettingsUi({
  setStatus,
  getChatUi,
  getWorkflowsUi,
  loadDeferred,
}) {
  let settingsDirtyTracker = null;

  function currentEffort() {
    const effort = state.settings?.effort || "medium";
    return effortOrder.includes(effort) ? effort : "medium";
  }

  function renderEffortSwitch() {
    const effort = currentEffort();
    if (effortSelect) {
      effortSelect.value = effort;
    }
  }

  async function setEffort(effort, persist = true) {
    if (!effortOrder.includes(effort)) return;
    state.settings = { ...(state.settings || {}), effort };
    renderEffortSwitch();
    if (!persist) return;
    try {
      const latest = await api("/api/settings");
      state.settings = await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({ ...latest, effort }),
      });
      renderEffortSwitch();
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  function normalizeModelCatalog(payload) {
    if (!Array.isArray(payload)) return [];
    return payload
      .map((item) => {
        if (typeof item === "string") {
          return {
            name: item,
            kind: inferModelKindFromName(item),
            family: "",
            families: [],
            parameter_size: "",
            quantization_level: "",
            format: "",
            details: {},
            model_info: {},
            capabilities: [],
            error: "",
          };
        }
        if (!item || typeof item !== "object" || typeof item.name !== "string") return null;
        return {
          name: item.name,
          kind: item.kind || inferModelKindFromName(item.name),
          family: item.family || "",
          families: Array.isArray(item.families) ? item.families : [],
          parameter_size: item.parameter_size || "",
          quantization_level: item.quantization_level || "",
          format: item.format || "",
          size: Number.isFinite(item.size) ? item.size : null,
          digest: item.digest || "",
          modified_at: item.modified_at || "",
          details: item.details && typeof item.details === "object" ? item.details : {},
          model_info: item.model_info && typeof item.model_info === "object" ? item.model_info : {},
          capabilities: Array.isArray(item.capabilities) ? item.capabilities : [],
          error: item.error || "",
        };
      })
      .filter(Boolean)
      .sort((first, second) => first.name.localeCompare(second.name));
  }

  function inferModelKindFromName(model) {
    const normalized = String(model || "").toLowerCase();
    return embeddingModelMarkers.some((marker) => normalized.includes(marker)) ? "embedding" : "chat";
  }

  function modelKind(model) {
    if (!model) return "unknown";
    if (model.kind) return model.kind;
    return inferModelKindFromName(model.name);
  }

  function modelByName(name) {
    return state.modelCatalog.find((model) => model.name === name) || null;
  }

  function isEmbeddingModelName(name) {
    const model = modelByName(name);
    return model ? modelKind(model) === "embedding" : inferModelKindFromName(name) === "embedding";
  }

  function roleAssignmentModels() {
    return state.modelCatalog
      .filter((model) => modelKind(model) !== "embedding")
      .map((model) => model.name);
  }

  function embeddingModels() {
    return state.modelCatalog
      .filter((model) => modelKind(model) === "embedding")
      .map((model) => model.name);
  }

  function modelOptionsHtml(selectedModel, placeholder = "Select model", models = state.availableModels) {
    const options = models
      .map((model) => `<option value="${escapeHtml(model)}"${model === selectedModel ? " selected" : ""}>${escapeHtml(model)}</option>`)
      .join("");
    const selectedExists = models.includes(selectedModel);
    const customOption = selectedModel && !selectedExists
      ? `<option value="${escapeHtml(selectedModel)}" selected>${escapeHtml(selectedModel)}</option>`
      : "";
    const emptySelected = selectedModel ? "" : " selected";
    return `<option value=""${emptySelected}>${escapeHtml(placeholder)}</option>${customOption}${options}`;
  }

  function normalizeModelRoles(modelRoles) {
    if (!Array.isArray(modelRoles) || modelRoles.length === 0) {
      return [
        { role: "assistant", model: "" },
        { role: "planner", model: "" },
        { role: "worker", model: "" },
        { role: "reviewer", model: "" },
        { role: "judge", model: "" },
        { role: "task_discovery", model: "" },
        { role: "vision", model: "" },
      ];
    }
    const roles = modelRoles.map((item) => ({
      role: item.role || "",
      model: item.model || "",
    }));
    if (!roles.some((item) => item.role.toLowerCase() === "vision")) {
      roles.push({ role: "vision", model: "" });
    }
    return roles;
  }

  function roleSelectOptionsHtml(selectedRole) {
    const cleanSelectedRole = String(selectedRole || "");
    const options = state.roles
      .map((role) => `<option value="${escapeHtml(role.name)}"${role.name.toLowerCase() === cleanSelectedRole.toLowerCase() ? " selected" : ""}>${escapeHtml(role.name)}</option>`)
      .join("");
    const selectedExists = state.roles.some((role) => role.name.toLowerCase() === cleanSelectedRole.toLowerCase());
    const customOption = cleanSelectedRole && !selectedExists
      ? `<option value="${escapeHtml(cleanSelectedRole)}" selected>${escapeHtml(cleanSelectedRole)}</option>`
      : "";
    const emptySelected = cleanSelectedRole ? "" : " selected";
    return `<option value=""${emptySelected}>Select role</option>${customOption}${options}`;
  }

  function renderModelRoles() {
    const roles = normalizeModelRoles(state.settings?.model_roles);
    modelRoleList.innerHTML = "";
    roles.forEach((roleConfig, index) => {
      const selectedModel = isEmbeddingModelName(roleConfig.model) ? "" : roleConfig.model;
      const row = document.createElement("div");
      row.className = "model-role-row";
      row.dataset.index = String(index);
      row.innerHTML = `
        <label class="model-role-field">
          <span class="model-role-label">Role</span>
          <select class="role-select">
            ${roleSelectOptionsHtml(roleConfig.role)}
          </select>
        </label>
        <label class="model-role-field">
          <span class="model-role-label">Model</span>
          <select class="model-select">
            ${modelOptionsHtml(selectedModel, "Select model", roleAssignmentModels())}
          </select>
        </label>
        <button class="remove-role" type="button" aria-label="Remove role">${uiIcon("minus")}</button>
      `;

      row.querySelector(".remove-role").addEventListener("click", () => {
        row.remove();
        updateSettingsDirtyState();
      });
      modelRoleList.append(row);
    });
  }

  function renderEmbeddingModel() {
    if (!embeddingModel) return;
    const selectedModel = isEmbeddingModelName(state.settings?.embedding_model) ? state.settings.embedding_model : "";
    embeddingModel.innerHTML = modelOptionsHtml(selectedModel, "No embedding model", embeddingModels());
  }

  function collectModelRoleDrafts() {
    return [...modelRoleList.querySelectorAll(".model-role-row")]
      .map((row) => ({
        role: row.querySelector(".role-select").value.trim(),
        model: row.querySelector(".model-select").value.trim(),
      }));
  }

  function collectModelRoles() {
    return collectModelRoleDrafts().filter((item) => item.role && item.model);
  }

  function buildSettingsPayload(includeIncompleteRoles = false) {
    if (!state.settings) return null;
    const roleDrafts = collectModelRoleDrafts()
      .map((item) => ({
        role: item.role.trim(),
        model: item.model.trim(),
      }))
      .filter((item) => includeIncompleteRoles ? (item.role || item.model) : (item.role && item.model));
    if (!includeIncompleteRoles && roleDrafts.length === 0) {
      return null;
    }
    const assistantRole = roleDrafts.find((item) => item.role.toLowerCase() === "assistant" && item.model)
      || roleDrafts.find((item) => item.model)
      || { model: state.settings.default_model || "" };
    return {
      ...state.settings,
      user_name: userName.value.trim(),
      ollama_base_url: ollamaBaseUrl.value.trim(),
      workspace_path: workspacePath.value.trim(),
      embedding_model: embeddingModel.value.trim(),
      require_tool_confirmation: requireToolConfirmation.checked,
      always_allowed_tools: [...new Set(
        (Array.isArray(state.settings?.always_allowed_tools) ? state.settings.always_allowed_tools : [])
          .map((item) => String(item).trim())
          .filter(Boolean),
      )].sort(),
      effort: currentEffort(),
      workflow_presets: {
        chat: workflowChat?.value || "simple",
        code: workflowCode?.value || "simple",
        agentic: workflowAgentic?.value || "simple",
      },
      email_provider: {
        ...(state.settings.email_provider || {}),
        provider: emailProvider.value,
      },
      default_model: assistantRole.model || state.settings.default_model || "",
      model_roles: roleDrafts,
    };
  }

  function mergeSettingsSnapshot(current, snapshot) {
    const base = current || {};
    const incoming = snapshot || {};
    const emailProviderSnapshot = incoming.email_provider || {};
    return {
      ...base,
      ...incoming,
      workflow_presets: {
        ...(base.workflow_presets || {}),
        ...(incoming.workflow_presets || {}),
      },
      email_provider: {
        ...(base.email_provider || {}),
        provider: typeof emailProviderSnapshot.provider === "string"
          ? emailProviderSnapshot.provider
          : (base.email_provider?.provider || ""),
      },
    };
  }

  function ensureSettingsDirtyTracker() {
    if (settingsDirtyTracker || !settingsForm) return settingsDirtyTracker;
    settingsDirtyTracker = registerDirtyTracker(settingsForm, {
      storageKey: "settings",
      getSnapshot: () => buildSettingsPayload(true),
      applySnapshot: (snapshot) => {
        if (!snapshot || typeof snapshot !== "object") return;
        state.settings = mergeSettingsSnapshot(state.settings, snapshot);
        renderSettings();
        getChatUi()?.syncHeaderWorkspace();
        if (messagesEl.querySelector(".empty")) {
          getChatUi()?.renderMessages([]);
        }
      },
      onDirtyChange: (dirty) => {
        if (!saveSettingsButton || !settingsFooter) return;
        saveSettingsButton.classList.toggle("is-hidden", !dirty);
        saveSettingsButton.disabled = !dirty;
        saveSettingsButton.setAttribute("aria-hidden", dirty ? "false" : "true");
        settingsFooter.classList.toggle("has-changes", dirty);
      },
    });
    return settingsDirtyTracker;
  }

  function updateSettingsDirtyState() {
    const tracker = ensureSettingsDirtyTracker();
    if (!tracker || !state.settings) return;
    tracker.refresh();
  }

  function captureSettingsBaselineFromForm() {
    const tracker = ensureSettingsDirtyTracker();
    if (!tracker || !state.settings) return;
    tracker.captureBaseline();
  }

  function restoreSettingsDraftFromStorage() {
    const tracker = ensureSettingsDirtyTracker();
    if (!tracker || !state.settings) return false;
    return tracker.restoreDraftIfAny();
  }

  function syncModelSelectionState() {
    if (!state.settings) return;
    const draftRoles = collectModelRoleDrafts();
    const nextSettings = { ...state.settings };
    if (draftRoles.length > 0) {
      nextSettings.model_roles = draftRoles;
    }
    if (embeddingModel.options.length > 0) {
      nextSettings.embedding_model = embeddingModel.value.trim();
    }
    state.settings = nextSettings;
  }

  function renderSettings() {
    if (!state.settings) return;
    userName.value = state.settings.user_name || "";
    ollamaBaseUrl.value = state.settings.ollama_base_url || "";
    workspacePath.value = state.settings.workspace_path || "";
    renderEmbeddingModel();
    requireToolConfirmation.checked = state.settings.require_tool_confirmation !== false;
    emailProvider.value = state.settings.email_provider?.provider || "";
    renderEmailProvider();
    renderAlwaysAllowedTools();
    renderAvailableTools();
    getWorkflowsUi()?.renderWorkflowSettings();
    renderModelRoles();
    renderSettingsSections();
    renderEffortSwitch();
    updateSettingsDirtyState();
  }

  async function ensureModelsLoaded(force = false) {
    if (state.modelsLoading) return;
    if (!force && state.modelsLoaded) return;
    await refreshModels();
  }

  function renderEmailProvider() {
    const provider = state.settings?.email_provider || {};
    const status = provider.status || "disconnected";
    const account = provider.account_email || "No account connected.";
    emailProviderStatus.textContent = status;
    emailProviderStatus.className = `provider-state ${status}`;
    emailProviderAccount.textContent = account;
    emailProviderHint.textContent = provider.provider
      ? "OAuth is prepared. The real browser flow needs a client ID, redirect URI, and token storage next."
      : "Choose Google or Microsoft, then start the auth flow.";
    connectEmailProviderButton.disabled = !emailProvider.value;
    disconnectEmailProviderButton.disabled = status === "disconnected" && !provider.provider;
  }

  function renderSettingsSections() {
    settingsNavButtons.forEach((button) => {
      const active = button.dataset.settingsSection === state.activeSettingsSection;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    settingsSections.forEach((section) => {
      section.classList.toggle("active", section.dataset.settingsPanel === state.activeSettingsSection);
    });
  }

  function renderAlwaysAllowedTools() {
    const tools = Array.isArray(state.settings?.always_allowed_tools) ? state.settings.always_allowed_tools : [];
    alwaysAllowedTools.innerHTML = "";
    if (tools.length === 0) {
      alwaysAllowedTools.innerHTML = '<p class="settings-empty">No function is permanently allowed yet.</p>';
      return;
    }
    tools.forEach((tool) => {
      const chip = document.createElement("span");
      chip.className = "tool-chip";
      chip.innerHTML = `
        <span>${escapeHtml(tool)}</span>
        <button type="button" aria-label="Remove ${escapeHtml(tool)}">${uiIcon("x")}</button>
      `;
      chip.querySelector("button").addEventListener("click", () => {
        state.settings.always_allowed_tools = tools.filter((item) => item !== tool);
        renderAlwaysAllowedTools();
      });
      alwaysAllowedTools.append(chip);
    });
    updateSettingsDirtyState();
  }

  function renderAvailableTools() {
    availableToolList.innerHTML = "";
    if (!Array.isArray(state.availableTools) || state.availableTools.length === 0) {
      availableToolList.innerHTML = '<p class="settings-empty">Loading tool list...</p>';
      return;
    }
    state.availableTools.forEach((tool) => {
      const item = document.createElement("article");
      item.className = "available-tool-item";
      const meta = tool.meta || {};
      item.innerHTML = `
        <div>
          <strong>${escapeHtml(tool.name)}</strong>
          <p>${escapeHtml(tool.description || "")}</p>
        </div>
        <div class="tool-meta">
          <span>${escapeHtml(meta.category || "tool")}</span>
          <span>${escapeHtml(meta.risk || "read")}</span>
          <span>${meta.alwaysAllowed ? "always allowed" : meta.requiresConfirmation ? "asks first" : "free"}</span>
        </div>
      `;
      availableToolList.append(item);
    });
  }

  function openSettings() {
    shell.classList.add("settings-open");
    settingsPanel.setAttribute("aria-hidden", "false");
    getWorkflowsUi()?.showWorkflowListView();
    renderSettings();
    loadDeferred();
    ensureModelsLoaded().catch((error) => {
      modelsHint.textContent = error.message;
    });
  }

  function closeSettings() {
    shell.classList.remove("settings-open");
    settingsPanel.setAttribute("aria-hidden", "true");
  }

  async function loadSettings(restoreDraft = false) {
    state.settings = await api("/api/settings");
    renderSettings();
    captureSettingsBaselineFromForm();
    const hasLocalDraft = Boolean(settingsForm && safeLocalStorageGet(dirtyStorageKey(settingsForm, "settings")));
    if (restoreDraft || hasLocalDraft) {
      restoreSettingsDraftFromStorage();
    }
    getChatUi()?.syncHeaderWorkspace();
    if (shell.classList.contains("settings-open")) {
      ensureModelsLoaded().catch((error) => {
        modelsHint.textContent = error.message;
      });
    }
  }

  async function loadTools() {
    const response = await api("/api/tools");
    state.availableTools = response.tools || [];
    renderAvailableTools();
  }

  async function refreshModels() {
    if (state.modelsLoading) return;
    state.modelsLoading = true;
    syncModelSelectionState();
    refreshModelsButton.disabled = true;
    refreshModelsButton.textContent = "Refreshing...";
    modelsHint.textContent = "Loading models...";
    try {
      state.modelCatalog = normalizeModelCatalog(await api("/api/settings/models"));
      state.availableModels = state.modelCatalog.map((model) => model.name);
      state.modelsLoaded = true;
      const roleModelCount = roleAssignmentModels().length;
      const embeddingModelCount = embeddingModels().length;
      modelsHint.textContent = state.modelCatalog.length
        ? `${state.modelCatalog.length} model(s) loaded from Ollama · ${roleModelCount} role · ${embeddingModelCount} embedding.`
        : "Ollama did not report any models.";
      renderModelRoles();
      renderEmbeddingModel();
    } catch (error) {
      state.modelsLoaded = false;
      modelsHint.textContent = error.message;
    } finally {
      state.modelsLoading = false;
      refreshModelsButton.disabled = false;
      refreshModelsButton.textContent = "Refresh Models";
    }
  }

  function init() {
    settingsClose.addEventListener("click", () => {
      closeSettings();
    });

    settingsNavButtons.forEach((button) => {
      button.addEventListener("click", () => {
        state.activeSettingsSection = button.dataset.settingsSection || "basis";
        renderSettingsSections();
      });
    });

    effortSelect?.addEventListener("change", () => {
      setEffort(effortSelect.value || "medium").catch((error) => setStatus(error.message, true));
    });

    emailProvider.addEventListener("change", () => {
      state.settings.email_provider = {
        ...(state.settings.email_provider || {}),
        provider: emailProvider.value,
        status: emailProvider.value ? (state.settings.email_provider?.status || "disconnected") : "disconnected",
      };
      renderEmailProvider();
    });

    connectEmailProviderButton.addEventListener("click", async () => {
      const provider = emailProvider.value;
      if (!provider) return;
      try {
        const response = await api("/api/settings/email-provider/auth", {
          method: "POST",
          body: JSON.stringify({ provider }),
        });
        state.settings = await api("/api/settings");
        renderSettings();
        setStatus(response.message || "Provider prepared");
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    disconnectEmailProviderButton.addEventListener("click", async () => {
      try {
        state.settings = await api("/api/settings/email-provider/disconnect", { method: "POST" });
        renderSettings();
        setStatus("Email provider disconnected");
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    addModelRoleButton.addEventListener("click", () => {
      const roles = collectModelRoleDrafts();
      roles.push({ role: "", model: "" });
      state.settings = { ...state.settings, model_roles: roles };
      renderModelRoles();
      const rows = modelRoleList.querySelectorAll(".model-role-row");
      rows[rows.length - 1]?.querySelector(".role-select")?.focus();
    });

    refreshModelsButton.addEventListener("click", () => {
      refreshModels().catch((error) => {
        modelsHint.textContent = error.message;
      });
    });

    settingsForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = buildSettingsPayload(false);
      if (!payload || !Array.isArray(payload.model_roles) || payload.model_roles.length === 0) {
        setStatus("At least one role with a model is required.", true);
        return;
      }
      try {
        state.settings = await api("/api/settings", {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        await loadTools();
        renderSettings();
        getChatUi()?.syncHeaderWorkspace();
        if (messagesEl.querySelector(".empty")) {
          getChatUi()?.renderMessages([]);
        }
        captureSettingsBaselineFromForm();
        setStatus("Settings saved");
      } catch (error) {
        setStatus(error.message, true);
      }
    });
  }

  return {
    buildSettingsPayload,
    captureSettingsBaselineFromForm,
    closeSettings,
    collectModelRoleDrafts,
    collectModelRoles,
    currentEffort,
    ensureModelsLoaded,
    init,
    loadSettings,
    loadTools,
    openSettings,
    refreshModels,
    renderAvailableTools,
    renderEffortSwitch,
    renderEmbeddingModel,
    renderModelRoles,
    renderSettings,
    renderSettingsSections,
    setEffort,
    updateSettingsDirtyState,
  };
}
