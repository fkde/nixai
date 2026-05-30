from __future__ import annotations

import pytest

from app.config import Settings, save_settings
from app.tools import editing
from app.tools.workspace import WorkspaceError


def test_edit_preview_rejects_traversal(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    with pytest.raises(WorkspaceError, match="escapes configured workspace"):
        editing.preview_edit_file({"path": "../outside.txt", "content": "nope\n"}, str(root))


def test_edit_preview_rejects_symlink_escape(tmp_path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspaceError, match="escapes configured workspace"):
        editing.preview_edit_file({"path": "link/secret.txt", "content": "nope\n"}, str(root))


def test_preview_does_not_write_and_adds_commit_hash(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("old\n", encoding="utf-8")

    preview = editing.preview_edit_file({"path": "note.txt", "content": "new\n"}, str(root))

    assert target.read_text(encoding="utf-8") == "old\n"
    assert "--- a/note.txt" in preview["diff"]
    assert "+++ b/note.txt" in preview["diff"]
    assert preview["commit_arguments"]["expected_sha256"] == preview["before_sha256"]


def test_edit_writes_atomically_and_returns_backup(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("old\n", encoding="utf-8")
    preview = editing.preview_edit_file({"path": "note.txt", "content": "new\n"}, str(root))

    result = editing.edit_file(preview["commit_arguments"], str(root))

    assert target.read_text(encoding="utf-8") == "new\n"
    assert result["backup_path"]
    assert (root / result["backup_path"]).read_text(encoding="utf-8") == "old\n"
    assert result["inverse_diff"]
    assert not list(root.glob(".note.txt.*.tmp"))


def test_edit_rejects_changed_file_after_preview(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("old\n", encoding="utf-8")
    preview = editing.preview_edit_file({"path": "note.txt", "content": "new\n"}, str(root))
    target.write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after preview"):
        editing.edit_file(preview["commit_arguments"], str(root))

    assert target.read_text(encoding="utf-8") == "changed\n"


def test_api_requires_preview_approval_before_write(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("old\n", encoding="utf-8")
    save_settings(Settings(workspace_path=str(root), require_tool_confirmation=True))
    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)

    response = client.post(
        "/api/tools/call",
        json={"name": "nixai_workspace_edit_file", "arguments": {"path": "note.txt", "content": "new\n"}},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["approval_required"] is True
    assert payload["preview"]["diff"]
    assert target.read_text(encoding="utf-8") == "old\n"

    approved = client.post(
        "/api/tools/call",
        json={"name": "nixai_workspace_edit_file", "arguments": payload["arguments"], "approved": True},
    )

    assert approved.status_code == 200
    assert approved.json()["result"]["success"] is True
    assert target.read_text(encoding="utf-8") == "new\n"


def test_write_tool_ignores_always_allow(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "note.txt").write_text("old\n", encoding="utf-8")
    save_settings(
        Settings(
            workspace_path=str(root),
            require_tool_confirmation=True,
            always_allowed_tools=["nixai_workspace_edit_file"],
        )
    )
    from app.main import app
    from fastapi.testclient import TestClient

    client = TestClient(app)

    response = client.post(
        "/api/tools/call",
        json={"name": "nixai_workspace_edit_file", "arguments": {"path": "note.txt", "content": "new\n"}},
    )

    assert response.status_code == 200
    assert response.json()["approval_required"] is True
