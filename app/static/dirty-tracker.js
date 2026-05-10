const DIRTY_STORAGE_PREFIX = "nixai:dirty:";
const dirtyTrackers = new Map();

function stableSerialize(value) {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableSerialize(item)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value).sort(([a], [b]) => a.localeCompare(b));
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${stableSerialize(item)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function dirtyStorageKey(form, explicitKey = "") {
  const raw = String(explicitKey || form?.dataset?.dirtyTrack || form?.id || "form").trim();
  return `${DIRTY_STORAGE_PREFIX}${raw}`;
}

export function safeLocalStorageGet(key) {
  try {
    return window.localStorage.getItem(key);
  } catch (_error) {
    return null;
  }
}

function safeLocalStorageSet(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch (_error) {
    // ignore storage errors (quota/private mode)
  }
}

function safeLocalStorageRemove(key) {
  try {
    window.localStorage.removeItem(key);
  } catch (_error) {
    // ignore storage errors
  }
}

function serializeFormFields(form) {
  const elements = [...form.querySelectorAll("input, select, textarea")]
    .filter((element) => element.type !== "submit" && element.type !== "button" && element.type !== "reset");
  const nameCounts = new Map();
  return {
    kind: "fields-v1",
    fields: elements.map((element, index) => {
      const name = element.getAttribute("name") || "";
      const nameCount = name ? (nameCounts.get(name) || 0) : 0;
      if (name) nameCounts.set(name, nameCount + 1);
      const locator = element.id
        ? `id:${element.id}`
        : name
          ? `name:${name}:${nameCount}`
          : `index:${index}`;
      let value;
      if (element instanceof HTMLInputElement && (element.type === "checkbox" || element.type === "radio")) {
        value = element.checked;
      } else if (element instanceof HTMLSelectElement && element.multiple) {
        value = [...element.selectedOptions].map((option) => option.value);
      } else {
        value = element.value;
      }
      return { locator, index, value };
    }),
  };
}

function applySerializedFormFields(form, snapshot) {
  if (!snapshot || snapshot.kind !== "fields-v1" || !Array.isArray(snapshot.fields)) return;
  const elements = [...form.querySelectorAll("input, select, textarea")]
    .filter((element) => element.type !== "submit" && element.type !== "button" && element.type !== "reset");
  const byLocator = new Map();
  const nameCounts = new Map();
  elements.forEach((element, index) => {
    const name = element.getAttribute("name") || "";
    const nameCount = name ? (nameCounts.get(name) || 0) : 0;
    if (name) nameCounts.set(name, nameCount + 1);
    const locator = element.id
      ? `id:${element.id}`
      : name
        ? `name:${name}:${nameCount}`
        : `index:${index}`;
    byLocator.set(locator, element);
  });
  const dispatchReplayEvents = (element) => {
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  };
  snapshot.fields.forEach((entry) => {
    const element = byLocator.get(String(entry.locator || "")) || elements[Number(entry.index || 0)];
    if (!element) return;
    if (element instanceof HTMLInputElement && (element.type === "checkbox" || element.type === "radio")) {
      element.checked = Boolean(entry.value);
      dispatchReplayEvents(element);
      return;
    }
    if (element instanceof HTMLSelectElement && element.multiple) {
      const selected = Array.isArray(entry.value) ? new Set(entry.value.map((item) => String(item))) : new Set();
      [...element.options].forEach((option) => {
        option.selected = selected.has(option.value);
      });
      dispatchReplayEvents(element);
      return;
    }
    element.value = entry.value == null ? "" : String(entry.value);
    dispatchReplayEvents(element);
  });
}

class DirtyFormTracker {
  constructor(form, options = {}) {
    this.form = form;
    this.storageKey = dirtyStorageKey(form, options.storageKey || "");
    this.getSnapshot = options.getSnapshot || (() => serializeFormFields(form));
    this.applySnapshot = options.applySnapshot || ((snapshot) => applySerializedFormFields(form, snapshot));
    this.onDirtyChange = options.onDirtyChange || (() => {});
    this.baselineSignature = "";
    this.lastDirty = false;
  }

  _currentSnapshot() {
    return this.getSnapshot();
  }

  _signature(snapshot) {
    return stableSerialize(snapshot ?? null);
  }

  captureBaseline(snapshot = null) {
    const baseline = snapshot ?? this._currentSnapshot();
    this.baselineSignature = this._signature(baseline);
    this.refresh();
    if (!this.lastDirty) {
      safeLocalStorageRemove(this.storageKey);
    }
  }

  refresh() {
    const snapshot = this._currentSnapshot();
    const currentSignature = this._signature(snapshot);
    const dirty = Boolean(this.baselineSignature) && currentSignature !== this.baselineSignature;
    this.lastDirty = dirty;
    this.onDirtyChange(dirty, snapshot);
    if (dirty) {
      safeLocalStorageSet(this.storageKey, JSON.stringify({
        snapshot,
        updatedAt: Date.now(),
      }));
    } else {
      safeLocalStorageRemove(this.storageKey);
    }
    return dirty;
  }

  restoreDraftIfAny() {
    const raw = safeLocalStorageGet(this.storageKey);
    if (!raw) return false;
    try {
      const parsed = JSON.parse(raw);
      const snapshot = parsed?.snapshot;
      if (!snapshot) return false;
      if (this._signature(snapshot) === this.baselineSignature) {
        safeLocalStorageRemove(this.storageKey);
        return false;
      }
      this.applySnapshot(snapshot);
      this.refresh();
      return this.lastDirty;
    } catch (_error) {
      safeLocalStorageRemove(this.storageKey);
      return false;
    }
  }
}

export function hasDirtyTracker(form) {
  return dirtyTrackers.has(form);
}

export function registerDirtyTracker(form, options = {}) {
  if (!form) return null;
  const tracker = new DirtyFormTracker(form, options);
  form.addEventListener("input", () => tracker.refresh());
  form.addEventListener("change", () => tracker.refresh());
  dirtyTrackers.set(form, tracker);
  return tracker;
}
