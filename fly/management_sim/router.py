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


class PredictionRequest(BaseModel):
    subject: str
    outcome: str
    direction: str
    confidence: int
    rationale: str


class DayReportRequest(BaseModel):
    report: str | None = None
    observations: str = ""
    hypotheses: str = ""
    questions: str = ""
    decision: str = ""
    change_mind: str = ""
    predictions: list[PredictionRequest] = Field(default_factory=list, max_length=3)

    def journal(self) -> str | dict:
        if self.report is not None:
            return self.report
        return {
            "observations": self.observations,
            "hypotheses": self.hypotheses,
            "questions": self.questions,
            "decision": self.decision,
            "change_mind": self.change_mind,
            "predictions": [prediction.model_dump() for prediction in self.predictions],
        }


class ReportRequest(BaseModel):
    report: str


class InterviewsRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=2, max_length=2)


class HireRequest(BaseModel):
    candidate_id: str


class TerminationsRequest(BaseModel):
    persona_ids: list[str] = Field(min_length=2, max_length=2)


class BackfillRequest(BaseModel):
    candidate_id: str | None = None


class TrackingRequest(BaseModel):
    focus: list[str] = Field(min_length=1, max_length=3)


class AdvanceRequest(BaseModel):
    expected_day: int


class InvestigateArtifactRequest(BaseModel):
    artifact_id: str


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


@router.post("/investigate")
async def investigate(req: InvestigateArtifactRequest, simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    try:
        return {"run": service.investigate_artifact(user["id"], req.artifact_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/day-report")
async def day_report(req: DayReportRequest, simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    try:
        return {"run": service.submit_day_report(user["id"], req.journal())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/week-report")
async def week_report(req: ReportRequest, simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    try:
        return {"run": service.submit_week_report(user["id"], req.report)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tracking")
async def tracking(req: TrackingRequest, simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    try:
        return {"run": service.set_tracking_focus(user["id"], req.focus)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/interviews")
async def interviews(req: InterviewsRequest, simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    try:
        return {"run": service.select_interviews(user["id"], req.candidate_ids)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/hire")
async def hire(req: HireRequest, simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    try:
        return {"run": service.choose_hire(user["id"], req.candidate_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/terminations")
async def terminations(req: TerminationsRequest, simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    try:
        return {"run": service.select_terminations(user["id"], req.persona_ids)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/backfill")
async def backfill(req: BackfillRequest, simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    try:
        return {"run": service.choose_backfill(user["id"], req.candidate_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/advance")
async def advance(req: AdvanceRequest, simulacrum_session: str | None = Cookie(None)):
    user = _require_user(simulacrum_session)
    try:
        state = service.advance_day(user["id"], expected_day=req.expected_day)
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
