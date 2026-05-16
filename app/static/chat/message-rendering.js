import { api } from "../api.js";
import { escapeHtml, formatContent, plainTextContent } from "../helpers.js";
import { state } from "../state.js";
import { thumbIcon } from "../ui.js";

export function createMessageRendering({ messagesEl, setStatus, streaming, bridge }) {
  function shouldRenderMarkdown(message) {
    return message?.role === "assistant";
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

  function renderMessages(messages) {
    messagesEl.innerHTML = "";
    if (!state.activeChatId) {
      messagesEl.innerHTML = emptyChatHtml("none");
      return;
    }
    if (messages.length === 0) {
      messagesEl.innerHTML = emptyChatHtml("chat");
      streaming.renderActiveStream();
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
    streaming.renderActiveStream();
    messagesEl.scrollTop = messagesEl.scrollHeight;
    state.autoScrollLocked = true;
    stabilizeMessagesBottomScroll();
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
      ${isThinking ? streaming.thinkingIndicatorHtml() : ""}
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

  function finalizeAssistantMessage(element, message) {
    if (!element || !message) return;
    element.dataset.messageId = message.id;
    element.classList.remove("streaming", "thinking");
    element.querySelector(".thinking-notice")?.remove();
    streaming.clearRuntimeStatus(element);
    if (!element.querySelector(".message-feedback")) {
      element.insertAdjacentHTML("beforeend", `
        <div class="message-feedback" aria-label="Rate response">
          <button class="feedback-button" type="button" data-message-id="${escapeHtml(message.id)}" data-rating="up" aria-label="Thumbs up">${thumbIcon("up")}</button>
          <button class="feedback-button" type="button" data-message-id="${escapeHtml(message.id)}" data-rating="down" aria-label="Thumbs down">${thumbIcon("down")}</button>
        </div>
      `);
    }
  }

  async function sendMessageFeedback(messageId, rating) {
    try {
      await api(`/api/chats/messages/${messageId}/feedback`, {
        method: "POST",
        body: JSON.stringify({ rating }),
      });
      if (state.activeChatId) {
        await bridge.loadActiveModeMessages();
      }
      setStatus(rating === "down" ? "Feedback saved, mistakes are being updated" : "Feedback saved");
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  return {
    shouldRenderMarkdown,
    firstName,
    emptyGreeting,
    emptyChatHtml,
    isMessagesNearBottom,
    scrollMessagesToBottom,
    stabilizeMessagesBottomScroll,
    renderMessages,
    appendMessage,
    finalizeAssistantMessage,
    sendMessageFeedback,
  };
}
