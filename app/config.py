from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir
from pydantic import BaseModel, Field


APP_NAME = "nixai"
APP_AUTHOR = "NixAI"


class ModelRole(BaseModel):
    role: str
    model: str


def default_model_roles() -> list[ModelRole]:
    return [
        ModelRole(role="assistant", model="llama3.1:8b"),
        ModelRole(role="planner", model="gemma4:e4b"),
        ModelRole(role="worker", model="llama3.1:8b"),
        ModelRole(role="reviewer", model="gemma4:e4b"),
        ModelRole(role="judge", model="llama3.1:8b"),
    ]


class Settings(BaseModel):
    ollama_base_url: str = "http://localhost:11434"
    default_model: str = "llama3.1:8b"
    planner_model: str = "gemma4:e4b"
    worker_model: str = "llama3.1:8b"
    reviewer_model: str = "gemma4:e4b"
    judge_model: str = "llama3.1:8b"
    workspace_path: str = Field(default_factory=lambda: str(Path.home()))
    model_roles: list[ModelRole] = Field(default_factory=default_model_roles)

    def model_for_role(self, role: str) -> str:
        wanted = role.strip().casefold()
        for model_role in self.model_roles:
            if model_role.role.strip().casefold() == wanted and model_role.model.strip():
                return model_role.model.strip()
        return self.default_model


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
        data = json.load(handle)
    settings = Settings.model_validate(data)
    if "model_roles" not in data:
        settings.model_roles = [
            ModelRole(role="assistant", model=settings.default_model),
            ModelRole(role="planner", model=settings.planner_model),
            ModelRole(role="worker", model=settings.worker_model),
            ModelRole(role="reviewer", model=settings.reviewer_model),
            ModelRole(role="judge", model=settings.judge_model),
        ]
        save_settings(settings)
    return settings


def save_settings(settings: Settings) -> None:
    settings.default_model = settings.model_for_role("assistant")
    settings.planner_model = settings.model_for_role("planner")
    settings.worker_model = settings.model_for_role("worker")
    settings.reviewer_model = settings.model_for_role("reviewer")
    settings.judge_model = settings.model_for_role("judge")
    path = config_path()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(settings.model_dump(), handle, indent=2)
        handle.write("\n")
