# AGENTS.md

Guidance for AI coding agents working on NixAI.

## Project Status

NixAI is a local proof-of-concept AI agent runner for Ollama models. The current implementation is intentionally small and conservative:

- FastAPI backend
- SQLite chat persistence
- Ollama chat adapter
- simple single-agent orchestrator
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
- `app/llm/ollama.py`: Ollama adapter
- `app/desktop.py`: native desktop wrapper using `pywebview`
- `app/tools/workspace.py`: workspace path normalization and boundary checks
- `app/tools/filesystem.py`: read-only file list/read/search helpers
- `app/tools/git.py`: read-only Git status/diff helpers
- `app/tools/shell.py`: allowlisted command runner
- `app/static/`: vanilla web UI

## Current Orchestrator Mode

The active orchestrator is a simple single-agent chat runner:

```python
Agent.run(chat_id: str, user_message: str) -> CreateMessageResponse
```

Current behavior:

1. Verify chat exists.
2. Store the user message.
3. Update the chat title if it is still the default.
4. Load chat history.
5. Send history to Ollama.
6. Store assistant response.
7. Return both persisted messages.

Not implemented yet:

- Planner / Worker / Reviewer / Judge loop
- model-routed roles
- tool calling from model output
- automatic test execution in the agent loop
- patch creation or file editing
- judge/retry/done decision logic
- acceptance criteria verification

Preferred next step: add a controlled agent mode that can read workspace context, run Git status/diff, and execute allowlisted tests, then feed those results into the model. Keep file writes out of the POC unless explicitly requested.

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
~/.local/share/nixai/nixai.sqlite
```

Windows:

```text
%APPDATA%/NixAI/config.json
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

- model indicator/select
- workspace path/status panel
- agent mode toggle
- Git status/diff tool buttons
- test command runner buttons
- settings screen for Ollama URL, model names, and workspace path

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
