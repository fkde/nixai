from __future__ import annotations

from fastapi import APIRouter
from fastapi import HTTPException
from pydantic import BaseModel

from app.memory import MemoryDocument, load_memory, save_memory
from app.mistake_review import MistakeReview, MistakeSolution
from app.mistakes import MistakeEntry, MistakesDocument, get_mistake_entry, list_mistake_entries, load_mistakes, save_mistakes


router = APIRouter(prefix="/api/mistakes", tags=["mistakes"])


class MistakesPayload(BaseModel):
    content: str


class MemoryPayload(BaseModel):
    content: str


class AcceptMistakeSolutionPayload(BaseModel):
    title: str
    instruction: str
    rationale: str = ""


@router.get("", response_model=MistakesDocument)
def get_mistakes() -> MistakesDocument:
    return load_mistakes()


@router.put("", response_model=MistakesDocument)
def put_mistakes(payload: MistakesPayload) -> MistakesDocument:
    return save_mistakes(payload.content)


@router.get("/entries", response_model=list[MistakeEntry])
def get_mistake_entries() -> list[MistakeEntry]:
    return list_mistake_entries()


@router.post("/entries/{entry_id}/suggest-solution", response_model=MistakeSolution)
async def post_suggest_solution(entry_id: str) -> MistakeSolution:
    entry = get_mistake_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Mistake entry not found")
    return await MistakeReview().propose_solution(entry)


@router.post("/entries/{entry_id}/accept-solution", response_model=MemoryDocument)
def post_accept_solution(entry_id: str, payload: AcceptMistakeSolutionPayload) -> MemoryDocument:
    entry = get_mistake_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Mistake entry not found")
    return MistakeReview().accept_solution(
        entry,
        MistakeSolution(title=payload.title, instruction=payload.instruction, rationale=payload.rationale),
    )


@router.get("/memory", response_model=MemoryDocument)
def get_memory() -> MemoryDocument:
    return load_memory()


@router.put("/memory", response_model=MemoryDocument)
def put_memory(payload: MemoryPayload) -> MemoryDocument:
    return save_memory(payload.content)
