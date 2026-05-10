from __future__ import annotations

import json
from pathlib import Path

from app.config import config_dir, default_workflow_presets, normalize_workflow_preset_id
from app.models import MessageMode
from app.workflows.models import WorkflowDefinition, WorkflowSummary


def bundled_workflow_dir() -> Path:
    return Path(__file__).parent / "presets"


def custom_workflow_dir() -> Path:
    return config_dir() / "workflows"


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


def _load_workflow_file(path: Path) -> WorkflowDefinition | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return WorkflowDefinition.model_validate(data)
    except Exception:
        return None
