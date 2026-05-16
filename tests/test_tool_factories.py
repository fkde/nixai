from __future__ import annotations

from app.tools.factories import base_tool_factories, create_base_tool_definitions


def test_tool_factories_create_expected_core_tools() -> None:
    definitions = create_base_tool_definitions(lambda _args: {"success": True, "tools": []})
    names = [definition.name for definition in definitions]

    assert names == [
        "nixai_workspace_list_files",
        "nixai_workspace_read_file",
        "nixai_workspace_search_files",
        "nixai_git_status",
        "nixai_git_diff",
        "nixai_run_command",
        "nixai_notify_desktop",
        "nixai_web_search",
        "nixai_web_fetch_url",
        "nixai_web_check_url",
        "nixai_tools_search",
    ]
    assert len(base_tool_factories(lambda _args: {})) == len(names)
