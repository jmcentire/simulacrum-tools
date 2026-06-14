"""Deterministic hidden-state transitions.

The simulator is probabilistic at the scenario level, but manager actions need
bounded, inspectable effects. The engine applies deterministic deltas modulated
by persona preferences so the assessor can later explain what happened.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import HiddenState, PersonaDefinition


ACTION_VOCABULARY = {
    "clarify_scope": "Clarify priorities and cut ambiguous work.",
    "delegate_ownership": "Give the person a bounded area to own.",
    "increase_checkins": "Increase manager check-ins and coordination.",
    "coach_directly": "Give direct feedback and a concrete growth path.",
    "recognize_work": "Recognize useful work publicly or privately.",
    "protect_slack": "Cut scope or move work to preserve capacity.",
    "push_scope": "Keep commitments and ask for more output.",
    "cross_train": "Invest in pairing, documentation, and redundancy.",
    "mediate_conflict": "Address a team friction directly.",
    "defer_decision": "Hold a decision while gathering more context.",
}


def _clamp(value: int) -> int:
    return max(0, min(100, value))


def state_hash(state: HiddenState) -> str:
    payload = json.dumps(state.to_dict(), separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def initial_state(persona: PersonaDefinition, week: int = 1) -> HiddenState:
    energy = persona.hidden["energy"]
    friction = persona.hidden["friction"]
    mastery = persona.hidden["mastery"]
    autonomy = persona.hidden["autonomy"]
    purpose = persona.hidden["purpose"]
    traits = persona.hidden["traits"]
    return HiddenState(
        persona_id=persona.id,
        week=week,
        battery=_clamp(int(energy["baseline"])),
        burnout=_clamp(int(friction["baseline"])),
        trust=55,
        morale=60,
        flight_risk=18,
        load=52,
        mastery_alignment=_clamp(int(mastery["baseline"])),
        autonomy_alignment=_clamp(int(autonomy["baseline"])),
        purpose_alignment=_clamp(int(purpose["baseline"])),
        atrophy=10,
        manager_assessment=50,
        known_hints=[],
    )


def _match_bonus(persona: PersonaDefinition, action: str) -> int:
    hidden = persona.hidden
    if action == "delegate_ownership" and hidden["autonomy"]["preferred"] >= 70:
        return 5
    if action == "coach_directly" and hidden["mastery"]["preferred"] >= 70:
        return 5
    if action == "protect_slack" and hidden["energy"]["resilience"] < 55:
        return 5
    if action == "clarify_scope" and hidden["traits"]["ambiguity_tolerance"] < 60:
        return 5
    if action == "cross_train" and hidden["traits"]["mentorship"] >= 70:
        return 4
    if action == "increase_checkins" and hidden["autonomy"]["preferred"] >= 80:
        return -5
    if action == "push_scope" and hidden["energy"]["resilience"] < 60:
        return -6
    return 0


def apply_action(state: HiddenState, persona: PersonaDefinition, action: str) -> tuple[HiddenState, dict[str, int]]:
    if action not in ACTION_VOCABULARY:
        raise ValueError(f"unknown action {action!r}")
    bonus = _match_bonus(persona, action)
    deltas = {
        "clarify_scope": {"trust": 4, "morale": 3, "load": -4, "burnout": -3, "purpose_alignment": 3},
        "delegate_ownership": {"trust": 4, "morale": 3, "autonomy_alignment": 7, "mastery_alignment": 2},
        "increase_checkins": {"trust": 2, "morale": -1, "load": 2, "autonomy_alignment": -2},
        "coach_directly": {"trust": 3, "mastery_alignment": 7, "manager_assessment": 4},
        "recognize_work": {"trust": 2, "morale": 5, "purpose_alignment": 2},
        "protect_slack": {"battery": 5, "burnout": -5, "load": -7, "trust": 2},
        "push_scope": {"battery": -8, "burnout": 8, "load": 9, "morale": -4, "purpose_alignment": -2},
        "cross_train": {"trust": 2, "mastery_alignment": 3, "load": 2, "atrophy": -4},
        "mediate_conflict": {"trust": 3, "morale": 2, "manager_assessment": 3},
        "defer_decision": {"trust": -1, "morale": -1, "load": 1, "purpose_alignment": -1},
    }[action].copy()
    if bonus:
        if action in ("delegate_ownership", "coach_directly", "protect_slack", "clarify_scope", "cross_train"):
            deltas["morale"] = deltas.get("morale", 0) + bonus
            deltas["trust"] = deltas.get("trust", 0) + max(1, bonus // 2)
        else:
            deltas["morale"] = deltas.get("morale", 0) + bonus
            deltas["trust"] = deltas.get("trust", 0) + bonus // 2

    next_state = HiddenState(**state.to_dict())
    for key, delta in deltas.items():
        setattr(next_state, key, _clamp(getattr(next_state, key) + delta))
    next_state.flight_risk = _clamp(
        next_state.flight_risk
        + max(0, next_state.burnout - 65) // 5
        + max(0, 45 - next_state.trust) // 8
        + max(0, 45 - next_state.morale) // 8
    )
    next_state.manager_assessment = _clamp(next_state.manager_assessment + max(-4, min(6, deltas.get("trust", 0))))
    return next_state, deltas


def advance_week(state: HiddenState, persona: PersonaDefinition) -> HiddenState:
    next_state = HiddenState(**state.to_dict())
    next_state.week = state.week + 1
    next_state.load = _clamp(next_state.load + 3)
    next_state.battery = _clamp(next_state.battery - max(2, next_state.load // 18))
    next_state.burnout = _clamp(next_state.burnout + max(0, next_state.load - 60) // 6)
    next_state.atrophy = _clamp(next_state.atrophy + max(0, 50 - next_state.mastery_alignment) // 12)
    next_state.flight_risk = _clamp(
        next_state.flight_risk
        + max(0, next_state.burnout - 60) // 6
        + max(0, 45 - next_state.trust) // 10
        + max(0, next_state.atrophy - 55) // 12
    )
    if next_state.flight_risk > 70:
        next_state.known_hints.append("has been less present in planning and less likely to volunteer context")
    if next_state.burnout > 70:
        next_state.known_hints.append("has started avoiding optional collaboration and follow-up work")
    if next_state.trust < 40:
        next_state.known_hints.append("answers in 1:1s have become shorter and more careful")
    return next_state


def visible_flags(state: HiddenState) -> list[str]:
    flags: list[str] = []
    if state.load > 70:
        flags.append("work is arriving faster than it is leaving")
    if state.burnout > 65:
        flags.append("has stopped volunteering for extra work")
    if state.trust < 40:
        flags.append("is careful about what they say in meetings")
    if state.atrophy > 55:
        flags.append("is doing repetitive work without visible growth")
    if state.flight_risk > 65:
        flags.append("has become less predictable about availability")
    return flags
