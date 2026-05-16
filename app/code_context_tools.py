from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.tools import filesystem, git
from app.tools.workspace import workspace_root


class CodeContextTools(Protocol):
    def workspace_root(self, workspace_path: str) -> Path: ...

    def list_files(self, path: str, workspace_path: str) -> object: ...

    def read_file(self, path: str, workspace_path: str) -> object: ...

    def search_files(self, query: str, workspace_path: str) -> object: ...

    def git_status(self, workspace_path: str) -> object: ...

    def git_diff(self, workspace_path: str) -> object: ...


class DefaultCodeContextTools:
    def workspace_root(self, workspace_path: str) -> Path:
        return workspace_root(workspace_path)

    def list_files(self, path: str, workspace_path: str) -> object:
        return filesystem.list_files(path, workspace_path)

    def read_file(self, path: str, workspace_path: str) -> object:
        return filesystem.read_file(path, workspace_path)

    def search_files(self, query: str, workspace_path: str) -> object:
        return filesystem.search_files(query, workspace_path)

    def git_status(self, workspace_path: str) -> object:
        return git.git_status(workspace_path)

    def git_diff(self, workspace_path: str) -> object:
        return git.git_diff(workspace_path)
