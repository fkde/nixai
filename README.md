# NixAI

NixAI is a local proof-of-concept AI agent runner for Ollama models. It provides a small FastAPI backend, SQLite chat persistence, a vanilla HTML/CSS/JS chat UI, and a prepared read-only workspace tool layer.

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

Later binary builds can use the checked-in application package:

```bash
pyinstaller --onefile --name nixai app/cli.py
```

For a desktop-focused binary, include pywebview and start the native mode:

```bash
pyinstaller --onefile --name nixai app/cli.py
./dist/nixai desktop
```

or:

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

## POC Scope

- Persistent local chats
- Ollama chat adapter with streaming responses
- Simple agent orchestrator
- Chat, Code, and Agentic message modes in one history
- Live assistant output with tokens-per-second status
- Code mode gathers bounded read-only workspace context through NixAI tools
- Per-chat workspace path with the global workspace as fallback
- Configurable model roles through the settings UI
- Grouped settings overlay for Basis, Modelle, Prompts, Tools, Memory, and Agentic
- E-mail provider settings scaffold for Google Gmail and Microsoft Outlook OAuth
- Markdown role prompts for Orchestrator, Worker, Reviewer, Judge, and custom roles
- Editable central `MISTAKES.md` review source and accepted `MEMORY.md` model context
- Tool approval prompts with settings for disabling confirmation and permanently allowed tools
- TaskDiscovery role for extracting recurring Agentic task definitions from user requests
- First Agentic Task definitions with create/edit/pause/delete API and UI
- Local Agentic scheduler with run history, approved tool calls, and failover to review
- RAG-style tool routing with optional Ollama embeddings
- Workspace file listing, reading, and search
- Git status and diff helpers
- macOS desktop notification tool
- Public URL check/fetch internet tools
- Strict shell command allowlist
- Minimal local chat UI

NixAI does not install Ollama or manage local models.
