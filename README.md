# NixAI

NixAI is a local AI agent runner for Ollama models. It provides a FastAPI backend, SQLite chat persistence, a vanilla HTML/CSS/JS chat UI, a read-only workspace tool layer, a configurable multi-node workflow engine, and a local Agentic Task scheduler.

Current version: `0.1.0`.

## Quick Start

```bash
pip install -r requirements.txt
python -m app.cli serve
```

Then open:

```text
http://localhost:8765
```

Ollama must run separately. Configure model names and the workspace path in the generated config file.

For editable local installation with the future `nixai` command:

```bash
pip install -e .
nixai serve
```

For the native desktop window:

```bash
pip install -r requirements-desktop.txt
python -m app.cli desktop
```

or, after editable installation:

```bash
pip install -e ".[desktop]"
nixai desktop
```

NixAI supports Python 3.9+. Desktop mode uses `pywebview`; on Linux you may need GTK or Qt WebKit/WebEngine system packages, and on Windows you may need the Microsoft Edge WebView2 Runtime.

The package metadata lives in `pyproject.toml`; runtime files such as config and SQLite databases are intentionally not committed.

## Build

Common build and development commands are bundled in the Makefile:

```bash
make help
make check
make build-cli
make build-macos-app
```

Platform binary scripts build on the target OS:

```bash
./scripts/build_linux_binary.sh --install-deps
```

```powershell
.\scripts\build_windows_binary.ps1 -InstallDeps
```

or from Windows cmd:

```cmd
scripts\build_windows_binary.cmd -InstallDeps
```

For the native desktop window during development:

```bash
make desktop
```

For a macOS `.app` bundle with an icon:

```bash
make build-macos-app
open dist/NixAI.app
```

To install it into `/Applications`:

```bash
make install-macos-app
```

The underlying scripts still exist in `scripts/` for direct use. Alternative binary tooling can be explored later, for example:

```bash
python -m nuitka --onefile --output-filename=nixai app/cli.py
```

## Config And Data

NixAI stores configuration and data outside this repository using `platformdirs`.

Typical paths:

- macOS/Linux config: `~/.config/nixai/config.json`
- macOS/Linux database: `~/.local/share/nixai/nixai.sqlite`
- Windows config: `%APPDATA%/NixAI/config.json`
- Windows database: `%LOCALAPPDATA%/NixAI/nixai.sqlite`

Example config:

```json
{
  "ollama_base_url": "http://localhost:11434",
  "default_model": "llama3.1:8b",
  "planner_model": "gemma4:e4b",
  "worker_model": "llama3.1:8b",
  "reviewer_model": "gemma4:e4b",
  "judge_model": "llama3.1:8b",
  "workspace_path": "/path/to/project"
}
```

## Features

### Chat And Modes

- Persistent local chats with SQLite history
- Ollama chat adapter with streamed responses and tokens-per-second status
- Three message modes in one history: `chat`, `code`, and `agentic`
- Code mode injects `WORKER.md`, reviewed `MEMORY.md`, and bounded read-only workspace context
- Per-chat workspace path with the global workspace as fallback
- Minimal dark local-agent chat UI with purple accent

### Workflows

- Multi-node workflow runner with Orchestrator, Worker(s), Reviewer, and Judge nodes
- Visual canvas-based workflow builder in the UI with drag-and-drop nodes, edges, and node configuration
- Bundled presets (`simple`, `deep_orchestra`) plus user-defined workflows stored in `~/.config/nixai/workflows/`
- Configurable per-node model role, prompt, output schema, worker instances, and `max_parallel` concurrency
- Structured phases: plan → workers → review → judge → final synthesis, with retry loops and effort-aware limits
- Persistent workflow scratchpad shared between nodes within a run
- Per-mode preset selection (chat / code / agentic)

### Model Management

- Settings UI discovers locally installed Ollama models through `/api/settings/models`
- Role-to-model mapping for `assistant`, `planner`, `worker`, `reviewer`, `judge`, and custom roles
- Models are picked from the Ollama catalog; NixAI does not install or pull models itself

### Roles And Memory

- Default Markdown role prompts auto-created on demand: `ASSISTANT.md`, `ORCHESTRATOR.md`, `TASK_DISCOVERY.md`, `WORKER.md`, `REVIEWER.md`, `JUDGE.md`
- Custom role creation, editing, and deletion from the settings UI via `/api/roles`
- Editable central `MISTAKES.md` review source and accepted `MEMORY.md` model context
- Mistakes review wizard that distills downvotes into future-facing guidance written to `MEMORY.md`
- `MEMORY.md` is injected into Code mode and scheduled Agentic prompts; `MISTAKES.md` is never sent to models

### Agentic Tasks

- `TaskDiscovery` role extracts recurring task definitions from user requests
- Agentic Task CRUD (create / edit / pause / delete) via API and UI
- Local scheduler with run history, approved autonomous tool calls, and failover to manual review
- Scheduled runs are limited to autonomous-safe and pre-approved tools

### Tools

- Workspace file listing, reading, and search (read-only, path-normalized)
- Git status and diff helpers
- Allowlisted shell command runner
- macOS desktop notification tool
- Public URL check / fetch internet tools with private-address blocking
- RAG-style tool routing with keyword fallback and optional Ollama embeddings
- Tool approval prompts with `Allow once`, `Always allow`, and a global confirmation toggle

### Settings, Updates, And Packaging

- Grouped settings overlay for Basis, Modelle, Prompts, Tools, Memory, Agentic, and Workflows
- E-mail provider settings scaffold for Google Gmail and Microsoft Outlook OAuth
- Update check against GitHub releases via `/api/updates`, with in-place macOS app swap support
- Optional native desktop window through `pywebview`
- PyInstaller builds for CLI and macOS `.app` bundle
