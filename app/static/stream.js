export function parseFrameEvent(frame) {
  const dataLines = frame
    .split("\n")
    .map((item) => item.trimEnd())
    .filter((item) => item.startsWith("data:"));
  if (dataLines.length === 0) return null;
  const payload = dataLines
    .map((item) => item.startsWith("data: ") ? item.slice(6) : item.slice(5))
    .join("\n");
  try {
    return JSON.parse(payload);
  } catch (_error) {
    return null;
  }
}
