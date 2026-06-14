"""Hypervisor assessment based on model-building, calibration, and outcomes."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .latent_state import advance_day
from .models import AssessmentAxis, AssessmentReport
from .models import HiddenState
from .persona_store import PersonaStore


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

        team_states = list(state.get("team_state", {}).values())
        avg_burnout = sum(item.get("burnout", 0) for item in team_states) // max(1, len(team_states))
        avg_load = sum(item.get("load", 0) for item in team_states) // max(1, len(team_states))
        avg_trust = sum(item.get("trust", 0) for item in team_states) // max(1, len(team_states))
        avg_quality = sum(item.get("quality", 0) for item in team_states) // max(1, len(team_states))
        avg_risk = sum(item.get("flight_risk", 0) for item in team_states) // max(1, len(team_states))
        product = state.get("product", {})
        sustainability_penalty, collapse_signature = self._forecast_collapse(state)
        trust_penalty = max(0, 48 - avg_trust) // 8
        quality_penalty = max(0, 52 - avg_quality) // 8

        person_score = _clamp(
            calibration
            + journal_quality
            + min(2, action_counts["coach_directly"] + action_counts["delegate_ownership"] + action_counts["recognize_work"])
            - min(3, action_counts["push_scope"])
            - sustainability_penalty
            - trust_penalty
            - max(0, misses - hits) // 2
        )
        team_score = _clamp(
            journal_quality
            + min(2, action_counts["cross_train"] + action_counts["mediate_conflict"] + action_counts["protect_slack"])
            - min(2, action_counts["increase_checkins"] + action_counts["push_scope"])
            - sustainability_penalty
            - trust_penalty
        )
        product_score = _clamp(
            calibration
            + min(2, action_counts["clarify_scope"] + action_counts["protect_slack"])
            - min(2, action_counts["defer_decision"] + action_counts["push_scope"])
            - quality_penalty
            - max(0, 45 - product.get("alignment", 50)) // 10
        )
        crisis_score = _clamp(
            calibration
            + min(2, action_counts["protect_slack"] + action_counts["cross_train"])
            - min(2, action_counts["push_scope"])
            - sustainability_penalty
            - max(0, misses - hits)
        )

        next_move = (
            "Write one prediction about a person, not the dashboard: what will they do next week, why, and what evidence would falsify your model?"
            if total_predictions < 3
            else "Compare the prediction misses to your next intervention. The point is not to be right immediately; it is to notice where your model keeps lying to you."
        )

        return AssessmentReport(
            person_traits=AssessmentAxis(
                person_score,
                evidence or ["No manager evidence recorded yet."],
                ["The simulator gives more weight to observed hypotheses and resolved predictions than to action labels."],
            ),
            team_dynamics=AssessmentAxis(
                team_score,
                evidence or ["No team-level interventions recorded yet."],
                [collapse_signature or "A team can look calm while hidden dependencies and resentment accumulate."],
            ),
            product_complications=AssessmentAxis(
                product_score,
                evidence or ["No roadmap tradeoffs recorded yet."],
                ["Product outcomes are evidence of judgment, not a scorecard to maximize directly."],
            ),
            crisis_outcomes=AssessmentAxis(
                crisis_score,
                evidence or ["No crisis or pre-crisis mitigation recorded yet."],
                [collapse_signature or "This axis remains low-confidence until the team sees real stress."],
            ),
            highest_value_next_move=next_move,
        )

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
