from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import Settings, load_settings, save_settings
from app.llm.ollama import OllamaClient, OllamaError
from app.models import OllamaModelInfo
from app.workflows.presets import list_workflow_summaries


router = APIRouter(prefix="/api/settings", tags=["settings"])


class EmailProviderAuthRequest(BaseModel):
    provider: str


class EmailProviderAuthResponse(BaseModel):
    provider: str
    status: str
    message: str
    auth_url: Optional[str] = None


@router.get("", response_model=Settings)
def get_settings() -> Settings:
    return load_settings()


@router.put("", response_model=Settings)
def put_settings(settings: Settings) -> Settings:
    save_settings(settings)
    return load_settings()


@router.get("/models", response_model=list[OllamaModelInfo])
async def get_models() -> list[OllamaModelInfo]:
    try:
        return await OllamaClient(load_settings()).list_model_catalog()
    except OllamaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/workflows")
def get_workflows() -> dict[str, object]:
    settings = load_settings()
    return {
        "success": True,
        "selected": settings.workflow_presets,
        "workflows": [workflow.model_dump(by_alias=True) for workflow in list_workflow_summaries()],
    }


@router.post("/email-provider/auth", response_model=EmailProviderAuthResponse)
def start_email_provider_auth(request: EmailProviderAuthRequest) -> EmailProviderAuthResponse:
    provider = request.provider.strip().lower()
    if provider not in {"google", "microsoft"}:
        raise HTTPException(status_code=400, detail="Unsupported email provider.")

    settings = load_settings()
    settings.email_provider.provider = provider
    settings.email_provider.status = "pending"
    settings.email_provider.account_email = ""
    settings.email_provider.scopes = _email_scopes(provider)
    save_settings(settings)

    label = "Google" if provider == "google" else "Microsoft"
    return EmailProviderAuthResponse(
        provider=provider,
        status="pending",
        message=f"{label} OAuth is prepared, but the real OAuth client flow is not configured yet.",
    )


@router.post("/email-provider/disconnect", response_model=Settings)
def disconnect_email_provider() -> Settings:
    settings = load_settings()
    settings.email_provider.provider = ""
    settings.email_provider.status = "disconnected"
    settings.email_provider.account_email = ""
    settings.email_provider.scopes = []
    save_settings(settings)
    return load_settings()


def _email_scopes(provider: str) -> list[str]:
    if provider == "google":
        return ["gmail.readonly"]
    if provider == "microsoft":
        return ["Mail.Read"]
    return []
