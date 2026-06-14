"""FastAPI router for the management simulator."""

from __future__ import annotations

from fastapi import APIRouter, Cookie, HTTPException
from pydantic import BaseModel, Field

import auth

from .service import ManagementSimService


router = APIRouter(prefix="/api/management-sim", tags=["management-sim"])
service = ManagementSimService()


class StartRequest(BaseModel):
    mission: str
    budget_cents: int


class DialogueRequest(BaseModel):
    message: str


class ActionRequest(BaseModel):
    persona_id: str
    action: str
    rationale: str = ""


def _require_user(session_token: str | None) -> dict:
    user = auth.current_user(session_token)
    if not user:
        raise HTTPException(status_code=401, detail="sign in required")
    return user


@router.get("/current")
async def current(simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    state = service.load_active_run(user["id"])
    return {"run": service.public_state(state)}


@router.post("/start")
async def start(req: StartRequest, simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    mission = req.mission.strip()
    if not mission:
        raise HTTPException(status_code=400, detail="mission required")
    if req.budget_cents < 500_000_00 or req.budget_cents > 5_000_000_00:
        raise HTTPException(status_code=400, detail="budget must be between $500,000 and $5,000,000")
    state = service.create_run(user["id"], mission, req.budget_cents)
    return {"run": service.public_state(state)}


@router.get("/week")
async def week(simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    state = service.load_active_run(user["id"])
    if not state:
        raise HTTPException(status_code=404, detail="no active run")
    return service.week_view(state)


@router.post("/dialogue/{persona_id}")
async def dialogue(persona_id: str, req: DialogueRequest, simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    try:
        return service.send_message(user["id"], persona_id, req.message)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/action")
async def action(req: ActionRequest, simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    try:
        return {"run": service.apply_manager_action(user["id"], req.persona_id, req.action, req.rationale)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/advance")
async def advance(simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    try:
        state = service.advance_week(user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"run": service.public_state(state)}


@router.get("/assessment")
async def assessment(simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    try:
        report = service.assessment(user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"report": report}
