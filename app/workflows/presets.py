from __future__ import annotations

import json
from pathlib import Path

from app.config import config_dir, default_workflow_presets, normalize_workflow_preset_id
from app.models import MessageMode
from app.validation import validate_slug
from app.workflows.ir import export_workflow_payload, migrate_workflow_payload
from app.workflows.models import WorkflowDefinition, WorkflowSummary


def bundled_workflow_dir() -> Path:
    return Path(__file__).parent / "presets"


def custom_workflow_dir() -> Path:
    path = config_dir() / "workflows"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_workflows(mode: MessageMode | None = None) -> list[WorkflowDefinition]:
    workflows: dict[str, WorkflowDefinition] = {}
    for directory in [bundled_workflow_dir(), custom_workflow_dir()]:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            workflow = _load_workflow_file(path)
            if workflow is None:
                continue
            if mode is not None and not workflow.supports_mode(mode):
                continue
            workflows[workflow.id] = workflow
    return sorted(workflows.values(), key=lambda item: (item.execution != "direct", item.name.casefold(), item.id))


def list_workflow_summaries(mode: MessageMode | None = None) -> list[WorkflowSummary]:
    return [
        WorkflowSummary(
            id=workflow.id,
            name=workflow.name,
            description=workflow.description,
            mode=workflow.supported_modes()[0],
            modes=workflow.supported_modes(),
            execution=workflow.execution,
            execution_profile=workflow.execution_profile,
            max_iterations=workflow.max_iterations,
            nodes=workflow.nodes,
            edges=workflow.edges,
        )
        for workflow in list_workflows(mode)
    ]


def get_workflow(workflow_id: str, mode: MessageMode | None = None) -> WorkflowDefinition | None:
    wanted = normalize_workflow_preset_id(workflow_id)
    if not wanted:
        return None
    return next((workflow for workflow in list_workflows(mode) if workflow.id == wanted), None)


def selected_workflow(settings, mode: MessageMode) -> WorkflowDefinition | None:
    workflow_map = getattr(settings, "workflow_presets", {}) or {}
    workflow_id = normalize_workflow_preset_id(str(workflow_map.get(mode) or default_workflow_presets().get(mode) or "").strip())
    workflow = get_workflow(workflow_id, mode)
    if workflow is not None:
        return workflow
    fallback_id = default_workflow_presets().get(mode, "")
    return get_workflow(fallback_id, mode)


def list_custom_workflow_ids() -> list[str]:
    directory = custom_workflow_dir()
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob("*.json") if path.stem)


def save_custom_workflow(workflow: WorkflowDefinition) -> WorkflowDefinition:
    workflow_id = _sanitize_workflow_id(workflow.id)
    payload = workflow.model_copy(update={"id": workflow_id})
    path = custom_workflow_dir() / f"{workflow_id}.json"
    data = export_workflow_payload(payload.model_dump(by_alias=True))
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    loaded = _load_workflow_file(path)
    if loaded is None:
        raise ValueError("Failed to load saved workflow definition.")
    return loaded


def delete_custom_workflow(workflow_id: str) -> bool:
    wanted = _sanitize_workflow_id(workflow_id)
    path = custom_workflow_dir() / f"{wanted}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


def _load_workflow_file(path: Path) -> WorkflowDefinition | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return WorkflowDefinition.model_validate(migrate_workflow_payload(data))
    except Exception:
        return None


def _sanitize_workflow_id(raw: str) -> str:
    normalized = normalize_workflow_preset_id(str(raw or "").strip())
    if not normalized:
        raise ValueError("Workflow id is required.")
    return validate_slug(normalized, field_name="workflow id")
