"""Hypervisor assessment based on model-building, calibration, and outcomes."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .latent_state import advance_day
from .models import AssessmentAxis, AssessmentReport
from .models import HiddenState
from .persona_store import PersonaStore
from .structure import structure_pressure, team_structure


def _clamp(score: int) -> int:
    return max(-5, min(5, score))


class HypervisorAssessor:
    def __init__(self):
        self.personas = PersonaStore()

    def assess(self, state: dict[str, Any], events: list[dict[str, Any]]) -> AssessmentReport:
        action_counts = Counter(
            event["payload"].get("action")
            for event in events
            if event["event_type"] == "manager_action"
        )
        daily_journals = [
            event["payload"].get("journal", {})
            for event in events
            if event["event_type"] == "daily_report_submitted"
        ]
        prediction_events = [
            event["payload"]
            for event in events
            if event["event_type"] == "prediction_resolved"
        ]
        investigation_events = [
            event["payload"]
            for event in events
            if event["event_type"] in {"artifact_investigated", "dialogue_turn"}
        ]
        action_events = [
            event["payload"]
            for event in events
            if event["event_type"] == "manager_action"
        ]
        evidence = [event["payload"].get("summary", event["event_type"]) for event in events[-14:]]
        evidence = [item for item in evidence if item]

        total_predictions = len(prediction_events)
        hits = sum(1 for item in prediction_events if item.get("hit"))
        misses = total_predictions - hits
        confidence_error = sum(
            abs((100 if item.get("hit") else 0) - int(item.get("confidence", 50)))
            for item in prediction_events
        )
        calibration = 0
        if total_predictions:
            hit_rate = hits / total_predictions
            mean_error = confidence_error / total_predictions
            calibration = round((hit_rate - 0.5) * 8 - max(0, mean_error - 35) / 15)

        journal_quality = 0
        for journal in daily_journals:
            if journal.get("observations"):
                journal_quality += 1
            if journal.get("hypotheses"):
                journal_quality += 1
            if journal.get("questions"):
                journal_quality += 1
            if journal.get("change_mind"):
                journal_quality += 1
        journal_quality = min(5, journal_quality // max(1, len(daily_journals) * 2))

        grounded_actions = 0
        for action in action_events:
            action_day = action.get("day")
            persona_id = action.get("persona_id")
            for investigation in investigation_events:
                if investigation.get("day") != action_day:
                    continue
                if investigation.get("persona_id") == persona_id or investigation.get("artifact_id"):
                    grounded_actions += 1
                    break
        ungrounded_actions = max(0, len(action_events) - grounded_actions)
        grounded_bonus = min(2, grounded_actions // 4)
        ungrounded_penalty = min(2, ungrounded_actions // 8)
        prediction_penalty = 0 if total_predictions >= 3 else 2

        team_states = list(state.get("team_state", {}).values())
        avg_burnout = sum(item.get("burnout", 0) for item in team_states) // max(1, len(team_states))
        avg_load = sum(item.get("load", 0) for item in team_states) // max(1, len(team_states))
        avg_trust = sum(item.get("trust", 0) for item in team_states) // max(1, len(team_states))
        avg_quality = sum(item.get("quality", 0) for item in team_states) // max(1, len(team_states))
        avg_risk = sum(item.get("flight_risk", 0) for item in team_states) // max(1, len(team_states))
        relationships = list(state.get("relationships", {}).values())
        avg_relationship_trust = sum(item.get("trust", 0) for item in relationships) // max(1, len(relationships))
        avg_relationship_friction = sum(item.get("friction", 0) for item in relationships) // max(1, len(relationships))
        product = state.get("product", {})
        workstreams = state.get("workstreams", [])
        blocked_work = sum(1 for item in workstreams if item.get("state") == "blocked")
        rework_work = sum(1 for item in workstreams if item.get("state") == "rework")
        unfinished_work = sum(1 for item in workstreams if item.get("state") not in {"done", "maintenance"})
        work_penalty = min(3, blocked_work + rework_work + max(0, unfinished_work - 2) // 2)
        velocity_penalty = max(0, 45 - product.get("velocity", 50)) // 10
        structure = team_structure(
            list(state.get("team", [])),
            {persona_id: self.personas.get(persona_id) for persona_id in state.get("team", [])},
            state.get("relationships", {}),
            "build" if int(state.get("day", 1)) <= 10 else "operate",
        )
        construction_penalty = structure_pressure(structure)
        sustainability_penalty, collapse_signature = self._forecast_collapse(state)
        trust_penalty = max(0, 48 - avg_trust) // 8
        quality_penalty = max(0, 52 - avg_quality) // 8
        relationship_penalty = max(0, 45 - avg_relationship_trust) // 8 + max(0, avg_relationship_friction - 55) // 10
        investigation_bonus = min(2, len(investigation_events) // 5)

        person_score = _clamp(
            calibration
            + journal_quality
            + investigation_bonus
            + grounded_bonus
            + min(2, action_counts["coach_directly"] + action_counts["delegate_ownership"] + action_counts["recognize_work"])
            - min(3, action_counts["push_scope"])
            - sustainability_penalty
            - trust_penalty
            - ungrounded_penalty
            - prediction_penalty
            - max(0, misses - hits) // 2
        )
        team_score = _clamp(
            journal_quality
            + investigation_bonus
            + grounded_bonus
            + min(2, action_counts["cross_train"] + action_counts["mediate_conflict"] + action_counts["protect_slack"])
            - min(2, action_counts["increase_checkins"] + action_counts["push_scope"])
            - sustainability_penalty
            - trust_penalty
            - relationship_penalty
            - ungrounded_penalty
            - construction_penalty
            - work_penalty
        )
        product_score = _clamp(
            calibration
            + min(2, action_counts["clarify_scope"] + action_counts["protect_slack"])
            - min(2, action_counts["defer_decision"] + action_counts["push_scope"])
            - quality_penalty
            - max(0, 45 - product.get("alignment", 50)) // 10
            - velocity_penalty
            - work_penalty
            - prediction_penalty // 2
        )
        crisis_score = _clamp(
            calibration
            + min(2, action_counts["protect_slack"] + action_counts["cross_train"])
            - min(2, action_counts["push_scope"])
            - sustainability_penalty
            - relationship_penalty
            - ungrounded_penalty
            - construction_penalty
            - work_penalty
            - velocity_penalty
            - max(0, misses - hits)
        )

        next_move = (
            "Write one prediction about a person, not the dashboard: what will they do next week, why, and what evidence would falsify your model?"
            if total_predictions < 3
            else "Compare the prediction misses to your next intervention. The point is not to be right immediately; it is to notice where your model keeps lying to you."
        )
        construction_insight = self._construction_insight(structure)

        return AssessmentReport(
            person_traits=AssessmentAxis(
                person_score,
                evidence or ["No manager evidence recorded yet."],
                [
                    "The simulator gives more weight to observed hypotheses and resolved predictions than to action labels.",
                    f"{grounded_actions} intervention(s) were preceded by same-day investigation or 1:1 evidence; {ungrounded_actions} were not.",
                    f"{blocked_work} workstream(s) remained blocked, {rework_work} were in rework, and the visible velocity ended at {product.get('velocity', 50)}.",
                ],
            ),
            team_dynamics=AssessmentAxis(
                team_score,
                evidence or ["No team-level interventions recorded yet."],
                [
                    collapse_signature or "A team can look calm while hidden dependencies and resentment accumulate.",
                    f"Current relationship context is inferred from observed behavior, not shown directly: trust, friction, and knowledge flow are all still partially hidden.",
                    construction_insight,
                    f"Work-state consequences are included here because a team can look socially healthy while work remains stuck in review, rework, or handoff debt.",
                ],
            ),
            product_complications=AssessmentAxis(
                product_score,
                evidence or ["No roadmap tradeoffs recorded yet."],
                ["Product outcomes are evidence of judgment, not a scorecard to maximize directly."],
            ),
            crisis_outcomes=AssessmentAxis(
                crisis_score,
                evidence or ["No crisis or pre-crisis mitigation recorded yet."],
                [collapse_signature or "This axis remains low-confidence until the team sees real stress.", construction_insight],
            ),
            highest_value_next_move=next_move,
        )

    def _construction_insight(self, structure: dict[str, int]) -> str:
        if structure["bus_factor"] < 40 or structure["redundancy"] < 60:
            return "The team carried too many critical areas with one remaining holder. The later leave converted missing redundancy into coordination work."
        if structure["phase_fit"] < 58:
            return "The team retained coverage, but its composition fit the earlier build phase better than the later operating phase."
        if structure["redundancy"] > 75 and structure["bus_factor"] > 60:
            return "The team retained overlapping coverage in the areas that mattered when the work shifted. That redundancy looked expensive before the shock and useful afterward."
        return "The team had some overlap, but not enough to make the later shock cheap. The remaining risk lives in the handoffs the manager chose not to simplify."

    def _forecast_collapse(self, state: dict[str, Any]) -> tuple[int, str | None]:
        """Project the current team forward without new intervention.

        The assessor does not penalize a hidden score merely crossing a line.
        It asks whether the current construction would produce visible failure
        signatures if the manager stopped intervening for a few simulated weeks.
        """
        current = {persona_id: HiddenState(**raw) for persona_id, raw in state.get("team_state", {}).items()}
        product_pressure = int(state.get("product_pressure", 65))
        worst = 0
        signature = None
        for step in range(1, 4):
            if not current:
                break
            context = {
                "avg_load": sum(item.load for item in current.values()) // len(current),
                "avg_morale": sum(item.morale for item in current.values()) // len(current),
                "avg_trust": sum(item.trust for item in current.values()) // len(current),
                "avg_output": sum(item.output for item in current.values()) // len(current),
            }
            next_states: dict[str, HiddenState] = {}
            for persona_id, hidden in current.items():
                persona = self.personas.get(persona_id)
                next_states[persona_id] = advance_day(
                    hidden,
                    persona,
                    f"forecast:{state.get('run_id', 'run')}:{step}:{persona_id}",
                    context,
                    product_pressure,
                )
            current = next_states
            attrition = sum(1 for item in current.values() if item.flight_risk > 72)
            quality_failures = sum(1 for item in current.values() if item.quality < 40)
            delivery_failures = sum(1 for item in current.values() if item.output < 35)
            avg_burnout = sum(item.burnout for item in current.values()) // len(current)
            severity = min(5, attrition + quality_failures + delivery_failures + max(0, avg_burnout - 74) // 6)
            if severity > worst:
                worst = severity
                if severity:
                    signature = (
                        f"Forward projection: without intervention, the current team would likely show "
                        f"{attrition} attrition-risk signal(s), {quality_failures} quality failure(s), "
                        f"and {delivery_failures} delivery failure(s) within {step} simulated week(s)."
                    )
        return min(4, worst), signature
