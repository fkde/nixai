import { hasDirtyTracker, registerDirtyTracker } from "./dirty-tracker.js";
import { dom } from "./dom.js";
import { escapeHtml, formatContent } from "./helpers.js";
import { state } from "./state.js";

export const modeOrder = ["chat", "code", "agentic"];
export const effortOrder = ["minimum", "medium", "high", "max"];
export const runtimeStatusHistoryLimit = 16;
export const runtimeStatusStoreLimit = 64;
export const streamRenderIntervalMs = 120;
export const embeddingModelMarkers = [
  "embed",
  "embedding",
  "nomic-bert",
  "sentence-transformer",
  "bge-",
  "all-minilm",
  "e5-",
  "gte-",
];

let desktopWindowControlsBound = false;

function bindDesktopWindowControls(api) {
  if (desktopWindowControlsBound || !api) return;

  const actionMethods = {
    close: "close_window",
    minimize: "minimize_window",
    zoom: "zoom_window",
  };
  const buttons = [...document.querySelectorAll("[data-window-action]")];
  buttons.forEach((button) => {
    const methodName = actionMethods[button.dataset.windowAction];
    if (!methodName || typeof api[methodName] !== "function") {
      button.disabled = true;
      return;
    }
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      try {
        await api[methodName]();
      } catch (error) {
        console.warn(error);
      }
    });
  });

  desktopWindowControlsBound = buttons.length > 0;
}

export function createStatusController() {
  const toastRegion = document.createElement("div");
  toastRegion.className = "toast-region";
  toastRegion.setAttribute("aria-live", "polite");
  toastRegion.setAttribute("aria-atomic", "true");
  document.body.append(toastRegion);

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

  return { setStatus, showToast };
}

export async function initDesktopChrome(stabilizeMessagesBottomScroll) {
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
    document.body.classList.toggle("frameless-window", Boolean(info?.frameless));
    document.body.classList.toggle("native-chrome", Boolean(info?.native_chrome ?? isMac));
    document.body.classList.toggle("native-traffic-lights", Boolean(info?.native_traffic_lights ?? isMac));
    document.body.classList.toggle("custom-window-controls", Boolean(info?.window_controls));
    return true;
  };

  const api = window.pywebview?.api;
  bindDesktopWindowControls(api);
  if (!api?.desktop_info) {
    const applied = addDesktopClasses();
    if (!applied) {
      window.addEventListener("pywebviewready", () => initDesktopChrome(stabilizeMessagesBottomScroll), { once: true });
    } else {
      stabilizeMessagesBottomScroll();
    }
    if (window.pywebview) {
      window.setTimeout(() => {
        if (!document.body.classList.contains("desktop-shell")) {
          initDesktopChrome(stabilizeMessagesBottomScroll);
        }
      }, 180);
    }
    return;
  }
  try {
    const info = await api.desktop_info();
    addDesktopClasses(info);
    bindDesktopWindowControls(api);
    stabilizeMessagesBottomScroll();
  } catch (error) {
    console.warn(error);
    if (addDesktopClasses()) {
      stabilizeMessagesBottomScroll();
    }
  }
}

export function initGenericDirtyTracking() {
  const trackedForms = [...document.querySelectorAll("form[data-dirty-track]")];
  trackedForms.forEach((trackedForm) => {
    if (trackedForm === dom.settingsForm) return;
    if (hasDirtyTracker(trackedForm)) return;
    const tracker = registerDirtyTracker(trackedForm);
    if (!tracker) return;
    tracker.captureBaseline();
    tracker.restoreDraftIfAny();
  });
}

export function thumbIcon(direction) {
  const rotate = direction === "down" ? ' class="thumb-down"' : "";
  return `
    <svg${rotate} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 10v10h3l4-7h5a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2h-9.5a2 2 0 0 0-1.8 1.1L7 6" />
      <path d="M3 10V4h4v6H3Z" />
    </svg>
  `;
}

export function uiIcon(name) {
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

export function markdownPreview(content) {
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

export function initInfoTooltips() {
  const infoTooltipEl = document.createElement("div");
  infoTooltipEl.className = "app-tooltip";
  infoTooltipEl.setAttribute("role", "tooltip");
  infoTooltipEl.setAttribute("aria-hidden", "true");
  document.body.appendChild(infoTooltipEl);

  function showInfoTooltip(trigger) {
    const text = trigger.getAttribute("data-tip");
    if (!text) return;
    infoTooltipEl.innerHTML = formatContent(text);
    infoTooltipEl.classList.add("is-visible");
    infoTooltipEl.setAttribute("aria-hidden", "false");
    positionInfoTooltip(trigger);
  }

  function positionInfoTooltip(trigger) {
    const triggerRect = trigger.getBoundingClientRect();
    const tipRect = infoTooltipEl.getBoundingClientRect();
    const margin = 10;
    let top = triggerRect.bottom + 8;
    let placement = "below";
    if (top + tipRect.height + margin > window.innerHeight) {
      top = Math.max(margin, triggerRect.top - tipRect.height - 8);
      placement = "above";
    }
    let left = triggerRect.left + triggerRect.width / 2 - tipRect.width / 2;
    left = Math.max(margin, Math.min(left, window.innerWidth - tipRect.width - margin));
    infoTooltipEl.style.top = `${Math.round(top)}px`;
    infoTooltipEl.style.left = `${Math.round(left)}px`;
    infoTooltipEl.dataset.placement = placement;
  }

  function hideInfoTooltip() {
    infoTooltipEl.classList.remove("is-visible");
    infoTooltipEl.setAttribute("aria-hidden", "true");
  }

  document.addEventListener("mouseover", (event) => {
    const tip = event.target.closest?.(".info-tip");
    if (tip) showInfoTooltip(tip);
  });

  document.addEventListener("mouseout", (event) => {
    const tip = event.target.closest?.(".info-tip");
    if (!tip) return;
    if (event.relatedTarget && tip.contains(event.relatedTarget)) return;
    hideInfoTooltip();
  });

  document.addEventListener("focusin", (event) => {
    if (event.target.classList?.contains("info-tip")) showInfoTooltip(event.target);
  });

  document.addEventListener("focusout", (event) => {
    if (event.target.classList?.contains("info-tip")) hideInfoTooltip();
  });

  ["pointerdown", "mousedown", "click"].forEach((type) => {
    document.addEventListener(
      type,
      (event) => {
        const tip = event.target.closest?.(".info-tip");
        if (!tip) return;
        event.preventDefault();
        event.stopPropagation();
      },
      true,
    );
  });

  window.addEventListener("scroll", hideInfoTooltip, true);
  window.addEventListener("resize", hideInfoTooltip);
}
