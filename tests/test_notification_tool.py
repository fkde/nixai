from __future__ import annotations

import subprocess

from app.tools import notification


def test_macos_notification_uses_osascript(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(notification.sys, "platform", "darwin")
    monkeypatch.setattr(notification.subprocess, "run", fake_run)

    result = notification.notify_desktop('Hi "there"', "Build done", "Tests", "Glass")

    assert result["success"] is True
    assert result["platform"] == "darwin"
    assert result["mechanism"] == "osascript"
    command, kwargs = calls[0]
    assert command[0:2] == ["osascript", "-e"]
    assert 'display notification "Build done" with title "Hi \\"there\\""' in command[2]
    assert 'subtitle "Tests"' in command[2]
    assert 'sound name "Glass"' in command[2]
    assert kwargs["check"] is True
    assert kwargs["timeout"] == 10


def test_linux_notification_uses_notify_send_when_available(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(notification.sys, "platform", "linux")
    monkeypatch.setattr(notification.shutil, "which", lambda name: "/usr/bin/notify-send" if name == "notify-send" else None)
    monkeypatch.setattr(notification.subprocess, "run", fake_run)

    result = notification.notify_desktop("NixAI", "Message", "Subtitle", "Glass")

    assert result["success"] is True
    assert result["platform"] == "linux"
    assert result["mechanism"] == "notify-send"
    command, kwargs = calls[0]
    assert command == ["/usr/bin/notify-send", "--app-name=NixAI", "NixAI", "Subtitle\nMessage"]
    assert kwargs["check"] is True
    assert kwargs["timeout"] == 10


def test_linux_notification_reports_missing_notify_send(monkeypatch) -> None:
    monkeypatch.setattr(notification.sys, "platform", "linux")
    monkeypatch.setattr(notification.shutil, "which", lambda _name: None)

    result = notification.notify_desktop("NixAI", "Message")

    assert result["success"] is False
    assert result["platform"] == "linux"
    assert result["accepted_by_system"] is False
    assert "notify-send" in result["error"]


def test_windows_notification_uses_powershell_winrt_toast(monkeypatch) -> None:
    calls = []
    lookups = {"powershell.exe": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"}

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(notification.sys, "platform", "win32")
    monkeypatch.setattr(notification.shutil, "which", lambda name: lookups.get(name))
    monkeypatch.setattr(notification.subprocess, "run", fake_run)

    result = notification.notify_desktop("NixAI", "Message", "Subtitle")

    assert result["success"] is True
    assert result["platform"] == "win32"
    assert result["mechanism"] == "powershell-winrt-toast"
    command, kwargs = calls[0]
    assert command[:6] == [
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
    ]
    assert "ToastNotificationManager" in command[6]
    assert command[-3:] == ["NixAI", "Message", "Subtitle"]
    assert kwargs["check"] is True
    assert kwargs["timeout"] == 10


def test_windows_notification_reports_missing_powershell(monkeypatch) -> None:
    monkeypatch.setattr(notification.sys, "platform", "win32")
    monkeypatch.setattr(notification.shutil, "which", lambda _name: None)

    result = notification.notify_desktop("NixAI", "Message")

    assert result["success"] is False
    assert result["platform"] == "win32"
    assert "PowerShell" in result["error"]


def test_notification_command_failure_returns_status(monkeypatch) -> None:
    def fake_run(_command, **_kwargs):
        raise subprocess.CalledProcessError(1, ["notify-send"], stderr="no display")

    monkeypatch.setattr(notification.sys, "platform", "linux")
    monkeypatch.setattr(notification.shutil, "which", lambda name: "/usr/bin/notify-send" if name == "notify-send" else None)
    monkeypatch.setattr(notification.subprocess, "run", fake_run)

    result = notification.notify_desktop("NixAI", "Message")

    assert result["success"] is False
    assert result["accepted_by_system"] is False
    assert result["details"] == "no display"


def test_notification_input_is_cleaned_and_limited(monkeypatch) -> None:
    monkeypatch.setattr(notification.sys, "platform", "freebsd13")

    result = notification.notify_desktop("  " + ("T" * 100), "  " + ("M" * 300), " A   B ")

    assert result["success"] is False
    assert result["title"] == "T" * notification.MAX_TITLE_CHARS
    assert result["message"] == "M" * notification.MAX_MESSAGE_CHARS
    assert result["subtitle"] == "A B"
