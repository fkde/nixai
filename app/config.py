from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir
from pydantic import BaseModel, Field, field_validator

from app.effort import normalize_effort
from app.validation import (
    MAX_NAME_LENGTH,
    clean_single_line,
    validate_http_url,
    validate_workspace_path,
)


APP_NAME = "nixai"
APP_AUTHOR = "NixAI"


class ModelRole(BaseModel):
    role: str
    model: str


class EmailProviderSettings(BaseModel):
    provider: str = ""
    status: str = "disconnected"
    account_email: str = ""
    scopes: list[str] = Field(default_factory=list)


def default_model_roles() -> list[ModelRole]:
    return [
        ModelRole(role="assistant", model="llama3.1:8b"),
        ModelRole(role="planner", model="gemma4:e4b"),
        ModelRole(role="worker", model="llama3.1:8b"),
        ModelRole(role="reviewer", model="gemma4:e4b"),
        ModelRole(role="judge", model="llama3.1:8b"),
        ModelRole(role="task_discovery", model="llama3.1:8b"),
        ModelRole(role="vision", model=""),
    ]


def default_workflow_presets() -> dict[str, str]:
    return {
        "chat": "simple",
        "code": "simple",
        "agentic": "simple",
    }


WORKFLOW_PRESET_ALIASES = {
    "chat_direct": "simple",
    "code_direct_worker": "simple",
    "agentic_direct_orchestrator": "simple",
    "code_review_loop": "deep_orchestra",
    "agentic_review_loop": "deep_orchestra",
}


def normalize_workflow_preset_id(workflow_id: str) -> str:
    clean = str(workflow_id or "").strip()
    return WORKFLOW_PRESET_ALIASES.get(clean, clean)


class Settings(BaseModel):
    user_name: str = ""
    ollama_base_url: str = "http://localhost:11434"
    default_model: str = "llama3.1:8b"
    planner_model: str = "gemma4:e4b"
    worker_model: str = "llama3.1:8b"
    reviewer_model: str = "gemma4:e4b"
    judge_model: str = "llama3.1:8b"
    workspace_path: str = Field(default_factory=lambda: str(Path.home()))
    model_roles: list[ModelRole] = Field(default_factory=default_model_roles)
    embedding_model: str = ""
    embedding_timeout: float = 1.5
    routing_min_score: float = 0.24
    require_tool_confirmation: bool = True
    always_allowed_tools: list[str] = Field(default_factory=list)
    workflow_presets: dict[str, str] = Field(default_factory=default_workflow_presets)
    effort: str = "medium"
    email_provider: EmailProviderSettings = Field(default_factory=EmailProviderSettings)

    @field_validator("user_name", mode="before")
    @classmethod
    def _clean_user_name(cls, value: object) -> str:
        return clean_single_line(value or "", max_length=MAX_NAME_LENGTH, field_name="user_name")

    @field_validator("ollama_base_url", mode="before")
    @classmethod
    def _clean_ollama_url(cls, value: object) -> str:
        if not value:
            return "http://localhost:11434"
        try:
            return validate_http_url(value, field_name="ollama_base_url")
        except ValueError:
            return "http://localhost:11434"

    @field_validator("workspace_path", mode="before")
    @classmethod
    def _clean_workspace(cls, value: object) -> str:
        try:
            return validate_workspace_path(value)
        except ValueError:
            return str(Path.home())

    @field_validator("embedding_timeout")
    @classmethod
    def _clamp_timeout(cls, value: float) -> float:
        if value < 0.1:
            return 0.1
        if value > 30.0:
            return 30.0
        return float(value)

    @field_validator("routing_min_score")
    @classmethod
    def _clamp_min_score(cls, value: float) -> float:
        if value < 0.0:
            return 0.0
        if value > 1.0:
            return 1.0
        return float(value)

    def model_for_role(self, role: str) -> str:
        wanted = role.strip().casefold()
        for model_role in self.model_roles:
            if model_role.role.strip().casefold() == wanted and model_role.model.strip():
                return model_role.model.strip()
        return self.default_model

    def is_tool_always_allowed(self, tool_name: str) -> bool:
        wanted = tool_name.strip()
        return bool(wanted) and wanted in {name.strip() for name in self.always_allowed_tools if name.strip()}


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
            ModelRole(role="task_discovery", model=settings.default_model),
            ModelRole(role="vision", model=""),
        ]
        save_settings(settings)
    else:
        changed_roles = False
        required_roles = {
            "task_discovery": settings.default_model,
            "vision": "",
        }
        existing = {role.role.strip().casefold() for role in settings.model_roles}
        for role, model in required_roles.items():
            if role not in existing:
                settings.model_roles.append(ModelRole(role=role, model=model))
                changed_roles = True
        if changed_roles:
            save_settings(settings)
    normalized_workflows = {
        mode: normalize_workflow_preset_id(str(settings.workflow_presets.get(mode) or fallback).strip())
        for mode, fallback in default_workflow_presets().items()
    }
    if settings.workflow_presets != normalized_workflows:
        settings.workflow_presets = normalized_workflows
        save_settings(settings)
    normalized_effort = normalize_effort(settings.effort)
    if settings.effort != normalized_effort:
        settings.effort = normalized_effort
        save_settings(settings)
    return settings


def save_settings(settings: Settings) -> None:
    settings.user_name = " ".join(settings.user_name.strip().split())[:80]
    settings.default_model = settings.model_for_role("assistant")
    settings.planner_model = settings.model_for_role("planner")
    settings.worker_model = settings.model_for_role("worker")
    settings.reviewer_model = settings.model_for_role("reviewer")
    settings.judge_model = settings.model_for_role("judge")
    settings.always_allowed_tools = sorted({name.strip() for name in settings.always_allowed_tools if name.strip()})
    settings.effort = normalize_effort(settings.effort)
    defaults = default_workflow_presets()
    workflow_presets = {
        mode: normalize_workflow_preset_id(str(settings.workflow_presets.get(mode) or defaults[mode]).strip())
        for mode in defaults
    }
    settings.workflow_presets = workflow_presets
    settings.email_provider.provider = settings.email_provider.provider.strip().lower()
    if settings.email_provider.provider not in {"", "google", "microsoft"}:
        settings.email_provider.provider = ""
    if settings.email_provider.status not in {"disconnected", "pending", "connected", "error"}:
        settings.email_provider.status = "disconnected"
    path = config_path()
    with path.open("w", encoding="utf-8") as handle:
        json.dump(settings.model_dump(), handle, indent=2)
        handle.write("\n")
