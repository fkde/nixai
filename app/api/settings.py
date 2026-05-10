from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import Settings, load_settings, save_settings
from app.llm.ollama import OllamaClient, OllamaError
from app.models import OllamaModelInfo
from app.workflows.models import WorkflowDefinition
from app.workflows.presets import delete_custom_workflow, list_custom_workflow_ids, list_workflow_summaries, save_custom_workflow


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
        "custom_ids": list_custom_workflow_ids(),
        "workflows": [workflow.model_dump(by_alias=True) for workflow in list_workflow_summaries()],
    }


@router.put("/workflows/{workflow_id}")
def put_workflow(workflow_id: str, workflow: WorkflowDefinition) -> dict[str, object]:
    if workflow.id != workflow_id:
        workflow = workflow.model_copy(update={"id": workflow_id})
    try:
        saved = save_custom_workflow(workflow)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "workflow": saved.model_dump(by_alias=True)}


@router.delete("/workflows/{workflow_id}")
def remove_workflow(workflow_id: str) -> dict[str, object]:
    try:
        deleted = delete_custom_workflow(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Custom workflow not found.")
    return {"success": True}


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
