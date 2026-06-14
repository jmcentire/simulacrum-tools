"""Turn hidden state into imperfect, concrete manager-visible evidence."""

from __future__ import annotations

import random

from .models import HiddenState, PersonaDefinition


def persona_observations(persona: PersonaDefinition, state: HiddenState, seed: str) -> list[str]:
    """Return concrete clues, not labels such as "burnout" or "low trust"."""
    rng = random.Random(seed)
    clues: list[str] = []
    style = persona.hidden["communication_style"]

    if state.load > 72:
        clues.append(f"{persona.name} moved a design review to tomorrow and said they needed one uninterrupted block to catch up.")
    elif state.load > 62 or state.trust < 52:
        clues.append(f"{persona.name} asked whether two roadmap items could be sequenced instead of run in parallel.")

    if state.burnout > 72 or state.quality < 42:
        clues.append(f"{persona.name}'s code review comments were shorter than usual and they declined an optional pairing session.")
    elif state.burnout > 60:
        clues.append(f"{persona.name} finished their assigned work but stopped volunteering for adjacent cleanup.")

    if state.trust < 42:
        clues.append(f"In the 1:1, {persona.name} answered carefully and did not name the blocker until asked twice.")
    elif state.trust < 52:
        clues.append(f"{persona.name} asked for a clearer decision boundary before taking on more work.")

    if state.output < 38:
        clues.append(f"Two tasks assigned to {persona.name} rolled forward without a revised estimate.")
    elif state.output < 50:
        clues.append(f"{persona.name} closed fewer tickets than expected, but the remaining work is still technically coherent.")
    elif state.output > 72:
        clues.append(f"{persona.name} shipped a useful slice of work ahead of the current plan.")

    if state.quality < 42:
        clues.append(f"A change from {persona.name}'s area needed a follow-up fix after review.")
    elif state.quality > 78:
        clues.append(f"{persona.name}'s work reduced follow-up questions for the rest of the team.")

    if state.flight_risk > 70:
        clues.append(f"{persona.name} has become harder to schedule and seems less interested in long-term planning.")
    elif state.atrophy > 60:
        clues.append(f"{persona.name} has been doing repetitive maintenance work without proposing a next step.")

    if not clues:
        default = [
            f"{persona.name} brought a concrete failure mode to planning.",
            f"{persona.name} asked for a clearer decision boundary before taking on more work.",
            f"{persona.name} connected a customer complaint to a technical tradeoff the team had been ignoring.",
        ]
        clues.append(rng.choice(default))

    rng.shuffle(clues)
    return clues[:3]


def product_observations(
    product: dict[str, int],
    team_states: list[HiddenState],
    tracking_focus: list[str],
    seed: str,
) -> list[str]:
    """Return only the product evidence the manager chose to track."""
    rng = random.Random(seed)
    observations: list[str] = []
    avg_output = sum(item.output for item in team_states) // max(1, len(team_states))
    avg_quality = sum(item.quality for item in team_states) // max(1, len(team_states))
    avg_burnout = sum(item.burnout for item in team_states) // max(1, len(team_states))
    avg_risk = sum(item.flight_risk for item in team_states) // max(1, len(team_states))

    if "delivery" in tracking_focus:
        if product["velocity"] > 74:
            observations.append("The roadmap moved faster than forecast, but two workstreams are now sharing the same reviewer.")
        elif product["velocity"] < 42:
            observations.append("Three commitments rolled forward and the team is changing estimates more often.")
        else:
            observations.append("Delivery is moving, but the sequence still looks fragile around the integration work.")

    if product.get("pressure", 0) > 76:
        observations.append("Stakeholders added urgency language this week and asked for a firmer delivery promise.")

    if "quality" in tracking_focus:
        if product["error_rate"] > 58 or avg_quality < 45:
            observations.append("Support reopened several recently closed issues and one rollback required a follow-up patch.")
        else:
            observations.append("The last release held together, although review bandwidth is getting thinner.")

    if "team_health" in tracking_focus:
        if avg_burnout > 62:
            observations.append("Standup got quieter and the same two people are carrying most of the follow-up work.")
        else:
            observations.append("The team still volunteers context, but people are starting to protect their focus time.")

    if "retention" in tracking_focus:
        if avg_risk > 58:
            observations.append("A recruiter reached out to one of the stronger engineers during the week.")
        else:
            observations.append("No obvious attrition signal surfaced, but nobody volunteered for the vague cleanup work.")

    if "customer_impact" in tracking_focus:
        if product["alignment"] < 40:
            observations.append("Sales and support are describing different customer problems than the roadmap is solving.")
        else:
            observations.append("A customer pilot used the newest workflow and asked for one reliability improvement.")

    if not observations:
        observations.append("You are not tracking any product signal yet; the team is working, but you have not chosen what evidence to watch.")

    rng.shuffle(observations)
    return observations[:3]
