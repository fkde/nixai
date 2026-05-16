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
      name.textContent = requestPayload.tool || definition.name || "Unknown tool";
      description.textContent = definition.description || requestPayload.message || "The model wants to run this function.";
      argumentsEl.textContent = JSON.stringify(requestPayload.arguments || {}, null, 2);
      modal.classList.add("open");
      modal.setAttribute("aria-hidden", "false");
    });
  }

  function finish(result) {
    const resolve = state.pendingToolApproval;
    state.pendingToolApproval = null;
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
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
