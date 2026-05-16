import { api } from "./api.js";
import { dom } from "./dom.js";
import { escapeHtml, formatContent } from "./helpers.js";
import { state } from "./state.js";

const {
  agenticTaskList,
  newAgenticTaskButton,
  saveAgenticTaskButton,
  deleteAgenticTaskButton,
  runAgenticTaskButton,
  agenticSchedulerStatus,
  agenticRunList,
  agenticTaskTitle,
  agenticTaskSchedule,
  agenticTaskStatus,
  agenticTaskPrompt,
} = dom;

export function createAgenticTasksUi({ setStatus }) {
  function activeAgenticTask() {
    return state.agenticTasks.find((task) => task.id === state.activeTaskId) || null;
  }

  function renderAgenticTasks() {
    agenticTaskList.innerHTML = "";
    if (state.agenticTasks.length === 0) {
      agenticTaskList.innerHTML = '<p class="settings-empty">No agentic tasks yet.</p>';
    }
    state.agenticTasks.forEach((task) => {
      const button = document.createElement("button");
      button.className = "agentic-task-item";
      button.classList.toggle("active", task.id === state.activeTaskId);
      button.type = "button";
      button.innerHTML = `
        <span>${escapeHtml(task.title)}</span>
        <small>${escapeHtml(task.schedule)} · ${escapeHtml(task.status)} · next ${escapeHtml(task.next_run_at || "pending")}</small>
      `;
      button.addEventListener("click", () => {
        state.activeTaskId = task.id;
        renderAgenticTasks();
        renderAgenticTaskEditor();
        loadAgenticRuns(task.id).catch((error) => setStatus(error.message, true));
      });
      agenticTaskList.append(button);
    });
    renderAgenticTaskEditor();
  }

  function renderAgenticTaskEditor() {
    const task = activeAgenticTask();
    deleteAgenticTaskButton.disabled = !task;
    runAgenticTaskButton.disabled = !task;
    agenticTaskTitle.value = task?.title || "";
    agenticTaskSchedule.value = task?.schedule || "daily at 18:00";
    agenticTaskStatus.value = task?.status || "active";
    agenticTaskPrompt.value = task?.prompt || "";
  }

  function renderAgenticRuns() {
    agenticRunList.innerHTML = "";
    if (!state.activeTaskId) {
      agenticRunList.innerHTML = '<p class="settings-empty">Select a task.</p>';
      return;
    }
    if (state.agenticRuns.length === 0) {
      agenticRunList.innerHTML = '<p class="settings-empty">No runs yet.</p>';
      return;
    }
    state.agenticRuns.forEach((run) => {
      const item = document.createElement("article");
      item.className = `agentic-run-item ${run.status}`;
      const summary = runSummaryParts(run.summary || run.error || "No result text.");
      item.innerHTML = `
        <div>
          <strong>${escapeHtml(run.status)}</strong>
          <small>${escapeHtml(run.started_at)} · attempt ${escapeHtml(run.attempt)}</small>
        </div>
        <section class="run-summary">${formatContent(summary.main)}</section>
        ${summary.details ? `
          <details class="run-details">
            <summary>Review details</summary>
            <div>${formatContent(summary.details)}</div>
          </details>
        ` : ""}
      `;
      agenticRunList.append(item);
    });
  }

  function runSummaryParts(value) {
    const clean = String(value || "")
      .replace(/\*{3,}/g, "\n\n")
      .replace(/#{1,6}\s*Reviewer Findings/gi, "### Review")
      .replace(/#{1,6}\s*Recommendations/gi, "### Recommendations")
      .trim();
    const detailsStart = clean.search(/(^|\n)\s*(#{2,6}\s*(Review|Recommendations)|\*\*Correctness:\*\*|\*\*Safety:\*\*)/i);
    if (detailsStart <= 0) {
      return { main: clean, details: "" };
    }
    return {
      main: clean.slice(0, detailsStart).trim(),
      details: clean.slice(detailsStart).trim(),
    };
  }

  async function loadAgenticTasks() {
    state.agenticTasks = await api("/api/agentic-tasks");
    if (state.activeTaskId && !state.agenticTasks.some((task) => task.id === state.activeTaskId)) {
      state.activeTaskId = null;
    }
    renderAgenticTasks();
    if (state.activeTaskId) {
      await loadAgenticRuns(state.activeTaskId);
    } else {
      state.agenticRuns = [];
      renderAgenticRuns();
    }
  }

  async function loadAgenticRuns(taskId) {
    if (!taskId) {
      state.agenticRuns = [];
      renderAgenticRuns();
      return;
    }
    state.agenticRuns = await api(`/api/agentic-tasks/${taskId}/runs`);
    renderAgenticRuns();
  }

  async function loadSchedulerStatus() {
    const status = await api("/api/agentic-tasks/scheduler/status");
    agenticSchedulerStatus.textContent = status.running
      ? `Scheduler active · ${status.active_runs.length} active run(s)`
      : "Scheduler paused";
  }

  function init() {
    newAgenticTaskButton.addEventListener("click", () => {
      state.activeTaskId = null;
      renderAgenticTasks();
      agenticTaskTitle.focus();
    });

    saveAgenticTaskButton.addEventListener("click", async () => {
      const payload = {
        title: agenticTaskTitle.value.trim(),
        schedule: agenticTaskSchedule.value.trim(),
        status: agenticTaskStatus.value,
        prompt: agenticTaskPrompt.value.trim(),
      };
      if (!payload.title || !payload.schedule || !payload.prompt) {
        setStatus("Title, schedule, and task are required.", true);
        return;
      }
      try {
        const task = activeAgenticTask();
        const saved = await api(task ? `/api/agentic-tasks/${task.id}` : "/api/agentic-tasks", {
          method: task ? "PUT" : "POST",
          body: JSON.stringify(payload),
        });
        state.activeTaskId = saved.id;
        await loadAgenticTasks();
        setStatus("Agentic task saved");
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    deleteAgenticTaskButton.addEventListener("click", async () => {
      const task = activeAgenticTask();
      if (!task) return;
      try {
        await api(`/api/agentic-tasks/${task.id}`, { method: "DELETE" });
        state.activeTaskId = null;
        state.agenticRuns = [];
        await loadAgenticTasks();
        setStatus("Agentic task deleted");
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    runAgenticTaskButton.addEventListener("click", async () => {
      const task = activeAgenticTask();
      if (!task) return;
      runAgenticTaskButton.disabled = true;
      setStatus("Agentic task running...");
      try {
        await api(`/api/agentic-tasks/${task.id}/run-now`, { method: "POST" });
        await loadAgenticTasks();
        await loadAgenticRuns(task.id);
        await loadSchedulerStatus();
        setStatus("Agentic run finished");
      } catch (error) {
        setStatus(error.message, true);
      } finally {
        runAgenticTaskButton.disabled = !activeAgenticTask();
      }
    });
  }

  return {
    activeAgenticTask,
    init,
    loadAgenticRuns,
    loadAgenticTasks,
    loadSchedulerStatus,
    renderAgenticRuns,
    renderAgenticTaskEditor,
    renderAgenticTasks,
  };
}
