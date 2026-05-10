import {
  dirtyStorageKey,
  hasDirtyTracker,
  registerDirtyTracker,
  safeLocalStorageGet,
} from "./dirty-tracker.js";
import { parseFrameEvent } from "./stream.js";
import { cloneWorkflowDraft, dedupeList, parseCsvList } from "./workflow-editor.js";

const state = {
  chats: [],
  activeChatId: null,
  loading: false,
  settings: null,
  availableTools: [],
  workflowPresets: [],
  customWorkflowIds: [],
  workflowEditorDraft: null,
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
  activeStream: null,
  messageRequestInFlight: false,
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
const effortSwitch = document.querySelector(".effort-switch");
const effortButtons = document.querySelectorAll(".effort-button");
const settingsClose = document.querySelector("#settings-close");
const settingsPanel = document.querySelector("#settings-panel");
const settingsForm = document.querySelector("#settings-form");
const settingsFooter = document.querySelector(".settings-footer");
const saveSettingsButton = document.querySelector("#save-settings");
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
const workflowEditorTarget = document.querySelector("#workflow-editor-target");
const workflowEditorNew = document.querySelector("#workflow-editor-new");
const workflowEditorDelete = document.querySelector("#workflow-editor-delete");
const workflowEditorSave = document.querySelector("#workflow-editor-save");
const workflowEditorId = document.querySelector("#workflow-editor-id");
const workflowEditorName = document.querySelector("#workflow-editor-name");
const workflowEditorDescription = document.querySelector("#workflow-editor-description");
const workflowEditorExecution = document.querySelector("#workflow-editor-execution");
const workflowEditorMaxIterations = document.querySelector("#workflow-editor-max-iterations");
const workflowEditorModeChat = document.querySelector("#workflow-editor-mode-chat");
const workflowEditorModeCode = document.querySelector("#workflow-editor-mode-code");
const workflowEditorModeAgentic = document.querySelector("#workflow-editor-mode-agentic");
const workflowEditorAssignChat = document.querySelector("#workflow-editor-assign-chat");
const workflowEditorAssignCode = document.querySelector("#workflow-editor-assign-code");
const workflowEditorAssignAgentic = document.querySelector("#workflow-editor-assign-agentic");
const workflowEditorSaveAssign = document.querySelector("#workflow-editor-save-assign");
const workflowEditorAddNode = document.querySelector("#workflow-editor-add-node");
const workflowEditorNodeList = document.querySelector("#workflow-editor-node-list");
const workflowGraphPreview = document.querySelector("#workflow-graph-preview");
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
const effortOrder = ["minimum", "medium", "high", "max"];
const runtimeStatusHistoryLimit = 16;
const runtimeStatusStoreLimit = 64;
// Throttle token DOM writes enough to keep PyWebView smooth while still feeling live.
const streamRenderIntervalMs = 120;
const embeddingModelMarkers = ["embed", "embedding", "nomic-bert", "sentence-transformer", "bge-", "all-minilm", "e5-", "gte-"];
const toastRegion = document.createElement("div");
toastRegion.className = "toast-region";
toastRegion.setAttribute("aria-live", "polite");
toastRegion.setAttribute("aria-atomic", "true");
document.body.append(toastRegion);

async function initDesktopChrome() {
  const addDesktopClasses = (info = null) => {
    if (!window.pywebview && !info) return false;
    const rawPlatform = String(info?.platform || window.pywebview?.platform || navigator.platform || "desktop")
      .replace(/[^a-z0-9_-]/gi, "-")
      .toLowerCase();
    const isMac = /darwin|mac|cocoa/.test(rawPlatform);
    document.body.classList.add("desktop-shell");
    document.body.classList.add(`desktop-${rawPlatform}`);
    if (isMac) {
      document.body.classList.add("desktop-macos");
    }
    document.body.classList.toggle("native-chrome", Boolean(info?.native_chrome ?? isMac));
    document.body.classList.toggle("native-traffic-lights", Boolean(info?.native_traffic_lights ?? isMac));
    return true;
  };

  const api = window.pywebview?.api;
  if (!api?.desktop_info) {
    const applied = addDesktopClasses();
    if (!applied) {
      window.addEventListener("pywebviewready", initDesktopChrome, { once: true });
    } else {
      stabilizeMessagesBottomScroll();
    }
    if (window.pywebview) {
      window.setTimeout(() => {
        if (!document.body.classList.contains("desktop-shell")) {
          initDesktopChrome();
        }
      }, 180);
    }
    return;
  }
  try {
    const info = await api.desktop_info();
    addDesktopClasses(info);
    stabilizeMessagesBottomScroll();
  } catch (error) {
    console.warn(error);
    if (addDesktopClasses()) {
      stabilizeMessagesBottomScroll();
    }
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

let settingsDirtyTracker = null;

function initGenericDirtyTracking() {
  const trackedForms = [...document.querySelectorAll("form[data-dirty-track]")];
  trackedForms.forEach((trackedForm) => {
    if (trackedForm === settingsForm) return;
    if (hasDirtyTracker(trackedForm)) return;
    const tracker = registerDirtyTracker(trackedForm);
    if (!tracker) return;
    tracker.captureBaseline();
    tracker.restoreDraftIfAny();
  });
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

function plainTextContent(content) {
  return escapeHtml(String(content ?? "")).replace(/\n/g, "<br>");
}

function shouldRenderMarkdown(message) {
  return message?.role === "assistant";
}

function normalizeAgenticRoute(path) {
  const clean = String(path || "").trim().toLowerCase();
  if (clean === "workflow") return "workflow";
  if (clean === "direct") return "direct";
  return "";
}

function applyAgenticRouteBadge(element, routePath, routeReason = "") {
  if (!element) return;
  const path = normalizeAgenticRoute(routePath);
  if (!path) return;
  const role = element.querySelector(".message-role");
  if (!role) return;
  let badge = role.querySelector(".message-route-badge");
  if (!badge) {
    badge = document.createElement("span");
    badge.className = "message-route-badge";
    role.append(badge);
  }
  badge.dataset.path = path;
  badge.textContent = `path: ${path}`;
  const reason = String(routeReason || "").trim();
  if (reason) {
    badge.title = reason;
  } else {
    badge.removeAttribute("title");
  }
}

function thinkingIndicatorHtml() {
  return `
    <div class="thinking-notice" aria-live="polite">
      <span class="thinking-dot" aria-hidden="true"></span>
      <span>Thinking...</span>
    </div>
  `;
}

function streamMatchesView(stream = state.activeStream) {
  return Boolean(stream && stream.chatId === state.activeChatId && stream.mode === state.activeMode);
}

function defaultStreamStatusLabel(stream = state.activeStream) {
  if (!stream) return "";
  return `${stream.mode || state.activeMode} working...`;
}

function streamStatusItems(stream = state.activeStream, limit = runtimeStatusHistoryLimit) {
  if (!stream) return [];
  return normalizeStatusItems(stream.statusItems, defaultStreamStatusLabel(stream), limit);
}

function streamStatusLabel(stream = state.activeStream) {
  const items = streamStatusItems(stream, runtimeStatusStoreLimit);
  return items[items.length - 1] || "";
}

function runtimeStatusHtml(items, isOpen = false) {
  const history = normalizeStatusItems(items, "Working...", runtimeStatusHistoryLimit);
  const current = history[history.length - 1] || "Working...";
  return `
    <details class="runtime-status" ${isOpen ? "open" : ""}>
      <summary>
        <span class="thinking-dot" aria-hidden="true"></span>
        <span class="runtime-status-current">${escapeHtml(current)}</span>
        <span class="runtime-status-count">${history.length} state${history.length === 1 ? "" : "s"}</span>
      </summary>
      <ol class="runtime-status-history">
        ${history.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
      </ol>
    </details>
  `;
}

function normalizeStatusItems(items, fallback = "", limit = runtimeStatusHistoryLimit) {
  const rawItems = Array.isArray(items) ? items : [];
  const history = [];
  const seen = new Set();
  for (const item of rawItems) {
    const label = String(item || "").trim();
    if (!label || history[history.length - 1] === label) continue;
    if (seen.has(label)) {
      const existingIndex = history.indexOf(label);
      if (existingIndex >= 0) {
        history.splice(existingIndex, 1);
      }
    } else {
      seen.add(label);
    }
    history.push(label);
  }
  const cleanFallback = String(fallback || "").trim();
  if (history.length === 0 && cleanFallback) {
    history.push(cleanFallback);
  }
  return history.slice(-limit);
}

function firstName() {
  return (state.settings?.user_name || "").trim().split(/\s+/)[0] || "";
}

function emptyGreeting() {
  const name = firstName();
  const suffix = name ? `, ${escapeHtml(name)}` : "";
  const variants = [
    {
      title: `Ready when you are${suffix}.`,
      text: "Start a conversation, inspect a project, or hand off a task.",
    },
    {
      title: `Local runtime online${suffix}.`,
      text: "Ask naturally. NixAI will use the selected mode for the next step.",
    },
    {
      title: `What should we work on${suffix}?`,
      text: "Send a message to begin.",
    },
    {
      title: `NixAI is ready${suffix}.`,
      text: "Use Chat for conversation, Code for project context, or Agentic for multi-step work.",
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
    button.innerHTML = `<span class="chat-item-title">${escapeHtml(displayChatTitle(chat))}</span>`;
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
  const fallbackPath = state.settings?.workspace_path?.trim();
  return fallbackPath || "No workspace configured";
}

function syncHeaderWorkspace(chat = activeChat()) {
  const label = workspaceLabel(chat);
  chatWorkspace.textContent = label;
  chatWorkspace.title = label;
  chatWorkspace.classList.toggle("is-empty", label === "No workspace configured");
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
    syncHeaderWorkspace(updatedChat);
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

function currentEffort() {
  const effort = state.settings?.effort || "medium";
  return effortOrder.includes(effort) ? effort : "medium";
}

function renderEffortSwitch() {
  const effort = currentEffort();
  const activeIndex = Math.max(0, effortOrder.indexOf(effort));
  effortSwitch?.style.setProperty("--effort-index", String(activeIndex));
  effortButtons.forEach((button) => {
    const active = button.dataset.effort === effort;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
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

function animateModeChange(direction) {
  if (!direction || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  messagesEl.classList.remove("mode-shift-forward", "mode-shift-back");
  void messagesEl.offsetWidth;
  messagesEl.classList.add(direction > 0 ? "mode-shift-forward" : "mode-shift-back");
}

function animateViewShift() {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  messagesEl.classList.remove("view-shift");
  void messagesEl.offsetWidth;
  messagesEl.classList.add("view-shift");
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
  setStatus(streamMatchesView() ? streamStatusLabel() : `${state.activeMode} ready`);
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

function normalizeWorkflowNodes(workflow) {
  const nodes = (Array.isArray(workflow?.nodes) ? workflow.nodes : []).map((node, index) => {
    const inputValues = Array.isArray(node.input)
      ? node.input.map((item) => String(item).trim()).filter(Boolean)
      : String(node.input || "").trim()
        ? [String(node.input || "").trim()]
        : [];
    return {
      id: String(node.id || `node_${index + 1}`),
      type: String(node.type || "role"),
      role: String(node.role || ""),
      title: String(node.title || ""),
      input: inputValues,
      output: String(node.output || ""),
      max_parallel: Math.min(8, Math.max(1, Number(node.max_parallel || 1))),
      max_items: Math.min(12, Math.max(1, Number(node.max_items || 4))),
      expects_json: Boolean(node.expects_json),
      receive_from: dedupeList(
        Array.isArray(node.receive_from) ? node.receive_from : parseCsvList(node.receive_from || ""),
      ),
      reports_to: dedupeList(
        Array.isArray(node.reports_to) ? node.reports_to : parseCsvList(node.reports_to || ""),
      ),
      worker_instances: Math.min(8, Math.max(1, Number(node.worker_instances || node.max_parallel || 1))),
      config: typeof node.config === "object" && node.config ? node.config : {},
    };
  });

  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = Array.isArray(workflow?.edges) ? workflow.edges : [];
  edges.forEach((edge) => {
    const source = String(edge.from || edge.from_node || "").trim();
    const target = String(edge.to || "").trim();
    if (!source || !target || !nodeIds.has(source) || !nodeIds.has(target)) return;
    const targetNode = nodes.find((node) => node.id === target);
    const sourceNode = nodes.find((node) => node.id === source);
    if (targetNode) targetNode.receive_from = dedupeList([...targetNode.receive_from, source]);
    if (sourceNode) sourceNode.reports_to = dedupeList([...sourceNode.reports_to, target]);
  });
  return nodes;
}

function normalizeWorkflowDraft(workflow) {
  const modes = Array.isArray(workflow?.modes) && workflow.modes.length > 0
    ? workflow.modes
    : [workflow?.mode || "chat"];
  const uniqueModes = dedupeList(modes.map((mode) => String(mode || "").toLowerCase())).filter((mode) => modeOrder.includes(mode));
  return {
    id: String(workflow?.id || ""),
    name: String(workflow?.name || ""),
    description: String(workflow?.description || ""),
    mode: uniqueModes[0] || "chat",
    modes: uniqueModes.length > 0 ? uniqueModes : ["chat"],
    execution: workflow?.execution === "direct" ? "direct" : "loop",
    max_iterations: Math.min(8, Math.max(1, Number(workflow?.max_iterations || 1))),
    nodes: normalizeWorkflowNodes(workflow || {}),
  };
}

function defaultRoleForNodeType(type) {
  const wanted = String(type || "").toLowerCase();
  if (wanted === "worker_pool") return "worker";
  if (wanted === "reviewer") return "reviewer";
  if (wanted === "judge") return "judge";
  return "orchestrator";
}

function newWorkflowDraftFrom(workflow) {
  const draft = normalizeWorkflowDraft(workflow || {});
  if (draft.nodes.length > 0) return draft;
  return {
    ...draft,
    nodes: [{
      id: "orchestrator",
      type: "role",
      role: "orchestrator",
      title: "Plan",
      input: [],
      output: "plan",
      max_parallel: 1,
      max_items: 4,
      expects_json: true,
      receive_from: [],
      reports_to: [],
      worker_instances: 1,
      config: {},
    }],
  };
}

function slugifyWorkflowId(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 80);
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
  updateSettingsDirtyState();
}

function workflowEditorTargetOptionsHtml(selectedId) {
  const options = state.workflowPresets
    .map((workflow) => {
      const marker = isCustomWorkflow(workflow.id) ? "custom" : "preset";
      return `<option value="${escapeHtml(workflow.id)}"${workflow.id === selectedId ? " selected" : ""}>${escapeHtml(workflow.name)} (${marker})</option>`;
    })
    .join("");
  const selectedExists = state.workflowPresets.some((workflow) => workflow.id === selectedId);
  const customOption = selectedId && !selectedExists
    ? `<option value="${escapeHtml(selectedId)}" selected>${escapeHtml(selectedId)} (draft)</option>`
    : "";
  return `${customOption}${options}`;
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
    const nodes = normalizeWorkflowNodes(workflow);
    const modes = Array.isArray(workflow.modes) && workflow.modes.length > 0 ? workflow.modes : [workflow.mode];
    const customBadge = isCustomWorkflow(workflow.id) ? " · custom" : "";
    item.innerHTML = `
      <div>
        <strong>${escapeHtml(workflow.name)}</strong>
        <small>${escapeHtml(modes.join(", "))} · ${escapeHtml(workflow.execution)} · ${escapeHtml(workflow.max_iterations || 1)} iteration(s)${customBadge}</small>
      </div>
      <p>${escapeHtml(workflow.description || "")}</p>
      <div class="workflow-node-list">
        ${nodes.map((node) => `<span>${escapeHtml(node.title || node.role || node.type || node.id)}</span>`).join("")}
      </div>
      <div class="workflow-graph-preview">
        ${workflowGraphMarkup(normalizeWorkflowDraft(workflow), true)}
      </div>
    `;
    workflowPresetList.append(item);
  });
}

function workflowGraphMarkup(workflow, compact = false) {
  const nodes = Array.isArray(workflow?.nodes) ? workflow.nodes : [];
  if (nodes.length === 0) {
    return '<p class="settings-empty">No nodes to display.</p>';
  }
  const nodeWidth = compact ? 150 : 176;
  const nodeHeight = compact ? 58 : 68;
  const gapX = compact ? 34 : 44;
  const gapY = compact ? 24 : 30;
  const pad = 18;
  const cols = compact ? Math.min(3, Math.max(1, nodes.length)) : Math.min(4, Math.max(1, nodes.length));
  const rows = Math.ceil(nodes.length / cols);
  const width = pad * 2 + (cols * nodeWidth) + ((cols - 1) * gapX);
  const height = pad * 2 + (rows * nodeHeight) + ((rows - 1) * gapY);
  const positions = {};
  nodes.forEach((node, index) => {
    const col = index % cols;
    const row = Math.floor(index / cols);
    positions[node.id] = {
      x: pad + col * (nodeWidth + gapX),
      y: pad + row * (nodeHeight + gapY),
    };
  });

  const edges = deriveWorkflowEdgesFromNodes(nodes);
  const edgeSvg = edges
    .map((edge) => {
      const source = positions[edge.from];
      const target = positions[edge.to];
      if (!source || !target) return "";
      if (target.x > source.x) {
        const sx = source.x + nodeWidth;
        const sy = source.y + nodeHeight / 2;
        const tx = target.x;
        const ty = target.y + nodeHeight / 2;
        return `<path class="workflow-graph-edge" d="M ${sx} ${sy} C ${sx + 30} ${sy}, ${tx - 30} ${ty}, ${tx} ${ty}" />`;
      }
      const sx = source.x + nodeWidth / 2;
      const sy = source.y + nodeHeight;
      const tx = target.x + nodeWidth / 2;
      const ty = target.y;
      return `<path class="workflow-graph-edge loop" d="M ${sx} ${sy} C ${sx} ${sy + 30}, ${tx} ${ty - 30}, ${tx} ${ty}" />`;
    })
    .join("");

  const nodeSvg = nodes
    .map((node) => {
      const pos = positions[node.id];
      const isWorker = String(node.type || "").toLowerCase() === "worker_pool";
      const title = escapeHtml(String(node.title || node.role || node.id || "node"));
      const metaParts = [String(node.type || "role")];
      if (isWorker) {
        metaParts.push(`x${Math.max(1, Number(node.worker_instances || node.max_parallel || 1))}`);
      }
      const meta = escapeHtml(metaParts.join(" · "));
      return `
        <g class="workflow-graph-node${isWorker ? " worker" : ""}">
          <rect x="${pos.x}" y="${pos.y}" width="${nodeWidth}" height="${nodeHeight}"></rect>
          <text x="${pos.x + 10}" y="${pos.y + 24}">
            <tspan>${title}</tspan>
            <tspan x="${pos.x + 10}" dy="18">${meta}</tspan>
          </text>
        </g>
      `;
    })
    .join("");

  return `
    <svg class="workflow-graph-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Workflow graph">
      <defs>
        <marker id="wf-arrow" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto">
          <path d="M0,0 L9,3.5 L0,7 z" fill="rgba(157, 250, 255, 0.7)"></path>
        </marker>
      </defs>
      ${edgeSvg}
      ${nodeSvg}
    </svg>
  `;
}

function deriveWorkflowEdgesFromNodes(nodes) {
  const available = new Set((nodes || []).map((node) => node.id));
  const dedupe = new Set();
  const edges = [];
  (nodes || []).forEach((node) => {
    const source = String(node.id || "").trim();
    if (!source) return;
    const reports = dedupeList(Array.isArray(node.reports_to) ? node.reports_to : parseCsvList(node.reports_to || ""));
    reports.forEach((target) => {
      const to = String(target || "").trim();
      if (!to || !available.has(to)) return;
      const key = `${source}->${to}`;
      if (dedupe.has(key)) return;
      dedupe.add(key);
      edges.push({ from: source, to });
    });
    const incoming = dedupeList(Array.isArray(node.receive_from) ? node.receive_from : parseCsvList(node.receive_from || ""));
    incoming.forEach((from) => {
      const cleanFrom = String(from || "").trim();
      if (!cleanFrom || !available.has(cleanFrom)) return;
      const key = `${cleanFrom}->${source}`;
      if (dedupe.has(key)) return;
      dedupe.add(key);
      edges.push({ from: cleanFrom, to: source });
    });
  });
  return edges;
}

function activeWorkflowDraft() {
  if (state.workflowEditorDraft) return state.workflowEditorDraft;
  const first = state.workflowPresets[0] || null;
  state.workflowEditorDraft = first ? newWorkflowDraftFrom(first) : null;
  return state.workflowEditorDraft;
}

function renderWorkflowEditorNodes() {
  const draft = activeWorkflowDraft();
  if (!workflowEditorNodeList || !draft) return;
  workflowEditorNodeList.innerHTML = "";
  draft.nodes.forEach((node, index) => {
    const isWorker = String(node.type || "").toLowerCase() === "worker_pool";
    const article = document.createElement("article");
    article.className = "workflow-editor-node";
    article.dataset.index = String(index);
    article.innerHTML = `
      <div class="workflow-editor-node-head">
        <strong>Node ${index + 1}</strong>
        <button class="danger-button remove-workflow-node" type="button">Remove</button>
      </div>
      <div class="workflow-editor-node-meta">
        <label class="field">
          <span>ID</span>
          <input class="wf-node-id" type="text" value="${escapeHtml(node.id)}" />
        </label>
        <label class="field">
          <span>Title</span>
          <input class="wf-node-title" type="text" value="${escapeHtml(node.title || "")}" />
        </label>
        <label class="field">
          <span>Type</span>
          <select class="wf-node-type">
            <option value="role"${node.type === "role" ? " selected" : ""}>role</option>
            <option value="worker_pool"${node.type === "worker_pool" ? " selected" : ""}>worker_pool</option>
            <option value="reviewer"${node.type === "reviewer" ? " selected" : ""}>reviewer</option>
            <option value="judge"${node.type === "judge" ? " selected" : ""}>judge</option>
          </select>
        </label>
        <label class="field">
          <span>Role</span>
          <input class="wf-node-role" type="text" value="${escapeHtml(node.role || "")}" placeholder="${escapeHtml(defaultRoleForNodeType(node.type))}" />
        </label>
      </div>
      <div class="workflow-editor-node-links">
        <label class="field">
          <span>receiveFrom (comma separated node ids)</span>
          <input class="wf-node-receive" type="text" value="${escapeHtml((node.receive_from || []).join(", "))}" />
        </label>
        <label class="field">
          <span>reportsTo (comma separated node ids)</span>
          <input class="wf-node-reports" type="text" value="${escapeHtml((node.reports_to || []).join(", "))}" />
        </label>
      </div>
      <div class="workflow-editor-node-io">
        <label class="field">
          <span>Input Fields</span>
          <input class="wf-node-input" type="text" value="${escapeHtml((node.input || []).join(", "))}" placeholder="plan, worker_reports" />
        </label>
        <label class="field">
          <span>Output Field</span>
          <input class="wf-node-output" type="text" value="${escapeHtml(node.output || "")}" placeholder="plan" />
        </label>
        <label class="field">
          <span>Worker Instances</span>
          <input class="wf-node-workers" type="number" min="1" max="8" value="${Math.max(1, Number(node.worker_instances || node.max_parallel || 1))}" ${isWorker ? "" : "disabled"} />
        </label>
        <label class="field">
          <span>Max Work Items</span>
          <input class="wf-node-max-items" type="number" min="1" max="12" value="${Math.max(1, Number(node.max_items || 4))}" />
        </label>
        <label class="toggle-field">
          <input class="wf-node-json" type="checkbox" ${node.expects_json ? "checked" : ""} />
          <span>expects_json</span>
        </label>
      </div>
    `;
    workflowEditorNodeList.append(article);
  });
}

function updateWorkflowNodeTypeControls(row, type) {
  if (!row) return;
  const isWorker = String(type || "").toLowerCase() === "worker_pool";
  const roleInput = row.querySelector(".wf-node-role");
  const workerInput = row.querySelector(".wf-node-workers");
  if (roleInput) {
    roleInput.placeholder = defaultRoleForNodeType(type);
  }
  if (workerInput) {
    workerInput.disabled = !isWorker;
  }
}

function renderWorkflowEditor() {
  const draft = activeWorkflowDraft();
  if (!workflowEditorTarget || !draft) return;
  workflowEditorTarget.innerHTML = workflowEditorTargetOptionsHtml(draft.id);
  workflowEditorDelete.disabled = !isCustomWorkflow(draft.id);
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
  renderWorkflowEditorNodes();
  workflowGraphPreview.innerHTML = workflowGraphMarkup(draft, false);
}

function collectWorkflowDraftFromEditor() {
  const previous = activeWorkflowDraft();
  if (!previous) return null;
  const nodes = [...workflowEditorNodeList.querySelectorAll(".workflow-editor-node")]
    .map((row, index) => {
      const type = row.querySelector(".wf-node-type")?.value || "role";
      const isWorker = type === "worker_pool";
      const role = row.querySelector(".wf-node-role")?.value.trim() || defaultRoleForNodeType(type);
      const workerInstances = Math.min(8, Math.max(1, Number(row.querySelector(".wf-node-workers")?.value || "1")));
      return {
        id: row.querySelector(".wf-node-id")?.value.trim() || `node_${index + 1}`,
        type,
        role,
        title: row.querySelector(".wf-node-title")?.value.trim() || "",
        input: parseCsvList(row.querySelector(".wf-node-input")?.value || ""),
        output: row.querySelector(".wf-node-output")?.value.trim() || "",
        max_parallel: workerInstances,
        max_items: Math.min(12, Math.max(1, Number(row.querySelector(".wf-node-max-items")?.value || "4"))),
        expects_json: Boolean(row.querySelector(".wf-node-json")?.checked),
        receive_from: dedupeList(parseCsvList(row.querySelector(".wf-node-receive")?.value || "")),
        reports_to: dedupeList(parseCsvList(row.querySelector(".wf-node-reports")?.value || "")),
        worker_instances: isWorker ? workerInstances : 1,
        config: {},
      };
    });
  const modes = [];
  if (workflowEditorModeChat.checked) modes.push("chat");
  if (workflowEditorModeCode.checked) modes.push("code");
  if (workflowEditorModeAgentic.checked) modes.push("agentic");
  const normalizedModes = modes.length > 0 ? modes : ["chat"];
  const draft = {
    id: slugifyWorkflowId(workflowEditorId.value || previous.id || workflowEditorName.value) || previous.id || "custom_workflow",
    name: workflowEditorName.value.trim() || "Custom Workflow",
    description: workflowEditorDescription.value.trim(),
    mode: normalizedModes[0],
    modes: normalizedModes,
    execution: workflowEditorExecution.value === "direct" ? "direct" : "loop",
    max_iterations: Math.min(8, Math.max(1, Number(workflowEditorMaxIterations.value || "1"))),
    nodes,
  };
  state.workflowEditorDraft = draft;
  workflowEditorId.value = draft.id;
  workflowGraphPreview.innerHTML = workflowGraphMarkup(draft, false);
  return draft;
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
  const next = {
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
  return next;
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
      syncHeaderWorkspace();
      if (messagesEl.querySelector(".empty")) {
        renderMessages([]);
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
  renderWorkflowSettings();
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
  renderSettings();
  loadStartupDeferred();
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
    renderActiveStream();
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
    const bubbleContent = shouldRenderMarkdown(message)
      ? formatContent(message.content)
      : plainTextContent(message.content);
    item.innerHTML = `
      <div class="message-role">${escapeHtml(message.role)}</div>
      <div class="bubble">${bubbleContent}</div>
      ${feedbackActions}
    `;
    messagesEl.append(item);
  }
  renderActiveStream();
  messagesEl.scrollTop = messagesEl.scrollHeight;
  state.autoScrollLocked = true;
  stabilizeMessagesBottomScroll();
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

function stabilizeMessagesBottomScroll() {
  const applyBottomScroll = () => {
    if (!state.activeChatId) return;
    scrollMessagesToBottom();
  };

  requestAnimationFrame(() => {
    requestAnimationFrame(applyBottomScroll);
  });

  if (document.fonts?.ready) {
    document.fonts.ready
      .then(() => {
        requestAnimationFrame(applyBottomScroll);
      })
      .catch(() => {});
  }
}

messagesEl.addEventListener("scroll", () => {
  if (state.streamingAssistant && streamMatchesView()) return;
  state.autoScrollLocked = isMessagesNearBottom();
});

function appendMessage(message, extraClass = "", scrollToBottom = state.autoScrollLocked) {
  const mode = message.mode || state.activeMode || "chat";
  const item = document.createElement("article");
  const isThinking = message.role === "assistant" && extraClass.includes("streaming") && !message.content;
  item.className = `message ${message.role} ${mode} ${extraClass}`.trim();
  if (isThinking) item.classList.add("thinking");
  item.dataset.messageId = message.id || "";
  const bubbleContent = isThinking
    ? ""
    : shouldRenderMarkdown(message)
      ? formatContent(message.content || "")
      : plainTextContent(message.content || "");
  item.innerHTML = `
    <div class="message-role">${escapeHtml(message.role)}</div>
    ${isThinking ? thinkingIndicatorHtml() : ""}
    <div class="bubble">${bubbleContent}</div>
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

function renderActiveStream() {
  const stream = state.activeStream;
  if (!streamMatchesView(stream)) return null;
  if (messagesEl.querySelector(".empty")) {
    messagesEl.innerHTML = "";
  }
  const element = ensureStreamAssistantElement(stream);
  if (stream.content && element) {
    setStreamingContent(element, stream.content, false);
  }
  return element;
}

function ensureStreamAssistantElement(stream = state.activeStream) {
  if (!streamMatchesView(stream)) return null;
  let element = stream.element || null;
  if (element && (!element.isConnected || element.parentElement !== messagesEl)) {
    element = null;
    stream.element = null;
  }
  if (!element) {
    element = appendMessage({ role: "assistant", mode: stream.mode, content: stream.content || "" }, "streaming", false);
    element.dataset.streamId = stream.id;
    stream.element = element;
  }
  if (!stream.content) {
    setRuntimeStatus(element, streamStatusItems(stream));
  }
  if (stream.mode === "agentic" && stream.routePath) {
    applyAgenticRouteBadge(element, stream.routePath, stream.routeReason);
  }
  return element;
}

function setStreamingContent(element, content, followScroll = true) {
  const bubble = element?.querySelector(".bubble");
  if (!bubble) return;
  element.classList.toggle("thinking", !content);
  if (content) {
    element.querySelector(".thinking-notice")?.remove();
    element.querySelector(".runtime-status-mount")?.remove();
    element.classList.remove("status-only");
  }
  bubble.classList.add("streaming-plain");
  bubble.textContent = content || "";
  if (followScroll) {
    scrollMessagesToBottom();
  }
}

function setMessageContent(element, content, followScroll = true) {
  const bubble = element?.querySelector(".bubble");
  if (!bubble) return;
  element.classList.toggle("thinking", !content);
  if (content) {
    element.querySelector(".thinking-notice")?.remove();
    element.querySelector(".runtime-status-mount")?.remove();
    element.classList.remove("status-only");
  }
  bubble.classList.remove("streaming-plain");
  bubble.innerHTML = formatContent(content);
  if (followScroll) {
    scrollMessagesToBottom();
  }
}

function setRuntimeStatus(element, items) {
  if (!element) return;
  const previous = element.querySelector(".runtime-status");
  const wasOpen = previous instanceof HTMLDetailsElement ? previous.open : false;
  element.classList.add("status-only");
  element.querySelector(".thinking-notice")?.remove();
  let mount = element.querySelector(".runtime-status-mount");
  if (!mount) {
    mount = document.createElement("div");
    mount.className = "runtime-status-mount";
    const role = element.querySelector(".message-role");
    if (role) {
      role.insertAdjacentElement("afterend", mount);
    } else {
      element.prepend(mount);
    }
  }
  mount.innerHTML = runtimeStatusHtml(items, wasOpen);
}

function clearRuntimeStatus(element) {
  if (!element) return;
  element.querySelector(".runtime-status-mount")?.remove();
  element.classList.remove("status-only");
}

function finalizeAssistantMessage(element, message) {
  if (!element || !message) return;
  element.dataset.messageId = message.id;
  element.classList.remove("streaming", "thinking");
  element.querySelector(".thinking-notice")?.remove();
  clearRuntimeStatus(element);
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
    syncHeaderWorkspace(chat);
  }
}

async function loadSettings(restoreDraft = false) {
  state.settings = await api("/api/settings");
  renderSettings();
  captureSettingsBaselineFromForm();
  const hasLocalDraft = Boolean(settingsForm && safeLocalStorageGet(dirtyStorageKey(settingsForm, "settings")));
  if (restoreDraft || hasLocalDraft) {
    restoreSettingsDraftFromStorage();
  }
  syncHeaderWorkspace();
  if (shell.classList.contains("settings-open")) {
    ensureModelsLoaded().catch((error) => {
      modelsHint.textContent = error.message;
    });
  }
}

async function loadWorkflowPresets() {
  const previousDraftId = state.workflowEditorDraft?.id || "";
  const response = await api("/api/settings/workflows");
  state.workflowPresets = response.workflows || [];
  state.customWorkflowIds = Array.isArray(response.custom_ids) ? response.custom_ids : [];
  if (response.selected && state.settings) {
    state.settings.workflow_presets = response.selected;
  }
  const candidate = workflowById(previousDraftId) || workflowById(state.settings?.workflow_presets?.[state.activeMode]) || state.workflowPresets[0] || null;
  state.workflowEditorDraft = candidate ? newWorkflowDraftFrom(candidate) : null;
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

function createNewCustomWorkflowDraft() {
  const base = normalizeWorkflowDraft(workflowById("deep_orchestra") || workflowById("simple") || state.workflowPresets[0] || {});
  const draftBase = cloneWorkflowDraft(base);
  const idBase = slugifyWorkflowId(`${base.id || "workflow"}_custom`) || "custom_workflow";
  let unique = idBase;
  let counter = 2;
  const taken = new Set(state.workflowPresets.map((workflow) => workflow.id));
  while (taken.has(unique)) {
    unique = `${idBase}_${counter}`;
    counter += 1;
  }
  state.workflowEditorDraft = {
    ...draftBase,
    id: unique,
    name: `${draftBase.name || "Workflow"} Custom`,
    description: draftBase.description || "",
    modes: draftBase.modes?.length ? draftBase.modes : ["chat", "code", "agentic"],
    mode: (draftBase.modes?.[0] || "chat"),
  };
  renderWorkflowEditor();
}

async function saveWorkflowEditorDraft() {
  return saveWorkflowEditorDraftWithAssignment(false);
}

function currentWorkflowAssignmentSelection() {
  return {
    chat: Boolean(workflowEditorAssignChat?.checked),
    code: Boolean(workflowEditorAssignCode?.checked),
    agentic: Boolean(workflowEditorAssignAgentic?.checked),
  };
}

async function applyWorkflowAssignment(workflowId, assignment = currentWorkflowAssignmentSelection()) {
  if (!workflowById(workflowId)) {
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
  renderWorkflowSettings();
  captureSettingsBaselineFromForm();
  setStatus("Workflow assigned & saved");
  return true;
}

async function saveWorkflowEditorDraftWithAssignment(assignAfterSave = false) {
  const draft = collectWorkflowDraftFromEditor();
  if (!draft) return;
  const assignment = assignAfterSave ? currentWorkflowAssignmentSelection() : null;
  if (!draft.id || !draft.name) {
    setStatus("Workflow id and name are required.", true);
    return;
  }
  if (!Array.isArray(draft.nodes) || draft.nodes.length === 0) {
    setStatus("At least one node is required.", true);
    return;
  }
  const edges = deriveWorkflowEdgesFromNodes(draft.nodes);
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
  const saved = workflowById(draft.id);
  if (saved) {
    state.workflowEditorDraft = newWorkflowDraftFrom(saved);
    renderWorkflowEditor();
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

async function deleteWorkflowEditorDraft() {
  const draft = collectWorkflowDraftFromEditor();
  if (!draft || !draft.id) return;
  if (!isCustomWorkflow(draft.id)) {
    setStatus("Only custom workflows can be deleted.", true);
    return;
  }
  await api(`/api/settings/workflows/${encodeURIComponent(draft.id)}`, { method: "DELETE" });
  await loadWorkflowPresets();
  setStatus("Custom workflow deleted");
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
  syncHeaderWorkspace(chat);
  renderChats();
  await loadActiveModeMessages();
  animateViewShift();
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
    syncHeaderWorkspace(null);
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
  if (state.messageRequestInFlight) return;
  state.messageRequestInFlight = true;
  try {
  if (!state.activeChatId) {
    await createChat();
  }
  const chatId = state.activeChatId;
  const mode = state.activeMode;
  const stream = {
    id: `${chatId}-${mode}-${Date.now()}`,
    chatId,
    mode,
    content: "",
    routePath: "",
    routeReason: "",
    statusItems: [],
    assistantMessage: null,
    element: null,
  };
  state.activeStream = stream;
  setLoading(true);
  const streamStartedAt = performance.now();
  let tokenChunks = 0;
  let assistantEl = null;
  let pendingRender = false;
  let pendingRenderTimer = null;
  let lastRenderTs = 0;
  let finalStatus = "";

  const flushRender = () => {
    if (!pendingRender) return;
    pendingRender = false;
    if (pendingRenderTimer !== null) {
      window.clearTimeout(pendingRenderTimer);
      pendingRenderTimer = null;
    }
    assistantEl = ensureStreamAssistantElement(stream);
    if (assistantEl) {
      setStreamingContent(assistantEl, stream.content, state.autoScrollLocked);
    }
  };

  const renderWorkflowProgress = () => {
    if (stream.content) return;
    assistantEl = ensureStreamAssistantElement(stream);
    if (!assistantEl) return;
    setRuntimeStatus(assistantEl, streamStatusItems(stream));
  };

  const pushRuntimeStatus = (label) => {
    const cleanLabel = String(label || "").trim();
    if (!cleanLabel) return;
    const previousItems = stream.statusItems;
    const previousLast = previousItems[previousItems.length - 1] || "";
    stream.statusItems = normalizeStatusItems(
      [...previousItems, cleanLabel],
      "",
      runtimeStatusStoreLimit,
    );
    const nextLast = stream.statusItems[stream.statusItems.length - 1] || "";
    if (nextLast !== previousLast || stream.statusItems.length !== previousItems.length) {
      renderWorkflowProgress();
    }
  };

  const scheduleRender = () => {
    if (pendingRender) return;
    pendingRender = true;
    const elapsed = performance.now() - lastRenderTs;
    const delay = Math.max(0, streamRenderIntervalMs - elapsed);
    pendingRenderTimer = window.setTimeout(() => {
      requestAnimationFrame(() => {
        pendingRender = false;
        pendingRenderTimer = null;
        lastRenderTs = performance.now();
        assistantEl = ensureStreamAssistantElement(stream);
        if (assistantEl) {
          setStreamingContent(assistantEl, stream.content, state.autoScrollLocked);
        }
      });
    }, delay);
  };

  const handleStreamEvent = (event) => {
    if (event.type === "user_message") {
      if (streamMatchesView(stream)) {
        appendMessage(event.message);
      }
      watchChatTitle(chatId);
      input.value = "";
      assistantEl = ensureStreamAssistantElement(stream);
      state.streamingAssistant = true;
      state.autoScrollLocked = true;
    } else if (event.type === "status") {
      const label = event.message || `${mode} working...`;
      setStatus(label);
      pushRuntimeStatus(label);
    } else if (event.type === "workflow_status") {
      const label = event.message || "Workflow step running...";
      setStatus(label);
      pushRuntimeStatus(label);
    } else if (event.type === "agentic_route") {
      stream.routePath = normalizeAgenticRoute(event.path);
      stream.routeReason = String(event.reason || "").trim();
      assistantEl = ensureStreamAssistantElement(stream);
      applyAgenticRouteBadge(assistantEl, stream.routePath, stream.routeReason);
    } else if (event.type === "token") {
      if (!state.streamingAssistant) {
        state.streamingAssistant = true;
        state.autoScrollLocked = true;
      }
      assistantEl = ensureStreamAssistantElement(stream);
      clearRuntimeStatus(assistantEl);
      stream.content += event.content || "";
      tokenChunks += 1;
      const elapsed = Math.max((performance.now() - streamStartedAt) / 1000, 0.1);
      setStatus(`${mode} streaming · ${(tokenChunks / elapsed).toFixed(1)} tok/s`);
      scheduleRender();
    } else if (event.type === "assistant_message") {
      stream.assistantMessage = event.message;
      flushRender();
      assistantEl = ensureStreamAssistantElement(stream);
      setMessageContent(assistantEl, event.message?.content || stream.content, false);
      finalizeAssistantMessage(assistantEl, event.message);
    } else if (event.type === "done") {
      flushRender();
      const exact = event.stats?.tokens_per_second;
      assistantEl = ensureStreamAssistantElement(stream);
      if (assistantEl && stream.content) {
        setMessageContent(assistantEl, stream.assistantMessage?.content || stream.content, false);
      }
      finalStatus = exact ? `Done · ${exact} tok/s` : "Ready";
      setStatus(finalStatus);
    } else if (event.type === "error") {
      throw new Error(event.message || "Stream failed");
    }
  };

  const processStreamFrame = (frame) => {
    const event = parseFrameEvent(frame);
    if (event) {
      handleStreamEvent(event);
    }
  };

  try {
    const response = await fetch(`/api/chats/${chatId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, mode, effort: currentEffort() }),
    });
    if (!response.ok || !response.body) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const processCompleteFrames = () => {
      const frames = buffer.split("\n\n");
      buffer = frames.pop() || "";
      frames.forEach(processStreamFrame);
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      processCompleteFrames();
    }
    buffer += decoder.decode();
    processCompleteFrames();
    if (buffer.trim()) {
      processStreamFrame(buffer);
      buffer = "";
    }

    await loadChats();
    renderChats();
    watchChatTitle(chatId);
    if (state.activeMode === "agentic") {
      await loadAgenticTasks();
    }
  } catch (error) {
    setStatus(error.message, true);
    if (assistantEl && !stream.content) {
      assistantEl.remove();
      stream.element = null;
    }
  } finally {
    flushRender();
    if (pendingRenderTimer !== null) {
      window.clearTimeout(pendingRenderTimer);
      pendingRenderTimer = null;
    }
    if (state.activeStream?.id === stream.id) {
      state.activeStream = null;
    }
    state.streamingAssistant = false;
    setLoading(false);
    if (finalStatus) setStatus(finalStatus);
  }
  } finally {
    state.messageRequestInFlight = false;
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

effortButtons.forEach((button) => {
  button.addEventListener("click", () => {
    setEffort(button.dataset.effort || "medium").catch((error) => setStatus(error.message, true));
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

workflowEditorTarget?.addEventListener("change", () => {
  const selectedId = workflowEditorTarget.value;
  const selected = workflowById(selectedId);
  if (!selected) return;
  state.workflowEditorDraft = newWorkflowDraftFrom(selected);
  renderWorkflowEditor();
});

workflowEditorNew?.addEventListener("click", () => {
  createNewCustomWorkflowDraft();
});

workflowEditorSave?.addEventListener("click", () => {
  saveWorkflowEditorDraft().catch((error) => setStatus(error.message, true));
});

workflowEditorSaveAssign?.addEventListener("click", () => {
  saveWorkflowEditorDraftWithAssignment(true).catch((error) => setStatus(error.message, true));
});

workflowEditorDelete?.addEventListener("click", () => {
  deleteWorkflowEditorDraft().catch((error) => setStatus(error.message, true));
});

workflowEditorAddNode?.addEventListener("click", () => {
  const draft = collectWorkflowDraftFromEditor() || activeWorkflowDraft();
  if (!draft) return;
  draft.nodes.push({
    id: `node_${draft.nodes.length + 1}`,
    type: "role",
    role: "orchestrator",
    title: "New Node",
    input: [],
    output: "",
    max_parallel: 1,
    max_items: 4,
    expects_json: false,
    receive_from: [],
    reports_to: [],
    worker_instances: 1,
    config: {},
  });
  state.workflowEditorDraft = draft;
  renderWorkflowEditor();
});

workflowEditorNodeList?.addEventListener("click", (event) => {
  const removeButton = event.target.closest(".remove-workflow-node");
  if (!removeButton) return;
  const row = removeButton.closest(".workflow-editor-node");
  const index = Number(row?.dataset.index ?? "-1");
  const draft = collectWorkflowDraftFromEditor() || activeWorkflowDraft();
  if (!draft || index < 0) return;
  draft.nodes.splice(index, 1);
  state.workflowEditorDraft = draft;
  renderWorkflowEditor();
});

workflowEditorNodeList?.addEventListener("change", (event) => {
  const typeSelect = event.target.closest(".wf-node-type");
  if (!typeSelect) {
    collectWorkflowDraftFromEditor();
    return;
  }
  const row = typeSelect.closest(".workflow-editor-node");
  const roleInput = row?.querySelector(".wf-node-role");
  if (roleInput && !roleInput.value.trim()) {
    roleInput.value = defaultRoleForNodeType(typeSelect.value);
  }
  updateWorkflowNodeTypeControls(row, typeSelect.value);
  collectWorkflowDraftFromEditor();
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
    collectWorkflowDraftFromEditor();
  });
  element?.addEventListener("change", () => {
    collectWorkflowDraftFromEditor();
  });
});

workflowEditorNodeList?.addEventListener("input", () => {
  collectWorkflowDraftFromEditor();
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
    syncHeaderWorkspace();
    if (messagesEl.querySelector(".empty")) {
      renderMessages([]);
    }
    captureSettingsBaselineFromForm();
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
initGenericDirtyTracking();

async function loadStartupCritical() {
  await loadSettings(true);
  await Promise.all([
    loadWorkflowPresets(),
    loadChats(),
  ]);
  if (state.activeChatId) {
    await selectChat(state.activeChatId);
  } else {
    renderMessages([]);
  }
}

function loadStartupDeferred() {
  Promise.all([
    loadRoles(),
    loadMistakes(),
    loadAgenticTasks(),
    loadSchedulerStatus(),
    loadTools(),
  ])
    .catch((error) => setStatus(error.message, true));
}

loadStartupCritical()
  .then(() => {
    setStatus("Ready");
    window.setTimeout(loadStartupDeferred, 0);
  })
  .catch((error) => setStatus(error.message, true));
