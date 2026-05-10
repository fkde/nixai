const state = {
  chats: [],
  activeChatId: null,
  loading: false,
  settings: null,
  availableTools: [],
  workflowPresets: [],
  availableModels: [],
  modelCatalog: [],
  modelsLoaded: false,
  modelsLoading: false,
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
  autoScrollLocked: true,
  toastTimer: null,
  titleWatchers: new Map(),
};

const shell = document.querySelector(".shell");
const chatList = document.querySelector("#chat-list");
const messagesEl = document.querySelector("#messages");
const chatTitle = document.querySelector("#chat-title");
const chatWorkspace = document.querySelector("#chat-workspace");
const form = document.querySelector("#message-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const composerPlusButton = document.querySelector("#composer-plus-button");
const composerPlusMenu = document.querySelector("#composer-plus-menu");
const addWorkspaceButton = document.querySelector("#add-workspace");
const newChatButton = document.querySelector("#new-chat");
const settingsToggle = document.querySelector("#settings-toggle");
const modeSwitch = document.querySelector(".mode-switch");
const modeButtons = document.querySelectorAll(".mode-button");
const settingsClose = document.querySelector("#settings-close");
const settingsPanel = document.querySelector("#settings-panel");
const settingsForm = document.querySelector("#settings-form");
const settingsNavButtons = document.querySelectorAll(".settings-nav-button");
const settingsSections = document.querySelectorAll(".settings-section");
const userName = document.querySelector("#user-name");
const ollamaBaseUrl = document.querySelector("#ollama-base-url");
const workspacePath = document.querySelector("#workspace-path");
const embeddingModel = document.querySelector("#embedding-model");
const requireToolConfirmation = document.querySelector("#require-tool-confirmation");
const alwaysAllowedTools = document.querySelector("#always-allowed-tools");
const workflowChat = document.querySelector("#workflow-chat");
const workflowCode = document.querySelector("#workflow-code");
const workflowAgentic = document.querySelector("#workflow-agentic");
const workflowPresetList = document.querySelector("#workflow-preset-list");
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
const modeOrder = ["chat", "code", "agentic"];
const embeddingModelMarkers = ["embed", "embedding", "nomic-bert", "sentence-transformer", "bge-", "all-minilm", "e5-", "gte-"];
const toastRegion = document.createElement("div");
toastRegion.className = "toast-region";
toastRegion.setAttribute("aria-live", "polite");
toastRegion.setAttribute("aria-atomic", "true");
document.body.append(toastRegion);

async function initDesktopChrome() {
  const api = window.pywebview?.api;
  if (!api?.desktop_info) {
    window.addEventListener("pywebviewready", initDesktopChrome, { once: true });
    return;
  }
  try {
    const info = await api.desktop_info();
    const platform = String(info.platform || "desktop").replace(/[^a-z0-9_-]/gi, "-").toLowerCase();
    document.body.classList.add("desktop-shell", `desktop-${platform}`);
    document.body.classList.toggle("native-chrome", Boolean(info.native_chrome));
    document.body.classList.toggle("native-traffic-lights", Boolean(info.native_traffic_lights));
  } catch (error) {
    console.warn(error);
  }
}

function setStatus(text, isError = false) {
  if (text && isError) {
    console.warn(text);
  }
  if (!text) return;
  if (isError) {
    showToast(text, "error");
    return;
  }
  if (/\b(saved|deleted|added|prepared|connected|disconnected|finished|set)\b/i.test(text)) {
    showToast(text, "success");
  }
}

function showToast(message, kind = "success") {
  window.clearTimeout(state.toastTimer);
  toastRegion.innerHTML = `
    <div class="toast ${kind}">
      <span>${escapeHtml(kind === "error" ? "Error" : "Done")}</span>
      <strong>${escapeHtml(message)}</strong>
    </div>
  `;
  state.toastTimer = window.setTimeout(() => {
    toastRegion.innerHTML = "";
  }, kind === "error" ? 5200 : 2600);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatInlineMarkdown(value) {
  const codeSpans = [];
  let html = escapeHtml(value).replace(/`([^`]+)`/g, (_match, code) => {
    const token = `@@CODE_SPAN_${codeSpans.length}@@`;
    codeSpans.push(`<code>${code}</code>`);
    return token;
  });
  html = html
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  codeSpans.forEach((code, index) => {
    html = html.replaceAll(`@@CODE_SPAN_${index}@@`, code);
  });
  return html;
}

function formatContent(content) {
  const lines = String(content ?? "").replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let paragraph = [];
  let list = null;
  let codeBlock = null;

  const flushParagraph = () => {
    const text = paragraph.join(" ").trim();
    if (text) {
      blocks.push(`<p>${formatInlineMarkdown(text)}</p>`);
    }
    paragraph = [];
  };

  const closeList = () => {
    if (!list) return;
    blocks.push(`<${list.type}>${list.items.map((item) => `<li>${item}</li>`).join("")}</${list.type}>`);
    list = null;
  };

  const addListItem = (type, text) => {
    flushParagraph();
    if (!list || list.type !== type) {
      closeList();
      list = { type, items: [] };
    }
    list.items.push(formatInlineMarkdown(text.trim()));
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (codeBlock) {
      if (trimmed.startsWith("```")) {
        blocks.push(`<pre><code>${escapeHtml(codeBlock.join("\n"))}</code></pre>`);
        codeBlock = null;
      } else {
        codeBlock.push(line);
      }
      continue;
    }

    if (trimmed.startsWith("```")) {
      flushParagraph();
      closeList();
      codeBlock = [];
      continue;
    }

    if (!trimmed) {
      flushParagraph();
      closeList();
      continue;
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      closeList();
      const level = Math.min(heading[1].length + 2, 5);
      blocks.push(`<h${level}>${formatInlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    const ordered = trimmed.match(/^\d+[.)]\s+(.+)$/);
    if (ordered) {
      addListItem("ol", ordered[1]);
      continue;
    }

    const unordered = trimmed.match(/^[-*+]\s+(.+)$/);
    if (unordered) {
      addListItem("ul", unordered[1]);
      continue;
    }

    if (list && list.items.length > 0) {
      list.items[list.items.length - 1] += ` ${formatInlineMarkdown(trimmed)}`;
      continue;
    }

    paragraph.push(trimmed);
  }

  flushParagraph();
  closeList();
  if (codeBlock) {
    blocks.push(`<pre><code>${escapeHtml(codeBlock.join("\n"))}</code></pre>`);
  }
  return blocks.join("");
}

function thinkingIndicatorHtml() {
  return `
    <div class="thinking-notice" aria-live="polite">
      <span class="thinking-dot" aria-hidden="true"></span>
      <span>Thinking...</span>
    </div>
  `;
}

function firstName() {
  return (state.settings?.user_name || "").trim().split(/\s+/)[0] || "";
}

function emptyGreeting() {
  const name = firstName();
  const suffix = name ? `, ${escapeHtml(name)}` : "";
  const variants = [
    {
      title: `Nixorious is awake${suffix}.`,
      text: "Local context is ready. Start with a thought, a question, or a task.",
    },
    {
      title: `Ready at the local console${suffix}.`,
      text: "Choose Chat, Code, or Agentic and NixAI will use the right workflow.",
    },
    {
      title: `Empty chat. Full control${suffix}.`,
      text: "Nothing has happened here yet. Send a message and we will change that.",
    },
    {
      title: `This is NixAI${suffix}.`,
      text: "Local, focused, and one prompt away from becoming useful.",
    },
  ];
  const seed = state.activeChatId
    ? [...state.activeChatId].reduce((sum, char) => sum + char.charCodeAt(0), 0)
    : new Date().getDate();
  return variants[seed % variants.length];
}

function emptyChatHtml(kind = "chat") {
  const greeting = emptyGreeting();
  const helper = kind === "none"
    ? "Create a new chat on the left to get started."
    : "";
  return `
    <section class="empty">
      <span>NixAI is waiting</span>
      <h3>${greeting.title}</h3>
      <p>${greeting.text}</p>
      ${helper ? `<small>${helper}</small>` : ""}
    </section>
  `;
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

function uiIcon(name) {
  const paths = {
    trash: `
      <path d="M4 6h16" />
      <path d="M9 6V4.8A1.8 1.8 0 0 1 10.8 3h2.4A1.8 1.8 0 0 1 15 4.8V6" />
      <path d="M7 6l.8 14h8.4L17 6" />
      <path d="M10 10.5v5" />
      <path d="M14 10.5v5" />
    `,
    minus: '<path d="M6 12h12" />',
    x: `
      <path d="M6 6l12 12" />
      <path d="M18 6 6 18" />
    `,
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || ""}</svg>`;
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
    button.textContent = displayChatTitle(chat);
    button.addEventListener("click", () => selectChat(chat.id));

    const deleteButton = document.createElement("button");
    deleteButton.className = "chat-delete-button";
    deleteButton.type = "button";
    deleteButton.setAttribute("aria-label", `Delete ${displayChatTitle(chat)}`);
    deleteButton.innerHTML = uiIcon("trash");
    deleteButton.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteChat(chat.id, chat.title).catch((error) => setStatus(error.message, true));
    });

    item.append(button, deleteButton);
    chatList.append(item);
  }
}

function activeChat() {
  return state.chats.find((item) => item.id === state.activeChatId) || null;
}

function workspaceLabel(chat) {
  const path = chat?.workspace_path?.trim();
  if (path) return path;
  return "Settings fallback";
}

function displayChatTitle(chat) {
  const title = typeof chat === "string" ? chat : chat?.title;
  return title === "Neuer Chat" ? "New Chat" : title || "Chat";
}

function isDefaultChatTitle(title) {
  return title === "Neuer Chat" || title === "New Chat";
}

function mergeChat(updatedChat) {
  if (!updatedChat?.id) return;
  const exists = state.chats.some((chat) => chat.id === updatedChat.id);
  state.chats = exists
    ? state.chats.map((chat) => chat.id === updatedChat.id ? updatedChat : chat)
    : [updatedChat, ...state.chats];
  renderChats();
  if (state.activeChatId === updatedChat.id) {
    chatTitle.textContent = displayChatTitle(updatedChat);
    chatWorkspace.textContent = workspaceLabel(updatedChat);
  }
}

function stopWatchingChatTitle(chatId) {
  const timer = state.titleWatchers.get(chatId);
  if (timer) {
    window.clearInterval(timer);
  }
  state.titleWatchers.delete(chatId);
}

function watchChatTitle(chatId) {
  const chat = state.chats.find((item) => item.id === chatId);
  if (!chat || !isDefaultChatTitle(chat.title)) return;
  stopWatchingChatTitle(chatId);

  let attempts = 0;
  const timer = window.setInterval(async () => {
    attempts += 1;
    try {
      const updatedChat = await api(`/api/chats/${chatId}`);
      mergeChat(updatedChat);
      if (!isDefaultChatTitle(updatedChat.title) || attempts >= 50) {
        stopWatchingChatTitle(chatId);
      }
    } catch (_error) {
      stopWatchingChatTitle(chatId);
    }
  }, 1200);
  state.titleWatchers.set(chatId, timer);
}

function renderModeSwitch() {
  const activeIndex = Math.max(0, modeOrder.indexOf(state.activeMode));
  modeSwitch?.style.setProperty("--mode-index", String(activeIndex));
  modeButtons.forEach((button) => {
    const active = button.dataset.mode === state.activeMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
  input.placeholder = {
    chat: "Write a message...",
    code: "Ask a code question or describe a project task...",
    agentic: "Describe an agentic task or recurring run...",
  }[state.activeMode];
}

function animateModeChange(direction) {
  if (!direction || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  messagesEl.classList.remove("mode-shift-forward", "mode-shift-back");
  void messagesEl.offsetWidth;
  messagesEl.classList.add(direction > 0 ? "mode-shift-forward" : "mode-shift-back");
}

function changeMode(nextMode) {
  if (!nextMode || nextMode === state.activeMode) return;
  const previousIndex = modeOrder.indexOf(state.activeMode);
  const nextIndex = modeOrder.indexOf(nextMode);
  state.activeMode = nextMode;
  renderModeSwitch();
  animateModeChange(nextIndex - previousIndex);
  if (state.activeChatId) {
    loadActiveModeMessages(nextMode).catch((error) => setStatus(error.message, true));
  } else {
    renderMessages([]);
  }
  setStatus(`${state.activeMode} ready`);
}

async function loadActiveModeMessages(mode = state.activeMode) {
  if (!state.activeChatId) {
    renderMessages([]);
    return;
  }
  const chatId = state.activeChatId;
  const messages = await api(`/api/chats/${chatId}/messages?mode=${encodeURIComponent(mode)}`);
  if (chatId !== state.activeChatId || mode !== state.activeMode) return;
  renderMessages(messages);
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

function roleSelectOptionsHtml(selectedRole) {
  const options = state.roles
    .map((role) => `<option value="${escapeHtml(role.name)}"${role.name.toLowerCase() === selectedRole.toLowerCase() ? " selected" : ""}>${escapeHtml(role.name)}</option>`)
    .join("");
  const selectedExists = state.roles.some((role) => role.name.toLowerCase() === selectedRole.toLowerCase());
  const customOption = selectedRole && !selectedExists
    ? `<option value="${escapeHtml(selectedRole)}" selected>${escapeHtml(selectedRole)}</option>`
    : "";
  const emptySelected = selectedRole ? "" : " selected";
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
    });
    modelRoleList.append(row);
  });
}

function workflowPresetsForMode(mode) {
  return state.workflowPresets.filter((workflow) => workflow.mode === mode);
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
  workflowChat.innerHTML = workflowOptionsHtml("chat", selected.chat || "chat_direct");
  workflowCode.innerHTML = workflowOptionsHtml("code", selected.code || "code_direct_worker");
  workflowAgentic.innerHTML = workflowOptionsHtml("agentic", selected.agentic || "agentic_direct_orchestrator");
  renderWorkflowPresetList();
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
    const nodes = Array.isArray(workflow.nodes) ? workflow.nodes : [];
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(workflow.name)}</strong>
        <small>${escapeHtml(workflow.mode)} · ${escapeHtml(workflow.execution)} · ${escapeHtml(workflow.max_iterations || 1)} iteration(s)</small>
      </div>
      <p>${escapeHtml(workflow.description || "")}</p>
      <div class="workflow-node-list">
        ${nodes.map((node) => `<span>${escapeHtml(node.title || node.role || node.type || node.id)}</span>`).join("")}
      </div>
    `;
    workflowPresetList.append(item);
  });
}

function renderEmbeddingModel() {
  if (!embeddingModel) return;
  const selectedModel = isEmbeddingModelName(state.settings?.embedding_model) ? state.settings.embedding_model : "";
  embeddingModel.innerHTML = modelOptionsHtml(selectedModel, "No embedding model", embeddingModels());
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
    mistakeEntryList.innerHTML = '<p class="settings-empty">No mistake entries found.</p>';
  }
  state.mistakeEntries.forEach((entry) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mistake-entry-item";
    button.classList.toggle("active", entry.id === state.activeMistakeId);
    button.innerHTML = `
      <span>${escapeHtml(entry.title || "Untitled mistake")}</span>
      <small>${escapeHtml(entry.timestamp || "no timestamp")}</small>
    `;
    button.addEventListener("click", () => {
      state.activeMistakeId = entry.id;
      state.suggestedMistakeSolution = null;
      renderMistakeWizard();
    });
    mistakeEntryList.append(button);
  });

  const entry = activeMistakeEntry();
  mistakeEntryDetail.innerHTML = entry ? markdownPreview(entry.content) : "<p>Select a mistake.</p>";
  mistakeSolution.value = state.suggestedMistakeSolution?.instruction || "";
  mistakeSolutionHint.textContent = state.suggestedMistakeSolution?.rationale || "Select a mistake and ask for a fix suggestion.";
  suggestMistakeSolutionButton.disabled = !entry;
  acceptMistakeSolutionButton.disabled = !entry || !mistakeSolution.value.trim();
}

function activeAgenticTask() {
  return state.agenticTasks.find((task) => task.id === state.activeTaskId) || null;
}

function renderAgenticTasks() {
  agenticTaskList.innerHTML = "";
  if (state.agenticTasks.length === 0) {
    agenticTaskList.innerHTML = '<p class="settings-empty">No agentic tasks yet.</p>';
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
    agenticRunList.innerHTML = '<p class="settings-empty">Select a task.</p>';
    return;
  }
  if (state.agenticRuns.length === 0) {
    agenticRunList.innerHTML = '<p class="settings-empty">No runs yet.</p>';
    return;
  }
  state.agenticRuns.forEach((run) => {
    const item = document.createElement("article");
    item.className = `agentic-run-item ${run.status}`;
    const summary = runSummaryParts(run.summary || run.error || "No result text.");
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(run.status)}</strong>
        <small>${escapeHtml(run.started_at)} · attempt ${escapeHtml(run.attempt)}</small>
      </div>
      <section class="run-summary">${formatContent(summary.main)}</section>
      ${summary.details ? `
        <details class="run-details">
          <summary>Review details</summary>
          <div>${formatContent(summary.details)}</div>
        </details>
      ` : ""}
    `;
    agenticRunList.append(item);
  });
}

function runSummaryParts(value) {
  const clean = String(value || "")
    .replace(/\*{3,}/g, "\n\n")
    .replace(/#{1,6}\s*Reviewer Findings/gi, "### Review")
    .replace(/#{1,6}\s*Recommendations/gi, "### Recommendations")
    .trim();
  const detailsStart = clean.search(/(^|\n)\s*(#{2,6}\s*(Review|Recommendations)|\*\*Correctness:\*\*|\*\*Safety:\*\*)/i);
  if (detailsStart <= 0) {
    return { main: clean, details: "" };
  }
  return {
    main: clean.slice(0, detailsStart).trim(),
    details: clean.slice(detailsStart).trim(),
  };
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
  renderWorkflowSettings();
  renderModelRoles();
  renderSettingsSections();
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
  renderSettings();
  ensureModelsLoaded().catch((error) => {
    modelsHint.textContent = error.message;
  });
}

function closeSettings() {
  shell.classList.remove("settings-open");
  settingsPanel.setAttribute("aria-hidden", "true");
}

function renderMessages(messages) {
  messagesEl.innerHTML = "";
  if (!state.activeChatId) {
    messagesEl.innerHTML = emptyChatHtml("none");
    return;
  }
  if (messages.length === 0) {
    messagesEl.innerHTML = emptyChatHtml("chat");
    return;
  }
  for (const message of messages) {
    const feedback = message.feedback || "";
    const item = document.createElement("article");
    item.className = `message ${message.role} ${message.mode || "chat"}`;
    const feedbackActions = message.role === "assistant"
      ? `
        <div class="message-feedback" aria-label="Rate response">
          <button class="feedback-button ${feedback === "up" ? "active" : ""}" type="button" data-message-id="${escapeHtml(message.id)}" data-rating="up" aria-label="Thumbs up">${thumbIcon("up")}</button>
          <button class="feedback-button ${feedback === "down" ? "active" : ""}" type="button" data-message-id="${escapeHtml(message.id)}" data-rating="down" aria-label="Thumbs down">${thumbIcon("down")}</button>
        </div>
      `
      : "";
    item.innerHTML = `
      <div class="message-role">${escapeHtml(message.role)}</div>
      <div class="bubble">${formatContent(message.content)}</div>
      ${feedbackActions}
    `;
    messagesEl.append(item);
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
  state.autoScrollLocked = true;
}

function isMessagesNearBottom() {
  return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 48;
}

function scrollMessagesToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
  if (!state.streamingAssistant) {
    state.autoScrollLocked = true;
  }
}

messagesEl.addEventListener("scroll", () => {
  if (state.streamingAssistant) return;
  state.autoScrollLocked = isMessagesNearBottom();
});

function appendMessage(message, extraClass = "", scrollToBottom = state.autoScrollLocked) {
  const mode = message.mode || state.activeMode || "chat";
  const item = document.createElement("article");
  const isThinking = message.role === "assistant" && extraClass.includes("streaming") && !message.content;
  item.className = `message ${message.role} ${mode} ${extraClass}`.trim();
  if (isThinking) item.classList.add("thinking");
  item.dataset.messageId = message.id || "";
  item.innerHTML = `
    <div class="message-role">${escapeHtml(message.role)}</div>
    ${isThinking ? thinkingIndicatorHtml() : ""}
    <div class="bubble">${isThinking ? "" : formatContent(message.content || "")}</div>
    ${message.role === "assistant" && message.id ? `
      <div class="message-feedback" aria-label="Rate response">
        <button class="feedback-button" type="button" data-message-id="${escapeHtml(message.id)}" data-rating="up" aria-label="Thumbs up">${thumbIcon("up")}</button>
        <button class="feedback-button" type="button" data-message-id="${escapeHtml(message.id)}" data-rating="down" aria-label="Thumbs down">${thumbIcon("down")}</button>
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
  element.classList.toggle("thinking", !content);
  if (content) {
    element.querySelector(".thinking-notice")?.remove();
  }
  bubble.innerHTML = formatContent(content);
  if (followScroll) {
    scrollMessagesToBottom();
  }
}

function finalizeAssistantMessage(element, message) {
  if (!element || !message) return;
  element.dataset.messageId = message.id;
  element.classList.remove("streaming", "thinking");
  element.querySelector(".thinking-notice")?.remove();
  if (!element.querySelector(".message-feedback")) {
    element.insertAdjacentHTML("beforeend", `
      <div class="message-feedback" aria-label="Rate response">
        <button class="feedback-button" type="button" data-message-id="${escapeHtml(message.id)}" data-rating="up" aria-label="Thumbs up">${thumbIcon("up")}</button>
        <button class="feedback-button" type="button" data-message-id="${escapeHtml(message.id)}" data-rating="down" aria-label="Thumbs down">${thumbIcon("down")}</button>
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
  const chat = activeChat();
  if (chat) {
    chatTitle.textContent = displayChatTitle(chat);
    chatWorkspace.textContent = workspaceLabel(chat);
  }
}

async function loadSettings() {
  state.settings = await api("/api/settings");
  renderSettings();
  if (shell.classList.contains("settings-open")) {
    ensureModelsLoaded().catch((error) => {
      modelsHint.textContent = error.message;
    });
  }
}

async function loadWorkflowPresets() {
  const response = await api("/api/settings/workflows");
  state.workflowPresets = response.workflows || [];
  if (response.selected && state.settings) {
    state.settings.workflow_presets = response.selected;
  }
  renderWorkflowSettings();
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
  if (state.settings) {
    renderModelRoles();
  }
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
    ? `Scheduler active · ${status.active_runs.length} active run(s)`
    : "Scheduler paused";
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

async function selectChat(chatId) {
  state.activeChatId = chatId;
  const chat = activeChat();
  chatTitle.textContent = chat ? displayChatTitle(chat) : "Chat";
  chatWorkspace.textContent = workspaceLabel(chat);
  renderChats();
  await loadActiveModeMessages();
}

async function saveChatWorkspace(workspace) {
  const chat = activeChat();
  if (!chat) return;
  const nextWorkspace = workspace.trim();
  if (nextWorkspace === (chat.workspace_path || "")) return;
  const updated = await api(`/api/chats/${chat.id}`, {
    method: "PUT",
    body: JSON.stringify({ workspace_path: nextWorkspace }),
  });
  mergeChat(updated);
}

function closeComposerMenu() {
  composerPlusMenu.hidden = true;
  composerPlusButton.setAttribute("aria-expanded", "false");
}

function toggleComposerMenu() {
  const open = composerPlusMenu.hidden;
  composerPlusMenu.hidden = !open;
  composerPlusButton.setAttribute("aria-expanded", open ? "true" : "false");
}

async function requestWorkspacePath() {
  if (!state.activeChatId) {
    await createChat();
  }
  const chat = activeChat();
  const current = chat?.workspace_path || "";
  let workspace = "";
  if (window.pywebview?.api?.choose_workspace) {
    workspace = await window.pywebview.api.choose_workspace();
    if (!workspace) return;
  } else {
    workspace = window.prompt("Workspace path for this chat", current);
  }
  if (workspace === null) return;
  await saveChatWorkspace(workspace);
  setStatus(workspace.trim() ? "Workspace set" : "Workspace fallback active");
}

async function createChat() {
  setStatus("Creating chat...");
  const chat = await api("/api/chats", {
    method: "POST",
    body: JSON.stringify({ title: null }),
  });
  state.activeChatId = chat.id;
  await loadChats();
  await selectChat(chat.id);
  input.focus();
  setStatus("Ready");
}

async function deleteChat(chatId, title) {
  const confirmed = window.confirm(`Delete chat "${displayChatTitle(title)}"?`);
  if (!confirmed) return;

  stopWatchingChatTitle(chatId);
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
    chatTitle.textContent = "No Chat Selected";
    chatWorkspace.textContent = workspaceLabel(null);
    renderMessages([]);
  }
  setStatus("Chat deleted");
}

function setLoading(loading) {
  state.loading = loading;
  input.disabled = loading;
  sendButton.disabled = loading;
  setStatus(loading ? `${state.activeMode} working...` : "Ready");
}

async function sendMessage(content) {
  if (!state.activeChatId) {
    await createChat();
  }
  const chatId = state.activeChatId;
  setLoading(true);
  const streamStartedAt = performance.now();
  let tokenChunks = 0;
  let streamedContent = "";
  const workflowProgress = [];
  let assistantEl = null;
  let pendingRender = false;
  let finalStatus = "";

  const renderWorkflowProgress = () => {
    if (!assistantEl || streamedContent) return;
    const recent = workflowProgress.slice(-12);
    setMessageContent(assistantEl, `### Workflow\n${recent.map((item) => `- ${item}`).join("\n")}`, false);
  };

  const scheduleRender = () => {
    if (pendingRender) return;
    pendingRender = true;
    requestAnimationFrame(() => {
      pendingRender = false;
      setMessageContent(assistantEl, streamedContent, false);
    });
  };

  try {
    const response = await fetch(`/api/chats/${chatId}/messages/stream`, {
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
          state.streamingAssistant = true;
          state.autoScrollLocked = false;
        } else if (event.type === "status") {
          setStatus(event.message || `${state.activeMode} working...`);
        } else if (event.type === "workflow_status") {
          const label = event.message || "Workflow step running...";
          workflowProgress.push(label);
          setStatus(label);
          renderWorkflowProgress();
        } else if (event.type === "token") {
          if (!state.streamingAssistant) {
            state.streamingAssistant = true;
            state.autoScrollLocked = false;
          }
          streamedContent += event.content || "";
          tokenChunks += 1;
          const elapsed = Math.max((performance.now() - streamStartedAt) / 1000, 0.1);
          setStatus(`${state.activeMode} streaming · ${(tokenChunks / elapsed).toFixed(1)} tok/s`);
          scheduleRender();
        } else if (event.type === "assistant_message") {
          finalizeAssistantMessage(assistantEl, event.message);
        } else if (event.type === "done") {
          const exact = event.stats?.tokens_per_second;
          finalStatus = exact ? `Done · ${exact} tok/s` : "Ready";
          setStatus(finalStatus);
        } else if (event.type === "error") {
          throw new Error(event.message || "Stream failed");
        }
      }
    }

    await loadChats();
    renderChats();
    watchChatTitle(chatId);
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
      await loadActiveModeMessages();
    }
    setStatus(rating === "down" ? "Feedback saved, mistakes are being updated" : "Feedback saved");
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
    throw new Error("Tool call cancelled.");
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
    toolApprovalName.textContent = request.tool || definition.name || "Unknown tool";
    toolApprovalDescription.textContent = definition.description || request.message || "The model wants to run this function.";
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

composerPlusButton.addEventListener("click", (event) => {
  event.stopPropagation();
  toggleComposerMenu();
});

addWorkspaceButton.addEventListener("click", () => {
  closeComposerMenu();
  requestWorkspacePath().catch((error) => setStatus(error.message, true));
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".composer-plus")) {
    closeComposerMenu();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeComposerMenu();
  }
});

modeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    changeMode(button.dataset.mode || "chat");
  });
});

messagesEl.addEventListener("animationend", () => {
  messagesEl.classList.remove("mode-shift-forward", "mode-shift-back");
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
    renderSettings();
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
    renderSettings();
    setStatus("Role deleted");
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
    setStatus("Mistakes saved");
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
  mistakeSolutionHint.textContent = "Distilling fix...";
  try {
    const solution = await api(`/api/mistakes/entries/${entry.id}/suggest-solution`, { method: "POST" });
    state.suggestedMistakeSolution = solution;
    mistakeSolution.value = solution.instruction || "";
    mistakeSolutionHint.textContent = solution.rationale || "Fix suggestion ready.";
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
    setStatus("Fix added to MEMORY.md");
    mistakeSolutionHint.textContent = "Added to MEMORY.md.";
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
    setStatus("Title, schedule, and task are required.", true);
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
    setStatus("Agentic task saved");
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
    setStatus("Agentic task deleted");
  } catch (error) {
    setStatus(error.message, true);
  }
});

runAgenticTaskButton.addEventListener("click", async () => {
  const task = activeAgenticTask();
  if (!task) return;
  runAgenticTaskButton.disabled = true;
  setStatus("Agentic task running...");
  try {
    await api(`/api/agentic-tasks/${task.id}/run-now`, { method: "POST" });
    await loadAgenticTasks();
    await loadAgenticRuns(task.id);
    await loadSchedulerStatus();
    setStatus("Agentic run finished");
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
    setStatus("At least one role with a model is required.", true);
    return;
  }
  const assistantRole = modelRoles.find((item) => item.role.toLowerCase() === "assistant") || modelRoles[0];
  const payload = {
    ...state.settings,
    user_name: userName.value.trim(),
    ollama_base_url: ollamaBaseUrl.value.trim(),
    workspace_path: workspacePath.value.trim(),
    embedding_model: embeddingModel.value.trim(),
    require_tool_confirmation: requireToolConfirmation.checked,
    always_allowed_tools: Array.isArray(state.settings?.always_allowed_tools) ? state.settings.always_allowed_tools : [],
    workflow_presets: {
      chat: workflowChat?.value || "chat_direct",
      code: workflowCode?.value || "code_direct_worker",
      agentic: workflowAgentic?.value || "agentic_direct_orchestrator",
    },
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
    if (messagesEl.querySelector(".empty")) {
      renderMessages([]);
    }
    setStatus("Settings saved");
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
initDesktopChrome();

Promise.all([
  loadRoles(),
  ensureModelsLoaded(),
  loadMistakes(),
  loadAgenticTasks(),
  loadSchedulerStatus(),
  loadSettings(),
  loadWorkflowPresets(),
  loadTools(),
  loadChats(),
])
  .then(() => {
    if (state.activeChatId) return selectChat(state.activeChatId);
    renderMessages([]);
    return null;
  })
  .then(() => setStatus("Ready"))
  .catch((error) => setStatus(error.message, true));
