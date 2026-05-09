const state = {
  chats: [],
  activeChatId: null,
  loading: false,
  settings: null,
  availableTools: [],
  availableModels: [],
  roles: [],
  activeRoleName: null,
  mistakes: null,
  mistakeEntries: [],
  activeMistakeId: null,
  suggestedMistakeSolution: null,
  activeMode: "chat",
  agenticTasks: [],
  activeTaskId: null,
  agenticRuns: [],
  pendingToolApproval: null,
  activeSettingsSection: "basis",
  streamingAssistant: false,
  streamDocked: false,
  streamDockEnabled: false,
};

const shell = document.querySelector(".shell");
const chatList = document.querySelector("#chat-list");
const messagesEl = document.querySelector("#messages");
const chatTitle = document.querySelector("#chat-title");
const form = document.querySelector("#message-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const newChatButton = document.querySelector("#new-chat");
const settingsToggle = document.querySelector("#settings-toggle");
const modeButtons = document.querySelectorAll(".mode-button");
const settingsClose = document.querySelector("#settings-close");
const settingsPanel = document.querySelector("#settings-panel");
const settingsForm = document.querySelector("#settings-form");
const settingsNavButtons = document.querySelectorAll(".settings-nav-button");
const settingsSections = document.querySelectorAll(".settings-section");
const ollamaBaseUrl = document.querySelector("#ollama-base-url");
const workspacePath = document.querySelector("#workspace-path");
const embeddingModel = document.querySelector("#embedding-model");
const requireToolConfirmation = document.querySelector("#require-tool-confirmation");
const alwaysAllowedTools = document.querySelector("#always-allowed-tools");
const emailProvider = document.querySelector("#email-provider");
const emailProviderStatus = document.querySelector("#email-provider-status");
const emailProviderAccount = document.querySelector("#email-provider-account");
const emailProviderHint = document.querySelector("#email-provider-hint");
const connectEmailProviderButton = document.querySelector("#connect-email-provider");
const disconnectEmailProviderButton = document.querySelector("#disconnect-email-provider");
const availableToolList = document.querySelector("#available-tool-list");
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
const saveMistakesButton = document.querySelector("#save-mistakes");
const analyzeMistakesButton = document.querySelector("#analyze-mistakes");
const mistakesContent = document.querySelector("#mistakes-content");
const mistakesPreview = document.querySelector("#mistakes-preview");
const mistakesModal = document.querySelector("#mistakes-modal");
const closeMistakesModalButton = document.querySelector("#close-mistakes-modal");
const mistakeEntryList = document.querySelector("#mistake-entry-list");
const mistakeEntryDetail = document.querySelector("#mistake-entry-detail");
const suggestMistakeSolutionButton = document.querySelector("#suggest-mistake-solution");
const acceptMistakeSolutionButton = document.querySelector("#accept-mistake-solution");
const mistakeSolution = document.querySelector("#mistake-solution");
const mistakeSolutionHint = document.querySelector("#mistake-solution-hint");
const agenticTaskList = document.querySelector("#agentic-task-list");
const newAgenticTaskButton = document.querySelector("#new-agentic-task");
const saveAgenticTaskButton = document.querySelector("#save-agentic-task");
const deleteAgenticTaskButton = document.querySelector("#delete-agentic-task");
const runAgenticTaskButton = document.querySelector("#run-agentic-task");
const agenticSchedulerStatus = document.querySelector("#agentic-scheduler-status");
const agenticRunList = document.querySelector("#agentic-run-list");
const agenticTaskTitle = document.querySelector("#agentic-task-title");
const agenticTaskSchedule = document.querySelector("#agentic-task-schedule");
const agenticTaskStatus = document.querySelector("#agentic-task-status");
const agenticTaskPrompt = document.querySelector("#agentic-task-prompt");
const toolApprovalModal = document.querySelector("#tool-approval-modal");
const toolApprovalName = document.querySelector("#tool-approval-name");
const toolApprovalDescription = document.querySelector("#tool-approval-description");
const toolApprovalArguments = document.querySelector("#tool-approval-arguments");
const approveToolCallButton = document.querySelector("#approve-tool-call");
const alwaysAllowToolCallButton = document.querySelector("#always-allow-tool-call");
const denyToolCallButton = document.querySelector("#deny-tool-call");

function setStatus(text, isError = false) {
  if (text && isError) {
    console.warn(text);
  }
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

function thumbIcon(direction) {
  const rotate = direction === "down" ? ' class="thumb-down"' : "";
  return `
    <svg${rotate} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 10v10h3l4-7h5a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2h-9.5a2 2 0 0 0-1.8 1.1L7 6" />
      <path d="M3 10V4h4v6H3Z" />
    </svg>
  `;
}

function renderChats() {
  chatList.innerHTML = "";
  for (const chat of state.chats) {
    const item = document.createElement("div");
    item.className = "chat-item-wrap";
    item.classList.toggle("active", chat.id === state.activeChatId);

    const button = document.createElement("button");
    button.className = "chat-item";
    button.type = "button";
    button.textContent = chat.title;
    button.addEventListener("click", () => selectChat(chat.id));

    const deleteButton = document.createElement("button");
    deleteButton.className = "chat-delete-button";
    deleteButton.type = "button";
    deleteButton.setAttribute("aria-label", `${chat.title} löschen`);
    deleteButton.innerHTML = `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M3 6h18" />
        <path d="M8 6V4h8v2" />
        <path d="M6 6l1 14h10l1-14" />
        <path d="M10 11v5" />
        <path d="M14 11v5" />
      </svg>
    `;
    deleteButton.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteChat(chat.id, chat.title).catch((error) => setStatus(error.message, true));
    });

    item.append(button, deleteButton);
    chatList.append(item);
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

function renderMistakes() {
  if (!state.mistakes) return;
  mistakesContent.value = state.mistakes.content || "";
  mistakesPreview.innerHTML = markdownPreview(state.mistakes.content || "");
}

function renderMistakeAnalyzeButton() {
  analyzeMistakesButton.disabled = state.mistakeEntries.length === 0;
}

function activeMistakeEntry() {
  return state.mistakeEntries.find((entry) => entry.id === state.activeMistakeId) || null;
}

function renderMistakeWizard() {
  renderMistakeAnalyzeButton();
  mistakeEntryList.innerHTML = "";
  if (state.mistakeEntries.length === 0) {
    mistakeEntryList.innerHTML = '<p class="settings-empty">Keine Fehler-Eintraege gefunden.</p>';
  }
  state.mistakeEntries.forEach((entry) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mistake-entry-item";
    button.classList.toggle("active", entry.id === state.activeMistakeId);
    button.innerHTML = `
      <span>${escapeHtml(entry.title || "Untitled mistake")}</span>
      <small>${escapeHtml(entry.timestamp || "ohne Timestamp")}</small>
    `;
    button.addEventListener("click", () => {
      state.activeMistakeId = entry.id;
      state.suggestedMistakeSolution = null;
      renderMistakeWizard();
    });
    mistakeEntryList.append(button);
  });

  const entry = activeMistakeEntry();
  mistakeEntryDetail.innerHTML = entry ? markdownPreview(entry.content) : "<p>Waehle einen Fehler aus.</p>";
  mistakeSolution.value = state.suggestedMistakeSolution?.instruction || "";
  mistakeSolutionHint.textContent = state.suggestedMistakeSolution?.rationale || "Waehle einen Fehler aus und lass dir eine Lösung vorschlagen.";
  suggestMistakeSolutionButton.disabled = !entry;
  acceptMistakeSolutionButton.disabled = !entry || !mistakeSolution.value.trim();
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
      <small>${escapeHtml(task.schedule)} · ${escapeHtml(task.status)} · next ${escapeHtml(task.next_run_at || "pending")}</small>
    `;
    button.addEventListener("click", () => {
      state.activeTaskId = task.id;
      renderAgenticTasks();
      renderAgenticTaskEditor();
      loadAgenticRuns(task.id).catch((error) => setStatus(error.message, true));
    });
    agenticTaskList.append(button);
  });
  renderAgenticTaskEditor();
}

function renderAgenticTaskEditor() {
  const task = activeAgenticTask();
  deleteAgenticTaskButton.disabled = !task;
  runAgenticTaskButton.disabled = !task;
  agenticTaskTitle.value = task?.title || "";
  agenticTaskSchedule.value = task?.schedule || "daily at 18:00";
  agenticTaskStatus.value = task?.status || "active";
  agenticTaskPrompt.value = task?.prompt || "";
}

function renderAgenticRuns() {
  agenticRunList.innerHTML = "";
  if (!state.activeTaskId) {
    agenticRunList.innerHTML = '<p class="settings-empty">Waehle einen Task aus.</p>';
    return;
  }
  if (state.agenticRuns.length === 0) {
    agenticRunList.innerHTML = '<p class="settings-empty">Noch keine Runs.</p>';
    return;
  }
  state.agenticRuns.forEach((run) => {
    const item = document.createElement("article");
    item.className = `agentic-run-item ${run.status}`;
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(run.status)}</strong>
        <small>${escapeHtml(run.started_at)} · attempt ${escapeHtml(run.attempt)}</small>
      </div>
      <p>${escapeHtml(run.summary || run.error || "Kein Ergebnistext.")}</p>
    `;
    agenticRunList.append(item);
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
  embeddingModel.value = state.settings.embedding_model || "";
  requireToolConfirmation.checked = state.settings.require_tool_confirmation !== false;
  emailProvider.value = state.settings.email_provider?.provider || "";
  renderEmailProvider();
  renderAlwaysAllowedTools();
  renderAvailableTools();
  renderModelRoles();
  renderSettingsSections();
}

function renderEmailProvider() {
  const provider = state.settings?.email_provider || {};
  const status = provider.status || "disconnected";
  const account = provider.account_email || "Kein Account verbunden.";
  emailProviderStatus.textContent = status;
  emailProviderStatus.className = `provider-state ${status}`;
  emailProviderAccount.textContent = account;
  emailProviderHint.textContent = provider.provider
    ? "OAuth ist vorbereitet. Der echte Browser-Flow braucht als nächsten Schritt Client-ID, Redirect URI und Token-Speicher."
    : "Wähle Google oder Microsoft und starte danach den Auth-Prozess.";
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
    alwaysAllowedTools.innerHTML = '<p class="settings-empty">Noch keine Funktion dauerhaft erlaubt.</p>';
    return;
  }
  tools.forEach((tool) => {
    const chip = document.createElement("span");
    chip.className = "tool-chip";
    chip.innerHTML = `
      <span>${escapeHtml(tool)}</span>
      <button type="button" aria-label="${escapeHtml(tool)} entfernen">x</button>
    `;
    chip.querySelector("button").addEventListener("click", () => {
      state.settings.always_allowed_tools = tools.filter((item) => item !== tool);
      renderAlwaysAllowedTools();
    });
    alwaysAllowedTools.append(chip);
  });
}

function renderAvailableTools() {
  availableToolList.innerHTML = "";
  if (!Array.isArray(state.availableTools) || state.availableTools.length === 0) {
    availableToolList.innerHTML = '<p class="settings-empty">Tool-Liste wird geladen...</p>';
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
        <span>${meta.alwaysAllowed ? "immer erlaubt" : meta.requiresConfirmation ? "fragt nach" : "frei"}</span>
      </div>
    `;
    availableToolList.append(item);
  });
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
    const feedback = message.feedback || "";
    const item = document.createElement("article");
    item.className = `message ${message.role} ${mode}`;
    const feedbackActions = message.role === "assistant"
      ? `
        <div class="message-feedback" aria-label="Antwort bewerten">
          <button class="feedback-button ${feedback === "up" ? "active" : ""}" type="button" data-message-id="${escapeHtml(message.id)}" data-rating="up" aria-label="Daumen hoch">${thumbIcon("up")}</button>
          <button class="feedback-button ${feedback === "down" ? "active" : ""}" type="button" data-message-id="${escapeHtml(message.id)}" data-rating="down" aria-label="Daumen runter">${thumbIcon("down")}</button>
        </div>
      `
      : "";
    item.innerHTML = `
      <div class="message-role"><span>[${escapeHtml(mode)}]</span> ${escapeHtml(message.role)}</div>
      <div class="bubble">${formatContent(message.content)}</div>
      ${feedbackActions}
    `;
    messagesEl.append(item);
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function isMessagesNearBottom() {
  return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 48;
}

function scrollMessagesToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

messagesEl.addEventListener("scroll", () => {
  if (state.streamingAssistant && state.streamDockEnabled) {
    state.streamDocked = isMessagesNearBottom();
  }
});

function appendMessage(message, extraClass = "", scrollToBottom = true) {
  const mode = message.mode || state.activeMode || "chat";
  const item = document.createElement("article");
  item.className = `message ${message.role} ${mode} ${extraClass}`.trim();
  item.dataset.messageId = message.id || "";
  item.innerHTML = `
    <div class="message-role"><span>[${escapeHtml(mode)}]</span> ${escapeHtml(message.role)}</div>
    <div class="bubble">${formatContent(message.content || "")}</div>
    ${message.role === "assistant" && message.id ? `
      <div class="message-feedback" aria-label="Antwort bewerten">
        <button class="feedback-button" type="button" data-message-id="${escapeHtml(message.id)}" data-rating="up" aria-label="Daumen hoch">${thumbIcon("up")}</button>
        <button class="feedback-button" type="button" data-message-id="${escapeHtml(message.id)}" data-rating="down" aria-label="Daumen runter">${thumbIcon("down")}</button>
      </div>
    ` : ""}
  `;
  if (messagesEl.querySelector(".empty")) {
    messagesEl.innerHTML = "";
  }
  messagesEl.append(item);
  if (scrollToBottom) {
    scrollMessagesToBottom();
  }
  return item;
}

function setMessageContent(element, content, followScroll = true) {
  const bubble = element?.querySelector(".bubble");
  if (!bubble) return;
  bubble.innerHTML = formatContent(content);
  if (followScroll) {
    scrollMessagesToBottom();
  }
}

function finalizeAssistantMessage(element, message) {
  if (!element || !message) return;
  element.dataset.messageId = message.id;
  element.classList.remove("streaming");
  if (!element.querySelector(".message-feedback")) {
    element.insertAdjacentHTML("beforeend", `
      <div class="message-feedback" aria-label="Antwort bewerten">
        <button class="feedback-button" type="button" data-message-id="${escapeHtml(message.id)}" data-rating="up" aria-label="Daumen hoch">${thumbIcon("up")}</button>
        <button class="feedback-button" type="button" data-message-id="${escapeHtml(message.id)}" data-rating="down" aria-label="Daumen runter">${thumbIcon("down")}</button>
      </div>
    `);
  }
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

async function loadTools() {
  const response = await api("/api/tools");
  state.availableTools = response.tools || [];
  renderAvailableTools();
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

async function loadMistakes() {
  state.mistakes = await api("/api/mistakes");
  state.mistakeEntries = await api("/api/mistakes/entries");
  if (state.activeMistakeId && !state.mistakeEntries.some((entry) => entry.id === state.activeMistakeId)) {
    state.activeMistakeId = null;
  }
  renderMistakes();
  renderMistakeWizard();
}

async function loadAgenticTasks() {
  state.agenticTasks = await api("/api/agentic-tasks");
  if (state.activeTaskId && !state.agenticTasks.some((task) => task.id === state.activeTaskId)) {
    state.activeTaskId = null;
  }
  renderAgenticTasks();
  if (state.activeTaskId) {
    await loadAgenticRuns(state.activeTaskId);
  } else {
    state.agenticRuns = [];
    renderAgenticRuns();
  }
}

async function loadAgenticRuns(taskId) {
  if (!taskId) {
    state.agenticRuns = [];
    renderAgenticRuns();
    return;
  }
  state.agenticRuns = await api(`/api/agentic-tasks/${taskId}/runs`);
  renderAgenticRuns();
}

async function loadSchedulerStatus() {
  const status = await api("/api/agentic-tasks/scheduler/status");
  agenticSchedulerStatus.textContent = status.running
    ? `Scheduler aktiv · ${status.active_runs.length} aktive Run(s)`
    : "Scheduler pausiert";
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

async function deleteChat(chatId, title) {
  const confirmed = window.confirm(`Chat "${title}" wirklich löschen?`);
  if (!confirmed) return;

  await api(`/api/chats/${chatId}`, { method: "DELETE" });
  if (state.activeChatId === chatId) {
    state.activeChatId = null;
  }
  await loadChats();
  if (state.activeChatId) {
    await selectChat(state.activeChatId);
  } else if (state.chats.length > 0) {
    await selectChat(state.chats[0].id);
  } else {
    chatTitle.textContent = "Kein Chat ausgewählt";
    renderMessages([]);
  }
  setStatus("Chat gelöscht");
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
  const streamStartedAt = performance.now();
  let tokenChunks = 0;
  let streamedContent = "";
  let assistantEl = null;
  let pendingRender = false;
  let finalStatus = "";

  const scheduleRender = () => {
    if (pendingRender) return;
    pendingRender = true;
    requestAnimationFrame(() => {
      pendingRender = false;
      setMessageContent(assistantEl, streamedContent, state.streamDocked && isMessagesNearBottom());
      state.streamDockEnabled = true;
    });
  };

  try {
    const response = await fetch(`/api/chats/${state.activeChatId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, mode: state.activeMode }),
    });
    if (!response.ok || !response.body) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() || "";

      for (const frame of frames) {
        const line = frame.split("\n").find((item) => item.startsWith("data: "));
        if (!line) continue;
        const event = JSON.parse(line.slice(6));
        if (event.type === "user_message") {
          appendMessage(event.message);
          input.value = "";
          assistantEl = appendMessage({ role: "assistant", mode: state.activeMode, content: "" }, "streaming");
        } else if (event.type === "token") {
          if (!state.streamingAssistant) {
            state.streamingAssistant = true;
            state.streamDocked = false;
            state.streamDockEnabled = false;
          }
          streamedContent += event.content || "";
          tokenChunks += 1;
          const elapsed = Math.max((performance.now() - streamStartedAt) / 1000, 0.1);
          setStatus(`${state.activeMode} streamt · ${(tokenChunks / elapsed).toFixed(1)} tok/s`);
          scheduleRender();
        } else if (event.type === "assistant_message") {
          finalizeAssistantMessage(assistantEl, event.message);
        } else if (event.type === "done") {
          const exact = event.stats?.tokens_per_second;
          finalStatus = exact ? `fertig · ${exact} tok/s` : "bereit";
          setStatus(finalStatus);
        } else if (event.type === "error") {
          throw new Error(event.message || "Stream fehlgeschlagen");
        }
      }
    }

    await loadChats();
    renderChats();
    if (state.activeMode === "agentic") {
      await loadAgenticTasks();
    }
  } catch (error) {
    setStatus(error.message, true);
    if (assistantEl && !streamedContent) {
      assistantEl.remove();
    }
  } finally {
    state.streamingAssistant = false;
    state.streamDocked = false;
    state.streamDockEnabled = false;
    setLoading(false);
    if (finalStatus) setStatus(finalStatus);
  }
}

async function sendMessageFeedback(messageId, rating) {
  try {
    await api(`/api/chats/messages/${messageId}/feedback`, {
      method: "POST",
      body: JSON.stringify({ rating }),
    });
    if (state.activeChatId) {
      const messages = await api(`/api/chats/${state.activeChatId}/messages`);
      renderMessages(messages);
    }
    setStatus(rating === "down" ? "Feedback gespeichert, Mistakes werden aktualisiert" : "Feedback gespeichert");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function callTool(name, argumentsPayload = {}) {
  const response = await api("/api/tools/call", {
    method: "POST",
    body: JSON.stringify({ name, arguments: argumentsPayload }),
  });
  if (!response.approval_required) return response;
  const approval = await requestToolApproval(response);
  if (!approval.approved) {
    throw new Error("Tool-Aufruf abgebrochen.");
  }
  const approvedResponse = await api("/api/tools/call", {
    method: "POST",
    body: JSON.stringify({
      name,
      arguments: argumentsPayload,
      approved: true,
      always_allow: approval.alwaysAllow,
    }),
  });
  if (approval.alwaysAllow) {
    await loadSettings();
  }
  return approvedResponse;
}

function requestToolApproval(request) {
  return new Promise((resolve) => {
    state.pendingToolApproval = resolve;
    const definition = request.tool_definition || {};
    toolApprovalName.textContent = request.tool || definition.name || "Unbekanntes Tool";
    toolApprovalDescription.textContent = definition.description || request.message || "Das Modell möchte diese Funktion ausführen.";
    toolApprovalArguments.textContent = JSON.stringify(request.arguments || {}, null, 2);
    toolApprovalModal.classList.add("open");
    toolApprovalModal.setAttribute("aria-hidden", "false");
  });
}

function finishToolApproval(result) {
  const resolve = state.pendingToolApproval;
  state.pendingToolApproval = null;
  toolApprovalModal.classList.remove("open");
  toolApprovalModal.setAttribute("aria-hidden", "true");
  if (resolve) resolve(result);
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

settingsNavButtons.forEach((button) => {
  button.addEventListener("click", () => {
    state.activeSettingsSection = button.dataset.settingsSection || "basis";
    renderSettingsSections();
  });
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
    setStatus(response.message || "Provider vorbereitet");
  } catch (error) {
    setStatus(error.message, true);
  }
});

disconnectEmailProviderButton.addEventListener("click", async () => {
  try {
    state.settings = await api("/api/settings/email-provider/disconnect", { method: "POST" });
    renderSettings();
    setStatus("E-Mail Provider getrennt");
  } catch (error) {
    setStatus(error.message, true);
  }
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

mistakesContent.addEventListener("input", () => {
  mistakesPreview.innerHTML = markdownPreview(mistakesContent.value);
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

saveMistakesButton.addEventListener("click", async () => {
  try {
    state.mistakes = await api("/api/mistakes", {
      method: "PUT",
      body: JSON.stringify({ content: mistakesContent.value }),
    });
    state.mistakeEntries = await api("/api/mistakes/entries");
    renderMistakes();
    renderMistakeWizard();
    setStatus("Mistakes gespeichert");
  } catch (error) {
    setStatus(error.message, true);
  }
});

analyzeMistakesButton.addEventListener("click", async () => {
  await loadMistakes();
  if (!state.activeMistakeId && state.mistakeEntries.length > 0) {
    state.activeMistakeId = state.mistakeEntries[0].id;
  }
  mistakesModal.classList.add("open");
  mistakesModal.setAttribute("aria-hidden", "false");
  renderMistakeWizard();
});

closeMistakesModalButton.addEventListener("click", () => {
  mistakesModal.classList.remove("open");
  mistakesModal.setAttribute("aria-hidden", "true");
});

approveToolCallButton.addEventListener("click", () => {
  finishToolApproval({ approved: true, alwaysAllow: false });
});

alwaysAllowToolCallButton.addEventListener("click", () => {
  finishToolApproval({ approved: true, alwaysAllow: true });
});

denyToolCallButton.addEventListener("click", () => {
  finishToolApproval({ approved: false, alwaysAllow: false });
});

suggestMistakeSolutionButton.addEventListener("click", async () => {
  const entry = activeMistakeEntry();
  if (!entry) return;
  suggestMistakeSolutionButton.disabled = true;
  mistakeSolutionHint.textContent = "Lösung wird destilliert...";
  try {
    const solution = await api(`/api/mistakes/entries/${entry.id}/suggest-solution`, { method: "POST" });
    state.suggestedMistakeSolution = solution;
    mistakeSolution.value = solution.instruction || "";
    mistakeSolutionHint.textContent = solution.rationale || "Lösungsvorschlag bereit.";
    acceptMistakeSolutionButton.disabled = !mistakeSolution.value.trim();
  } catch (error) {
    mistakeSolutionHint.textContent = error.message;
  } finally {
    suggestMistakeSolutionButton.disabled = false;
  }
});

mistakeSolution.addEventListener("input", () => {
  acceptMistakeSolutionButton.disabled = !activeMistakeEntry() || !mistakeSolution.value.trim();
});

acceptMistakeSolutionButton.addEventListener("click", async () => {
  const entry = activeMistakeEntry();
  if (!entry) return;
  try {
    const payload = {
      title: state.suggestedMistakeSolution?.title || entry.title || "Reviewed mistake",
      instruction: mistakeSolution.value.trim(),
      rationale: state.suggestedMistakeSolution?.rationale || "",
    };
    await api(`/api/mistakes/entries/${entry.id}/accept-solution`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setStatus("Lösung in MEMORY.md übernommen");
    mistakeSolutionHint.textContent = "In MEMORY.md übernommen.";
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
    state.agenticRuns = [];
    await loadAgenticTasks();
    setStatus("Agentic Task geloescht");
  } catch (error) {
    setStatus(error.message, true);
  }
});

runAgenticTaskButton.addEventListener("click", async () => {
  const task = activeAgenticTask();
  if (!task) return;
  runAgenticTaskButton.disabled = true;
  setStatus("Agentic Task laeuft...");
  try {
    await api(`/api/agentic-tasks/${task.id}/run-now`, { method: "POST" });
    await loadAgenticTasks();
    await loadAgenticRuns(task.id);
    await loadSchedulerStatus();
    setStatus("Agentic Run abgeschlossen");
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    runAgenticTaskButton.disabled = !activeAgenticTask();
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
    require_tool_confirmation: requireToolConfirmation.checked,
    always_allowed_tools: Array.isArray(state.settings?.always_allowed_tools) ? state.settings.always_allowed_tools : [],
    email_provider: {
      ...(state.settings.email_provider || {}),
      provider: emailProvider.value,
    },
    default_model: assistantRole.model,
    model_roles: modelRoles,
  };
  try {
    state.settings = await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    await loadTools();
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

messagesEl.addEventListener("click", (event) => {
  const button = event.target.closest(".feedback-button");
  if (!button) return;
  sendMessageFeedback(button.dataset.messageId, button.dataset.rating);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

renderModeSwitch();

Promise.all([loadRoles(), loadMistakes(), loadAgenticTasks(), loadSchedulerStatus(), loadSettings(), loadTools(), loadChats()])
  .then(() => {
    if (state.activeChatId) return selectChat(state.activeChatId);
    renderMessages([]);
    return null;
  })
  .then(() => setStatus("bereit"))
  .catch((error) => setStatus(error.message, true));
