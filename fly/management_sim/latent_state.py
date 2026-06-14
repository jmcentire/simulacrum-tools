"""Deterministic hidden-state transitions.

The simulator is probabilistic at the scenario level, but manager actions need
bounded, inspectable effects. The engine applies deterministic deltas modulated
by persona preferences so the assessor can later explain what happened.
"""

from __future__ import annotations

import hashlib
import json
import random
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
    "assign_maintenance": "Keep the person on routine maintenance work.",
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
        output=_clamp(int((sum(persona.skills.values()) / max(1, len(persona.skills))) * 0.72)),
        quality=_clamp(int((traits["reliability"] + persona.skills.get("quality", 60)) / 2)),
        opinion_of_manager=50,
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
    if action == "assign_maintenance" and (
        "maintenance work" in hidden["purpose"]["anti_purpose"]
        or "repetitive cleanup" in hidden["energy"]["drains"]
        or hidden["mastery"]["preferred"] >= 78
    ):
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
        "assign_maintenance": {"mastery_alignment": -8, "purpose_alignment": -3, "morale": -3, "load": 1},
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


def advance_day(
    state: HiddenState,
    persona: PersonaDefinition,
    seed: str,
    team_context: dict[str, int] | None = None,
    product_pressure: int = 55,
    relationship_context: dict[str, int] | None = None,
) -> HiddenState:
    """Run one simulated work interval after the manager leaves the room.

    Manager actions are applied during the participant session. This tick is
    the asynchronous world advance: people work, react to the team around
    them, form opinions, and produce visible consequences before the next
    participant session begins.
    """
    next_state = HiddenState(**state.to_dict())
    next_state.week = state.week + 1
    rng = random.Random(seed)

    context = team_context or {}
    team_load = context.get("avg_load", state.load)
    team_morale = context.get("avg_morale", state.morale)
    team_trust = context.get("avg_trust", state.trust)
    team_output = context.get("avg_output", state.output)
    relationship = relationship_context or {}
    relationship_trust = relationship.get("relationship_trust", 55)
    relationship_friction = relationship.get("relationship_friction", 30)
    dependency_load = relationship.get("dependency_load", 25)
    knowledge_flow = relationship.get("knowledge_flow", 45)

    traits = persona.hidden["traits"]
    energy = persona.hidden["energy"]
    friction = persona.hidden["friction"]
    alignment = (state.mastery_alignment + state.autonomy_alignment + state.purpose_alignment) // 3
    overload = max(0, state.load - 58)
    team_overload = max(0, team_load - 62)
    ambiguity_penalty = max(0, 65 - traits["ambiguity_tolerance"]) // 10
    friction_pressure = max(0, overload + team_overload + product_pressure - friction["tolerance"])
    recovery = max(0, alignment - 52) // 10 + max(0, energy["resilience"] - 48) // 12

    next_state.load = _clamp(
        state.load
        + 0
        + max(0, product_pressure - 60) // 10
        + team_overload // 10
        + max(0, dependency_load - 50) // 12
        + ambiguity_penalty
        + rng.randint(-3, 3)
    )
    next_state.battery = _clamp(
        state.battery
        - max(1, next_state.load // 20)
        - friction_pressure // 16
        + recovery
        + rng.randint(-2, 3)
    )
    next_state.burnout = _clamp(
        state.burnout
        + friction_pressure // 9
        + max(0, relationship_friction - 48) // 10
        + max(0, 50 - next_state.battery) // 14
        - recovery // 2
        + rng.randint(-1, 2)
    )
    next_state.atrophy = _clamp(
        state.atrophy
        + max(0, 58 - state.mastery_alignment) // 9
        + max(0, 50 - state.autonomy_alignment) // 12
        - max(0, state.output - 65) // 14
    )
    next_state.trust = _clamp(
        state.trust
        + max(-3, min(3, (state.manager_assessment - 50) // 12))
        + max(-2, min(2, (team_trust - 50) // 18))
        + max(-2, min(3, (relationship_trust - 50) // 12))
        - max(0, next_state.burnout - 70) // 10
        + rng.randint(-2, 2)
    )
    next_state.morale = _clamp(
        state.morale
        + max(-4, min(5, (alignment - 55) // 8))
        + max(-2, min(2, (team_morale - 55) // 20))
        + max(-2, min(2, (knowledge_flow - 45) // 16))
        - max(0, next_state.burnout - 55) // 8
        + rng.randint(-3, 2)
    )
    next_state.output = _clamp(
        28
        + traits["reliability"] // 2
        + alignment // 3
        + next_state.battery // 5
        + max(0, team_output - 55) // 8
        + max(-3, min(3, (knowledge_flow - 45) // 12))
        - next_state.burnout // 3
        - next_state.load // 6
        + rng.randint(-8, 8)
    )
    next_state.quality = _clamp(
        30
        + traits["reliability"] // 2
        + persona.skills.get("quality", 60) // 3
        + next_state.battery // 8
        + max(-2, min(2, (relationship_trust - 50) // 18))
        - next_state.burnout // 4
        - max(0, next_state.load - 70) // 3
        + rng.randint(-6, 6)
    )
    next_state.opinion_of_manager = _clamp(
        state.opinion_of_manager
        + (next_state.trust - 50) // 8
        + (next_state.morale - 55) // 10
        - max(0, next_state.burnout - 65) // 10
        + rng.randint(-2, 2)
    )
    next_state.flight_risk = _clamp(
        next_state.flight_risk
        + max(0, next_state.burnout - 60) // 6
        + max(0, 45 - next_state.trust) // 10
        + max(0, next_state.atrophy - 55) // 12
        + max(0, 45 - next_state.opinion_of_manager) // 12
    )
    _append_hint(next_state, next_state.flight_risk > 70, "has been less present in planning and less likely to volunteer context")
    _append_hint(next_state, next_state.burnout > 70, "has started avoiding optional collaboration and follow-up work")
    _append_hint(next_state, next_state.trust < 40, "answers in 1:1s have become shorter and more careful")
    _append_hint(next_state, next_state.output < 35, "has delivered less than expected without making a big issue of it")
    _append_hint(next_state, next_state.quality < 40, "has begun shipping work that needs more follow-up than usual")
    return next_state


def _append_hint(state: HiddenState, condition: bool, hint: str) -> None:
    if condition and hint not in state.known_hints:
        state.known_hints.append(hint)


def advance_week(state: HiddenState, persona: PersonaDefinition) -> HiddenState:
    """Backward-compatible alias for older callers and tests."""
    return advance_day(state, persona, f"legacy:{state.persona_id}:{state.week + 1}")


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
