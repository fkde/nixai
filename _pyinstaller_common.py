from __future__ import annotations

from PyInstaller.utils.hooks import collect_submodules


def _exclude_android_webview(name: str) -> bool:
    return not name.startswith("webview.platforms.android")


def collect_hiddenimports() -> list[str]:
    hiddenimports: list[str] = []
    hiddenimports += collect_submodules("app")

    for package in (
        "webview",
        "objc",
        "Foundation",
        "AppKit",
        "WebKit",
        "Quartz",
        "Security",
    ):
        try:
            if package == "webview":
                hiddenimports += collect_submodules(package, filter=_exclude_android_webview)
            else:
                hiddenimports += collect_submodules(package)
        except Exception:
            pass
    return hiddenimports


def common_datas() -> list[tuple[str, str]]:
    return [
        ("app/static", "app/static"),
        ("app/templates", "app/templates"),
        ("app/workflows/presets", "app/workflows/presets"),
    ]


def common_excludes() -> list[str]:
    return ["webview.platforms.android", "android"]
