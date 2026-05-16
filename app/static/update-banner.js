const POLL_INTERVAL_MS = 1500;

export function createUpdateBanner({ setStatus } = {}) {
  const pill = document.getElementById("update-pill");
  const modal = document.getElementById("update-modal");
  const installButton = document.getElementById("update-modal-install");
  const currentEl = document.getElementById("update-modal-current");
  const latestEl = document.getElementById("update-modal-latest");
  const notesEl = document.getElementById("update-modal-notes");
  const progressEl = document.getElementById("update-modal-progress");

  if (!pill || !modal || !installButton) {
    return { init() {} };
  }

  let info = null;
  let pollTimer = null;

  function openModal() {
    if (!info) return;
    currentEl.textContent = info.current ? `v${info.current}` : "current";
    latestEl.textContent = info.latest ? info.latest : "";
    notesEl.textContent = (info.notes || "").trim() || "No release notes provided.";
    progressEl.hidden = true;
    progressEl.textContent = "";
    installButton.disabled = false;
    installButton.textContent = "Install & Restart";
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
  }

  function closeModal() {
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  }

  modal.querySelectorAll("[data-update-modal-close]").forEach((el) => {
    el.addEventListener("click", closeModal);
  });
  modal.addEventListener("click", (event) => {
    if (event.target === modal) closeModal();
  });

  function showProgress(text) {
    progressEl.hidden = false;
    progressEl.textContent = text;
  }

  async function pollStatus() {
    try {
      const response = await fetch("/api/updates/status");
      if (!response.ok) return;
      const status = await response.json();
      if (status.status === "downloading") {
        const pct = Math.round((status.progress || 0) * 100);
        showProgress(`Downloading update… ${pct}%`);
      } else if (status.status === "staging") {
        showProgress("Preparing installer…");
      } else if (status.status === "swapping") {
        showProgress("Restarting to finish update…");
      } else if (status.status === "error") {
        showProgress(`Update failed: ${status.message}`);
        installButton.disabled = false;
        return;
      }
      pollTimer = window.setTimeout(pollStatus, POLL_INTERVAL_MS);
    } catch (error) {
      showProgress(`Update failed: ${error.message}`);
      installButton.disabled = false;
    }
  }

  installButton.addEventListener("click", async () => {
    installButton.disabled = true;
    installButton.textContent = "Installing…";
    showProgress("Starting update…");
    try {
      const response = await fetch("/api/updates/install", { method: "POST" });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.detail || `HTTP ${response.status}`);
      }
      pollStatus();
    } catch (error) {
      showProgress(`Update failed: ${error.message}`);
      installButton.disabled = false;
      installButton.textContent = "Install & Restart";
      setStatus?.(error.message, true);
    }
  });

  pill.addEventListener("click", openModal);

  async function check() {
    try {
      const response = await fetch("/api/updates/check");
      if (!response.ok) return;
      const data = await response.json();
      info = data;
      if (data.available && data.asset_url) {
        const label = pill.querySelector(".update-pill-label");
        if (label && data.latest) label.textContent = `Update ${data.latest}`;
        pill.hidden = false;
      } else {
        pill.hidden = true;
      }
    } catch {
      // Silent — update check is best-effort.
    }
  }

  return {
    init() {
      check();
    },
  };
}
