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

The package metadata lives in `pyproject.toml`; runtime files such as config and SQLite databases are intentionally not committed.

## Build

Later binary builds can use the checked-in application package:

```bash
pyinstaller --onefile --name nixai app/cli.py
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
- Ollama chat adapter
- Simple agent orchestrator
- Workspace file listing, reading, and search
- Git status and diff helpers
- Strict shell command allowlist
- Minimal local chat UI

NixAI does not install Ollama or manage local models.
