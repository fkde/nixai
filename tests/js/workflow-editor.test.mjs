import test from "node:test";
import assert from "node:assert/strict";

import {
  cloneWorkflowDraft,
  dedupeList,
  parseCsvList,
} from "../../app/static/workflow-editor.js";

test("parseCsvList trims entries and drops empty values", () => {
  assert.deepEqual(parseCsvList(" one, two ,, three , "), ["one", "two", "three"]);
  assert.deepEqual(parseCsvList(null), []);
});

test("dedupeList trims values, preserves first occurrence order, and drops blanks", () => {
  assert.deepEqual(dedupeList([" a ", "b", "a", "", null, " b "]), ["a", "b"]);
});

test("cloneWorkflowDraft returns a deep copy", () => {
  const original = { nodes: [{ id: "a", config: { nested: true } }] };
  const clone = cloneWorkflowDraft(original);
  clone.nodes[0].config.nested = false;

  assert.equal(original.nodes[0].config.nested, true);
  assert.notEqual(clone, original);
  assert.notEqual(clone.nodes[0], original.nodes[0]);
});
