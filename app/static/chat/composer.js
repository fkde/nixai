import { api } from "../api.js";
import { state } from "../state.js";
import { startMessageStream } from "../stream.js";
import { modeOrder, runtimeStatusStoreLimit, streamRenderIntervalMs } from "../ui.js";

export function createComposer({
  messagesEl,
  input,
  sendButton,
  modeSwitch,
  modeButtons,
  composerPlusButton,
  composerPlusMenu,
  addWorkspaceButton,
  setStatus,
  toolApprovals,
  getSettingsUi,
  getAgenticTasksUi,
  getRunsUi,
  streaming,
  messageRendering,
  chatList,
}) {
  function attachInspectorBadge(assistantEl, runId) {
    if (!assistantEl || !runId) return;
    if (assistantEl.querySelector(".inspector-badge")) return;
    const badge = document.createElement("button");
    badge.type = "button";
    badge.className = "inspector-badge";
    badge.dataset.runId = runId;
    badge.textContent = "Open Inspector";
    badge.addEventListener("click", () => {
      const runsUi = getRunsUi && getRunsUi();
      runsUi?.openRunInInspector?.(runId);
    });
    assistantEl.prepend(badge);
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

  async function loadActiveModeMessages(mode = state.activeMode) {
    if (!state.activeChatId) {
      messageRendering.renderMessages([]);
      return;
    }
    const chatId = state.activeChatId;
    const messages = await api(`/api/chats/${chatId}/messages?mode=${encodeURIComponent(mode)}`);
    if (chatId !== state.activeChatId || mode !== state.activeMode) return;
    messageRendering.renderMessages(messages);
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
      messageRendering.renderMessages([]);
    }
    setStatus(streaming.streamMatchesView() ? streaming.streamStatusLabel() : `${state.activeMode} ready`);
  }

  async function requestWorkspacePath() {
    if (!state.activeChatId) {
      await chatList.createChat();
    }
    const chat = chatList.activeChat();
    const current = chat?.workspace_path || "";
    let workspace = "";
    if (window.pywebview?.api?.choose_workspace) {
      workspace = await window.pywebview.api.choose_workspace();
      if (!workspace) return;
    } else {
      workspace = window.prompt("Workspace path for this chat", current);
    }
    if (workspace === null) return;
    await chatList.saveChatWorkspace(workspace);
    setStatus(workspace.trim() ? "Workspace set" : "Workspace fallback active");
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
        await chatList.createChat();
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
        assistantEl = streaming.ensureStreamAssistantElement(stream);
        if (assistantEl) {
          streaming.setStreamingContent(assistantEl, stream.content, state.autoScrollLocked);
        }
      };

      const renderWorkflowProgress = () => {
        if (stream.content) return;
        assistantEl = streaming.ensureStreamAssistantElement(stream);
        if (!assistantEl) return;
        streaming.setRuntimeStatus(assistantEl, streaming.streamStatusItems(stream));
      };

      const pushRuntimeStatus = (label) => {
        const cleanLabel = String(label || "").trim();
        if (!cleanLabel) return;
        const previousItems = stream.statusItems;
        const previousLast = previousItems[previousItems.length - 1] || "";
        stream.statusItems = streaming.normalizeStatusItems(
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
            assistantEl = streaming.ensureStreamAssistantElement(stream);
            if (assistantEl) {
              streaming.setStreamingContent(assistantEl, stream.content, state.autoScrollLocked);
            }
          });
        }, delay);
      };

      const handleStreamEvent = (event) => {
        if (event.type === "user_message") {
          if (streaming.streamMatchesView(stream)) {
            messageRendering.appendMessage(event.message);
          }
          chatList.watchChatTitle(chatId);
          input.value = "";
          resizeMessageInput();
          assistantEl = streaming.ensureStreamAssistantElement(stream);
          state.streamingAssistant = true;
          state.autoScrollLocked = true;
        } else if (event.type === "status") {
          const label = event.message || "Thinking…";
          setStatus(label);
          pushRuntimeStatus(label);
        } else if (event.type === "workflow_run") {
          stream.runId = event.run_id;
          assistantEl = streaming.ensureStreamAssistantElement(stream);
          attachInspectorBadge(assistantEl, event.run_id);
        } else if (event.type === "workflow_status") {
          const label = event.message || "Workflow step running...";
          setStatus(label);
          pushRuntimeStatus(label);
          streaming.highlightWorkflowNode(event.node);
        } else if (event.type === "agentic_route") {
          stream.routePath = streaming.normalizeAgenticRoute(event.path);
          stream.routeReason = String(event.reason || "").trim();
          assistantEl = streaming.ensureStreamAssistantElement(stream);
          streaming.applyAgenticRouteBadge(assistantEl, stream.routePath, stream.routeReason);
        } else if (event.type === "token") {
          if (!state.streamingAssistant) {
            state.streamingAssistant = true;
            state.autoScrollLocked = true;
          }
          assistantEl = streaming.ensureStreamAssistantElement(stream);
          streaming.clearRuntimeStatus(assistantEl);
          stream.content += event.content || "";
          tokenChunks += 1;
          const elapsed = Math.max((performance.now() - streamStartedAt) / 1000, 0.1);
          setStatus(`${mode} streaming · ${(tokenChunks / elapsed).toFixed(1)} tok/s`);
          scheduleRender();
        } else if (event.type === "assistant_message") {
          stream.assistantMessage = event.message;
          flushRender();
          assistantEl = streaming.ensureStreamAssistantElement(stream);
          streaming.setMessageContent(assistantEl, event.message?.content || stream.content, false);
          messageRendering.finalizeAssistantMessage(assistantEl, event.message);
        } else if (event.type === "done") {
          flushRender();
          const exact = event.stats?.tokens_per_second;
          assistantEl = streaming.ensureStreamAssistantElement(stream);
          if (assistantEl && stream.content) {
            streaming.setMessageContent(assistantEl, stream.assistantMessage?.content || stream.content, false);
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

        await chatList.loadChats();
        chatList.renderChats();
        chatList.watchChatTitle(chatId);
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

  return {
    closeComposerMenu,
    toggleComposerMenu,
    resizeMessageInput,
    renderModeSwitch,
    animateModeChange,
    animateViewShift,
    loadActiveModeMessages,
    changeMode,
    requestWorkspacePath,
    setLoading,
    sendMessage,
    callTool,
  };
}
