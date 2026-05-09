const state = {
  chats: [],
  activeChatId: null,
  loading: false,
};

const chatList = document.querySelector("#chat-list");
const messagesEl = document.querySelector("#messages");
const chatTitle = document.querySelector("#chat-title");
const statusEl = document.querySelector("#status");
const form = document.querySelector("#message-form");
const input = document.querySelector("#message-input");
const sendButton = document.querySelector("#send-button");
const newChatButton = document.querySelector("#new-chat");

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatContent(content) {
  const escaped = escapeHtml(content);
  return escaped.replace(/```([\s\S]*?)```/g, (_match, code) => `<pre><code>${code.trim()}</code></pre>`);
}

function renderChats() {
  chatList.innerHTML = "";
  for (const chat of state.chats) {
    const button = document.createElement("button");
    button.className = "chat-item";
    button.classList.toggle("active", chat.id === state.activeChatId);
    button.type = "button";
    button.textContent = chat.title;
    button.addEventListener("click", () => selectChat(chat.id));
    chatList.append(button);
  }
}

function renderMessages(messages) {
  messagesEl.innerHTML = "";
  if (!state.activeChatId) {
    messagesEl.innerHTML = '<p class="empty">Lege links einen Chat an und sende deine erste Nachricht.</p>';
    return;
  }
  if (messages.length === 0) {
    messagesEl.innerHTML = '<p class="empty">Dieser Chat ist noch leer.</p>';
    return;
  }
  for (const message of messages) {
    const item = document.createElement("article");
    item.className = `message ${message.role}`;
    item.innerHTML = `
      <div class="message-role">${message.role}</div>
      <div class="bubble">${formatContent(message.content)}</div>
    `;
    messagesEl.append(item);
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

async function loadChats() {
  state.chats = await api("/api/chats");
  if (!state.activeChatId && state.chats.length > 0) {
    state.activeChatId = state.chats[0].id;
  }
  renderChats();
}

async function selectChat(chatId) {
  state.activeChatId = chatId;
  const chat = state.chats.find((item) => item.id === chatId);
  chatTitle.textContent = chat ? chat.title : "Chat";
  renderChats();
  const messages = await api(`/api/chats/${chatId}/messages`);
  renderMessages(messages);
}

async function createChat() {
  setStatus("erstelle Chat...");
  const chat = await api("/api/chats", {
    method: "POST",
    body: JSON.stringify({ title: null }),
  });
  state.activeChatId = chat.id;
  await loadChats();
  await selectChat(chat.id);
  input.focus();
  setStatus("bereit");
}

function setLoading(loading) {
  state.loading = loading;
  input.disabled = loading;
  sendButton.disabled = loading;
  setStatus(loading ? "Ollama antwortet..." : "bereit");
}

async function sendMessage(content) {
  if (!state.activeChatId) {
    await createChat();
  }
  setLoading(true);
  try {
    await api(`/api/chats/${state.activeChatId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    await loadChats();
    await selectChat(state.activeChatId);
    input.value = "";
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    setLoading(false);
  }
}

newChatButton.addEventListener("click", () => {
  createChat().catch((error) => setStatus(error.message, true));
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const content = input.value.trim();
  if (!content || state.loading) return;
  sendMessage(content);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

loadChats()
  .then(() => {
    if (state.activeChatId) return selectChat(state.activeChatId);
    renderMessages([]);
    return null;
  })
  .then(() => setStatus("bereit"))
  .catch((error) => setStatus(error.message, true));
