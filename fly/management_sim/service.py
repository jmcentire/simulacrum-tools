"""Orchestration for the management-simulation curriculum loop."""

from __future__ import annotations

import random
from typing import Any

import db

from . import persistence
from .artifacts import ArtifactService
from .assessor import HypervisorAssessor
from .curriculum import day_in_week, plan_for_day, week_for_day
from .interviews import CandidateInterviewService
from .latent_state import ACTION_VOCABULARY, advance_day, apply_action, initial_state, state_hash
from .models import HiddenState
from .observations import persona_observations, product_observations
from .persona_store import PersonaStore
from .relationships import (
    add_persona_relationships,
    advance_relationships,
    generate_inbox,
    initial_relationships,
    public_inbox,
    relationship_context,
    remove_persona_relationships,
)
from .retention import advance_retention_watch, choose_voluntary_exit, initial_retention_watch
from .structure import structure_pressure, team_structure
from .work import advance_workstreams, initial_workstreams, public_workstreams, work_artifacts, work_pressure


STARTING_TEAM_IDS = ["maya", "jonah", "elena", "trent", "rhea"]
FINAL_DAY = 20


def _clamp(value: int) -> int:
    return max(0, min(100, value))


def _preventable_exit_summary(name: str, reason: str) -> str:
    if reason == "micromanagement":
        return f"{name} accepted another role after saying the current review cadence left too little room to own decisions."
    if reason == "stagnation":
        return f"{name} accepted another role after asking for work with more room to learn and build."
    if reason == "overload":
        return f"{name} accepted another role after several weeks of carrying more work than they could sustainably absorb."
    if reason == "trust_loss":
        return f"{name} accepted another role after becoming less convinced the team could change course."
    return f"{name} accepted another role after several weeks of disengaging from the current work."


def _preventable_exit_detail(name: str, reason: str) -> str:
    if reason == "micromanagement":
        return f"{name} said they were tired of owning the work without owning the decisions. The team now has to reconstruct the context they carried."
    if reason == "stagnation":
        return f"{name} said the role had become mostly maintenance and follow-up work. The team now has to reconstruct the context they carried."
    if reason == "overload":
        return f"{name} said they could not keep absorbing the extra work without dropping quality. The team now has to reconstruct the context they carried."
    if reason == "trust_loss":
        return f"{name} said they no longer understood whether the team was allowed to change course. The team now has to reconstruct the context they carried."
    return f"{name} said the work no longer felt worth the cost. The team now has to reconstruct the context they carried."


class ManagementSimService:
    def __init__(self):
        self.personas = PersonaStore()
        self.artifacts = ArtifactService()
        self.candidate_interviews = CandidateInterviewService()
        self.assessor = HypervisorAssessor()

    def create_run(self, user_id: str, mission: str, budget_cents: int) -> dict[str, Any]:
        persistence.archive_active_runs(user_id)
        run_id = db.new_id()
        team = list(STARTING_TEAM_IDS)
        salary = sum(self.personas.get(persona_id).salary_cents for persona_id in team)
        state = {
            "run_id": run_id,
            "phase": "daily_loop",
            "day": 1,
            "week": 1,
            "day_in_week": 1,
            "mission": mission,
            "budget_cents": budget_cents,
            "cash_remaining_cents": budget_cents - salary,
            "team": team,
            "team_state": {persona_id: initial_state(self.personas.get(persona_id), 1).to_dict() for persona_id in team},
            "product": {"velocity": 58, "error_rate": 14, "alignment": 52, "total_value": 48},
            "product_pressure": 74,
            "reports": {"daily": {}, "weekly": {}},
            "tracking_focus": [],
            "relationships": initial_relationships(run_id, team, self._persona_map(team)),
            "attention": {"budget": 4, "remaining": 4, "spent": []},
            "artifact_inbox": [],
            "day_actions": [],
            "world_events": [],
            "retention_watch": initial_retention_watch(team),
            "retention_alerts": [],
            "departed_people": [],
            "workstreams": initial_workstreams(team, self._persona_map(team)),
            "candidate_interviews": {},
            "milestones": {
                "week_1_hire": {
                    "pool": self._candidate_ids(run_id, "week_1_hire", team),
                    "interview_ids": [],
                    "selected_id": None,
                    "status": "open",
                },
                "week_2_reduction": {
                    "selected_ids": [],
                    "backfill_pool": [],
                    "backfill_selected_id": None,
                    "backfill_decided": False,
                    "applied": False,
                },
            },
        }
        persistence.create_run(user_id, mission, budget_cents, state)
        persistence.append_event(run_id, user_id, "run_started", {"summary": "Started with five-person team and an oversized mission."})
        self._refresh_day_context(state)
        persistence.save_run(user_id, state)
        self._ensure_week_artifacts(user_id, state)
        return state

    def load_active_run(self, user_id: str) -> dict[str, Any] | None:
        state = persistence.load_active_run(user_id)
        if not state:
            return None
        changed = self._normalize_state(state)
        if changed:
            persistence.save_run(user_id, state)
        return state

    def public_state(self, state: dict[str, Any] | None) -> dict[str, Any] | None:
        if not state:
            return None
        self._normalize_state(state)
        team = []
        for persona_id in state["team"]:
            persona = self.personas.get(persona_id)
            hidden = HiddenState(**state["team_state"][persona_id])
            team.append(
                {
                    **persona.public_summary(),
                    "observations": persona_observations(persona, hidden, f"team:{state['day']}:{persona_id}"),
                }
            )
        return {
            "run_id": state["run_id"],
            "phase": state["phase"],
            "day": state["day"],
            "week": state["week"],
            "day_in_week": state["day_in_week"],
            "mission": state["mission"],
            "budget_cents": state["budget_cents"],
            "cash_remaining_cents": state["cash_remaining_cents"],
            "team": team,
            "product": state["product"],
            "tracking_focus": state["tracking_focus"],
            "attention": state["attention"],
            "artifact_inbox": public_inbox(state["artifact_inbox"]),
            "world_events": self._public_world_events(state),
            "workstreams": public_workstreams(state["workstreams"], self._persona_map(state["team"])),
            "curriculum": plan_for_day(state["day"]),
            "reports_due": self._reports_due(state),
            "milestones": self._public_milestones(state),
            "actions": [{"id": key, "label": label} for key, label in ACTION_VOCABULARY.items()],
        }

    def week_view(self, state: dict[str, Any]) -> dict[str, Any]:
        self._normalize_state(state)
        artifacts = persistence.list_artifacts(state["run_id"], state["day"])
        by_persona = {item["persona_id"]: item for item in artifacts}
        reports = []
        for persona_id in state["team"]:
            persona = self.personas.get(persona_id)
            artifact = by_persona.get(persona_id)
            reports.append(
                {
                    "persona_id": persona_id,
                    "name": persona.name,
                    "role": persona.role,
                    "report_text": artifact["report_text"] if artifact else "",
                    "observations": persona_observations(persona, HiddenState(**state["team_state"][persona_id]), f"team:{state['day']}:{persona_id}"),
                }
            )
        team_states = [HiddenState(**state["team_state"][persona_id]) for persona_id in state["team"]]
        return {
            "day": state["day"],
            "week": state["week"],
            "day_in_week": state["day_in_week"],
            "curriculum": plan_for_day(state["day"]),
            "reports": reports,
            "product": state["product"],
            "tracking_focus": state["tracking_focus"],
            "attention": state["attention"],
            "artifact_inbox": public_inbox(state["artifact_inbox"]),
            "world_events": self._public_world_events(state),
            "workstreams": public_workstreams(state["workstreams"], self._persona_map(state["team"])),
            "product_observations": product_observations(
                {**state["product"], "pressure": state["product_pressure"]},
                team_states,
                state["tracking_focus"],
                f"product:{state['run_id']}:{state['day']}",
            ),
            "reports_due": self._reports_due(state),
            "milestones": self._public_milestones(state),
            "candidate_pool": self._candidate_pool_view(state),
            "actions": [{"id": key, "label": label} for key, label in ACTION_VOCABULARY.items()],
        }

    def send_message(self, user_id: str, persona_id: str, message: str) -> dict[str, Any]:
        state = self._require_run(user_id)
        if persona_id not in state["team"]:
            raise ValueError("persona is not on this team")
        history = persistence.list_turns(state["run_id"], persona_id, state["day"])
        has_spent_attention = any(item.get("type") == "1:1" and item.get("persona_id") == persona_id for item in state["attention"]["spent"])
        if not history and not has_spent_attention:
            self._spend_attention(state, "1:1", persona_id, f"Opened a 1:1 with {persona_id}.")
        persona = self.personas.get(persona_id)
        hidden = HiddenState(**state["team_state"][persona_id])
        response = self.artifacts.send_message(state["run_id"], persona, hidden, message)
        persistence.save_run(user_id, state)
        persistence.append_event(
            state["run_id"],
            user_id,
            "dialogue_turn",
            {"persona_id": persona_id, "turn_number": response["turn_number"], "state_hash": state_hash(hidden)},
        )
        return response

    def send_candidate_interview(self, user_id: str, candidate_id: str, message: str) -> dict[str, Any]:
        state = self._require_run(user_id)
        pool = self._active_candidate_pool_ids(state)
        if candidate_id not in pool:
            raise ValueError("candidate is not in the active interview pool")
        milestone = state["milestones"]["week_1_hire"] if state["day"] in (4, 5) else state["milestones"]["week_2_reduction"]
        if state["day"] in (4, 5) and candidate_id not in milestone["interview_ids"]:
            raise ValueError("choose the candidate for an interview before asking questions")
        history = state["candidate_interviews"].setdefault(candidate_id, [])
        if not history:
            self._spend_attention(state, "candidate_interview", candidate_id, f"Interviewed candidate {candidate_id}.")
        persona = self.personas.get(candidate_id)
        response = self.candidate_interviews.reply(persona, message, history)
        history.append({"role": "manager", "content": message})
        history.append({"role": "candidate", "content": response})
        persistence.save_run(user_id, state)
        persistence.append_event(
            state["run_id"],
            user_id,
            "candidate_interview_turn",
            {"day": state["day"], "candidate_id": candidate_id, "summary": f"Interviewed {persona.name}."},
        )
        return {"candidate_id": candidate_id, "response_text": response, "turn_number": len(history) // 2}

    def investigate_artifact(self, user_id: str, artifact_id: str) -> dict[str, Any]:
        state = self._require_run(user_id)
        artifact = next((item for item in state["artifact_inbox"] if item["id"] == artifact_id), None)
        if not artifact:
            raise ValueError("artifact not found")
        if not artifact.get("revealed", False):
            self._spend_attention(state, "artifact", artifact_id, f"Investigated {artifact['channel']} artifact.")
            artifact["revealed"] = True
            persistence.append_event(
                state["run_id"],
                user_id,
                "artifact_investigated",
                {
                    "day": state["day"],
                    "artifact_id": artifact_id,
                    "channel": artifact["channel"],
                    "summary": artifact["title"],
                },
            )
        persistence.save_run(user_id, state)
        return self.public_state(state) or {}

    def apply_manager_action(self, user_id: str, persona_id: str, action: str, rationale: str = "") -> dict[str, Any]:
        state = self._require_run(user_id)
        if persona_id not in state["team"]:
            raise ValueError("persona is not on this team")
        persona = self.personas.get(persona_id)
        before = HiddenState(**state["team_state"][persona_id])
        before_hash = state_hash(before)
        after, deltas = apply_action(before, persona, action)
        after_hash = state_hash(after)
        state["team_state"][persona_id] = after.to_dict()
        state["day_actions"].append({"persona_id": persona_id, "action": action})
        self._update_product_metrics_for_action(state, action)
        persistence.save_run(user_id, state)
        persistence.save_snapshot(state["run_id"], after, after_hash)
        persistence.append_event(
            state["run_id"],
            user_id,
            "manager_action",
            {
                "persona_id": persona_id,
                "action": action,
                "day": state["day"],
                "summary": f"{action} applied to {persona.name}.",
                "prior_state_hash": before_hash,
                "new_state_hash": after_hash,
                "deltas": deltas,
                "rationale": rationale[:400],
            },
        )
        return self.public_state(state) or {}

    def submit_day_report(self, user_id: str, report: str | dict[str, Any]) -> dict[str, Any]:
        state = self._require_run(user_id)
        if isinstance(report, str):
            report = report.strip()
            if len(report) < 20:
                raise ValueError("daily team report must be at least 20 characters")
            journal = {
                "observations": report[:1200],
                "hypotheses": "",
                "questions": "",
                "decision": "",
                "predictions": [],
                "change_mind": "",
            }
        else:
            journal = self._validate_journal(report)
        state["reports"]["daily"][str(state["day"])] = journal
        persistence.save_run(user_id, state)
        persistence.append_event(
            state["run_id"],
            user_id,
            "daily_report_submitted",
            {
                "day": state["day"],
                "week": state["week"],
                "summary": journal["observations"][:220],
                "journal": journal,
            },
        )
        return self.public_state(state) or {}

    def set_tracking_focus(self, user_id: str, focus: list[str]) -> dict[str, Any]:
        state = self._require_run(user_id)
        allowed = {"delivery", "quality", "team_health", "retention", "customer_impact"}
        cleaned = [item for item in dict.fromkeys(focus) if item in allowed]
        if not cleaned or len(cleaned) > 3:
            raise ValueError("choose between one and three tracking signals")
        state["tracking_focus"] = cleaned
        persistence.save_run(user_id, state)
        persistence.append_event(
            state["run_id"],
            user_id,
            "tracking_focus_set",
            {"day": state["day"], "focus": cleaned, "summary": f"Tracking focus set to {', '.join(cleaned)}."},
        )
        return self.public_state(state) or {}

    def _validate_journal(self, report: dict[str, Any]) -> dict[str, Any]:
        journal = {
            "observations": str(report.get("observations", "")).strip(),
            "hypotheses": str(report.get("hypotheses", "")).strip(),
            "questions": str(report.get("questions", "")).strip(),
            "decision": str(report.get("decision", "")).strip(),
            "change_mind": str(report.get("change_mind", "")).strip(),
            "predictions": [],
        }
        if len(journal["observations"]) < 20:
            raise ValueError("observations must be at least 20 characters")
        if len(journal["hypotheses"]) < 20:
            raise ValueError("hypotheses must be at least 20 characters")
        if len(journal["decision"]) < 12:
            raise ValueError("decision must be at least 12 characters")
        raw_predictions = report.get("predictions", [])
        if not isinstance(raw_predictions, list) or len(raw_predictions) > 3:
            raise ValueError("submit between zero and three predictions")
        allowed_outcomes = {"energy", "trust", "quality", "delivery", "risk"}
        allowed_directions = {"up", "down", "stable"}
        for raw in raw_predictions:
            if not isinstance(raw, dict):
                raise ValueError("prediction must be an object")
            subject = str(raw.get("subject", "")).strip()
            outcome = str(raw.get("outcome", "")).strip()
            direction = str(raw.get("direction", "")).strip()
            confidence = int(raw.get("confidence", 0))
            rationale = str(raw.get("rationale", "")).strip()
            if not subject or outcome not in allowed_outcomes or direction not in allowed_directions:
                raise ValueError("prediction has invalid subject, outcome, or direction")
            if confidence < 20 or confidence > 95:
                raise ValueError("prediction confidence must be between 20 and 95")
            if len(rationale) < 10:
                raise ValueError("prediction rationale must be at least 10 characters")
            journal["predictions"].append(
                {
                    "subject": subject,
                    "outcome": outcome,
                    "direction": direction,
                    "confidence": confidence,
                    "rationale": rationale[:500],
                }
            )
        return journal

    def submit_week_report(self, user_id: str, report: str) -> dict[str, Any]:
        state = self._require_run(user_id)
        if state["day_in_week"] != 5:
            raise ValueError("weekly project reports are due at the end of each five-day block")
        report = report.strip()
        if len(report) < 40:
            raise ValueError("weekly project report must be at least 40 characters")
        state["reports"]["weekly"][str(state["week"])] = report[:6000]
        persistence.save_run(user_id, state)
        persistence.append_event(
            state["run_id"],
            user_id,
            "weekly_report_submitted",
            {"day": state["day"], "week": state["week"], "summary": report[:300]},
        )
        return self.public_state(state) or {}

    def select_interviews(self, user_id: str, candidate_ids: list[str]) -> dict[str, Any]:
        state = self._require_run(user_id)
        if state["day"] != 4:
            raise ValueError("interview selection opens on day 4")
        pool = state["milestones"]["week_1_hire"]["pool"]
        if len(candidate_ids) != 2 or len(set(candidate_ids)) != 2 or any(candidate_id not in pool for candidate_id in candidate_ids):
            raise ValueError("choose exactly two candidates from the active pool")
        state["milestones"]["week_1_hire"]["interview_ids"] = list(candidate_ids)
        persistence.save_run(user_id, state)
        persistence.append_event(
            state["run_id"],
            user_id,
            "interviews_selected",
            {"day": state["day"], "candidate_ids": candidate_ids, "summary": "Selected two candidates for interviews."},
        )
        return self.public_state(state) or {}

    def choose_hire(self, user_id: str, candidate_id: str) -> dict[str, Any]:
        state = self._require_run(user_id)
        milestone = state["milestones"]["week_1_hire"]
        if state["day"] != 5:
            raise ValueError("the hire decision is due on day 5")
        if candidate_id not in milestone["pool"]:
            raise ValueError("candidate is not in the active pool")
        if milestone["interview_ids"] and candidate_id not in milestone["interview_ids"]:
            raise ValueError("choose from the candidates you interviewed")
        if milestone["selected_id"]:
            raise ValueError("hire already selected")
        persona = self.personas.get(candidate_id)
        if persona.salary_cents > state["cash_remaining_cents"]:
            raise ValueError("candidate does not fit the remaining budget")
        self._add_hire(state, candidate_id)
        milestone["selected_id"] = candidate_id
        milestone["status"] = "hired"
        persistence.save_run(user_id, state)
        persistence.append_event(
            state["run_id"],
            user_id,
            "hire_selected",
            {"day": state["day"], "candidate_id": candidate_id, "summary": f"Hired {persona.name}."},
        )
        return self.public_state(state) or {}

    def select_terminations(self, user_id: str, persona_ids: list[str]) -> dict[str, Any]:
        state = self._require_run(user_id)
        if state["week"] != 2 or state["day_in_week"] < 2:
            raise ValueError("termination decisions open after the first week of observation")
        if len(persona_ids) != 2 or len(set(persona_ids)) != 2 or any(persona_id not in state["team"] for persona_id in persona_ids):
            raise ValueError("choose exactly two current team members")
        state["milestones"]["week_2_reduction"]["selected_ids"] = list(persona_ids)
        persistence.save_run(user_id, state)
        persistence.append_event(
            state["run_id"],
            user_id,
            "terminations_selected",
            {"day": state["day"], "persona_ids": persona_ids, "summary": "Selected two roles for termination."},
        )
        return self.public_state(state) or {}

    def choose_backfill(self, user_id: str, candidate_id: str | None) -> dict[str, Any]:
        state = self._require_run(user_id)
        if state["week"] != 2 or state["day_in_week"] < 4:
            raise ValueError("backfill decision opens late in week 2")
        milestone = state["milestones"]["week_2_reduction"]
        self._ensure_backfill_pool(state)
        if candidate_id is not None and candidate_id not in milestone["backfill_pool"]:
            raise ValueError("candidate is not in the active backfill pool")
        if candidate_id is not None:
            candidate = self.personas.get(candidate_id)
            removed_salary = sum(self.personas.get(persona_id).salary_cents for persona_id in milestone["selected_ids"])
            available = state["cash_remaining_cents"] + removed_salary
            if candidate.salary_cents > available:
                raise ValueError("candidate does not fit the post-reduction budget")
        milestone["backfill_selected_id"] = candidate_id
        milestone["backfill_decided"] = True
        persistence.save_run(user_id, state)
        persistence.append_event(
            state["run_id"],
            user_id,
            "backfill_selected",
            {"day": state["day"], "candidate_id": candidate_id, "summary": "Selected a backfill candidate." if candidate_id else "Declined the backfill slot."},
        )
        return self.public_state(state) or {}

    def advance_day(self, user_id: str, expected_day: int | None = None) -> dict[str, Any]:
        state = self._require_run(user_id)
        if expected_day is not None and state["day"] != expected_day:
            raise ValueError(f"simulation is already on day {state['day']}; refresh before advancing again")
        if state["day"] >= FINAL_DAY:
            raise ValueError("the simulation is complete")
        blocker = self._advance_blocker(state)
        if blocker:
            raise ValueError(blocker)

        self._apply_pending_milestones(state)
        before_states = [HiddenState(**state["team_state"][persona_id]) for persona_id in state["team"]]
        before_by_persona = {item.persona_id: item for item in before_states}
        before_product = dict(state["product"])
        context = self._team_context(before_states)
        next_team_state: dict[str, dict[str, Any]] = {}
        for persona_id in state["team"]:
            persona = self.personas.get(persona_id)
            current = HiddenState(**state["team_state"][persona_id])
            seed = f"{state['run_id']}:day:{state['day']}:persona:{persona_id}"
            next_state = advance_day(
                current,
                persona,
                seed,
                context,
                min(100, state["product_pressure"] + self._world_event_pressure(state)),
                relationship_context(state["relationships"], persona_id),
            )
            next_team_state[persona_id] = next_state.to_dict()
            persistence.save_snapshot(state["run_id"], next_state, state_hash(next_state))
        state["team_state"] = next_team_state
        state["relationships"] = advance_relationships(
            state["relationships"],
            state["team_state"],
            self._persona_map(state["team"]),
            state["day_actions"],
        )
        state["workstreams"] = advance_workstreams(
            state["workstreams"],
            state["team"],
            state["team_state"],
            self._persona_map(state["team"]),
            state["day_actions"],
            f"{state['run_id']}:day:{state['day']}:work",
            state["world_events"],
        )
        next_product = self._advance_product_metrics(state, next_team_state)
        self._resolve_predictions(user_id, state, before_by_persona, next_team_state, before_product, next_product)
        state["product"] = next_product
        state["product_pressure"] = self._advance_product_pressure(state, next_product)
        state["retention_watch"], retention_warnings = advance_retention_watch(
            state["retention_watch"],
            state["team_state"],
            self._persona_map(state["team"]),
            state["day_actions"],
        )
        state["day"] += 1
        state["week"] = week_for_day(state["day"])
        state["day_in_week"] = day_in_week(state["day"])
        self._append_retention_warnings(state, retention_warnings)
        self._expire_world_events(state)
        self._apply_voluntary_attrition(user_id, state)
        self._seed_discontinuities(state)
        state["day_actions"] = []
        state["attention"] = {"budget": 4, "remaining": 4, "spent": []}
        self._refresh_day_context(state)
        persistence.save_run(user_id, state)
        persistence.append_event(
            state["run_id"],
            user_id,
            "day_advanced",
            {
                "day": state["day"],
                "week": state["week"],
                "summary": f"Advanced to participant day {state['day']} after the team ran for a simulated week.",
            },
        )
        self._ensure_week_artifacts(user_id, state)
        return state

    def _resolve_predictions(
        self,
        user_id: str,
        state: dict[str, Any],
        before_by_persona: dict[str, HiddenState],
        next_team_state: dict[str, dict[str, Any]],
        before_product: dict[str, int],
        next_product: dict[str, int],
    ) -> None:
        journal = state["reports"]["daily"].get(str(state["day"]))
        if not isinstance(journal, dict):
            return
        for prediction in journal.get("predictions", []):
            actual_direction = self._prediction_direction(prediction, before_by_persona, next_team_state, before_product, next_product)
            hit = actual_direction == prediction["direction"]
            persistence.append_event(
                state["run_id"],
                user_id,
                "prediction_resolved",
                {
                    "day": state["day"],
                    "subject": prediction["subject"],
                    "outcome": prediction["outcome"],
                    "expected_direction": prediction["direction"],
                    "actual_direction": actual_direction,
                    "confidence": prediction["confidence"],
                    "hit": hit,
                    "summary": f"Predicted {prediction['subject']} {prediction['outcome']} would move {prediction['direction']}; it moved {actual_direction}.",
                },
            )

    def _prediction_direction(
        self,
        prediction: dict[str, Any],
        before_by_persona: dict[str, HiddenState],
        next_team_state: dict[str, dict[str, Any]],
        before_product: dict[str, int],
        next_product: dict[str, int],
    ) -> str:
        subject = prediction["subject"]
        outcome = prediction["outcome"]
        if subject in before_by_persona and subject in next_team_state:
            before = before_by_persona[subject]
            after = HiddenState(**next_team_state[subject])
            mapping = {
                "energy": ("battery", "battery"),
                "trust": ("trust", "trust"),
                "quality": ("quality", "quality"),
                "delivery": ("output", "output"),
                "risk": ("flight_risk", "flight_risk"),
            }
            before_key, after_key = mapping[outcome]
            delta = getattr(after, after_key) - getattr(before, before_key)
        else:
            mapping = {
                "energy": ("alignment", "alignment"),
                "trust": ("alignment", "alignment"),
                "quality": ("error_rate", "error_rate"),
                "delivery": ("velocity", "velocity"),
                "risk": ("error_rate", "error_rate"),
            }
            before_key, after_key = mapping[outcome]
            delta = next_product[after_key] - before_product[before_key]
            if outcome in {"quality", "risk"}:
                delta = -delta
        if delta > 3:
            return "up"
        if delta < -3:
            return "down"
        return "stable"

    def advance_week(self, user_id: str) -> dict[str, Any]:
        """Backward-compatible name for the end-of-day world tick."""
        return self.advance_day(user_id)

    def assessment(self, user_id: str) -> dict[str, Any]:
        state = self._require_run(user_id)
        events = persistence.list_events(state["run_id"], user_id)
        return self.assessor.assess(state, events).to_dict()

    def _require_run(self, user_id: str) -> dict[str, Any]:
        state = self.load_active_run(user_id)
        if not state:
            raise ValueError("no active run")
        return state

    def _normalize_state(self, state: dict[str, Any]) -> bool:
        changed = False
        if "day" not in state:
            state["day"] = int(state.get("week", 1))
            changed = True
        expected_week = week_for_day(state["day"])
        if state.get("week") != expected_week:
            state["week"] = expected_week
            changed = True
        expected_day_in_week = day_in_week(state["day"])
        if state.get("day_in_week") != expected_day_in_week:
            state["day_in_week"] = expected_day_in_week
            changed = True
        if state.get("phase") != "daily_loop":
            state["phase"] = "daily_loop"
            changed = True
        if "reports" not in state:
            state["reports"] = {"daily": {}, "weekly": {}}
            changed = True
        if "tracking_focus" not in state:
            state["tracking_focus"] = []
            changed = True
        if "relationships" not in state:
            state["relationships"] = initial_relationships(state["run_id"], state["team"], self._persona_map(state["team"]))
            changed = True
        if "attention" not in state:
            state["attention"] = {"budget": 4, "remaining": 4, "spent": []}
            changed = True
        if "artifact_inbox" not in state:
            state["artifact_inbox"] = []
            self._refresh_day_context(state)
            changed = True
        if "day_actions" not in state:
            state["day_actions"] = []
            changed = True
        if "world_events" not in state:
            state["world_events"] = []
            changed = True
        if "retention_watch" not in state:
            state["retention_watch"] = initial_retention_watch(state["team"])
            changed = True
        if "retention_alerts" not in state:
            state["retention_alerts"] = []
            changed = True
        if "departed_people" not in state:
            state["departed_people"] = []
            changed = True
        if "workstreams" not in state:
            state["workstreams"] = initial_workstreams(state["team"], self._persona_map(state["team"]))
            changed = True
        if "candidate_interviews" not in state:
            state["candidate_interviews"] = {}
            changed = True
        if "product_pressure" not in state:
            state["product_pressure"] = 74
            changed = True
        if "milestones" not in state:
            state["milestones"] = {
                "week_1_hire": {
                    "pool": self._candidate_ids(state["run_id"], "week_1_hire", state["team"]),
                    "interview_ids": [],
                    "selected_id": None,
                    "status": "open",
                },
                "week_2_reduction": {
                    "selected_ids": [],
                    "backfill_pool": [],
                    "backfill_selected_id": None,
                    "backfill_decided": False,
                    "applied": False,
                },
            }
            changed = True
        for persona_id, raw in list(state["team_state"].items()):
            normalized = HiddenState(**raw).to_dict()
            if normalized != raw:
                state["team_state"][persona_id] = normalized
                changed = True
        return changed

    def _ensure_week_artifacts(self, user_id: str, state: dict[str, Any]) -> None:
        plan = plan_for_day(state["day"])
        for persona_id in state["team"]:
            persona = self.personas.get(persona_id)
            hidden = HiddenState(**state["team_state"][persona_id])
            digest = state_hash(hidden)
            persistence.save_snapshot(state["run_id"], hidden, digest)
            self.artifacts.generate_report(state["run_id"], persona, hidden, plan)
            persistence.append_event(
                state["run_id"],
                user_id,
                "artifact_generated",
                {
                    "persona_id": persona_id,
                    "day": state["day"],
                    "week": state["week"],
                    "state_hash": digest,
                    "summary": f"Generated simulated-week report for {persona.name}.",
                },
            )

    def _candidate_ids(self, run_id: str, salt: str, exclude_ids: list[str]) -> list[str]:
        ids = [persona.id for persona in self.personas.load_all() if persona.id not in set(exclude_ids)]
        rng = random.Random(f"{run_id}:{salt}")
        rng.shuffle(ids)
        selected: list[str] = []
        for frontier_candidate in ("quinn", "xavier"):
            if frontier_candidate in ids:
                selected.append(frontier_candidate)
                ids.remove(frontier_candidate)
        selected.extend(ids[: max(0, 5 - len(selected))])
        return selected

    def _ensure_backfill_pool(self, state: dict[str, Any]) -> None:
        milestone = state["milestones"]["week_2_reduction"]
        if milestone["backfill_pool"]:
            return
        exclude = list(state["team"]) + list(milestone["selected_ids"])
        milestone["backfill_pool"] = self._candidate_ids(state["run_id"], "week_2_backfill", exclude)

    def _candidate_pool_view(self, state: dict[str, Any]) -> dict[str, Any] | None:
        if state["day"] in (4, 5):
            milestone = state["milestones"]["week_1_hire"]
            return {
                "kind": "week_1_hire",
                "interview_ids": milestone["interview_ids"],
                "selected_id": milestone["selected_id"],
                "candidates": [
                    {
                        **self.personas.get(persona_id).public_summary(),
                        "interview_history": state["candidate_interviews"].get(persona_id, []),
                    }
                    for persona_id in milestone["pool"]
                ],
            }
        if state["week"] == 2 and state["day_in_week"] in (4, 5):
            self._ensure_backfill_pool(state)
            milestone = state["milestones"]["week_2_reduction"]
            return {
                "kind": "week_2_backfill",
                "selected_id": milestone["backfill_selected_id"],
                "candidates": [
                    {
                        **self.personas.get(persona_id).public_summary(),
                        "interview_history": state["candidate_interviews"].get(persona_id, []),
                    }
                    for persona_id in milestone["backfill_pool"]
                ],
            }
        return None

    def _active_candidate_pool_ids(self, state: dict[str, Any]) -> list[str]:
        if state["day"] in (4, 5):
            return state["milestones"]["week_1_hire"]["pool"]
        if state["week"] == 2 and state["day_in_week"] in (4, 5):
            self._ensure_backfill_pool(state)
            return state["milestones"]["week_2_reduction"]["backfill_pool"]
        return []

    def _public_milestones(self, state: dict[str, Any]) -> dict[str, Any]:
        week_1 = state["milestones"]["week_1_hire"]
        week_2 = state["milestones"]["week_2_reduction"]
        return {
            "week_1_hire": {
                "status": week_1["status"],
                "interview_ids": week_1["interview_ids"],
                "selected_id": week_1["selected_id"],
            },
            "week_2_reduction": {
                "selected_ids": week_2["selected_ids"],
                "backfill_selected_id": week_2["backfill_selected_id"],
                "backfill_decided": week_2["backfill_decided"],
                "applied": week_2["applied"],
            },
        }

    def _reports_due(self, state: dict[str, Any]) -> dict[str, bool]:
        daily_done = str(state["day"]) in state["reports"]["daily"]
        weekly_due = state["day_in_week"] == 5
        weekly_done = str(state["week"]) in state["reports"]["weekly"]
        return {
            "daily": not daily_done,
            "weekly": weekly_due and not weekly_done,
        }

    def _advance_blocker(self, state: dict[str, Any]) -> str | None:
        if not state["tracking_focus"]:
            return "choose at least one tracking signal before the world advances"
        if str(state["day"]) not in state["reports"]["daily"]:
            return "submit your end-of-day team report before the world advances"
        if state["day_in_week"] == 5 and str(state["week"]) not in state["reports"]["weekly"]:
            return "submit your end-of-week project report before the world advances"
        if state["day"] == 5 and not state["milestones"]["week_1_hire"]["selected_id"]:
            return "choose a hire before the offer window closes"
        if state["day"] == 10:
            reduction = state["milestones"]["week_2_reduction"]
            if len(reduction["selected_ids"]) != 2:
                return "select two terminations before the reduction closes"
            if not reduction["backfill_decided"]:
                return "choose a backfill candidate or decline the slot"
        return None

    def _apply_pending_milestones(self, state: dict[str, Any]) -> None:
        if state["day"] != 10:
            return
        milestone = state["milestones"]["week_2_reduction"]
        if milestone["applied"]:
            return
        for persona_id in milestone["selected_ids"]:
            self._remove_persona(state, persona_id, "termination")
        if milestone["backfill_selected_id"]:
            self._add_hire(state, milestone["backfill_selected_id"])
        milestone["applied"] = True

    def _add_hire(self, state: dict[str, Any], persona_id: str) -> None:
        if persona_id in state["team"]:
            return
        persona = self.personas.get(persona_id)
        state["team"].append(persona_id)
        state["cash_remaining_cents"] -= persona.salary_cents
        hidden = initial_state(persona, state["day"]).to_dict()
        hidden["load"] = 38
        hidden["battery"] = max(0, hidden["battery"] - 6)
        hidden["output"] = min(hidden["output"], 38)
        hidden["quality"] = min(hidden["quality"], 58)
        state["team_state"][persona_id] = hidden
        state["retention_watch"][persona_id] = initial_retention_watch([persona_id])[persona_id]
        add_persona_relationships(state["relationships"], state["run_id"], persona_id, state["team"], self._persona_map(state["team"]))

    def _remove_persona(self, state: dict[str, Any], persona_id: str, reason: str = "removed") -> None:
        if persona_id not in state["team"]:
            return
        persona = self.personas.get(persona_id)
        state["team"].remove(persona_id)
        state["cash_remaining_cents"] += persona.salary_cents
        state["team_state"].pop(persona_id, None)
        state["retention_watch"].pop(persona_id, None)
        state["departed_people"].append({"persona_id": persona_id, "reason": reason, "day": state["day"]})
        remove_persona_relationships(state["relationships"], persona_id)

    def _refresh_day_context(self, state: dict[str, Any]) -> None:
        state["artifact_inbox"] = generate_inbox(
            state["run_id"],
            state["day"],
            state["team"],
            state["team_state"],
            state["relationships"],
            self._persona_map(state["team"]),
            state["product_pressure"],
        )
        for item in work_artifacts(state["workstreams"], self._persona_map(state["team"])):
            state["artifact_inbox"].append(
                {
                    "id": f"{state['day']}:work:{item['title'].lower().replace(' ', '-')}",
                    "kind": "work",
                    "channel": item["channel"],
                    "title": item["title"],
                    "preview": item["title"],
                    "detail": item["detail"],
                    "revealed": False,
                }
            )
        for alert in state.get("retention_alerts", []):
            if alert["start_day"] == state["day"]:
                state["artifact_inbox"].append(
                    {
                        "id": alert["id"],
                        "kind": "retention",
                        "channel": "calendar",
                        "title": alert["title"],
                        "preview": alert["title"],
                        "detail": alert["detail"],
                        "revealed": False,
                    }
                )
        for event in reversed(self._public_world_events(state)):
            if event["start_day"] == state["day"]:
                state["artifact_inbox"].insert(
                    0,
                    {
                        "id": f"{state['day']}:event:{event['kind']}",
                        "kind": f"event:{event['kind']}",
                        "channel": "executive",
                        "title": event["title"],
                        "preview": event["summary"],
                        "detail": event["detail"],
                        "revealed": True,
                    },
                )

    def _append_retention_warnings(self, state: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
        for warning in warnings:
            state["retention_alerts"].append(
                {
                    "id": f"{state['day']}:retention:{warning['persona_id']}",
                    "persona_id": warning["persona_id"],
                    "reason": warning["reason"],
                    "title": warning["title"],
                    "detail": warning["detail"],
                    "start_day": state["day"],
                }
            )

    def _apply_voluntary_attrition(self, user_id: str, state: dict[str, Any]) -> None:
        exit_decision = choose_voluntary_exit(
            state["run_id"],
            state["day"],
            state["retention_watch"],
            state["team_state"],
            self._persona_map(state["team"]),
        )
        if not exit_decision:
            return
        persona_id = exit_decision["persona_id"]
        persona = self.personas.get(persona_id)
        context = relationship_context(state["relationships"], persona_id)
        structure = self._team_structure(state)
        severity = 4 + max(0, 70 - structure["redundancy"]) // 3 + max(0, 70 - structure["bus_factor"]) // 3 + max(0, 64 - context["knowledge_flow"]) // 6
        self._remove_persona(state, persona_id, "voluntary_exit")
        for hidden in state["team_state"].values():
            hidden["load"] = _clamp(hidden["load"] + 3 + severity // 2)
            hidden["battery"] = _clamp(hidden["battery"] - 2)
        state["product"]["velocity"] = _clamp(state["product"]["velocity"] - 4 - severity)
        state["product"]["error_rate"] = _clamp(state["product"]["error_rate"] + 2 + severity // 2)
        state["product_pressure"] = _clamp(state["product_pressure"] + 4 + severity)
        if exit_decision["cause"] == "preventable":
            summary = _preventable_exit_summary(persona.name, exit_decision["reason"])
            detail = _preventable_exit_detail(persona.name, exit_decision["reason"])
        else:
            summary = f"{persona.name} accepted an outside offer and is leaving after the next handoff."
            detail = f"{persona.name} accepted an outside offer. The timing was not caused by a single manager action, but the team now has to reconstruct their context and redistribute the work."
        state["world_events"].append(
            {
                "kind": "voluntary_exit",
                "title": f"{persona.name} gave notice.",
                "summary": summary,
                "detail": detail,
                "start_day": state["day"],
                "end_day": state["day"] + 2,
                "status": "active",
                "affected_persona_id": persona_id,
                "severity": severity,
                "cause": exit_decision["cause"],
                "reason": exit_decision["reason"],
            }
        )
        persistence.append_event(
            state["run_id"],
            user_id,
            "voluntary_exit",
            {
                "day": state["day"],
                "persona_id": persona_id,
                "cause": exit_decision["cause"],
                "reason": exit_decision["reason"],
                "severity": severity,
                "summary": f"{persona.name} gave notice.",
            },
        )

    def _spend_attention(self, state: dict[str, Any], kind: str, target: str, summary: str) -> None:
        if state["attention"]["remaining"] <= 0:
            raise ValueError("you have no attention left this day; choose what to leave uninvestigated")
        state["attention"]["remaining"] -= 1
        state["attention"]["spent"].append({"type": kind, "target": target, "persona_id": target if kind == "1:1" else None, "summary": summary})

    def _persona_map(self, ids: list[str]) -> dict[str, Any]:
        return {persona_id: self.personas.get(persona_id) for persona_id in ids}

    def _public_world_events(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "kind": event["kind"],
                "title": event["title"],
                "summary": event["summary"],
                "detail": event["detail"],
                "start_day": event["start_day"],
                "end_day": event["end_day"],
                "affected_persona_id": event.get("affected_persona_id"),
            }
            for event in state.get("world_events", [])
            if event.get("status") == "active"
        ]

    def _team_structure(self, state: dict[str, Any]) -> dict[str, int]:
        phase = "build" if state["day"] <= 10 else "operate"
        return team_structure(state["team"], self._persona_map(state["team"]), state["relationships"], phase)

    def _expire_world_events(self, state: dict[str, Any]) -> None:
        for event in state.get("world_events", []):
            if event.get("status") == "active" and event["end_day"] < state["day"]:
                event["status"] = "resolved"

    def _seed_discontinuities(self, state: dict[str, Any]) -> None:
        if state["day"] == 12 and not any(event["kind"] == "scope_pivot" for event in state["world_events"]):
            structure = self._team_structure(state)
            relationship_values = list(state["relationships"].values())
            avg_flow = sum(item["knowledge_flow"] for item in relationship_values) // max(1, len(relationship_values))
            severity = 5 + max(0, 68 - structure["phase_fit"]) // 5 + max(0, 64 - avg_flow) // 7
            state["world_events"].append(
                {
                    "kind": "scope_pivot",
                    "title": "Roadmap pivot: a customer segment is moving faster than expected.",
                    "summary": "The executive team wants the workflow builder moved ahead of reliability work without changing the quarter deadline.",
                    "detail": "A major customer pilot now wants the workflow builder in the next release. The executive ask is to move it ahead of reliability work while keeping the quarter deadline unchanged.",
                    "start_day": 12,
                    "end_day": 15,
                    "status": "active",
                    "severity": severity,
                }
            )
            state["product"]["alignment"] = _clamp(state["product"]["alignment"] - 10 - severity)
            state["product"]["velocity"] = _clamp(state["product"]["velocity"] - severity)
            state["product_pressure"] = _clamp(state["product_pressure"] + 7 + severity)
        if state["day"] == 16 and not any(event["kind"] == "dependency_leave" for event in state["world_events"]):
            affected_persona_id = self._dependency_hotspot(state)
            affected_persona = self.personas.get(affected_persona_id)
            structure = self._team_structure(state)
            context = relationship_context(state["relationships"], affected_persona_id)
            severity = 5 + max(0, 70 - structure["redundancy"]) // 3 + max(0, 70 - structure["bus_factor"]) // 3 + max(0, 64 - context["knowledge_flow"]) // 6
            state["world_events"].append(
                {
                    "kind": "dependency_leave",
                    "title": f"{affected_persona.name} is unexpectedly out for two weeks.",
                    "summary": "The team loses a key source of context during an integration push.",
                    "detail": f"{affected_persona.name} is out for two simulated weeks during the integration push. The work can continue, but the team now has to reconstruct decisions and handoffs without their usual context.",
                    "start_day": 16,
                    "end_day": 18,
                    "status": "active",
                    "affected_persona_id": affected_persona_id,
                    "severity": severity,
                }
            )
            affected = state["team_state"][affected_persona_id]
            affected["output"] = _clamp(affected["output"] - 16 - severity)
            affected["quality"] = _clamp(affected["quality"] - 5 - severity // 2)
            affected["battery"] = _clamp(affected["battery"] - 6 - severity // 2)
            for persona_id, hidden in state["team_state"].items():
                if persona_id != affected_persona_id:
                    hidden["load"] = _clamp(hidden["load"] + 3 + severity // 2)
            state["product"]["velocity"] = _clamp(state["product"]["velocity"] - 4 - severity)
            state["product"]["error_rate"] = _clamp(state["product"]["error_rate"] + 3 + severity // 2)
            state["product_pressure"] = _clamp(state["product_pressure"] + 5 + severity)

    def _dependency_hotspot(self, state: dict[str, Any]) -> str:
        candidates = {}
        for persona_id in state["team"]:
            context = relationship_context(state["relationships"], persona_id)
            candidates[persona_id] = context["dependency_load"] - context["knowledge_flow"] // 2
        return max(candidates, key=candidates.get)

    def _world_event_pressure(self, state: dict[str, Any]) -> int:
        structure = self._team_structure(state)
        pressure = 0
        for event in state.get("world_events", []):
            if event.get("status") != "active":
                continue
            if event["kind"] == "scope_pivot":
                pressure += max(3, int(event.get("severity", 7)) // 2)
            elif event["kind"] == "dependency_leave":
                pressure += max(4, int(event.get("severity", 8)) // 2)
            elif event["kind"] == "voluntary_exit":
                pressure += max(4, int(event.get("severity", 8)) // 2)
        return pressure + structure_pressure(structure)

    def _team_context(self, states: list[HiddenState]) -> dict[str, int]:
        if not states:
            return {"avg_load": 0, "avg_morale": 0, "avg_trust": 0, "avg_output": 0}
        return {
            "avg_load": sum(item.load for item in states) // len(states),
            "avg_morale": sum(item.morale for item in states) // len(states),
            "avg_trust": sum(item.trust for item in states) // len(states),
            "avg_output": sum(item.output for item in states) // len(states),
        }

    def _advance_product_metrics(self, state: dict[str, Any], team_state: dict[str, dict[str, Any]]) -> dict[str, int]:
        states = [HiddenState(**raw) for raw in team_state.values()]
        if not states:
            return {"velocity": 0, "error_rate": 100, "alignment": 0, "total_value": 0}
        avg_output = sum(item.output for item in states) // len(states)
        avg_quality = sum(item.quality for item in states) // len(states)
        avg_burnout = sum(item.burnout for item in states) // len(states)
        avg_purpose = sum(item.purpose_alignment for item in states) // len(states)
        avg_trust = sum(item.trust for item in states) // len(states)
        rng = random.Random(f"{state['run_id']}:day:{state['day']}:product")
        prior = state["product"]
        event_pressure = self._world_event_pressure(state)
        work_drag = work_pressure(state["workstreams"])
        velocity = _clamp(prior["velocity"] + (avg_output - 55) // 8 - max(0, avg_burnout - 65) // 10 - event_pressure // 8 - work_drag // 4 + rng.randint(-3, 3))
        error_rate = _clamp(prior["error_rate"] + (55 - avg_quality) // 7 + max(0, avg_burnout - 55) // 10 + event_pressure // 10 + work_drag // 3 + rng.randint(-2, 3))
        alignment = _clamp(prior["alignment"] + (avg_purpose - 55) // 8 + (avg_trust - 50) // 12 - event_pressure // 12 + rng.randint(-2, 2))
        total_value = _clamp(prior["total_value"] + (velocity - 50) // 8 + (alignment - 50) // 10 - error_rate // 20 + rng.randint(-2, 3))
        return {"velocity": velocity, "error_rate": error_rate, "alignment": alignment, "total_value": total_value}

    def _advance_product_pressure(self, state: dict[str, Any], product: dict[str, int]) -> int:
        rng = random.Random(f"{state['run_id']}:day:{state['day']}:pressure")
        pressure = state["product_pressure"]
        pressure += max(0, 55 - product["velocity"]) // 12
        pressure += max(0, 45 - product["alignment"]) // 14
        pressure -= max(0, product["alignment"] - 62) // 16
        return _clamp(pressure + rng.randint(-2, 3))

    def _update_product_metrics_for_action(self, state: dict[str, Any], action: str) -> None:
        product = state["product"]
        if action == "clarify_scope":
            product["alignment"] = min(100, product["alignment"] + 5)
            product["velocity"] = max(0, product["velocity"] - 2)
            product["total_value"] = min(100, product["total_value"] + 1)
            state["product_pressure"] = max(0, state["product_pressure"] - 7)
        elif action == "protect_slack":
            product["error_rate"] = max(0, product["error_rate"] - 3)
            product["velocity"] = max(0, product["velocity"] - 2)
            product["total_value"] = min(100, product["total_value"] + 1)
            state["product_pressure"] = max(0, state["product_pressure"] - 2)
        elif action == "push_scope":
            product["velocity"] = min(100, product["velocity"] + 4)
            product["error_rate"] = min(100, product["error_rate"] + 5)
            product["alignment"] = max(0, product["alignment"] - 3)
            state["product_pressure"] = min(100, state["product_pressure"] + 8)
        elif action == "cross_train":
            product["total_value"] = min(100, product["total_value"] + 2)
            product["error_rate"] = max(0, product["error_rate"] - 1)
        elif action == "assign_maintenance":
            product["velocity"] = min(100, product["velocity"] + 1)
            product["error_rate"] = max(0, product["error_rate"] - 2)
            product["alignment"] = max(0, product["alignment"] - 1)
            state["product_pressure"] = min(100, state["product_pressure"] + 1)
