const state = {
  chats: [],
  activeChatId: null,
  loading: false,
  settings: null,
  availableModels: [],
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
const settingsClose = document.querySelector("#settings-close");
const settingsPanel = document.querySelector("#settings-panel");
const settingsForm = document.querySelector("#settings-form");
const ollamaBaseUrl = document.querySelector("#ollama-base-url");
const workspacePath = document.querySelector("#workspace-path");
const modelRoleList = document.querySelector("#model-role-list");
const addModelRoleButton = document.querySelector("#add-model-role");
const refreshModelsButton = document.querySelector("#refresh-models");
const modelsHint = document.querySelector("#models-hint");

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

function escapeHtml(value) {
  return value
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
    ];
  }
  return modelRoles.map((item) => ({
    role: item.role || "",
    model: item.model || "",
  }));
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
        <input class="role-input" type="text" value="${escapeHtml(roleConfig.role)}" placeholder="assistant" />
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
    const item = document.createElement("article");
    item.className = `message ${message.role}`;
    item.innerHTML = `
      <div class="message-role">${message.role}</div>
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
  setStatus(loading ? "Ollama antwortet..." : "bereit");
}

async function sendMessage(content) {
  if (!state.activeChatId) {
    await createChat();
  }
  setLoading(true);
  try {
    await api(`/api/chats/${state.activeChatId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    await loadChats();
    await selectChat(state.activeChatId);
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

Promise.all([loadSettings(), loadChats()])
  .then(() => {
    if (state.activeChatId) return selectChat(state.activeChatId);
    renderMessages([]);
    return null;
  })
  .then(() => setStatus("bereit"))
  .catch((error) => setStatus(error.message, true));
