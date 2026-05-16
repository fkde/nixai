import { api } from "./api.js";
import { dom } from "./dom.js";
import {
  escapeHtml,
  findStreamSealOffset,
  formatContent,
  plainTextContent,
} from "./helpers.js";
import { startMessageStream } from "./stream.js";
import { state } from "./state.js";
import {
  modeOrder,
  runtimeStatusHistoryLimit,
  runtimeStatusStoreLimit,
  streamRenderIntervalMs,
  thumbIcon,
  uiIcon,
} from "./ui.js";

const {
  chatList,
  messagesEl,
  chatTitle,
  chatWorkspace,
  form,
  input,
  sendButton,
  composerPlusButton,
  composerPlusMenu,
  addWorkspaceButton,
  newChatButton,
  modeSwitch,
  modeButtons,
} = dom;

export function createChatUi({ setStatus, toolApprovals, getSettingsUi, getAgenticTasksUi }) {
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
    return "Thinking…";
  }

  function streamStatusItems(stream = state.activeStream, limit = runtimeStatusHistoryLimit) {
    if (!stream) return [];
    return normalizeStatusItems(stream.statusItems, defaultStreamStatusLabel(stream), limit);
  }

  function streamStatusLabel(stream = state.activeStream) {
    const items = streamStatusItems(stream, runtimeStatusStoreLimit);
    return items[items.length - 1] || "";
  }

  function highlightWorkflowNode(nodeId) {
    const clean = String(nodeId || "").trim();
    document
      .querySelectorAll(".workflow-canvas-node.is-active-run")
      .forEach((node) => node.classList.remove("is-active-run"));
    if (!clean) return;
    document
      .querySelector(`.workflow-canvas-node[data-node-id="${cssEscape(clean)}"]`)
      ?.classList.add("is-active-run");
  }

  function cssEscape(value) {
    if (typeof CSS !== "undefined" && typeof CSS.escape === "function") return CSS.escape(value);
    return String(value).replace(/(["\\\]])/g, "\\$1");
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
    document.body.dataset.activeMode = state.activeMode;
    modeSwitch?.style.setProperty("--mode-index", String(activeIndex));
    modeButtons.forEach((button) => {
      const active = button.dataset.mode === state.activeMode;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    if (state.activeMode === "chat") {
      closeComposerMenu();
    }
    input.placeholder = {
      chat: "Write a message...",
      code: "Ask a code question or describe a project task...",
      agentic: "Describe an agentic task or recurring run...",
    }[state.activeMode];
    resizeMessageInput();
  }

  function resizeMessageInput() {
    if (!input) return;
    const rootStyles = getComputedStyle(document.documentElement);
    const inputStyles = getComputedStyle(input);
    const minHeight = parseFloat(rootStyles.getPropertyValue("--footer-action-size")) || 42;
    const maxHeight = parseFloat(inputStyles.maxHeight) || 150;
    input.style.height = `${minHeight}px`;
    const nextHeight = Math.min(Math.max(input.scrollHeight, minHeight), maxHeight);
    input.style.height = `${nextHeight}px`;
    input.style.overflowY = input.scrollHeight > maxHeight ? "auto" : "hidden";
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
    bubble.classList.remove("streaming-plain");
    const text = content || "";
    let render = bubble._streamRender;
    if (!render || !render.tailMarker?.isConnected || render.tailMarker.parentNode !== bubble) {
      bubble.innerHTML = "";
      const tailMarker = document.createComment("stream-tail");
      bubble.appendChild(tailMarker);
      render = { sealedOffset: 0, tailMarker };
      bubble._streamRender = render;
    }
    const sealOffset = findStreamSealOffset(text);
    if (sealOffset > render.sealedOffset) {
      const html = formatContent(text.slice(render.sealedOffset, sealOffset));
      if (html) {
        const template = document.createElement("template");
        template.innerHTML = html;
        bubble.insertBefore(template.content, render.tailMarker);
      }
      render.sealedOffset = sealOffset;
    }
    let tailNode = render.tailMarker.nextSibling;
    while (tailNode) {
      const next = tailNode.nextSibling;
      bubble.removeChild(tailNode);
      tailNode = next;
    }
    const tailText = text.slice(render.sealedOffset);
    if (tailText) {
      const html = formatContent(tailText);
      if (html) {
        const template = document.createElement("template");
        template.innerHTML = html;
        bubble.appendChild(template.content);
      }
    }
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
    bubble._streamRender = null;
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
    setStatus(loading ? "Thinking…" : "Ready");
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
          resizeMessageInput();
          assistantEl = ensureStreamAssistantElement(stream);
          state.streamingAssistant = true;
          state.autoScrollLocked = true;
        } else if (event.type === "status") {
          const label = event.message || "Thinking…";
          setStatus(label);
          pushRuntimeStatus(label);
        } else if (event.type === "workflow_status") {
          const label = event.message || "Workflow step running...";
          setStatus(label);
          pushRuntimeStatus(label);
          highlightWorkflowNode(event.node);
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

      try {
        await startMessageStream({
          chatId,
          body: { content, mode, effort: getSettingsUi()?.currentEffort() || "medium" },
          onEvent: handleStreamEvent,
        });

        await loadChats();
        renderChats();
        watchChatTitle(chatId);
        if (state.activeMode === "agentic") {
          await getAgenticTasksUi()?.loadAgenticTasks();
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
    const approval = await toolApprovals.request(response);
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
      await getSettingsUi()?.loadSettings();
    }
    return approvedResponse;
  }

  function init() {
    newChatButton.addEventListener("click", () => {
      createChat().catch((error) => setStatus(error.message, true));
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

    messagesEl.addEventListener("scroll", () => {
      if (state.streamingAssistant && streamMatchesView()) return;
      state.autoScrollLocked = isMessagesNearBottom();
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

    input.addEventListener("input", resizeMessageInput);
    resizeMessageInput();
  }

  return {
    activeChat,
    callTool,
    changeMode,
    createChat,
    displayChatTitle,
    init,
    loadActiveModeMessages,
    loadChats,
    renderChats,
    renderMessages,
    renderModeSwitch,
    selectChat,
    sendMessage,
    sendMessageFeedback,
    stabilizeMessagesBottomScroll,
    syncHeaderWorkspace,
  };
}
