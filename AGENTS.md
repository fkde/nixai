# AGENTS.md

Guidance for AI coding agents working on NixAI.

## Project Status

NixAI is a local proof-of-concept AI agent runner for Ollama models. The current implementation is intentionally small and conservative:

- FastAPI backend
- SQLite chat persistence
- Ollama chat adapter
- simple single-agent orchestrator
- shared Chat / Code / Agentic message modes
- settings UI for dynamic model roles
- Markdown role prompt library for Orchestrator/Worker/Reviewer-style contexts
- first Agentic Task definitions with API and settings UI management
- local Agentic scheduler with run history and bounded failover
- TaskDiscovery role for distilling Agentic requests into structured JSON
- central editable `MISTAKES.md` learning document
- RAG-style tool routing with optional Ollama embeddings
- vanilla HTML/CSS/JS chat UI
- optional native desktop window via `pywebview`
- prepared read-only workspace tools for filesystem, Git, and allowlisted shell commands
- PyInstaller build spec for a local binary

The repository is on `main` and tracks:

```text
origin git@github.com:fkde/nixai.git
```

Current runtime target:

```text
Python 3.9+
```

Do not raise the Python minimum unless a concrete feature requires it and the tradeoff is documented.

## Common Commands

Install base dependencies:

```bash
pip install -r requirements.txt
```

Run the web UI:

```bash
python -m app.cli serve
```

Open:

```text
http://127.0.0.1:8765
```

Install desktop dependencies:

```bash
pip install -r requirements-desktop.txt
```

Run native desktop mode:

```bash
python -m app.cli desktop
```

Build local binary:

```bash
python -m PyInstaller nixai.spec
```

Current local binary output path:

```text
dist/nixai
```

Basic syntax check:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/nixai-pycache python3 -m compileall app
```

## Architecture

Current flow:

```text
Chat UI
  -> FastAPI API
  -> Agent
  -> OllamaClient
  -> Ollama /api/chat
```

Important files:

- `app/cli.py`: CLI entrypoint for `serve` and `desktop`
- `app/main.py`: FastAPI application factory and static UI mounting
- `app/database.py`: SQLite schema and chat/message persistence
- `app/models.py`: Pydantic models
- `app/agent.py`: current single-agent orchestrator
- `app/agentic_runner.py`: scheduled Agentic Task execution, tool calls, failover, and run summaries
- `app/agentic_schedule.py`: small parser for recurring schedules such as `daily at 18:00`
- `app/agentic_scheduler.py`: background loop and manual run entrypoint
- `app/code_context.py`: safe read-only code-mode context builder using NixAI tools
- `app/mistakes.py`: central `MISTAKES.md` storage and context helper
- `app/api/settings.py`: settings and Ollama model discovery API
- `app/api/agentic_tasks.py`: Agentic Task create/list/update/delete API
- `app/api/roles.py`: Markdown role prompt API
- `app/api/tools.py`: tool list, route/select, and call API
- `app/llm/ollama.py`: Ollama adapter
- `app/desktop.py`: native desktop wrapper using `pywebview`
- `app/roles.py`: role prompt storage, defaults, and filename safety
- `app/task_discovery.py`: TaskDiscovery adapter for extracting task intent from user requests
- `app/tools/workspace.py`: workspace path normalization and boundary checks
- `app/tools/filesystem.py`: read-only file list/read/search helpers
- `app/tools/git.py`: read-only Git status/diff helpers
- `app/tools/shell.py`: allowlisted command runner
- `app/tools/registry.py`: executable tool registry
- `app/tools/catalog.py`: tool metadata enrichment for routing
- `app/tools/routing/`: keyword and optional embedding-based tool retrieval
- `app/static/`: vanilla web UI

## Current Orchestrator Mode

The active orchestrator is a simple single-agent chat runner:

```python
Agent.run(chat_id: str, user_message: str, mode: MessageMode = "chat") -> CreateMessageResponse
```

Current behavior:

1. Verify chat exists.
2. Store the user message.
3. Update the chat title if it is still the default.
4. Load chat history.
5. Send history to Ollama.
6. Store assistant response with the selected message mode.
7. Return both persisted messages.

The assistant model is selected through the `assistant` entry in `model_roles`, falling back to `default_model`.
Code mode injects `WORKER.md`, `MISTAKES.md`, the configured workspace path, and bounded read-only tool results from `app/code_context.py`. The model does not get native shell access; all gathered context goes through `app/tools/*` so workspace boundaries and allowlists still apply. Agentic mode first runs TaskDiscovery using the `task_discovery` model role and `TASK_DISCOVERY.md`, then either creates an Agentic Task definition, asks for missing task information, or falls back to the Orchestrator chat path. Scheduled Agentic runs also receive `MISTAKES.md`.

Agentic Task execution is active while the FastAPI app is running. The scheduler checks due active tasks, runs the Orchestrator through structured JSON, executes only approved autonomous tools, stores run logs, and pauses tasks after repeated failures. Unsupported capabilities, invalid model JSON, and unexpected tool requests are marked `needs_review` instead of being treated as success.

Default role prompt files are created on demand:

```text
ASSISTANT.md
ORCHESTRATOR.md
TASK_DISCOVERY.md
WORKER.md
REVIEWER.md
JUDGE.md
```

Not implemented yet:

- Planner / Worker / Reviewer / Judge loop
- model-routed roles
- broader model-driven tool calling from structured output
- automatic test execution in the agent loop
- patch creation or file editing
- judge/retry/done decision logic
- acceptance criteria verification

Preferred next step: add concrete external connectors/tools, such as email or calendar, then expand Agentic Tasks from workspace-only tools to those approved integrations with per-tool risk controls.

## Safety Rules

This project is intentionally read-only-heavy.

Workspace tools must:

- only operate inside the configured workspace
- normalize and resolve paths before use
- reject directory traversal
- avoid writing files in the POC tool layer

Shell tools must:

- never execute arbitrary commands
- use the allowlist in `app/tools/shell.py`
- keep outputs explicit and bounded where practical

Currently allowlisted commands:

```text
git status
git diff
composer test
composer phpunit
vendor/bin/phpunit
npm test
npm run build
```

Do not add write-capable commands without a clear UX/control plan.

## Config And Runtime Data

Config and SQLite data are intentionally outside the repository through `platformdirs`.

macOS/Linux:

```text
~/.config/nixai/config.json
~/.config/nixai/MISTAKES.md
~/.config/nixai/roles/*.md
~/.local/share/nixai/nixai.sqlite
```

Windows:

```text
%APPDATA%/NixAI/config.json
%APPDATA%/NixAI/MISTAKES.md
%APPDATA%/NixAI/roles/*.md
%LOCALAPPDATA%/NixAI/nixai.sqlite
```

Do not commit runtime databases, local configs, generated `dist/`, or generated `build/` directories.

## Desktop Notes

The desktop mode wraps the existing local FastAPI UI in a native window via `pywebview`.

Platform notes:

- macOS: uses Cocoa/WKWebView; Python 3.9 requires PyObjC `<12` pins.
- Windows: may require Microsoft Edge WebView2 Runtime.
- Linux: requires GTK or Qt WebKit/WebEngine system dependencies depending on backend.

The browser UI and desktop UI intentionally share the same frontend files.

## Frontend Direction

Keep the frontend simple and app-like:

- no React/Vue unless there is a strong reason
- no Monaco editor in the POC
- dark, focused, local-agent interface
- sidebar for chats
- main panel for messages
- compact controls
- readable code blocks

Upcoming useful UI additions:

- model indicator in the chat header
- workspace path/status panel
- agent mode toggle
- first Orchestrator -> Worker -> Reviewer flow using saved role prompts
- Git status/diff tool buttons
- test command runner buttons

## Git And Commit Hygiene

Before committing:

```bash
git status --short
PYTHONPYCACHEPREFIX=/private/tmp/nixai-pycache python3 -m compileall app
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
