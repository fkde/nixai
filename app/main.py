from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from app import database
from app.api.agentic_tasks import router as agentic_tasks_router
from app.api.chats import router as chats_router
from app.api.mistakes import router as mistakes_router
from app.api.roles import router as roles_router
from app.api.settings import router as settings_router
from app.api.tools import router as tools_router
from app.agentic_scheduler import scheduler


class RevalidatingStaticFiles(StaticFiles):
    """Force browsers (and pywebview's WKWebView) to revalidate static assets.

    Starlette already emits ETag/Last-Modified; `no-cache` means "you may
    cache, but always ask first." Combined with the existing validators this
    yields a 304 when nothing changed, or fresh content when it did — so a
    plain reload picks up CSS/JS edits without a hard refresh.
    """

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


def _build_static_version(static_dir: Path) -> str:
    """Hash of every static file's path + mtime — changes when anything changes.

    Used as a cache-busting query string on entry-point assets in index.html
    so the embedded webview cannot serve a stale bundle from an earlier
    session even if Cache-Control headers are ignored.
    """
    hasher = hashlib.sha1()
    for path in sorted(static_dir.rglob("*")):
        if not path.is_file():
            continue
        hasher.update(str(path.relative_to(static_dir)).encode("utf-8"))
        hasher.update(str(path.stat().st_mtime_ns).encode("utf-8"))
    return hasher.hexdigest()[:12]


_ASSET_REF_RE = re.compile(
    r"""(?P<prefix>(?:href|src)=["'])(?P<url>/static/[^"'?\s]+\.(?:css|js))(?P<suffix>["'])""",
)


def _render_index(static_dir: Path, version: str) -> str:
    raw = (static_dir / "index.html").read_text(encoding="utf-8")
    return _ASSET_REF_RE.sub(
        lambda match: f"{match.group('prefix')}{match.group('url')}?v={version}{match.group('suffix')}",
        raw,
    )


def create_app() -> FastAPI:
    database.init_db()

    fastapi_app = FastAPI(title="NixAI", version="0.1.0")
    static_dir = Path(__file__).parent / "static"
    static_version = _build_static_version(static_dir)
    fastapi_app.include_router(agentic_tasks_router)
    fastapi_app.include_router(chats_router)
    fastapi_app.include_router(mistakes_router)
    fastapi_app.include_router(roles_router)
    fastapi_app.include_router(settings_router)
    fastapi_app.include_router(tools_router)
    fastapi_app.mount("/static", RevalidatingStaticFiles(directory=static_dir), name="static")

    @fastapi_app.on_event("startup")
    async def start_agentic_scheduler() -> None:
        scheduler.start()

    @fastapi_app.on_event("shutdown")
    async def stop_agentic_scheduler() -> None:
        await scheduler.stop()

    @fastapi_app.get("/")
    def index() -> HTMLResponse:
        # The shell HTML must never be cached so it always references the
        # current static version. Combined with the ?v=<hash> stamp this makes
        # stale bundles impossible after a restart, even inside WKWebView.
        return HTMLResponse(
            _render_index(static_dir, static_version),
            headers={"Cache-Control": "no-store, must-revalidate"},
        )

    return fastapi_app


app = create_app()
