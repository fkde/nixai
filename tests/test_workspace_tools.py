from __future__ import annotations

import pytest

from app.tools.workspace import WorkspaceError, resolve_workspace_path, workspace_root


def test_workspace_root_requires_existing_directory(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    assert workspace_root(str(root)) == root.resolve()

    with pytest.raises(WorkspaceError, match="does not exist"):
        workspace_root(str(tmp_path / "missing"))


def test_resolve_workspace_path_stays_inside_root(tmp_path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()

    assert resolve_workspace_path("src/app.py", str(root)) == (root / "src/app.py").resolve()

    with pytest.raises(WorkspaceError, match="escapes configured workspace"):
        resolve_workspace_path("../outside.txt", str(root))


def test_resolve_workspace_path_rejects_symlink_escape(tmp_path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspaceError, match="escapes configured workspace"):
        resolve_workspace_path("link/secret.txt", str(root))
