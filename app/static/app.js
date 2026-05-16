import { createAgenticTasksUi } from "./agentic-tasks-ui.js";
import { createToolApprovalController } from "./approvals-ui.js";
import { createChatUi } from "./chat.js";
import { dom } from "./dom.js";
import { createMistakesUi } from "./mistakes-ui.js";
import { createRolesUi } from "./roles-ui.js";
import { createSettingsUi } from "./settings.js";
import { state } from "./state.js";
import { createUpdateBanner } from "./update-banner.js";
import {
  createStatusController,
  initDesktopChrome,
  initGenericDirtyTracking,
  initInfoTooltips,
} from "./ui.js";
import { createWorkflowsUi } from "./workflows-ui.js";

const {
  settingsToggle,
  toolApprovalModal,
  toolApprovalName,
  toolApprovalDescription,
  toolApprovalArguments,
  approveToolCallButton,
  alwaysAllowToolCallButton,
  denyToolCallButton,
} = dom;

const { setStatus } = createStatusController();

const toolApprovals = createToolApprovalController({
  state,
  modal: toolApprovalModal,
  name: toolApprovalName,
  description: toolApprovalDescription,
  argumentsEl: toolApprovalArguments,
  approveButton: approveToolCallButton,
  alwaysAllowButton: alwaysAllowToolCallButton,
  denyButton: denyToolCallButton,
});

let chatUi;
let settingsUi;
let workflowsUi;
let rolesUi;
let mistakesUi;
let agenticTasksUi;

settingsUi = createSettingsUi({
  setStatus,
  getChatUi: () => chatUi,
  getWorkflowsUi: () => workflowsUi,
  loadDeferred: () => loadStartupDeferred(),
});

workflowsUi = createWorkflowsUi({
  setStatus,
  getSettingsUi: () => settingsUi,
});

rolesUi = createRolesUi({
  setStatus,
  getSettingsUi: () => settingsUi,
  getWorkflowsUi: () => workflowsUi,
});

mistakesUi = createMistakesUi({ setStatus });
agenticTasksUi = createAgenticTasksUi({ setStatus });

chatUi = createChatUi({
  setStatus,
  toolApprovals,
  getSettingsUi: () => settingsUi,
  getAgenticTasksUi: () => agenticTasksUi,
});

function initFeatureWiring() {
  chatUi.init();
  settingsUi.init();
  workflowsUi.init();
  rolesUi.init();
  mistakesUi.init();
  agenticTasksUi.init();

  settingsToggle.addEventListener("click", () => {
    settingsUi.openSettings();
  });
}

async function loadStartupCritical() {
  await settingsUi.loadSettings(true);
  await Promise.all([
    workflowsUi.loadWorkflowPresets(),
    chatUi.loadChats(),
  ]);
  if (state.activeChatId) {
    await chatUi.selectChat(state.activeChatId);
  } else {
    chatUi.renderMessages([]);
  }
}

function loadStartupDeferred() {
  Promise.all([
    rolesUi.loadRoles(),
    mistakesUi.loadMistakes(),
    agenticTasksUi.loadAgenticTasks(),
    agenticTasksUi.loadSchedulerStatus(),
    settingsUi.loadTools(),
  ])
    .catch((error) => setStatus(error.message, true));
}

initFeatureWiring();
chatUi.renderModeSwitch();
settingsUi.renderEffortSwitch();
initDesktopChrome(chatUi.stabilizeMessagesBottomScroll);
initGenericDirtyTracking();
initInfoTooltips();

const updateBanner = createUpdateBanner({ setStatus });
updateBanner.init();

loadStartupCritical()
  .then(() => {
    setStatus("Ready");
    window.setTimeout(loadStartupDeferred, 0);
  })
  .catch((error) => setStatus(error.message, true));
