from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.mistakes import MistakesDocument, load_mistakes, save_mistakes


router = APIRouter(prefix="/api/mistakes", tags=["mistakes"])


class MistakesPayload(BaseModel):
    content: str


@router.get("", response_model=MistakesDocument)
def get_mistakes() -> MistakesDocument:
    return load_mistakes()


@router.put("", response_model=MistakesDocument)
def put_mistakes(payload: MistakesPayload) -> MistakesDocument:
    return save_mistakes(payload.content)
