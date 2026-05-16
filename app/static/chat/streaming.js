import { escapeHtml, findStreamSealOffset, formatContent } from "../helpers.js";
import { state } from "../state.js";
import { runtimeStatusHistoryLimit, runtimeStatusStoreLimit } from "../ui.js";

export function createStreamingHelpers({ messagesEl, bridge }) {
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
      element = bridge.appendMessage(
        { role: "assistant", mode: stream.mode, content: stream.content || "" },
        "streaming",
        false,
      );
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
      bridge.scrollMessagesToBottom();
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
      bridge.scrollMessagesToBottom();
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

  return {
    thinkingIndicatorHtml,
    streamMatchesView,
    defaultStreamStatusLabel,
    streamStatusItems,
    streamStatusLabel,
    normalizeStatusItems,
    highlightWorkflowNode,
    cssEscape,
    runtimeStatusHtml,
    normalizeAgenticRoute,
    applyAgenticRouteBadge,
    renderActiveStream,
    ensureStreamAssistantElement,
    setStreamingContent,
    setMessageContent,
    setRuntimeStatus,
    clearRuntimeStatus,
  };
}
