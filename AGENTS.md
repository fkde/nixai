# AGENTS.md

Guidance for AI coding agents working on NixAI.

## Current Stand

NixAI is a local proof-of-concept AI agent runner for Ollama models. The current version is intentionally local-first, read-heavy, and approval-oriented.

Implemented:

- FastAPI backend with vanilla HTML/CSS/JS UI
- optional native desktop window through `pywebview`
- SQLite persistence for chats, messages, feedback, Agentic Tasks, and Agentic Task runs
- Ollama chat adapter using `/api/chat`, including streamed responses
- live assistant output with tokens-per-second status in the UI
- shared `chat`, `code`, and `agentic` message modes in one chat history
- configurable model-role mapping in settings
- editable Markdown role prompts for built-in and custom roles
- `TaskDiscovery` role for extracting recurring Agentic Task intent from user requests
- Agentic Task CRUD UI, scheduler, run history, failover, and pause-after-failure behavior
- read-only workspace context for Code mode through NixAI tools
- workspace filesystem, Git status/diff, allowlisted shell, and tool-search registry
- macOS desktop notification tool
- public URL check/fetch internet tools with private-address blocking
- RAG-style tool routing with keyword fallback and optional Ollama embeddings
- tool-call approval flow with `Einmal erlauben`, `Immer erlauben`, and global confirmation toggle
- grouped settings overlay over the chat area for Basis, Modelle, Prompts, Tools, Memory, and Agentic
- editable `MISTAKES.md` review source
- Mistakes review wizard that proposes future-facing fixes and writes accepted guidance to `MEMORY.md`
- shared reviewed `MEMORY.md` context injected into relevant model prompts
- PyInstaller spec and current local binary output at `dist/nixai`

Repository:

```text
origin git@github.com:fkde/nixai.git
branch main
```

Runtime target:

```text
Python 3.9+
```

Do not raise the Python minimum unless a concrete feature requires it and the tradeoff is documented.

## Common Commands

Install base dependencies:

```bash
pip install -r requirements.txt
```

Install desktop dependencies:

```bash
pip install -r requirements-desktop.txt
```

Run the web UI:

```bash
python -m app.cli serve
```

Open:

```text
http://127.0.0.1:8765
```

Run native desktop mode:

```bash
python -m app.cli desktop
```

Check desktop dependencies:

```bash
python -m app.cli desktop --check
```

Build the local binary:

```bash
python3 -m PyInstaller --clean nixai.spec
```

Check the built binary:

```bash
./dist/nixai desktop --check
```

Basic syntax checks:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/nixai-pycache python3 -m compileall app
node --check app/static/app.js
git diff --check
```

## Architecture

Interactive chat flow:

```text
UI
  -> FastAPI API
  -> Agent
  -> OllamaClient
  -> Ollama /api/chat
  -> streamed SSE token events
  -> SQLite persisted messages
```

Code mode context flow:

```text
User message
  -> CodeContextBuilder
  -> ToolRegistry
  -> workspace/Git/search tools
  -> WORKER.md + MEMORY.md + bounded tool results
  -> Ollama
```

Agentic task flow:

```text
User request
  -> TaskDiscovery
  -> Agentic Task definition or clarification
  -> scheduler/manual run
  -> AgenticRunner structured JSON plan
  -> approved autonomous tools
  -> reviewer summary / needs_review failover
```

Tool approval flow:

```text
/api/tools/call
  -> require_tool_confirmation?
  -> approval_required response
  -> UI prompt
  -> approved one time or always_allowed_tools
  -> ToolRegistry.call(...)
```

Scheduled Agentic runs cannot display an interactive prompt. They only execute tools that are autonomous-safe and either permanently allowed or covered by disabled confirmation. Otherwise the run becomes `needs_review`.

## Important Files

- `app/cli.py`: Typer CLI for `serve` and `desktop`
- `app/main.py`: FastAPI app, API router mounting, static UI mounting, scheduler lifecycle
- `app/desktop.py`: native desktop wrapper around the local FastAPI UI
- `app/database.py`: SQLite schema, migrations, chat/message/task/run persistence
- `app/models.py`: Pydantic request/response/domain models
- `app/config.py`: platformdirs-backed settings, model roles, tool approval settings
- `app/agent.py`: main chat/code/agentic orchestrator entrypoint
- `app/code_context.py`: bounded read-only Code mode context builder
- `app/task_discovery.py`: recurring-task intent extraction through the `task_discovery` role
- `app/agentic_scheduler.py`: background scheduler loop and manual run coordination
- `app/agentic_runner.py`: scheduled Agentic execution, approved tool calls, failover, summaries
- `app/agentic_schedule.py`: small recurring schedule parser
- `app/roles.py`: default/custom role prompt storage and filename safety
- `app/mistakes.py`: `MISTAKES.md` storage and entry parser
- `app/mistake_distiller.py`: downvote-to-mistake distillation
- `app/mistake_review.py`: mistake-to-memory solution proposal and acceptance
- `app/memory.py`: `MEMORY.md` storage and context helper
- `app/llm/ollama.py`: Ollama API client
- `app/api/chats.py`: chat, message, and feedback routes
- `app/api/settings.py`: settings and Ollama model discovery routes
- `app/api/roles.py`: role prompt routes
- `app/api/mistakes.py`: mistakes, review wizard, and memory routes
- `app/api/agentic_tasks.py`: Agentic Task CRUD/run routes
- `app/api/tools.py`: tool list, route/select, approval-aware call route
- `app/tools/workspace.py`: workspace path normalization and boundary checks
- `app/tools/filesystem.py`: read-only file list/read/search helpers
- `app/tools/git.py`: read-only Git status/diff helpers
- `app/tools/shell.py`: allowlisted shell runner
- `app/tools/notification.py`: macOS desktop notification helper
- `app/tools/internet.py`: public URL check/fetch helpers with localhost/private-network blocking
- `app/tools/registry.py`: executable tool registry
- `app/tools/catalog.py`: tool metadata enrichment
- `app/tools/routing/`: keyword, cosine, embedding, and hard-filter routing helpers
- `app/static/index.html`: UI structure
- `app/static/app.js`: UI state, API calls, settings, feedback, approvals, wizards
- `app/static/style.css`: dark UI styling with purple accent
- `nixai.spec`: PyInstaller build configuration

## Modes

`chat`:

- plain assistant conversation
- uses the `assistant` model role
- does not assume workspace tool access

`code`:

- uses the `worker` model role
- requires a configured workspace for useful answers
- injects `WORKER.md`, reviewed `MEMORY.md`, workspace path, and bounded read-only tool results
- may inspect file lists, specific files, search results, Git status, and Git diff through NixAI tools
- does not give the model native shell access
- test/build commands remain allowlisted and should be explicit

`agentic`:

- first runs `TaskDiscovery` using `TASK_DISCOVERY.md` and the `task_discovery` model role
- creates recurring Agentic Tasks when enough schedule/task information is found
- asks for missing information when the request is incomplete
- falls back to Orchestrator chat behavior for non-recurring tasks
- scheduled runs use `ORCHESTRATOR.md`, reviewed `MEMORY.md`, structured JSON, approved tools, and reviewer summaries

## Roles And Memory

Default role prompt files are created on demand in the config directory:

```text
ASSISTANT.md
ORCHESTRATOR.md
TASK_DISCOVERY.md
WORKER.md
REVIEWER.md
JUDGE.md
```

Users can add custom roles from the settings UI. Role names are normalized and saved as Markdown files under `roles/`.

`MISTAKES.md`:

- editable in settings
- receives downvote distillations
- can be reviewed in the Mistakes wizard
- must never be injected into model context

`MEMORY.md`:

- receives accepted guidance from reviewed mistakes
- is injected into Code mode and scheduled Agentic model prompts
- is the only persistent learning document that models should see

When adding new model prompts, prefer `MEMORY.md` over raw `MISTAKES.md`.

## Tool Policy

All tools should remain explicit and bounded.

Workspace tools must:

- only operate inside the configured workspace
- normalize and resolve paths before use
- reject directory traversal
- avoid write operations in the POC tool layer

Shell tools must:

- never execute arbitrary commands
- use the allowlist in `app/tools/shell.py`
- keep outputs explicit and bounded where practical

Currently allowlisted shell commands:

```text
git status
git diff
composer test
composer phpunit
vendor/bin/phpunit
npm test
npm run build
```

Internet tools must:

- only allow `http` and `https`
- reject embedded credentials
- reject localhost, private, loopback, link-local, multicast, reserved, and unspecified addresses
- keep fetched response bodies bounded

Notification tools must:

- remain approval-gated by default
- keep title/message lengths bounded
- currently target macOS only through `osascript`

Tool approval settings live in `config.json`:

```json
{
  "require_tool_confirmation": true,
  "always_allowed_tools": []
}
```

Manual `/api/tools/call` requests require approval by default. The UI can approve a call once or add the tool to `always_allowed_tools`. Disabling `require_tool_confirmation` allows calls without prompts.

Autonomous scheduled Agentic tools are limited to the `AUTO_TOOLS` set in `app/agentic_runner.py` and still respect tool confirmation settings.

Do not add write-capable tools or broader shell commands without a clear approval, preview, and rollback UX.

## Config And Runtime Data

Config and data are intentionally outside the repository through `platformdirs`.

macOS/Linux:

```text
~/.config/nixai/config.json
~/.config/nixai/MISTAKES.md
~/.config/nixai/MEMORY.md
~/.config/nixai/roles/*.md
~/.local/share/nixai/nixai.sqlite
```

Windows:

```text
%APPDATA%/NixAI/config.json
%APPDATA%/NixAI/MISTAKES.md
%APPDATA%/NixAI/MEMORY.md
%APPDATA%/NixAI/roles/*.md
%LOCALAPPDATA%/NixAI/nixai.sqlite
```

Do not commit runtime databases, local configs, generated `build/`, or generated `dist/`.

## Desktop Notes

Desktop mode wraps the existing local FastAPI UI in a native window via `pywebview`.

Platform notes:

- macOS: Cocoa/WKWebView; Python 3.9 uses PyObjC `<12` pins
- Windows: may require Microsoft Edge WebView2 Runtime
- Linux: requires GTK or Qt WebKit/WebEngine system dependencies depending on backend

The browser UI and desktop UI intentionally share `app/static/*`.

## Frontend Direction

Keep the frontend simple and app-like:

- vanilla HTML/CSS/JS
- no React/Vue unless there is a strong reason
- no Monaco editor in the POC
- dark local-agent interface with purple accent
- compact settings and controls
- settings open as a grouped overlay over the chat area, not as a narrow side panel
- readable code blocks
- modal prompts for explicit approvals and guided review flows

Near-term useful UI work:

- model indicator in the chat header
- workspace status panel
- dedicated tool/result timeline in messages
- clearer Agentic run detail view with raw tool results
- Git status/diff tool buttons
- test command runner buttons with approval prompts

## Not Implemented Yet

- full Planner -> Worker -> Reviewer -> Judge loop
- patch creation or controlled file editing
- automatic test execution in an agent loop
- judge retry/done decision logic
- acceptance criteria verification
- external connectors such as email or calendar
- full plugin system
- RAG over project documents beyond current tool routing
- authentication or remote access

Preferred next step: add concrete external connectors/tools, such as email or calendar, then expand Agentic Tasks from workspace-only tools to approved integrations with per-tool risk controls.

## Git And Commit Hygiene

Before committing:

```bash
git status --short
PYTHONPYCACHEPREFIX=/private/tmp/nixai-pycache python3 -m compileall app
node --check app/static/app.js
git diff --check
```

Commit only source, docs, and build configuration. Leave ignored local files alone.

Ignored generated/local files currently include:

```text
.idea/
.DS_Store
build/
dist/
*.sqlite
*.sqlite3
data/
```

When changing packaging, keep `nixai.spec` updated so the binary build remains reproducible.
