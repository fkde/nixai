from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.workflows.models import WORKFLOW_IR_VERSION


def migrate_workflow_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a portable workflow IR payload at the current schema version."""
    migrated = deepcopy(payload)
    version = int(migrated.get("schema_version") or migrated.get("ir_version") or 0)
    if version <= 0:
        version = 1
    if version > WORKFLOW_IR_VERSION:
        raise ValueError(f"Unsupported workflow schema_version: {version}")

    migrated["schema_version"] = WORKFLOW_IR_VERSION
    migrated.pop("ir_version", None)
    migrated.setdefault("execution_profile", "")
    for node in migrated.get("nodes") or []:
        if isinstance(node, dict):
            node["schema_version"] = WORKFLOW_IR_VERSION
            node.setdefault("execution_profile", "")
    return migrated


def export_workflow_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize workflow JSON before writing it to disk or returning it via APIs."""
    exported = migrate_workflow_payload(payload)
    for node in exported.get("nodes") or []:
        if isinstance(node, dict):
            node["receive_from"] = []
            node["reports_to"] = []
    return exported
