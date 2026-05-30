export function createToolApprovalController({
  state,
  modal,
  name,
  description,
  argumentsEl,
  approveButton,
  alwaysAllowButton,
  denyButton,
}) {
  function request(requestPayload) {
    return new Promise((resolve) => {
      state.pendingToolApproval = resolve;
      const definition = requestPayload.tool_definition || {};
      const meta = definition.meta || {};
      const preview = requestPayload.preview || null;
      name.textContent = requestPayload.tool || definition.name || "Unknown tool";
      description.textContent = definition.description || requestPayload.message || "The model wants to run this function.";
      if (preview?.diff) {
        argumentsEl.textContent = [
          `Path: ${preview.path || requestPayload.arguments?.path || ""}`,
          `Before: ${preview.before_sha256 || ""}`,
          `After:  ${preview.after_sha256 || ""}`,
          "",
          preview.diff,
        ].join("\n");
        argumentsEl.dataset.preview = "diff";
      } else {
        argumentsEl.textContent = JSON.stringify(requestPayload.arguments || {}, null, 2);
        argumentsEl.dataset.preview = "arguments";
      }
      alwaysAllowButton.hidden = meta.requiresPerCallConfirmation === true;
      modal.classList.add("open");
      modal.setAttribute("aria-hidden", "false");
    });
  }

  function finish(result) {
    const resolve = state.pendingToolApproval;
    state.pendingToolApproval = null;
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    alwaysAllowButton.hidden = false;
    delete argumentsEl.dataset.preview;
    if (resolve) resolve(result);
  }

  approveButton.addEventListener("click", () => {
    finish({ approved: true, alwaysAllow: false });
  });

  alwaysAllowButton.addEventListener("click", () => {
    finish({ approved: true, alwaysAllow: true });
  });

  denyButton.addEventListener("click", () => {
    finish({ approved: false, alwaysAllow: false });
  });

  return { finish, request };
}
