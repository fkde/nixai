from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from app.config import config_path, database_path, load_settings
from app.database import init_db


TEMPLATE_DIR = Path(__file__).with_name("templates")


class DesktopApi:
    def __init__(self) -> None:
        self.window = None

    def _dispatch_macos_action(self, action: object) -> bool:
        if sys.platform != "darwin" or self.window is None:
            return False
        try:
            from PyObjCTools import AppHelper
        except Exception:
            return False
        try:
            AppHelper.callAfter(action)
            return True
        except Exception:
            return False

    def choose_workspace(self) -> str:
        if self.window is None:
            return ""
        import webview

        result = self.window.create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
        if not result:
            return ""
        return str(result[0])

    def desktop_info(self) -> dict[str, object]:
        return {
            "platform": sys.platform,
            "native_chrome": sys.platform == "darwin",
            "native_traffic_lights": sys.platform == "darwin",
        }

    def close_window(self) -> None:
        if self.window is None:
            return

        def action() -> None:
            try:
                import AppKit

                app = AppKit.NSApplication.sharedApplication()
                if app is not None and hasattr(app, "terminate_"):
                    app.terminate_(None)
                    return
            except Exception:
                pass
            native = getattr(self.window, "native", None)
            if native is not None and hasattr(native, "performClose_"):
                native.performClose_(None)
                return
            self.window.destroy()

        if self._dispatch_macos_action(action):
            return
        self.window.destroy()

    def minimize_window(self) -> None:
        if self.window is None:
            return

        def action() -> None:
            native = getattr(self.window, "native", None)
            if native is not None and hasattr(native, "miniaturize_"):
                native.miniaturize_(None)
                return
            self.window.minimize()

        if self._dispatch_macos_action(action):
            return
        self.window.minimize()

    def zoom_window(self) -> None:
        if self.window is None:
            return

        def action() -> None:
            native = getattr(self.window, "native", None)
            if native is not None and hasattr(native, "zoom_"):
                native.zoom_(None)
                return
            self.window.toggle_fullscreen()

        if self._dispatch_macos_action(action):
            return
        self.window.toggle_fullscreen()


def ensure_desktop_dependencies() -> None:
    try:
        import webview  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "Desktop mode requires pywebview. Install it with `pip install -r requirements-desktop.txt` "
            "or `pip install -e \".[desktop]\"`."
        ) from exc


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(url: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=0.5) as response:  # nosec B310: local loopback URL from own process
                if int(getattr(response, "status", 200)) < 500:
                    return
        except URLError:
            time.sleep(0.1)
    raise RuntimeError(f"NixAI desktop server did not become ready at {url}")


def _configure_macos_chrome(window: object) -> None:
    try:
        import AppKit
    except Exception:
        return

    native = getattr(window, "native", None)
    if native is None:
        return

    try:
        if hasattr(native, "setTitlebarAppearsTransparent_"):
            native.setTitlebarAppearsTransparent_(True)
        if hasattr(native, "setTitleVisibility_") and hasattr(AppKit, "NSWindowTitleHidden"):
            native.setTitleVisibility_(AppKit.NSWindowTitleHidden)
        if hasattr(native, "setMovableByWindowBackground_"):
            native.setMovableByWindowBackground_(True)
        if hasattr(native, "setToolbarStyle_") and hasattr(AppKit, "NSWindowToolbarStyleUnifiedCompact"):
            native.setToolbarStyle_(AppKit.NSWindowToolbarStyleUnifiedCompact)

        for button_type in (
            AppKit.NSWindowCloseButton,
            AppKit.NSWindowMiniaturizeButton,
            AppKit.NSWindowZoomButton,
        ):
            button = native.standardWindowButton_(button_type)
            if button is not None:
                button.setHidden_(False)
    except Exception:
        return


def _schedule_macos_chrome(window: object) -> None:
    if sys.platform != "darwin":
        return
    try:
        from PyObjCTools import AppHelper
    except Exception:
        return
    try:
        AppHelper.callAfter(_configure_macos_chrome, window)
    except Exception:
        return


def _read_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def _loading_html() -> str:
    return _read_template("loading.html")


def _error_html(message: str) -> str:
    safe = (message or "Unknown startup error").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _read_template("error.html").replace("{{ message }}", safe)


def run_desktop(host: str = "127.0.0.1", port: int = 0) -> None:
    ensure_desktop_dependencies()
    import webview
    import uvicorn

    settings = load_settings()
    init_db()

    actual_port = port or _free_port(host)
    url = f"http://{host}:{actual_port}"
    config = uvicorn.Config("app.main:app", host=host, port=actual_port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="nixai-desktop-server", daemon=True)

    api = DesktopApi()
    is_macos = sys.platform == "darwin"
    window = webview.create_window(
        "NixAI",
        html=_loading_html(),
        width=1280,
        height=820,
        min_size=(920, 640),
        frameless=False,
        easy_drag=False,
        vibrancy=is_macos,
        background_color="#08090d",
        text_select=True,
        js_api=api,
    )
    api.window = window
    window.events.closing += lambda: setattr(server, "should_exit", True)
    if is_macos:
        window.events.shown += lambda: _schedule_macos_chrome(window)

    print(f"NixAI desktop at {url}")
    print(f"Config: {config_path()}")
    print(f"Database: {database_path()}")
    print(f"Workspace: {settings.workspace_path}")

    def bootstrap() -> None:
        thread.start()
        try:
            _wait_until_ready(url)
            if api.window is not None:
                api.window.load_url(url)
        except Exception as exc:
            server.should_exit = True
            if api.window is not None:
                api.window.load_html(_error_html(str(exc)))

    webview.start(func=bootstrap, debug=False)
