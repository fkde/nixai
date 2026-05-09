from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import database
from app.api.agentic_tasks import router as agentic_tasks_router
from app.api.chats import router as chats_router
from app.api.roles import router as roles_router
from app.api.settings import router as settings_router
from app.api.tools import router as tools_router


def create_app() -> FastAPI:
    database.init_db()

    fastapi_app = FastAPI(title="NixAI", version="0.1.0")
    static_dir = Path(__file__).parent / "static"
    fastapi_app.include_router(agentic_tasks_router)
    fastapi_app.include_router(chats_router)
    fastapi_app.include_router(roles_router)
    fastapi_app.include_router(settings_router)
    fastapi_app.include_router(tools_router)
    fastapi_app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @fastapi_app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return fastapi_app


app = create_app()
