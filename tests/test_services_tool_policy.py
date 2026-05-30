from __future__ import annotations

from app.config import Settings
from app.services.tool_policy import AUTO_TOOL_NAMES, CONTEXT_TOOL_NAMES, ToolPolicyService


def _settings(**overrides) -> Settings:
    base = dict(require_tool_confirmation=True, always_allowed_tools=[])
    base.update(overrides)
    return Settings(**base)


def test_notify_desktop_is_autonomous_without_approval() -> None:
    policy = ToolPolicyService(_settings())

    assert policy.is_autonomous("nixai_notify_desktop") is True


def test_unlisted_tool_is_not_autonomous() -> None:
    policy = ToolPolicyService(_settings())

    assert policy.is_autonomous("nixai_run_command") is False
    assert policy.is_autonomous("nixai_workspace_edit_file") is False
    assert policy.is_autonomous("not_a_tool") is False


def test_auto_tool_needs_always_allow_when_confirmation_required() -> None:
    policy_required = ToolPolicyService(_settings(require_tool_confirmation=True))
    policy_relaxed = ToolPolicyService(_settings(require_tool_confirmation=False))
    policy_allowed = ToolPolicyService(_settings(always_allowed_tools=["nixai_web_search"]))

    assert policy_required.is_autonomous("nixai_web_search") is False
    assert policy_relaxed.is_autonomous("nixai_web_search") is True
    assert policy_allowed.is_autonomous("nixai_web_search") is True


def test_context_tools_subset_of_auto_tools_minus_notify() -> None:
    assert "nixai_notify_desktop" not in CONTEXT_TOOL_NAMES
    assert CONTEXT_TOOL_NAMES <= AUTO_TOOL_NAMES


def test_requires_confirmation_and_annotate() -> None:
    policy = ToolPolicyService(_settings(always_allowed_tools=["nixai_git_status"]))

    assert policy.requires_confirmation("nixai_git_status") is False
    assert policy.requires_confirmation("nixai_web_search") is True

    annotated = policy.annotate({"name": "nixai_web_search", "meta": {"autoRun": False}})

    assert annotated["meta"]["requiresConfirmation"] is True
    assert annotated["meta"]["alwaysAllowed"] is False
    assert annotated["meta"]["autoRun"] is False


def test_write_tool_always_requires_per_call_confirmation() -> None:
    policy = ToolPolicyService(
        _settings(require_tool_confirmation=False, always_allowed_tools=["nixai_workspace_edit_file"])
    )

    assert policy.requires_confirmation("nixai_workspace_edit_file") is True
    assert policy.is_always_allowed("nixai_workspace_edit_file") is False
    assert policy.requires_per_call_confirmation("nixai_workspace_edit_file") is True
