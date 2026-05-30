from __future__ import annotations

import json

from app.config import ModelRole, Settings, config_path, load_settings, save_settings


def test_model_for_role_uses_model_roles_and_default_fallback() -> None:
    settings = Settings(
        default_model="fallback:model",
        model_roles=[
            ModelRole(role="assistant", model="assistant:model"),
            ModelRole(role=" worker ", model=" worker:model "),
        ],
    )

    assert settings.model_for_role("WORKER") == "worker:model"
    assert settings.model_for_role("missing") == "fallback:model"


def test_legacy_model_scalar_fields_are_ignored_and_dropped_on_save() -> None:
    path = config_path()
    legacy_model_fields = [f"{role}_model" for role in ("planner", "worker", "reviewer", "judge")]
    path.write_text(
        json.dumps(
            {
                "default_model": "fallback:model",
                **{field: f"legacy-{field}:model" for field in legacy_model_fields},
                "model_roles": [
                    {"role": "assistant", "model": "assistant:model"},
                    {"role": "planner", "model": "roles-planner:model"},
                    {"role": "worker", "model": "roles-worker:model"},
                    {"role": "reviewer", "model": "roles-reviewer:model"},
                    {"role": "judge", "model": "roles-judge:model"},
                    {"role": "task_discovery", "model": "task:model"},
                    {"role": "vision", "model": ""},
                ],
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings.model_for_role("planner") == "roles-planner:model"
    assert settings.model_for_role("worker") == "roles-worker:model"
    assert settings.model_for_role("reviewer") == "roles-reviewer:model"
    assert settings.model_for_role("judge") == "roles-judge:model"
    for field in legacy_model_fields:
        assert not hasattr(settings, field)

    save_settings(settings)
    saved = json.loads(path.read_text(encoding="utf-8"))
    for field in legacy_model_fields:
        assert field not in saved


def test_settings_save_load_roundtrip_preserves_model_roles() -> None:
    settings = Settings(
        default_model="fallback:model",
        model_roles=[
            ModelRole(role="assistant", model="assistant:model"),
            ModelRole(role="worker", model="worker:model"),
            ModelRole(role="task_discovery", model="task:model"),
            ModelRole(role="vision", model="vision:model"),
        ],
    )

    save_settings(settings)
    loaded = load_settings()

    assert loaded.default_model == "fallback:model"
    assert loaded.model_for_role("assistant") == "assistant:model"
    assert loaded.model_for_role("worker") == "worker:model"
    assert loaded.model_for_role("task_discovery") == "task:model"
    assert loaded.model_for_role("vision") == "vision:model"
