import { api } from "../api.js";
import { escapeHtml } from "../helpers.js";
import { state } from "../state.js";
import { uiIcon } from "../ui.js";

export function createChatList({ chatList, chatTitle, chatWorkspace, input, setStatus, bridge }) {
  function displayChatTitle(chat) {
    const title = typeof chat === "string" ? chat : chat?.title;
    return title === "Neuer Chat" ? "New Chat" : title || "Chat";
  }

  function isDefaultChatTitle(title) {
    return title === "Neuer Chat" || title === "New Chat";
  }

  function activeChat() {
    return state.chats.find((item) => item.id === state.activeChatId) || null;
  }

  function workspaceLabel(chat) {
    const path = chat?.workspace_path?.trim();
    if (path) return path;
    const fallbackPath = state.settings?.workspace_path?.trim();
    return fallbackPath || "No workspace configured";
  }

  function syncHeaderWorkspace(chat = activeChat()) {
    const label = workspaceLabel(chat);
    chatWorkspace.textContent = label;
    chatWorkspace.title = label;
    chatWorkspace.classList.toggle("is-empty", label === "No workspace configured");
  }

  function renderChats() {
    chatList.innerHTML = "";
    for (const chat of state.chats) {
      const item = document.createElement("div");
      item.className = "chat-item-wrap";
      item.classList.toggle("active", chat.id === state.activeChatId);

      const button = document.createElement("button");
      button.className = "chat-item";
      button.type = "button";
      button.innerHTML = `<span class="chat-item-title">${escapeHtml(displayChatTitle(chat))}</span>`;
      button.addEventListener("click", () => selectChat(chat.id));

      const deleteButton = document.createElement("button");
      deleteButton.className = "chat-delete-button";
      deleteButton.type = "button";
      deleteButton.setAttribute("aria-label", `Delete ${displayChatTitle(chat)}`);
      deleteButton.innerHTML = uiIcon("trash");
      deleteButton.addEventListener("click", (event) => {
        event.stopPropagation();
        deleteChat(chat.id, chat.title).catch((error) => setStatus(error.message, true));
      });

      item.append(button, deleteButton);
      chatList.append(item);
    }
  }

  function mergeChat(updatedChat) {
    if (!updatedChat?.id) return;
    const exists = state.chats.some((chat) => chat.id === updatedChat.id);
    state.chats = exists
      ? state.chats.map((chat) => chat.id === updatedChat.id ? updatedChat : chat)
      : [updatedChat, ...state.chats];
    renderChats();
    if (state.activeChatId === updatedChat.id) {
      chatTitle.textContent = displayChatTitle(updatedChat);
      syncHeaderWorkspace(updatedChat);
    }
  }

  function stopWatchingChatTitle(chatId) {
    const timer = state.titleWatchers.get(chatId);
    if (timer) {
      window.clearInterval(timer);
    }
    state.titleWatchers.delete(chatId);
  }

  function watchChatTitle(chatId) {
    const chat = state.chats.find((item) => item.id === chatId);
    if (!chat || !isDefaultChatTitle(chat.title)) return;
    stopWatchingChatTitle(chatId);

    let attempts = 0;
    const timer = window.setInterval(async () => {
      attempts += 1;
      try {
        const updatedChat = await api(`/api/chats/${chatId}`);
        mergeChat(updatedChat);
        if (!isDefaultChatTitle(updatedChat.title) || attempts >= 50) {
          stopWatchingChatTitle(chatId);
        }
      } catch (_error) {
        stopWatchingChatTitle(chatId);
      }
    }, 1200);
    state.titleWatchers.set(chatId, timer);
  }

  async function loadChats() {
    state.chats = await api("/api/chats");
    if (!state.activeChatId && state.chats.length > 0) {
      state.activeChatId = state.chats[0].id;
    }
    renderChats();
    const chat = activeChat();
    if (chat) {
      chatTitle.textContent = displayChatTitle(chat);
      syncHeaderWorkspace(chat);
    }
  }

  async function selectChat(chatId) {
    state.activeChatId = chatId;
    const chat = activeChat();
    chatTitle.textContent = chat ? displayChatTitle(chat) : "Chat";
    syncHeaderWorkspace(chat);
    renderChats();
    await bridge.loadActiveModeMessages();
    bridge.animateViewShift();
  }

  async function saveChatWorkspace(workspace) {
    const chat = activeChat();
    if (!chat) return;
    const nextWorkspace = workspace.trim();
    if (nextWorkspace === (chat.workspace_path || "")) return;
    const updated = await api(`/api/chats/${chat.id}`, {
      method: "PUT",
      body: JSON.stringify({ workspace_path: nextWorkspace }),
    });
    mergeChat(updated);
  }

  async function createChat() {
    setStatus("Creating chat...");
    const chat = await api("/api/chats", {
      method: "POST",
      body: JSON.stringify({ title: null }),
    });
    state.activeChatId = chat.id;
    await loadChats();
    await selectChat(chat.id);
    input.focus();
    setStatus("Ready");
  }

  async function deleteChat(chatId, title) {
    const confirmed = window.confirm(`Delete chat "${displayChatTitle(title)}"?`);
    if (!confirmed) return;

    stopWatchingChatTitle(chatId);
    await api(`/api/chats/${chatId}`, { method: "DELETE" });
    if (state.activeChatId === chatId) {
      state.activeChatId = null;
    }
    await loadChats();
    if (state.activeChatId) {
      await selectChat(state.activeChatId);
    } else if (state.chats.length > 0) {
      await selectChat(state.chats[0].id);
    } else {
      chatTitle.textContent = "No Chat Selected";
      syncHeaderWorkspace(null);
      bridge.renderMessages([]);
    }
    setStatus("Chat deleted");
  }

  return {
    displayChatTitle,
    isDefaultChatTitle,
    activeChat,
    workspaceLabel,
    syncHeaderWorkspace,
    renderChats,
    mergeChat,
    stopWatchingChatTitle,
    watchChatTitle,
    loadChats,
    selectChat,
    saveChatWorkspace,
    createChat,
    deleteChat,
  };
}
