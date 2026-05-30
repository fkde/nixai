import { api } from "../api.js";
import { escapeHtml, formatContent, plainTextContent } from "../helpers.js";
import { state } from "../state.js";
import { thumbIcon } from "../ui.js";

export function createMessageRendering({ messagesEl, setStatus, streaming, bridge }) {
  let emptyGreetingTimer = null;

  function shouldRenderMarkdown(message) {
    return message?.role === "assistant";
  }

  function firstName() {
    return (state.settings?.user_name || "").trim().split(/\s+/)[0] || "";
  }

  function emptyGreetingVariants() {
    const name = firstName();
    const suffix = name ? ` ${escapeHtml(name)}` : "";
    return [
      {
        title: `Awaiting signal${suffix}`,
        text: "Drop the first packet. I will route it through chat, code context, or the agentic loop.",
        meta: "local-first / approval-gated / no cloud handoff",
      },
      {
        title: `Runtime warm${suffix}`,
        text: "Local stack is awake. Feed it a question, a repo, or a tiny impossible thing.",
        meta: "ollama linkup / sqlite memory / tools on standby",
      },
      {
        title: `Console armed${suffix}`,
        text: "Messy intent is fine. We can compile it into a plan after the first keystroke.",
        meta: "mode switch ready / workspace optional",
      },
      {
        title: `NixAI standing by${suffix}`,
        text: "Chat for thinking, Code for project context, Agentic when the task wants a runbook.",
        meta: "chat <-> code <-> agentic",
      },
      {
        title: `Prompt socket open${suffix}`,
        text: "Send raw intent. I will negotiate with the local machinery and ask before touching sharp tools.",
        meta: "bounded tools / visible approvals / local trace",
      },
    ];
  }

  function emptyGreeting(index = null) {
    const variants = emptyGreetingVariants();
    const seed = state.activeChatId
      ? [...state.activeChatId].reduce((sum, char) => sum + char.charCodeAt(0), 0)
      : new Date().getDate();
    return variants[(index ?? seed) % variants.length];
  }

  function emptyGreetingCopy(greeting) {
    return `
      <span class="empty-kicker">nixai://session</span>
      <h3>${greeting.title}</h3>
      <p>${greeting.text}</p>
      <div class="empty-meta">
        <span>${greeting.meta}</span>
      </div>
    `;
  }

  function stopEmptyGreetingRotation() {
    if (emptyGreetingTimer !== null) {
      clearInterval(emptyGreetingTimer);
      emptyGreetingTimer = null;
    }
  }

  function startEmptyGreetingRotation() {
    stopEmptyGreetingRotation();
    const empty = messagesEl.querySelector(".empty");
    const copy = empty?.querySelector(".empty-copy");
    if (!empty || !copy || window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) return;
    let index = Number(empty.dataset.greetingIndex || 0);
    emptyGreetingTimer = setInterval(() => {
      const current = messagesEl.querySelector(".empty");
      const target = current?.querySelector(".empty-copy");
      if (!current || !target) {
        stopEmptyGreetingRotation();
        return;
      }
      index = (index + 1) % emptyGreetingVariants().length;
      current.dataset.greetingIndex = String(index);
      target.classList.add("is-swapping");
      window.setTimeout(() => {
        if (!messagesEl.contains(target)) return;
        target.innerHTML = emptyGreetingCopy(emptyGreeting(index));
        target.classList.remove("is-swapping");
      }, 260);
    }, 5600);
  }

  function emptyChatHtml(kind = "chat") {
    const variants = emptyGreetingVariants();
    const seed = state.activeChatId
      ? [...state.activeChatId].reduce((sum, char) => sum + char.charCodeAt(0), 0)
      : new Date().getDate();
    const index = seed % variants.length;
    const greeting = variants[index];
    const helper = kind === "none"
      ? "Create a chat on the left to start the loop."
      : "";
    return `
      <section class="empty" data-greeting-index="${index}">
        <div class="empty-shell" aria-hidden="true">
          <span></span><span></span><span></span>
        </div>
        <div class="empty-copy">
          ${emptyGreetingCopy(greeting)}
        </div>
        ${helper ? `<small class="empty-helper">${helper}</small>` : ""}
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
      startEmptyGreetingRotation();
      return;
    }
    if (messages.length === 0) {
      messagesEl.innerHTML = emptyChatHtml("chat");
      startEmptyGreetingRotation();
      streaming.renderActiveStream();
      return;
    }
    stopEmptyGreetingRotation();
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
      stopEmptyGreetingRotation();
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
    stopEmptyGreetingRotation,
    isMessagesNearBottom,
    scrollMessagesToBottom,
    stabilizeMessagesBottomScroll,
    renderMessages,
    appendMessage,
    finalizeAssistantMessage,
    sendMessageFeedback,
  };
}
