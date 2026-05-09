from __future__ import annotations

import socket
import threading
import time

import httpx
import uvicorn

from app.config import config_path, database_path, load_settings
from app.database import init_db


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(url: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=0.5)
            if response.status_code < 500:
                return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise RuntimeError(f"NixAI desktop server did not become ready at {url}")


def run_desktop(host: str = "127.0.0.1", port: int = 0) -> None:
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "Desktop mode requires pywebview. Install it with `pip install -r requirements-desktop.txt` "
            "or `pip install -e \".[desktop]\"`."
        ) from exc

    settings = load_settings()
    init_db()

    actual_port = port or _free_port(host)
    url = f"http://{host}:{actual_port}"
    config = uvicorn.Config("app.main:app", host=host, port=actual_port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="nixai-desktop-server", daemon=True)
    thread.start()
    _wait_until_ready(url)

    window = webview.create_window(
        "NixAI",
        url,
        width=1280,
        height=820,
        min_size=(920, 640),
        text_select=True,
    )
    window.events.closing += lambda: setattr(server, "should_exit", True)

    print(f"NixAI desktop at {url}")
    print(f"Config: {config_path()}")
    print(f"Database: {database_path()}")
    print(f"Workspace: {settings.workspace_path}")
    webview.start(debug=False)
