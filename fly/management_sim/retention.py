"""Delayed retention pressure, warning signals, and voluntary exits."""

from __future__ import annotations

import random
from typing import Any

from .models import HiddenState, PersonaDefinition


# People should not leave instantly after one bad interaction. A run has a
# first-week hiring exercise and a second-week reduction exercise, so exits
# begin only after the manager has had time to establish a pattern.
MIN_EXIT_DAY = 11
# Three sustained pressure ticks is enough for a visible warning signal.
WARNING_THRESHOLD = 3
# Five ticks creates a real resignation probability, but not certainty.
PROBABILITY_THRESHOLD = 5
# Eight ticks means the person has been under the same bad pattern long enough
# that staying would be less realistic than leaving.
FORCED_THRESHOLD = 8
# External offers are not meant to be a lottery. They arrive as a subtle
# retention signal, remain open for a short response window, and then turn
# into an exit only if the manager does not respond or cannot make the work
# compelling enough to keep the person.
OUTSIDE_OFFER_MIN_DAY = 12
OUTSIDE_OFFER_RESPONSE_WINDOW = 2
OUTSIDE_OFFER_COOLDOWN = 4
RETENTION_RESPONSE_ACTIONS = {
    "recognize_work",
    "delegate_ownership",
    "coach_directly",
    "protect_slack",
    "clarify_scope",
}


def initial_retention_watch(team: list[str]) -> dict[str, dict[str, Any]]:
    return {persona_id: _blank_watch() for persona_id in team}


def ensure_retention_watch(
    watch: dict[str, dict[str, Any]],
    team: list[str],
) -> dict[str, dict[str, Any]]:
    next_watch = {persona_id: _normalized_record(values) for persona_id, values in watch.items() if persona_id in team}
    for persona_id in team:
        next_watch.setdefault(persona_id, _blank_watch())
    return next_watch


def advance_retention_watch(
    watch: dict[str, dict[str, Any]],
    team_state: dict[str, dict[str, Any]],
    personas: dict[str, PersonaDefinition],
    day_actions: list[dict[str, str]],
    run_id: str | None = None,
    day: int | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    next_watch = ensure_retention_watch(watch, list(team_state))
    actions_by_persona: dict[str, list[str]] = {}
    for action in day_actions:
        actions_by_persona.setdefault(action["persona_id"], []).append(action["action"])

    warnings: list[dict[str, Any]] = []
    outside_offer_slot_used = any(record["outside_offer_active"] for record in next_watch.values())
    for persona_id, raw in team_state.items():
        persona = personas[persona_id]
        state = HiddenState(**raw)
        record = next_watch[persona_id]
        actions = actions_by_persona.get(persona_id, [])
        reason, pressure, signals = _pressure(persona, state, actions)

        if signals["micromanagement"]:
            record["micromanagement_days"] += 1
        else:
            record["micromanagement_days"] = max(0, record["micromanagement_days"] - 1)
        if signals["stagnation"]:
            record["stagnation_days"] += 1
        else:
            record["stagnation_days"] = max(0, record["stagnation_days"] - 1)
        if signals["overload"]:
            record["overload_days"] += 1
        else:
            record["overload_days"] = max(0, record["overload_days"] - 1)
        if signals["trust_loss"]:
            record["trust_loss_days"] += 1
        else:
            record["trust_loss_days"] = max(0, record["trust_loss_days"] - 1)

        if pressure >= 4:
            record["pressure_days"] += 1
        else:
            record["pressure_days"] = max(0, record["pressure_days"] - 1)

        record["last_reason"] = reason
        record["last_pressure"] = pressure

        if record["pressure_days"] == WARNING_THRESHOLD:
            warnings.append(
                {
                    "persona_id": persona_id,
                    "reason": reason,
                    "title": _warning_title(persona.name, reason),
                    "detail": _warning_detail(persona.name, reason),
                }
            )

        _advance_outside_offer(
            record,
            persona,
            state,
            actions,
            run_id,
            day,
            outside_offer_slot_used,
        )
        if record["outside_offer_active"] and not outside_offer_slot_used:
            outside_offer_slot_used = True
            warnings.append(
                {
                    "persona_id": persona_id,
                    "reason": "outside_offer",
                    "title": _outside_offer_title(persona.name),
                    "detail": _outside_offer_detail(persona.name),
                }
            )
    return next_watch, warnings


def choose_voluntary_exit(
    run_id: str,
    day: int,
    watch: dict[str, dict[str, Any]],
    team_state: dict[str, dict[str, Any]],
    personas: dict[str, PersonaDefinition],
) -> dict[str, Any] | None:
    if day < MIN_EXIT_DAY:
        return None

    candidates: list[dict[str, Any]] = []
    for persona_id, raw in team_state.items():
        persona = personas[persona_id]
        state = HiddenState(**raw)
        record = _normalized_record(watch.get(persona_id, _blank_watch()))
        preventable_probability = _preventable_exit_probability(state, record)
        external_probability = _external_exit_probability(day, persona, state, record)
        if preventable_probability:
            candidates.append(
                {
                    "persona_id": persona_id,
                    "cause": "preventable",
                    "reason": record["last_reason"],
                    "probability": preventable_probability,
                    "pressure_days": record["pressure_days"],
                }
            )
        if external_probability:
            candidates.append(
                {
                    "persona_id": persona_id,
                    "cause": "external",
                    "reason": "outside_offer",
                    "probability": external_probability,
                    "pressure_days": record["pressure_days"],
                }
            )

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item["cause"] == "preventable", item["probability"], item["persona_id"]), reverse=True)
    for candidate in candidates:
        if candidate["cause"] == "preventable" and candidate["pressure_days"] >= FORCED_THRESHOLD:
            return candidate
        rng = random.Random(f"{run_id}:day:{day}:exit:{candidate['persona_id']}:{candidate['cause']}")
        if rng.randint(1, 100) <= candidate["probability"]:
            return candidate
    return None


def _pressure(
    persona: PersonaDefinition,
    state: HiddenState,
    actions: list[str],
) -> tuple[str, int, dict[str, bool]]:
    autonomy = persona.hidden["autonomy"]["preferred"]
    mastery = persona.hidden["mastery"]["preferred"]
    micromanagement = "increase_checkins" in actions and autonomy >= 80
    stagnation = "assign_maintenance" in actions or (
        state.atrophy > 48 and state.mastery_alignment < 60 and mastery >= 70
    )
    overload = state.burnout > 64 or state.battery < 42 or state.load > 78
    trust_loss = state.trust < 42 or state.opinion_of_manager < 42
    pressure = 0
    if state.flight_risk > 62:
        pressure += 2
    if state.flight_risk > 75:
        pressure += 2
    if micromanagement:
        pressure += 4
    if stagnation:
        pressure += 4
    if overload:
        pressure += 2
    if trust_loss:
        pressure += 2

    reasons = [
        ("micromanagement", micromanagement, 4),
        ("stagnation", stagnation, 3),
        ("overload", overload, 2),
        ("trust_loss", trust_loss, 1),
    ]
    reason = next((name for name, active, _weight in reasons if active), "general_drift")
    return reason, pressure, {
        "micromanagement": micromanagement,
        "stagnation": stagnation,
        "overload": overload,
        "trust_loss": trust_loss,
    }


def _preventable_exit_probability(state: HiddenState, record: dict[str, Any]) -> int:
    if record["pressure_days"] < PROBABILITY_THRESHOLD or state.flight_risk < 66:
        return 0
    probability = 8 + record["pressure_days"] * 7
    probability += min(14, record["micromanagement_days"] * 3)
    probability += min(14, record["stagnation_days"] * 3)
    probability += min(10, record["overload_days"] * 2)
    probability += min(10, record["trust_loss_days"] * 2)
    return min(70, probability)


def _external_exit_probability(
    day: int,
    persona: PersonaDefinition,
    state: HiddenState,
    record: dict[str, Any],
) -> int:
    if (
        day < MIN_EXIT_DAY
        or not record["outside_offer_active"]
        or record["outside_offer_days"] < OUTSIDE_OFFER_RESPONSE_WINDOW
        or record["pressure_days"] >= PROBABILITY_THRESHOLD
    ):
        return 0
    skill_signal = sum(persona.skills.values()) // max(1, len(persona.skills))
    probability = 24 + record["outside_offer_days"] * 8
    probability += max(0, skill_signal - 78) // 5
    probability += max(0, state.output - 65) // 8
    probability -= record["outside_offer_response_strength"] * 12
    return max(0, min(72, probability))


def _advance_outside_offer(
    record: dict[str, Any],
    persona: PersonaDefinition,
    state: HiddenState,
    actions: list[str],
    run_id: str | None,
    day: int | None,
    outside_offer_slot_used: bool,
) -> None:
    if record["outside_offer_active"]:
        record["outside_offer_days"] += 1
        response_strength = sum(1 for action in actions if action in RETENTION_RESPONSE_ACTIONS)
        if response_strength:
            record["outside_offer_response_strength"] += response_strength
            if (
                record["outside_offer_response_strength"] >= 2
                or (record["outside_offer_response_strength"] >= 1 and state.trust >= 55 and state.morale >= 55)
            ):
                record["outside_offer_active"] = False
                record["outside_offer_days"] = 0
                record["outside_offer_response_strength"] = 0
                record["outside_offer_cooldown"] = OUTSIDE_OFFER_COOLDOWN
        return

    record["outside_offer_days"] = 0
    record["outside_offer_response_strength"] = 0
    record["outside_offer_cooldown"] = max(0, record["outside_offer_cooldown"] - 1)
    if outside_offer_slot_used or run_id is None or day is None:
        return
    probability = _outside_offer_arrival_probability(day, persona, state, record)
    if not probability:
        return
    rng = random.Random(f"{run_id}:day:{day}:offer:{persona.id}")
    if rng.randint(1, 100) <= probability:
        record["outside_offer_active"] = True
        record["outside_offer_days"] = 0


def _outside_offer_arrival_probability(
    day: int,
    persona: PersonaDefinition,
    state: HiddenState,
    record: dict[str, Any],
) -> int:
    if (
        day < OUTSIDE_OFFER_MIN_DAY
        or record["outside_offer_cooldown"] > 0
        or record["pressure_days"] >= PROBABILITY_THRESHOLD
        or state.flight_risk > 58
    ):
        return 0
    skill_signal = sum(persona.skills.values()) // max(1, len(persona.skills))
    if skill_signal < 78 or state.output < 60:
        return 0
    return min(4, 1 + max(0, skill_signal - 80) // 8 + max(0, state.output - 68) // 16)


def _warning_title(name: str, reason: str) -> str:
    if reason == "micromanagement":
        return f"{name} declined another recurring check-in."
    if reason == "stagnation":
        return f"{name} asked whether there is anything harder to own than the maintenance queue."
    if reason == "overload":
        return f"{name} declined an optional planning session after saying they needed to catch up."
    if reason == "trust_loss":
        return f"{name} asked for a clearer decision boundary before taking on more work."
    return f"{name} has been less present in planning."


def _warning_detail(name: str, reason: str) -> str:
    if reason == "micromanagement":
        return f"{name} said they can own the outcome, but the current review cadence makes it hard to make decisions without waiting for approval."
    if reason == "stagnation":
        return f"{name} has kept the same operational work moving, but asked whether the role still has room to learn or build anything new."
    if reason == "overload":
        return f"{name} said they are finishing the work already in flight before taking on another meeting or follow-up commitment."
    if reason == "trust_loss":
        return f"{name} asked whether the team is actually allowed to change course or whether every decision has already been made elsewhere."
    return f"{name} has stopped volunteering context and seems less interested in long-term planning."


def _outside_offer_title(name: str) -> str:
    return f"{name} asked what the next six months could look like before taking on another large initiative."


def _outside_offer_detail(name: str) -> str:
    return (
        f"{name} seemed less interested in the immediate task list and more interested in whether there is room "
        "here to own something that matters. They did not say they were leaving."
    )


def _blank_watch() -> dict[str, Any]:
    return {
        "pressure_days": 0,
        "micromanagement_days": 0,
        "stagnation_days": 0,
        "overload_days": 0,
        "trust_loss_days": 0,
        "last_reason": "",
        "last_pressure": 0,
        "outside_offer_active": False,
        "outside_offer_days": 0,
        "outside_offer_response_strength": 0,
        "outside_offer_cooldown": 0,
    }


def _normalized_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = _blank_watch()
    normalized.update(record)
    return normalized
