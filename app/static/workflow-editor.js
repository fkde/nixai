export function parseCsvList(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function dedupeList(values) {
  const seen = new Set();
  const result = [];
  values.forEach((value) => {
    const clean = String(value || "").trim();
    if (!clean || seen.has(clean)) return;
    seen.add(clean);
    result.push(clean);
  });
  return result;
}

export function cloneWorkflowDraft(value) {
  if (typeof structuredClone === "function") {
    return structuredClone(value);
  }
  return JSON.parse(JSON.stringify(value));
}
