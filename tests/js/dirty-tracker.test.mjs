import test from "node:test";
import assert from "node:assert/strict";

import {
  dirtyStorageKey,
  hasDirtyTracker,
  registerDirtyTracker,
  safeLocalStorageGet,
} from "../../app/static/dirty-tracker.js";

const originalWindow = globalThis.window;

function createStorage(throwing = false) {
  const values = new Map();
  return {
    values,
    getItem(key) {
      if (throwing) throw new Error("blocked");
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      if (throwing) throw new Error("blocked");
      values.set(key, String(value));
    },
    removeItem(key) {
      if (throwing) throw new Error("blocked");
      values.delete(key);
    },
  };
}

function createFakeForm({ id = "form-id", dirtyTrack = "" } = {}) {
  const listeners = new Map();
  return {
    id,
    dataset: dirtyTrack ? { dirtyTrack } : {},
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
    dispatch(type) {
      listeners.get(type)?.();
    },
  };
}

test.afterEach(() => {
  globalThis.window = originalWindow;
});

test("dirtyStorageKey prefers explicit keys, then data attribute, then form id", () => {
  const form = createFakeForm({ id: "settings", dirtyTrack: "settings-panel" });

  assert.equal(dirtyStorageKey(form, "explicit"), "nixai:dirty:explicit");
  assert.equal(dirtyStorageKey(form), "nixai:dirty:settings-panel");
  assert.equal(dirtyStorageKey(createFakeForm({ id: "profile" })), "nixai:dirty:profile");
  assert.equal(dirtyStorageKey(null), "nixai:dirty:form");
});

test("safeLocalStorageGet returns null when storage access is blocked", () => {
  globalThis.window = { localStorage: createStorage(true) };

  assert.equal(safeLocalStorageGet("anything"), null);
});

test("registerDirtyTracker captures baselines, stores dirty drafts, and clears clean snapshots", () => {
  const storage = createStorage();
  globalThis.window = { localStorage: storage };
  const form = createFakeForm();
  let snapshot = { fields: [{ locator: "id:name", value: "initial" }] };
  const changes = [];
  const tracker = registerDirtyTracker(form, {
    storageKey: "profile",
    getSnapshot: () => snapshot,
    onDirtyChange: (dirty, currentSnapshot) => changes.push({ dirty, currentSnapshot }),
  });

  assert.equal(hasDirtyTracker(form), true);
  tracker.captureBaseline();
  assert.equal(storage.values.has("nixai:dirty:profile"), false);

  snapshot = { fields: [{ locator: "id:name", value: "changed" }] };
  assert.equal(tracker.refresh(), true);
  assert.equal(JSON.parse(storage.values.get("nixai:dirty:profile")).snapshot.fields[0].value, "changed");

  snapshot = { fields: [{ locator: "id:name", value: "initial" }] };
  assert.equal(tracker.refresh(), false);
  assert.equal(storage.values.has("nixai:dirty:profile"), false);
  assert.deepEqual(changes.map((change) => change.dirty), [false, true, false]);
});

test("registerDirtyTracker responds to input and change events", () => {
  const storage = createStorage();
  globalThis.window = { localStorage: storage };
  const form = createFakeForm();
  let value = "a";
  let dirtyChanges = 0;
  const tracker = registerDirtyTracker(form, {
    storageKey: "events",
    getSnapshot: () => ({ value }),
    onDirtyChange: (dirty) => {
      if (dirty) dirtyChanges += 1;
    },
  });
  tracker.captureBaseline();

  value = "b";
  form.dispatch("input");
  value = "c";
  form.dispatch("change");

  assert.equal(dirtyChanges, 2);
  assert.equal(JSON.parse(storage.values.get("nixai:dirty:events")).snapshot.value, "c");
});

test("restoreDraftIfAny applies valid stored drafts and removes stale or invalid drafts", () => {
  const storage = createStorage();
  globalThis.window = { localStorage: storage };
  const form = createFakeForm();
  let snapshot = { value: "clean" };
  const applied = [];
  const tracker = registerDirtyTracker(form, {
    storageKey: "restore",
    getSnapshot: () => snapshot,
    applySnapshot: (draft) => {
      applied.push(draft);
      snapshot = draft;
    },
  });
  tracker.captureBaseline();

  storage.setItem("nixai:dirty:restore", JSON.stringify({ snapshot: { value: "draft" } }));
  assert.equal(tracker.restoreDraftIfAny(), true);
  assert.deepEqual(applied, [{ value: "draft" }]);

  tracker.captureBaseline({ value: "draft" });
  storage.setItem("nixai:dirty:restore", JSON.stringify({ snapshot: { value: "draft" } }));
  assert.equal(tracker.restoreDraftIfAny(), false);
  assert.equal(storage.values.has("nixai:dirty:restore"), false);

  storage.setItem("nixai:dirty:restore", "{not-json");
  assert.equal(tracker.restoreDraftIfAny(), false);
  assert.equal(storage.values.has("nixai:dirty:restore"), false);
});
