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

export async function startMessageStream({ chatId, body, onEvent }) {
  const response = await fetch(`/api/chats/${chatId}/messages/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (frame) => {
    const event = parseFrameEvent(frame);
    if (event) onEvent(event);
  };

  const drainBuffer = () => {
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    frames.forEach(dispatch);
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    drainBuffer();
  }
  buffer += decoder.decode();
  drainBuffer();
  if (buffer.trim()) dispatch(buffer);
}
