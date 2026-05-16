import { api } from "./api.js";
import { dom } from "./dom.js";
import { escapeHtml } from "./helpers.js";
import { state } from "./state.js";
import { markdownPreview } from "./ui.js";

const {
  roleNameOptions,
  rolePromptList,
  newRoleButton,
  saveRoleButton,
  deleteRoleButton,
  roleNameInput,
  roleContentInput,
  rolePreview,
} = dom;

export function createRolesUi({ setStatus, getSettingsUi, getWorkflowsUi }) {
  function roleOptionsHtml() {
    return state.roles
      .map((role) => `<option value="${escapeHtml(role.name)}">${escapeHtml(role.filename)}</option>`)
      .join("");
  }

  function activeRole() {
    return state.roles.find((role) => role.name === state.activeRoleName) || null;
  }

  function renderRoleOptions() {
    roleNameOptions.innerHTML = roleOptionsHtml();
  }

  function renderRoleList() {
    rolePromptList.innerHTML = "";
    state.roles.forEach((role) => {
      const button = document.createElement("button");
      button.className = "role-prompt-item";
      button.classList.toggle("active", role.name === state.activeRoleName);
      button.type = "button";
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", role.name === state.activeRoleName ? "true" : "false");
      button.innerHTML = `
        <span>${escapeHtml(role.name)}</span>
      `;
      button.addEventListener("click", () => {
        state.activeRoleName = role.name;
        renderRoleList();
        renderRoleEditor();
      });
      rolePromptList.append(button);
    });
  }

  function renderRoleEditor() {
    const role = activeRole();
    deleteRoleButton.disabled = !role || role.default;
    if (!role) {
      roleNameInput.value = "";
      roleContentInput.value = "# CUSTOM_ROLE\n\n## Mission\n- \n\n## Boundaries\n- \n";
      rolePreview.innerHTML = markdownPreview(roleContentInput.value);
      return;
    }
    roleNameInput.value = role.name;
    roleContentInput.value = role.content || "";
    rolePreview.innerHTML = markdownPreview(role.content || "");
  }

  function renderRoles() {
    renderRoleOptions();
    renderRoleList();
    renderRoleEditor();
  }

  async function loadRoles() {
    state.roles = await api("/api/roles");
    if (!state.activeRoleName && state.roles.length > 0) {
      state.activeRoleName = state.roles[0].name;
    }
    if (state.activeRoleName && !state.roles.some((role) => role.name === state.activeRoleName)) {
      state.activeRoleName = state.roles[0]?.name || null;
    }
    renderRoles();
    if (state.settings) {
      getSettingsUi()?.renderModelRoles();
    }
    getWorkflowsUi()?.syncSelectedNodeRoleOptions();
  }

  function init() {
    newRoleButton.addEventListener("click", () => {
      state.activeRoleName = null;
      renderRoleList();
      renderRoleEditor();
      roleNameInput.focus();
    });

    roleContentInput.addEventListener("input", () => {
      rolePreview.innerHTML = markdownPreview(roleContentInput.value);
    });

    roleNameInput.addEventListener("input", () => {
      const normalized = roleNameInput.value.trim().replace(/[^A-Za-z0-9_-]+/g, "_").toUpperCase();
      if (!roleContentInput.value.trim()) {
        roleContentInput.value = `# ${normalized || "CUSTOM_ROLE"}\n\n## Mission\n- \n\n## Boundaries\n- \n`;
      }
      rolePreview.innerHTML = markdownPreview(roleContentInput.value);
    });

    saveRoleButton.addEventListener("click", async () => {
      const name = roleNameInput.value.trim();
      if (!name) {
        setStatus("Role name is missing.", true);
        return;
      }
      try {
        const saved = await api(`/api/roles/${encodeURIComponent(name)}`, {
          method: "PUT",
          body: JSON.stringify({ name, content: roleContentInput.value }),
        });
        state.activeRoleName = saved.name;
        await loadRoles();
        getSettingsUi()?.renderSettings();
        setStatus("Role saved");
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    deleteRoleButton.addEventListener("click", async () => {
      const role = activeRole();
      if (!role || role.default) return;
      try {
        await api(`/api/roles/${encodeURIComponent(role.name)}`, { method: "DELETE" });
        state.activeRoleName = null;
        await loadRoles();
        getSettingsUi()?.renderSettings();
        setStatus("Role deleted");
      } catch (error) {
        setStatus(error.message, true);
      }
    });
  }

  return {
    activeRole,
    init,
    loadRoles,
    renderRoleEditor,
    renderRoleList,
    renderRoleOptions,
    renderRoles,
    roleOptionsHtml,
  };
}
