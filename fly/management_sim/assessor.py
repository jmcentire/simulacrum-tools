"""Hypervisor assessment based on model-building, calibration, and outcomes."""

from __future__ import annotations

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
        prediction_events = [
            event["payload"]
            for event in events
            if event["event_type"] == "prediction_resolved"
        ]
        investigation_events = [
            {**event["payload"], "event_type": event["event_type"]}
            for event in events
            if event["event_type"] in {"dialogue_turn", "desk_query"}
        ]
        action_events = [
            event["payload"]
            for event in events
            if event["event_type"] == "manager_action"
        ]
        exit_events = [
            event["payload"]
            for event in events
            if event["event_type"] == "voluntary_exit"
        ]
        evidence = self._high_signal_evidence(events)

        total_predictions = len(prediction_events)
        hits = sum(1 for item in prediction_events if item.get("hit"))
        misses = total_predictions - hits
        calibration = 0
        if total_predictions:
            hit_rate = hits / total_predictions
            calibration = max(-1, min(1, round((hit_rate - 0.5) * 8)))

        grounded_actions = 0
        for action in action_events:
            action_day = action.get("day")
            persona_id = action.get("persona_id")
            for investigation in investigation_events:
                if investigation.get("day") != action_day:
                    continue
                if investigation.get("persona_id") == persona_id and investigation.get("clue_used"):
                    grounded_actions += 1
                    break
                if investigation.get("event_type") == "desk_query" and (
                    set(investigation.get("topics", [])) & set(action.get("topics", []))
                ):
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
        avg_morale = sum(item.get("morale", 0) for item in team_states) // max(1, len(team_states))
        avg_quality = sum(item.get("quality", 0) for item in team_states) // max(1, len(team_states))
        avg_risk = sum(item.get("flight_risk", 0) for item in team_states) // max(1, len(team_states))
        avg_alignment = sum(
            (
                item.get("mastery_alignment", 0)
                + item.get("autonomy_alignment", 0)
                + item.get("purpose_alignment", 0)
            )
            // 3
            for item in team_states
        ) // max(1, len(team_states))
        avg_manager_assessment = sum(item.get("manager_assessment", 0) for item in team_states) // max(1, len(team_states))
        avg_opinion = sum(item.get("opinion_of_manager", 0) for item in team_states) // max(1, len(team_states))
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
        error_penalty = max(0, product.get("error_rate", 0) - 28) // 10
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
        preventable_exits = sum(1 for event in exit_events if event.get("cause") == "preventable")
        external_exits = sum(1 for event in exit_events if event.get("cause") == "external")
        preventable_exit_penalty = min(5, preventable_exits * 3)
        exit_handoff_penalty = min(4, len(exit_events) * 2)
        sustainable_load_penalty = max(0, avg_burnout - 58) // 10 + max(0, avg_load - 78) // 10
        people_fit_penalty = max(0, 52 - avg_manager_assessment) // 10 + max(0, 55 - avg_opinion) // 10
        human_outcome_bonus = min(
            2,
            max(0, avg_trust - 65) // 14
            + max(0, avg_morale - 68) // 12
            + max(0, avg_alignment - 70) // 14,
        )
        product_outcome_bonus = min(
            4,
            max(0, product.get("alignment", 50) - 68) // 12
            + max(0, avg_quality - 68) // 14
            + max(0, product.get("total_value", 50) - 78) // 10
            + max(0, product.get("velocity", 50) - 38) // 8,
        )
        crisis_outcome_bonus = min(
            4,
            max(0, 70 - avg_risk) // 15
            + max(0, 70 - avg_burnout) // 15
            + max(0, structure["redundancy"] - 65) // 15
            + max(0, structure["bus_factor"] - 65) // 15,
        )

        person_score = _clamp(
            calibration
            + investigation_bonus
            + grounded_bonus
            + human_outcome_bonus
            - sustainability_penalty
            - sustainable_load_penalty
            - people_fit_penalty
            - trust_penalty
            - ungrounded_penalty
            - prediction_penalty
            - max(0, misses - hits) // 2
            - preventable_exit_penalty
        )
        team_score = _clamp(
            investigation_bonus
            + grounded_bonus
            + min(2, max(0, avg_relationship_trust - 55) // 10 + max(0, 55 - avg_relationship_friction) // 12)
            - sustainability_penalty
            - sustainable_load_penalty
            - trust_penalty
            - relationship_penalty
            - ungrounded_penalty
            - construction_penalty
            - work_penalty
            - exit_handoff_penalty
        )
        product_score = _clamp(
            calibration
            + product_outcome_bonus
            - quality_penalty
            - error_penalty
            - max(0, 45 - product.get("alignment", 50)) // 10
            - velocity_penalty
            - work_penalty
            - prediction_penalty // 2
            - preventable_exit_penalty
        )
        crisis_score = _clamp(
            calibration
            + crisis_outcome_bonus
            - sustainability_penalty
            - sustainable_load_penalty
            - relationship_penalty
            - ungrounded_penalty
            - construction_penalty
            - work_penalty
            - velocity_penalty
            - max(0, misses - hits)
            - exit_handoff_penalty
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
                    "The simulator gives more weight to observed outcomes and resolved predictions than to action labels.",
                    f"{grounded_actions} intervention(s) were preceded by same-day clue-using 1:1s or relevant desk evidence; {ungrounded_actions} were not.",
                    f"{blocked_work} workstream(s) remained blocked, {rework_work} were in rework, and the visible velocity ended at {product.get('velocity', 50)}.",
                    f"{preventable_exits} preventable exit(s) and {external_exits} outside-offer exit(s) occurred during the run.",
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
                    "Not every exit is manager-caused. Outside offers still test whether the team can absorb the loss without collapsing.",
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

    def _high_signal_evidence(self, events: list[dict[str, Any]]) -> list[str]:
        """Prefer causal evidence over whatever happened to occur last.

        Daily journals and world ticks are useful for auditability, but they
        are not the reason a manager scored well or poorly. The report should
        lead with decisions and consequences: hires, cuts, interventions,
        missed predictions, and attrition.
        """
        candidates: list[tuple[int, int, str]] = []
        for index, event in enumerate(events):
            event_type = event["event_type"]
            payload = event["payload"]
            summary = self._evidence_summary(event_type, payload)
            if not summary:
                continue
            priority = self._evidence_priority(event_type, payload)
            if priority:
                candidates.append((priority, index, summary))

        candidates.sort(key=lambda item: (-item[0], -item[1]))
        selected: list[str] = []
        seen: set[str] = set()
        for _priority, _index, summary in candidates:
            if summary in seen:
                continue
            selected.append(summary)
            seen.add(summary)
            if len(selected) == 6:
                break
        return selected

    def _evidence_priority(self, event_type: str, payload: dict[str, Any]) -> int:
        if event_type == "voluntary_exit":
            return 100
        if event_type in {"hire_selected", "terminations_selected", "backfill_selected"}:
            return 85
        if event_type == "manager_action":
            action = payload.get("action", "")
            if action in {"push_scope", "increase_checkins", "assign_maintenance"}:
                return 82
            if action in {"protect_slack", "cross_train", "delegate_ownership", "coach_directly", "clarify_scope"}:
                return 76
            return 60
        if event_type == "prediction_resolved" and not payload.get("hit"):
            return 68
        if event_type == "prediction_resolved":
            return 45
        if event_type in {"dialogue_turn", "desk_query"}:
            return 35
        return 0

    def _evidence_summary(self, event_type: str, payload: dict[str, Any]) -> str | None:
        if event_type == "voluntary_exit":
            cause = payload.get("cause", "unknown")
            reason = payload.get("reason", "unknown")
            return f"{payload.get('persona_id', 'A team member')} left: {cause} / {reason}."
        if event_type == "hire_selected":
            return f"Hired {payload.get('candidate_id', 'a candidate')}."
        if event_type == "terminations_selected":
            people = ", ".join(payload.get("persona_ids", []))
            return f"Selected terminations for {people}."
        if event_type == "backfill_selected":
            candidate = payload.get("candidate_id")
            return f"Selected backfill {candidate}." if candidate else "Declined the backfill slot."
        if event_type == "manager_action":
            plan = payload.get("plan")
            return plan[:180] if plan else payload.get("summary")
        if event_type == "prediction_resolved":
            return payload.get("summary")
        if event_type in {"dialogue_turn", "desk_query"}:
            return payload.get("summary")
        return None

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
