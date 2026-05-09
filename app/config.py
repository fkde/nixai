from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir
from pydantic import BaseModel, Field


APP_NAME = "nixai"
APP_AUTHOR = "NixAI"


class Settings(BaseModel):
    ollama_base_url: str = "http://localhost:11434"
    default_model: str = "llama3.1:8b"
    planner_model: str = "gemma4:e4b"
    worker_model: str = "llama3.1:8b"
    reviewer_model: str = "gemma4:e4b"
    judge_model: str = "llama3.1:8b"
    workspace_path: str = Field(default_factory=lambda: str(Path.home()))


def config_dir() -> Path:
    if sys.platform == "win32":
        path = Path(user_config_dir(APP_NAME, APP_AUTHOR))
    else:
        path = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    if sys.platform == "win32":
        path = Path(user_data_dir(APP_NAME, APP_AUTHOR))
    else:
        path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def database_path() -> Path:
    return data_dir() / "nixai.sqlite"


def load_settings() -> Settings:
    path = config_path()
    if not path.exists():
        settings = Settings()
        save_settings(settings)
        return settings

    with path.open("r", encoding="utf-8") as handle:
        return Settings.model_validate(json.load(handle))


def save_settings(settings: Settings) -> None:
    path = config_path()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(settings.model_dump(), handle, indent=2)
        handle.write("\n")
