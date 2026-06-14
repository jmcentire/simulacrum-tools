"""Orchestration for the first honest management-simulation loop."""

from __future__ import annotations

from typing import Any

import db

from .artifacts import ArtifactService
from .assessor import HypervisorAssessor
from .latent_state import ACTION_VOCABULARY, advance_week, apply_action, initial_state, state_hash, visible_flags
from .models import HiddenState
from .persona_store import PersonaStore
from . import persistence


STARTING_TEAM_IDS = ["maya", "jonah", "elena", "trent", "rhea"]


class ManagementSimService:
    def __init__(self):
        self.personas = PersonaStore()
        self.artifacts = ArtifactService()
        self.assessor = HypervisorAssessor()

    def create_run(self, user_id: str, mission: str, budget_cents: int) -> dict[str, Any]:
        persistence.archive_active_runs(user_id)
        run_id = db.new_id()
        team = list(STARTING_TEAM_IDS)
        salary = sum(self.personas.get(persona_id).salary_cents for persona_id in team)
        state = {
            "run_id": run_id,
            "phase": "weekly_loop",
            "week": 1,
            "mission": mission,
            "budget_cents": budget_cents,
            "cash_remaining_cents": budget_cents - salary,
            "team": team,
            "team_state": {persona_id: initial_state(self.personas.get(persona_id), 1).to_dict() for persona_id in team},
            "product": {"velocity": 58, "error_rate": 14, "alignment": 52, "total_value": 48},
        }
        persistence.create_run(user_id, mission, budget_cents, state)
        persistence.append_event(run_id, user_id, "run_started", {"summary": "Started with five-person team and an oversized mission."})
        self._ensure_week_artifacts(user_id, state)
        return state

    def load_active_run(self, user_id: str) -> dict[str, Any] | None:
        return persistence.load_active_run(user_id)

    def public_state(self, state: dict[str, Any] | None) -> dict[str, Any] | None:
        if not state:
            return None
        team = []
        for persona_id in state["team"]:
            persona = self.personas.get(persona_id)
            hidden = HiddenState(**state["team_state"][persona_id])
            team.append(
                {
                    **persona.public_summary(),
                    "visible_flags": visible_flags(hidden),
                }
            )
        return {
            "run_id": state["run_id"],
            "phase": state["phase"],
            "week": state["week"],
            "mission": state["mission"],
            "budget_cents": state["budget_cents"],
            "cash_remaining_cents": state["cash_remaining_cents"],
            "team": team,
            "product": state["product"],
            "actions": [{"id": key, "label": label} for key, label in ACTION_VOCABULARY.items()],
        }

    def week_view(self, state: dict[str, Any]) -> dict[str, Any]:
        artifacts = persistence.list_artifacts(state["run_id"], state["week"])
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
                    "visible_flags": visible_flags(HiddenState(**state["team_state"][persona_id])),
                }
            )
        return {
            "week": state["week"],
            "reports": reports,
            "product": state["product"],
            "actions": [{"id": key, "label": label} for key, label in ACTION_VOCABULARY.items()],
        }

    def send_message(self, user_id: str, persona_id: str, message: str) -> dict[str, Any]:
        state = self._require_run(user_id)
        if persona_id not in state["team"]:
            raise ValueError("persona is not on this team")
        persona = self.personas.get(persona_id)
        hidden = HiddenState(**state["team_state"][persona_id])
        response = self.artifacts.send_message(state["run_id"], persona, hidden, message)
        persistence.append_event(
            state["run_id"],
            user_id,
            "dialogue_turn",
            {"persona_id": persona_id, "turn_number": response["turn_number"], "state_hash": state_hash(hidden)},
        )
        return response

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
        self._update_product_metrics(state, action)
        persistence.save_run(user_id, state)
        persistence.save_snapshot(state["run_id"], after, after_hash)
        persistence.append_event(
            state["run_id"],
            user_id,
            "manager_action",
            {
                "persona_id": persona_id,
                "action": action,
                "summary": f"{action} applied to {persona.name}.",
                "prior_state_hash": before_hash,
                "new_state_hash": after_hash,
                "deltas": deltas,
                "rationale": rationale[:400],
            },
        )
        return self.public_state(state) or {}

    def advance_week(self, user_id: str) -> dict[str, Any]:
        state = self._require_run(user_id)
        for persona_id in state["team"]:
            persona = self.personas.get(persona_id)
            current = HiddenState(**state["team_state"][persona_id])
            next_state = advance_week(current, persona)
            state["team_state"][persona_id] = next_state.to_dict()
            persistence.save_snapshot(state["run_id"], next_state, state_hash(next_state))
        state["week"] += 1
        state["product"]["velocity"] = max(0, min(100, state["product"]["velocity"] - 2))
        state["product"]["error_rate"] = max(0, min(100, state["product"]["error_rate"] + 1))
        state["product"]["alignment"] = max(0, min(100, state["product"]["alignment"] - 1))
        state["product"]["total_value"] = max(0, min(100, state["product"]["total_value"] + 1))
        persistence.save_run(user_id, state)
        persistence.append_event(
            state["run_id"],
            user_id,
            "week_advanced",
            {"week": state["week"], "summary": f"Advanced to week {state['week']}."},
        )
        self._ensure_week_artifacts(user_id, state)
        return state

    def assessment(self, user_id: str) -> dict[str, Any]:
        state = self._require_run(user_id)
        events = persistence.list_events(state["run_id"], user_id)
        return self.assessor.assess(state, events).to_dict()

    def _require_run(self, user_id: str) -> dict[str, Any]:
        state = self.load_active_run(user_id)
        if not state:
            raise ValueError("no active run")
        return state

    def _ensure_week_artifacts(self, user_id: str, state: dict[str, Any]) -> None:
        for persona_id in state["team"]:
            persona = self.personas.get(persona_id)
            hidden = HiddenState(**state["team_state"][persona_id])
            digest = state_hash(hidden)
            persistence.save_snapshot(state["run_id"], hidden, digest)
            self.artifacts.generate_report(state["run_id"], persona, hidden)
            persistence.append_event(
                state["run_id"],
                user_id,
                "artifact_generated",
                {"persona_id": persona_id, "week": hidden.week, "state_hash": digest, "summary": f"Generated weekly report for {persona.name}."},
            )

    def _update_product_metrics(self, state: dict[str, Any], action: str) -> None:
        product = state["product"]
        if action == "clarify_scope":
            product["alignment"] = min(100, product["alignment"] + 5)
            product["velocity"] = min(100, product["velocity"] + 2)
        elif action == "protect_slack":
            product["error_rate"] = max(0, product["error_rate"] - 3)
            product["total_value"] = min(100, product["total_value"] + 2)
        elif action == "push_scope":
            product["velocity"] = min(100, product["velocity"] + 4)
            product["error_rate"] = min(100, product["error_rate"] + 5)
            product["alignment"] = max(0, product["alignment"] - 3)
        elif action == "cross_train":
            product["total_value"] = min(100, product["total_value"] + 2)
            product["error_rate"] = max(0, product["error_rate"] - 1)
