"""Read-only hypervisor assessor.

The assessor does not claim a single right answer. It reports where the
manager's observed actions aligned or misaligned with the simulated people and
system, using bounded -5..+5 scores and explicit assumptions.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .models import AssessmentAxis, AssessmentReport


def _clamp(score: int) -> int:
    return max(-5, min(5, score))


class HypervisorAssessor:
    def assess(self, state: dict[str, Any], events: list[dict[str, Any]]) -> AssessmentReport:
        action_counts = Counter(
            event["payload"].get("action")
            for event in events
            if event["event_type"] == "manager_action"
        )
        evidence = [event["payload"].get("summary", event["event_type"]) for event in events[-12:]]
        evidence = [item for item in evidence if item]

        person_score = _clamp(
            action_counts["delegate_ownership"]
            + action_counts["coach_directly"]
            + action_counts["recognize_work"]
            - action_counts["push_scope"]
        )
        team_score = _clamp(
            action_counts["cross_train"]
            + action_counts["mediate_conflict"]
            + action_counts["protect_slack"]
            - action_counts["increase_checkins"]
            - action_counts["push_scope"]
        )
        product_score = _clamp(
            action_counts["clarify_scope"]
            + action_counts["protect_slack"]
            - action_counts["defer_decision"]
            - action_counts["push_scope"]
        )
        crisis_score = _clamp(
            action_counts["protect_slack"]
            + action_counts["cross_train"]
            - action_counts["push_scope"]
        )

        return AssessmentReport(
            person_traits=AssessmentAxis(
                person_score,
                evidence or ["No manager actions recorded yet."],
                ["The simulator infers alignment from action patterns and later visible behavior, not intent alone."],
            ),
            team_dynamics=AssessmentAxis(
                team_score,
                evidence or ["No team-level interventions recorded yet."],
                ["A team can look calm while hidden dependencies and resentment accumulate."],
            ),
            product_complications=AssessmentAxis(
                product_score,
                evidence or ["No roadmap tradeoffs recorded yet."],
                ["Scope reduction is not automatically good; it is scored only when it matches observed constraints."],
            ),
            crisis_outcomes=AssessmentAxis(
                crisis_score,
                evidence or ["No crisis or pre-crisis mitigation recorded yet."],
                ["This axis remains low-confidence until the team sees real stress."],
            ),
            highest_value_next_move=(
                "Spend one more 1:1 on the person whose reports have become shorter or more careful, then decide whether the roadmap still deserves its current shape."
            ),
        )
