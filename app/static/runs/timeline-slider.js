import { escapeHtml } from "../helpers.js";

const MARK_TYPES = new Set(["node_failed", "node_finished", "run_finished", "run_failed", "run_paused"]);

export function createTimelineSlider({ host, onChange }) {
  let events = [];
  let position = 0;
  let live = true;
  let playing = false;
  let playTimer = null;

  function render() {
    if (!host) return;
    const current = events[Math.max(0, position - 1)] || null;
    const marks = events
      .map((event, index) => ({ event, index: index + 1 }))
      .filter(({ event }) => MARK_TYPES.has(event.type))
      .map(({ event, index }) => {
        const left = events.length ? (index / events.length) * 100 : 0;
        return `<button class="runs-timeline-tick runs-timeline-${escapeHtml(event.type)}" type="button" data-timeline-index="${index}" style="left:${left}%"></button>`;
      })
      .join("");
    host.innerHTML = `
      <div class="runs-timeline-controls">
        <button type="button" class="settings-secondary-button" data-timeline-action="home">Home</button>
        <button type="button" class="settings-secondary-button" data-timeline-action="prev">Prev</button>
        <button type="button" class="settings-secondary-button" data-timeline-action="play">${playing ? "Pause" : "Play"}</button>
        <button type="button" class="settings-secondary-button" data-timeline-action="next">Next</button>
        <button type="button" class="settings-secondary-button" data-timeline-action="live" ${live ? "disabled" : ""}>Live</button>
        <span class="runs-timeline-meta">${escapeHtml(label(current))}</span>
      </div>
      <div class="runs-timeline-track">
        <input type="range" min="0" max="${events.length}" value="${position}" data-timeline-range>
        <div class="runs-timeline-marks">${marks}</div>
      </div>
    `;
  }

  function label(event) {
    if (!event) return `event 0 / ${events.length}`;
    const date = event.ts ? new Date(event.ts) : null;
    const ts = date && !Number.isNaN(date.getTime()) ? date.toLocaleTimeString() : event.ts || "";
    return `seq ${event.seq ?? position} · event ${position}/${events.length}${ts ? ` · ${ts}` : ""}`;
  }

  function emit(details = {}) {
    onChange && onChange({ position, live, ...details });
  }

  function setPosition(next, { user = false } = {}) {
    position = Math.max(0, Math.min(events.length, Number(next) || 0));
    if (user && position < events.length) live = false;
    if (position >= events.length && user) live = true;
    render();
    emit({ user });
  }

  function step(delta) {
    setPosition(position + delta, { user: true });
  }

  function stopPlayback() {
    playing = false;
    if (playTimer !== null) clearInterval(playTimer);
    playTimer = null;
  }

  function togglePlayback() {
    if (playing) {
      stopPlayback();
      render();
      return;
    }
    live = false;
    playing = true;
    playTimer = setInterval(() => {
      if (position >= events.length) {
        stopPlayback();
        render();
        return;
      }
      setPosition(position + 1, { user: true });
    }, 450);
    render();
  }

  host?.addEventListener("input", (event) => {
    const range = event.target.closest("[data-timeline-range]");
    if (!range) return;
    stopPlayback();
    setPosition(range.value, { user: true });
  });

  host?.addEventListener("click", (event) => {
    const tick = event.target.closest("[data-timeline-index]");
    if (tick) {
      stopPlayback();
      setPosition(tick.dataset.timelineIndex, { user: true });
      return;
    }
    const action = event.target.closest("[data-timeline-action]")?.dataset.timelineAction;
    if (!action) return;
    if (action === "home") setPosition(0, { user: true });
    if (action === "prev") step(-1);
    if (action === "play") togglePlayback();
    if (action === "next") step(1);
    if (action === "live") {
      stopPlayback();
      live = true;
      setPosition(events.length);
    }
  });

  host?.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") { event.preventDefault(); step(-1); }
    if (event.key === "ArrowRight") { event.preventDefault(); step(1); }
    if (event.key === "Home") { event.preventDefault(); setPosition(0, { user: true }); }
    if (event.key === "End") { event.preventDefault(); live = true; setPosition(events.length); }
  });

  return {
    setEvents(nextEvents, { keepPosition = false } = {}) {
      events = Array.isArray(nextEvents) ? nextEvents : [];
      if (live) position = events.length;
      else if (!keepPosition) position = Math.min(position, events.length);
      render();
    },
    reset(nextEvents, { live: nextLive = false } = {}) {
      stopPlayback();
      events = Array.isArray(nextEvents) ? nextEvents : [];
      live = Boolean(nextLive);
      position = live ? events.length : 0;
      render();
    },
    get live() { return live; },
    get position() { return position; },
    goLive() {
      live = true;
      setPosition(events.length);
    },
  };
}
