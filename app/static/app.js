const state = {
  chats: [],
  activeChatId: null,
  loading: false,
  settings: null,
  availableModels: [],
  roles: [],
  activeRoleName: null,
  activeMode: "chat",
  agenticTasks: [],
  activeTaskId: null,
};

const shell = document.querySelector(".shell");
const chatList = document.querySelector("#chat-list");
const messagesEl = document.querySelector("#messages");
const chatTitle = document.querySelector("#chat-title");
const statusEl = document.querySelector("#status");
const form = document.querySelector("#message-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const newChatButton = document.querySelector("#new-chat");
const settingsToggle = document.querySelector("#settings-toggle");
const modeButtons = document.querySelectorAll(".mode-button");
const settingsClose = document.querySelector("#settings-close");
const settingsPanel = document.querySelector("#settings-panel");
const settingsForm = document.querySelector("#settings-form");
const ollamaBaseUrl = document.querySelector("#ollama-base-url");
const workspacePath = document.querySelector("#workspace-path");
const embeddingModel = document.querySelector("#embedding-model");
const modelRoleList = document.querySelector("#model-role-list");
const roleNameOptions = document.querySelector("#role-name-options");
const addModelRoleButton = document.querySelector("#add-model-role");
const refreshModelsButton = document.querySelector("#refresh-models");
const modelsHint = document.querySelector("#models-hint");
const rolePromptList = document.querySelector("#role-prompt-list");
const newRoleButton = document.querySelector("#new-role");
const saveRoleButton = document.querySelector("#save-role");
const deleteRoleButton = document.querySelector("#delete-role");
const roleNameInput = document.querySelector("#role-name");
const roleContentInput = document.querySelector("#role-content");
const rolePreview = document.querySelector("#role-preview");
const agenticTaskList = document.querySelector("#agentic-task-list");
const newAgenticTaskButton = document.querySelector("#new-agentic-task");
const saveAgenticTaskButton = document.querySelector("#save-agentic-task");
const deleteAgenticTaskButton = document.querySelector("#delete-agentic-task");
const agenticTaskTitle = document.querySelector("#agentic-task-title");
const agenticTaskSchedule = document.querySelector("#agentic-task-schedule");
const agenticTaskStatus = document.querySelector("#agentic-task-status");
const agenticTaskPrompt = document.querySelector("#agentic-task-prompt");

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatContent(content) {
  const escaped = escapeHtml(content);
  return escaped.replace(/```([\s\S]*?)```/g, (_match, code) => `<pre><code>${code.trim()}</code></pre>`);
}

function renderChats() {
  chatList.innerHTML = "";
  for (const chat of state.chats) {
    const button = document.createElement("button");
    button.className = "chat-item";
    button.classList.toggle("active", chat.id === state.activeChatId);
    button.type = "button";
    button.textContent = chat.title;
    button.addEventListener("click", () => selectChat(chat.id));
    chatList.append(button);
  }
}

function renderModeSwitch() {
  modeButtons.forEach((button) => {
    const active = button.dataset.mode === state.activeMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
  input.placeholder = {
    chat: "Nachricht schreiben...",
    code: "Code-Frage oder Projektauftrag schreiben...",
    agentic: "Agentic Aufgabe oder wiederkehrenden Task beschreiben...",
  }[state.activeMode];
}

function modelOptionsHtml(selectedModel) {
  const options = state.availableModels
    .map((model) => `<option value="${escapeHtml(model)}"${model === selectedModel ? " selected" : ""}>${escapeHtml(model)}</option>`)
    .join("");
  const selectedExists = state.availableModels.includes(selectedModel);
  const customOption = selectedModel && !selectedExists
    ? `<option value="${escapeHtml(selectedModel)}" selected>${escapeHtml(selectedModel)}</option>`
    : "";
  return `${customOption}${options}`;
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
    ];
  }
  return modelRoles.map((item) => ({
    role: item.role || "",
    model: item.model || "",
  }));
}

function roleOptionsHtml() {
  return state.roles
    .map((role) => `<option value="${escapeHtml(role.name)}">${escapeHtml(role.filename)}</option>`)
    .join("");
}

function renderModelRoles() {
  const roles = normalizeModelRoles(state.settings?.model_roles);
  modelRoleList.innerHTML = "";
  roles.forEach((roleConfig, index) => {
    const row = document.createElement("div");
    row.className = "model-role-row";
    row.dataset.index = String(index);
    row.innerHTML = `
      <label class="model-role-field">
        <span class="model-role-label">Rolle</span>
        <input class="role-input" type="text" value="${escapeHtml(roleConfig.role)}" placeholder="ASSISTANT" list="role-name-options" />
      </label>
      <label class="model-role-field">
        <span class="model-role-label">Modell</span>
        <select class="model-select">
          ${modelOptionsHtml(roleConfig.model)}
          <option value="">Manuell eintragen...</option>
        </select>
        <input class="model-input" type="text" value="${escapeHtml(roleConfig.model)}" placeholder="llama3.1:8b" />
      </label>
      <button class="remove-role" type="button" aria-label="Rolle entfernen">-</button>
    `;

    const select = row.querySelector(".model-select");
    const modelInput = row.querySelector(".model-input");
    select.addEventListener("change", () => {
      if (select.value) {
        modelInput.value = select.value;
      }
    });
    row.querySelector(".remove-role").addEventListener("click", () => {
      row.remove();
    });
    modelRoleList.append(row);
  });
}

function activeRole() {
  return state.roles.find((role) => role.name === state.activeRoleName) || null;
}

function renderRoleOptions() {
  roleNameOptions.innerHTML = roleOptionsHtml();
}

function markdownPreview(content) {
  let inCode = false;
  const html = String(content ?? "")
    .split("\n")
    .map((line) => {
      if (line.trim().startsWith("```")) {
        inCode = !inCode;
        return inCode ? "<pre><code>" : "</code></pre>";
      }
      if (inCode) return `${escapeHtml(line)}\n`;
      if (line.startsWith("### ")) return `<h4>${escapeHtml(line.slice(4))}</h4>`;
      if (line.startsWith("## ")) return `<h3>${escapeHtml(line.slice(3))}</h3>`;
      if (line.startsWith("# ")) return `<h2>${escapeHtml(line.slice(2))}</h2>`;
      if (line.startsWith("- ")) return `<p class="preview-list-item">${escapeHtml(line.slice(2))}</p>`;
      if (!line.trim()) return "<br />";
      return `<p>${escapeHtml(line)}</p>`;
    })
    .join("");
  return inCode ? `${html}</code></pre>` : html;
}

function renderRoleList() {
  rolePromptList.innerHTML = "";
  state.roles.forEach((role) => {
    const button = document.createElement("button");
    button.className = "role-prompt-item";
    button.classList.toggle("active", role.name === state.activeRoleName);
    button.type = "button";
    button.innerHTML = `
      <span>${escapeHtml(role.name)}</span>
      ${role.default ? '<small>Default</small>' : "<small>Custom</small>"}
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

function activeAgenticTask() {
  return state.agenticTasks.find((task) => task.id === state.activeTaskId) || null;
}

function renderAgenticTasks() {
  agenticTaskList.innerHTML = "";
  if (state.agenticTasks.length === 0) {
    agenticTaskList.innerHTML = '<p class="settings-empty">Noch keine Agentic Tasks.</p>';
  }
  state.agenticTasks.forEach((task) => {
    const button = document.createElement("button");
    button.className = "agentic-task-item";
    button.classList.toggle("active", task.id === state.activeTaskId);
    button.type = "button";
    button.innerHTML = `
      <span>${escapeHtml(task.title)}</span>
      <small>${escapeHtml(task.schedule)} · ${escapeHtml(task.status)}</small>
    `;
    button.addEventListener("click", () => {
      state.activeTaskId = task.id;
      renderAgenticTasks();
      renderAgenticTaskEditor();
    });
    agenticTaskList.append(button);
  });
  renderAgenticTaskEditor();
}

function renderAgenticTaskEditor() {
  const task = activeAgenticTask();
  deleteAgenticTaskButton.disabled = !task;
  agenticTaskTitle.value = task?.title || "";
  agenticTaskSchedule.value = task?.schedule || "daily at 18:00";
  agenticTaskStatus.value = task?.status || "active";
  agenticTaskPrompt.value = task?.prompt || "";
}

function collectModelRoles() {
  return [...modelRoleList.querySelectorAll(".model-role-row")]
    .map((row) => ({
      role: row.querySelector(".role-input").value.trim(),
      model: row.querySelector(".model-input").value.trim(),
    }))
    .filter((item) => item.role && item.model);
}

function renderSettings() {
  if (!state.settings) return;
  ollamaBaseUrl.value = state.settings.ollama_base_url || "";
  workspacePath.value = state.settings.workspace_path || "";
  embeddingModel.value = state.settings.embedding_model || "";
  renderModelRoles();
}

function openSettings() {
  shell.classList.add("settings-open");
  settingsPanel.setAttribute("aria-hidden", "false");
  renderSettings();
}

function closeSettings() {
  shell.classList.remove("settings-open");
  settingsPanel.setAttribute("aria-hidden", "true");
}

function renderMessages(messages) {
  messagesEl.innerHTML = "";
  if (!state.activeChatId) {
    messagesEl.innerHTML = '<p class="empty">Lege links einen Chat an und sende deine erste Nachricht.</p>';
    return;
  }
  if (messages.length === 0) {
    messagesEl.innerHTML = '<p class="empty">Dieser Chat ist noch leer.</p>';
    return;
  }
  for (const message of messages) {
    const mode = message.mode || "chat";
    const item = document.createElement("article");
    item.className = `message ${message.role} ${mode}`;
    item.innerHTML = `
      <div class="message-role"><span>[${escapeHtml(mode)}]</span> ${escapeHtml(message.role)}</div>
      <div class="bubble">${formatContent(message.content)}</div>
    `;
    messagesEl.append(item);
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

async function loadChats() {
  state.chats = await api("/api/chats");
  if (!state.activeChatId && state.chats.length > 0) {
    state.activeChatId = state.chats[0].id;
  }
  renderChats();
}

async function loadSettings() {
  state.settings = await api("/api/settings");
  renderSettings();
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
}

async function loadAgenticTasks() {
  state.agenticTasks = await api("/api/agentic-tasks");
  if (state.activeTaskId && !state.agenticTasks.some((task) => task.id === state.activeTaskId)) {
    state.activeTaskId = null;
  }
  renderAgenticTasks();
}

async function refreshModels() {
  modelsHint.textContent = "lade Modelle...";
  try {
    state.availableModels = await api("/api/settings/models");
    modelsHint.textContent = state.availableModels.length
      ? `${state.availableModels.length} Modell(e) aus Ollama geladen.`
      : "Ollama hat keine Modelle gemeldet.";
    renderModelRoles();
  } catch (error) {
    modelsHint.textContent = error.message;
  }
}

async function selectChat(chatId) {
  state.activeChatId = chatId;
  const chat = state.chats.find((item) => item.id === chatId);
  chatTitle.textContent = chat ? chat.title : "Chat";
  renderChats();
  const messages = await api(`/api/chats/${chatId}/messages`);
  renderMessages(messages);
}

async function createChat() {
  setStatus("erstelle Chat...");
  const chat = await api("/api/chats", {
    method: "POST",
    body: JSON.stringify({ title: null }),
  });
  state.activeChatId = chat.id;
  await loadChats();
  await selectChat(chat.id);
  input.focus();
  setStatus("bereit");
}

function setLoading(loading) {
  state.loading = loading;
  input.disabled = loading;
  sendButton.disabled = loading;
  setStatus(loading ? `${state.activeMode} arbeitet...` : "bereit");
}

async function sendMessage(content) {
  if (!state.activeChatId) {
    await createChat();
  }
  setLoading(true);
  try {
    await api(`/api/chats/${state.activeChatId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content, mode: state.activeMode }),
    });
    await loadChats();
    await selectChat(state.activeChatId);
    if (state.activeMode === "agentic") {
      await loadAgenticTasks();
    }
    input.value = "";
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    setLoading(false);
  }
}

newChatButton.addEventListener("click", () => {
  createChat().catch((error) => setStatus(error.message, true));
});

settingsToggle.addEventListener("click", () => {
  openSettings();
});

modeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    state.activeMode = button.dataset.mode || "chat";
    renderModeSwitch();
    setStatus(`${state.activeMode} bereit`);
  });
});

settingsClose.addEventListener("click", () => {
  closeSettings();
});

addModelRoleButton.addEventListener("click", () => {
  const roles = collectModelRoles();
  roles.push({ role: "", model: "" });
  state.settings = { ...state.settings, model_roles: roles };
  renderModelRoles();
  const rows = modelRoleList.querySelectorAll(".model-role-row");
  rows[rows.length - 1]?.querySelector(".role-input")?.focus();
});

refreshModelsButton.addEventListener("click", () => {
  refreshModels().catch((error) => {
    modelsHint.textContent = error.message;
  });
});

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
    setStatus("Rollenname fehlt.", true);
    return;
  }
  try {
    const saved = await api(`/api/roles/${encodeURIComponent(name)}`, {
      method: "PUT",
      body: JSON.stringify({ name, content: roleContentInput.value }),
    });
    state.activeRoleName = saved.name;
    await loadRoles();
    renderSettings();
    setStatus("Rolle gespeichert");
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
    renderSettings();
    setStatus("Rolle geloescht");
  } catch (error) {
    setStatus(error.message, true);
  }
});

newAgenticTaskButton.addEventListener("click", () => {
  state.activeTaskId = null;
  renderAgenticTasks();
  agenticTaskTitle.focus();
});

saveAgenticTaskButton.addEventListener("click", async () => {
  const payload = {
    title: agenticTaskTitle.value.trim(),
    schedule: agenticTaskSchedule.value.trim(),
    status: agenticTaskStatus.value,
    prompt: agenticTaskPrompt.value.trim(),
  };
  if (!payload.title || !payload.schedule || !payload.prompt) {
    setStatus("Titel, Schedule und Aufgabe sind erforderlich.", true);
    return;
  }
  try {
    const task = activeAgenticTask();
    const saved = await api(task ? `/api/agentic-tasks/${task.id}` : "/api/agentic-tasks", {
      method: task ? "PUT" : "POST",
      body: JSON.stringify(payload),
    });
    state.activeTaskId = saved.id;
    await loadAgenticTasks();
    setStatus("Agentic Task gespeichert");
  } catch (error) {
    setStatus(error.message, true);
  }
});

deleteAgenticTaskButton.addEventListener("click", async () => {
  const task = activeAgenticTask();
  if (!task) return;
  try {
    await api(`/api/agentic-tasks/${task.id}`, { method: "DELETE" });
    state.activeTaskId = null;
    await loadAgenticTasks();
    setStatus("Agentic Task geloescht");
  } catch (error) {
    setStatus(error.message, true);
  }
});

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const modelRoles = collectModelRoles();
  if (modelRoles.length === 0) {
    setStatus("Mindestens eine Rolle mit Modell ist erforderlich.", true);
    return;
  }
  const assistantRole = modelRoles.find((item) => item.role.toLowerCase() === "assistant") || modelRoles[0];
  const payload = {
    ...state.settings,
    ollama_base_url: ollamaBaseUrl.value.trim(),
    workspace_path: workspacePath.value.trim(),
    embedding_model: embeddingModel.value.trim(),
    default_model: assistantRole.model,
    model_roles: modelRoles,
  };
  try {
    state.settings = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    renderSettings();
    setStatus("Einstellungen gespeichert");
  } catch (error) {
    setStatus(error.message, true);
  }
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const content = input.value.trim();
  if (!content || state.loading) return;
  sendMessage(content);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

renderModeSwitch();

Promise.all([loadRoles(), loadAgenticTasks(), loadSettings(), loadChats()])
  .then(() => {
    if (state.activeChatId) return selectChat(state.activeChatId);
    renderMessages([]);
    return null;
  })
  .then(() => setStatus("bereit"))
  .catch((error) => setStatus(error.message, true));
