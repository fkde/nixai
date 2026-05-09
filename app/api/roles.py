from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.roles import RolePrompt
from app.roles import create_role as create_role_file
from app.roles import delete_role as delete_role_file
from app.roles import list_roles as list_role_files
from app.roles import load_role
from app.roles import normalize_role_name
from app.roles import save_role


router = APIRouter(prefix="/api/roles", tags=["roles"])


class RolePromptPayload(BaseModel):
    name: Optional[str] = None
    content: str


@router.get("", response_model=list[RolePrompt])
def get_roles() -> list[RolePrompt]:
    return list_role_files()


@router.post("", response_model=RolePrompt)
def post_role(payload: RolePromptPayload) -> RolePrompt:
    if not payload.name:
        raise HTTPException(status_code=422, detail="Role name is required.")
    try:
        return create_role_file(payload.name, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail="Role already exists.") from exc


@router.get("/{name}", response_model=RolePrompt)
def get_role(name: str) -> RolePrompt:
    try:
        return load_role(name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Role not found.") from exc


@router.put("/{name}", response_model=RolePrompt)
def put_role(name: str, payload: RolePromptPayload) -> RolePrompt:
    try:
        role_name = normalize_role_name(payload.name or name)
        path_name = normalize_role_name(name)
        if role_name != path_name:
            raise HTTPException(status_code=409, detail="Role name and URL do not match.")
        return save_role(role_name, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{name}", status_code=204)
def delete_role(name: str) -> Response:
    try:
        delete_role_file(name)
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Role not found.") from exc
    return Response(status_code=204)
