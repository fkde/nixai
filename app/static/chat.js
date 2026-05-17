import { createChatList } from "./chat/chat-list.js";
import { createComposer } from "./chat/composer.js";
import { createMessageRendering } from "./chat/message-rendering.js";
import { createStreamingHelpers } from "./chat/streaming.js";
import { dom } from "./dom.js";
import { state } from "./state.js";

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

export function createChatUi({ setStatus, toolApprovals, getSettingsUi, getAgenticTasksUi, getRunsUi }) {
  const bridge = {};

  const streaming = createStreamingHelpers({ messagesEl, bridge });
  const messageRendering = createMessageRendering({ messagesEl, setStatus, streaming, bridge });

  bridge.appendMessage = messageRendering.appendMessage;
  bridge.scrollMessagesToBottom = messageRendering.scrollMessagesToBottom;
  bridge.renderMessages = messageRendering.renderMessages;

  const chatListApi = createChatList({
    chatList,
    chatTitle,
    chatWorkspace,
    input,
    setStatus,
    bridge,
  });

  const composer = createComposer({
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
    chatList: chatListApi,
  });

  bridge.loadActiveModeMessages = composer.loadActiveModeMessages;
  bridge.animateViewShift = composer.animateViewShift;

  function init() {
    newChatButton.addEventListener("click", () => {
      chatListApi.createChat().catch((error) => setStatus(error.message, true));
    });

    composerPlusButton.addEventListener("click", (event) => {
      event.stopPropagation();
      composer.toggleComposerMenu();
    });

    addWorkspaceButton.addEventListener("click", () => {
      composer.closeComposerMenu();
      composer.requestWorkspacePath().catch((error) => setStatus(error.message, true));
    });

    document.addEventListener("click", (event) => {
      if (!event.target.closest(".composer-plus")) {
        composer.closeComposerMenu();
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        composer.closeComposerMenu();
      }
    });

    modeButtons.forEach((button) => {
      button.addEventListener("click", () => {
        composer.changeMode(button.dataset.mode || "chat");
      });
    });

    messagesEl.addEventListener("animationend", () => {
      messagesEl.classList.remove("mode-shift-forward", "mode-shift-back");
    });

    messagesEl.addEventListener("scroll", () => {
      if (state.streamingAssistant && streaming.streamMatchesView()) return;
      state.autoScrollLocked = messageRendering.isMessagesNearBottom();
    });

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const content = input.value.trim();
      if (!content || state.loading) return;
      composer.sendMessage(content);
    });

    messagesEl.addEventListener("click", (event) => {
      const button = event.target.closest(".feedback-button");
      if (!button) return;
      messageRendering.sendMessageFeedback(button.dataset.messageId, button.dataset.rating);
    });

    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
      }
    });

    input.addEventListener("input", composer.resizeMessageInput);
    composer.resizeMessageInput();
  }

  return {
    activeChat: chatListApi.activeChat,
    callTool: composer.callTool,
    changeMode: composer.changeMode,
    createChat: chatListApi.createChat,
    displayChatTitle: chatListApi.displayChatTitle,
    init,
    loadActiveModeMessages: composer.loadActiveModeMessages,
    loadChats: chatListApi.loadChats,
    renderChats: chatListApi.renderChats,
    renderMessages: messageRendering.renderMessages,
    renderModeSwitch: composer.renderModeSwitch,
    selectChat: chatListApi.selectChat,
    sendMessage: composer.sendMessage,
    sendMessageFeedback: messageRendering.sendMessageFeedback,
    stabilizeMessagesBottomScroll: messageRendering.stabilizeMessagesBottomScroll,
    syncHeaderWorkspace: chatListApi.syncHeaderWorkspace,
  };
}
