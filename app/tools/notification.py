from __future__ import annotations

from typing import Any

import shutil
import subprocess
import sys


MAX_TITLE_CHARS = 80
MAX_MESSAGE_CHARS = 240
MAX_SOUND_CHARS = 40


def notify_desktop(title: str, message: str, subtitle: str = "", sound: str = "Glass") -> dict[str, Any]:
    clean_title = _clean(title, MAX_TITLE_CHARS) or "NixAI"
    clean_message = _clean(message, MAX_MESSAGE_CHARS)
    clean_subtitle = _clean(subtitle, MAX_TITLE_CHARS)
    clean_sound = _clean(sound, MAX_SOUND_CHARS) or "Glass"
    if not clean_message:
        raise ValueError("Notification message is required.")

    if sys.platform == "darwin":
        return _notify_macos(clean_title, clean_message, clean_subtitle, clean_sound)
    if sys.platform.startswith("linux"):
        return _notify_linux(clean_title, clean_message, clean_subtitle)
    if sys.platform.startswith("win"):
        return _notify_windows(clean_title, clean_message, clean_subtitle)

    return _unavailable(
        sys.platform,
        "Desktop notifications are not implemented for this platform.",
        clean_title,
        clean_message,
        clean_subtitle,
    )


def _notify_macos(title: str, message: str, subtitle: str, sound: str) -> dict[str, Any]:
    script = 'display notification "{message}" with title "{title}"'.format(
        message=_escape_osascript(message), title=_escape_osascript(title)
    )
    if subtitle:
        script += ' subtitle "{subtitle}"'.format(subtitle=_escape_osascript(subtitle))
    if sound.casefold() != "none":
        script += ' sound name "{sound}"'.format(sound=_escape_osascript(sound))

    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return _failure("darwin", "macOS notification command failed.", title, message, subtitle, exc)
    return {
        "success": True,
        "platform": "darwin",
        "mechanism": "osascript",
        "accepted_by_system": True,
        "accepted_by_macos": True,
        "title": title,
        "message": message,
        "subtitle": subtitle,
        "sound": sound,
        "delivery_note": "macOS accepted the notification request. Visibility can still be suppressed by Focus mode or notification permissions for the sending app.",
    }


def _notify_linux(title: str, message: str, subtitle: str) -> dict[str, Any]:
    notify_send = shutil.which("notify-send")
    if not notify_send:
        return _unavailable(
            "linux",
            "notify-send is not available. Install libnotify to enable desktop notifications.",
            title,
            message,
            subtitle,
        )

    body = f"{subtitle}\n{message}" if subtitle else message
    try:
        subprocess.run(
            [notify_send, "--app-name=NixAI", title, body],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return _failure("linux", "notify-send failed.", title, message, subtitle, exc)
    return {
        "success": True,
        "platform": "linux",
        "mechanism": "notify-send",
        "accepted_by_system": True,
        "title": title,
        "message": message,
        "subtitle": subtitle,
        "delivery_note": "Linux accepted the notification request through notify-send. Visibility can still depend on the desktop environment and notification settings.",
    }


def _notify_windows(title: str, message: str, subtitle: str) -> dict[str, Any]:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return _unavailable(
            "win32",
            "PowerShell is not available, so NixAI cannot request a Windows toast notification.",
            title,
            message,
            subtitle,
        )

    script = r"""
$ErrorActionPreference = "Stop"
$title = $args[0]
$message = $args[1]
$subtitle = $args[2]
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$template = [Windows.UI.Notifications.ToastTemplateType]::ToastText02
if ($subtitle) { $template = [Windows.UI.Notifications.ToastTemplateType]::ToastText04 }
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($template)
$nodes = $xml.GetElementsByTagName("text")
$nodes.Item(0).AppendChild($xml.CreateTextNode($title)) > $null
if ($subtitle) {
    $nodes.Item(1).AppendChild($xml.CreateTextNode($subtitle)) > $null
    $nodes.Item(2).AppendChild($xml.CreateTextNode($message)) > $null
} else {
    $nodes.Item(1).AppendChild($xml.CreateTextNode($message)) > $null
}
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("NixAI")
$notifier.Show($toast)
""".strip()
    command = [
        powershell,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
        title,
        message,
        subtitle,
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return _failure("win32", "Windows toast notification failed.", title, message, subtitle, exc)
    return {
        "success": True,
        "platform": "win32",
        "mechanism": "powershell-winrt-toast",
        "accepted_by_system": True,
        "title": title,
        "message": message,
        "subtitle": subtitle,
        "delivery_note": "Windows accepted the toast notification request. Visibility can still depend on Focus Assist and notification permissions.",
    }


def _unavailable(platform_name: str, error: str, title: str, message: str, subtitle: str) -> dict[str, Any]:
    return {
        "success": False,
        "platform": platform_name,
        "accepted_by_system": False,
        "title": title,
        "message": message,
        "subtitle": subtitle,
        "error": error,
    }


def _failure(platform_name: str, error: str, title: str, message: str, subtitle: str, exc: BaseException) -> dict[str, Any]:
    details = str(exc)
    stderr = getattr(exc, "stderr", None)
    if stderr:
        details = str(stderr).strip()[:500]
    return {
        "success": False,
        "platform": platform_name,
        "accepted_by_system": False,
        "title": title,
        "message": message,
        "subtitle": subtitle,
        "error": error,
        "details": details,
    }


def _clean(value: str, limit: int) -> str:
    return " ".join(str(value or "").strip().split())[:limit]


def _escape_osascript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
