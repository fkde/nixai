import { api } from "./api.js";
import { dom } from "./dom.js";
import { escapeHtml } from "./helpers.js";
import { state } from "./state.js";
import { markdownPreview } from "./ui.js";

const {
  saveMistakesButton,
  analyzeMistakesButton,
  mistakesContent,
  mistakesPreview,
  mistakesModal,
  closeMistakesModalButton,
  mistakeEntryList,
  mistakeEntryDetail,
  suggestMistakeSolutionButton,
  acceptMistakeSolutionButton,
  mistakeSolution,
  mistakeSolutionHint,
} = dom;

export function createMistakesUi({ setStatus }) {
  function renderMistakes() {
    if (!state.mistakes) return;
    mistakesContent.value = state.mistakes.content || "";
    mistakesPreview.innerHTML = markdownPreview(state.mistakes.content || "");
  }

  function renderMistakeAnalyzeButton() {
    analyzeMistakesButton.disabled = state.mistakeEntries.length === 0;
  }

  function activeMistakeEntry() {
    return state.mistakeEntries.find((entry) => entry.id === state.activeMistakeId) || null;
  }

  function renderMistakeWizard() {
    renderMistakeAnalyzeButton();
    mistakeEntryList.innerHTML = "";
    if (state.mistakeEntries.length === 0) {
      mistakeEntryList.innerHTML = '<p class="settings-empty">No mistake entries found.</p>';
    }
    state.mistakeEntries.forEach((entry) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "mistake-entry-item";
      button.classList.toggle("active", entry.id === state.activeMistakeId);
      button.innerHTML = `
        <span>${escapeHtml(entry.title || "Untitled mistake")}</span>
        <small>${escapeHtml(entry.timestamp || "no timestamp")}</small>
      `;
      button.addEventListener("click", () => {
        state.activeMistakeId = entry.id;
        state.suggestedMistakeSolution = null;
        renderMistakeWizard();
      });
      mistakeEntryList.append(button);
    });

    const entry = activeMistakeEntry();
    mistakeEntryDetail.innerHTML = entry ? markdownPreview(entry.content) : "<p>Select a mistake.</p>";
    mistakeSolution.value = state.suggestedMistakeSolution?.instruction || "";
    mistakeSolutionHint.textContent = state.suggestedMistakeSolution?.rationale
      || "Select a mistake and ask for a fix suggestion.";
    suggestMistakeSolutionButton.disabled = !entry;
    acceptMistakeSolutionButton.disabled = !entry || !mistakeSolution.value.trim();
  }

  async function loadMistakes() {
    state.mistakes = await api("/api/mistakes");
    state.mistakeEntries = await api("/api/mistakes/entries");
    if (state.activeMistakeId && !state.mistakeEntries.some((entry) => entry.id === state.activeMistakeId)) {
      state.activeMistakeId = null;
    }
    renderMistakes();
    renderMistakeWizard();
  }

  function init() {
    mistakesContent.addEventListener("input", () => {
      mistakesPreview.innerHTML = markdownPreview(mistakesContent.value);
    });

    saveMistakesButton.addEventListener("click", async () => {
      try {
        state.mistakes = await api("/api/mistakes", {
          method: "PUT",
          body: JSON.stringify({ content: mistakesContent.value }),
        });
        state.mistakeEntries = await api("/api/mistakes/entries");
        renderMistakes();
        renderMistakeWizard();
        setStatus("Mistakes saved");
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    analyzeMistakesButton.addEventListener("click", async () => {
      await loadMistakes();
      if (!state.activeMistakeId && state.mistakeEntries.length > 0) {
        state.activeMistakeId = state.mistakeEntries[0].id;
      }
      mistakesModal.classList.add("open");
      mistakesModal.setAttribute("aria-hidden", "false");
      renderMistakeWizard();
    });

    closeMistakesModalButton.addEventListener("click", () => {
      mistakesModal.classList.remove("open");
      mistakesModal.setAttribute("aria-hidden", "true");
    });

    suggestMistakeSolutionButton.addEventListener("click", async () => {
      const entry = activeMistakeEntry();
      if (!entry) return;
      suggestMistakeSolutionButton.disabled = true;
      mistakeSolutionHint.textContent = "Distilling fix...";
      try {
        const solution = await api(`/api/mistakes/entries/${entry.id}/suggest-solution`, { method: "POST" });
        state.suggestedMistakeSolution = solution;
        mistakeSolution.value = solution.instruction || "";
        mistakeSolutionHint.textContent = solution.rationale || "Fix suggestion ready.";
        acceptMistakeSolutionButton.disabled = !mistakeSolution.value.trim();
      } catch (error) {
        mistakeSolutionHint.textContent = error.message;
      } finally {
        suggestMistakeSolutionButton.disabled = false;
      }
    });

    mistakeSolution.addEventListener("input", () => {
      acceptMistakeSolutionButton.disabled = !activeMistakeEntry() || !mistakeSolution.value.trim();
    });

    acceptMistakeSolutionButton.addEventListener("click", async () => {
      const entry = activeMistakeEntry();
      if (!entry) return;
      try {
        const payload = {
          title: state.suggestedMistakeSolution?.title || entry.title || "Reviewed mistake",
          instruction: mistakeSolution.value.trim(),
          rationale: state.suggestedMistakeSolution?.rationale || "",
        };
        await api(`/api/mistakes/entries/${entry.id}/accept-solution`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
        setStatus("Fix added to MEMORY.md");
        mistakeSolutionHint.textContent = "Added to MEMORY.md.";
      } catch (error) {
        setStatus(error.message, true);
      }
    });
  }

  return {
    activeMistakeEntry,
    init,
    loadMistakes,
    renderMistakeAnalyzeButton,
    renderMistakeWizard,
    renderMistakes,
  };
}
