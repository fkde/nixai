from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.config import Settings, load_settings, save_settings
from app.llm.ollama import OllamaClient, OllamaError


router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=Settings)
def get_settings() -> Settings:
    return load_settings()


@router.put("", response_model=Settings)
def put_settings(settings: Settings) -> Settings:
    save_settings(settings)
    return load_settings()


@router.get("/models", response_model=list[str])
async def get_models() -> list[str]:
    try:
        return await OllamaClient(load_settings()).list_models()
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
