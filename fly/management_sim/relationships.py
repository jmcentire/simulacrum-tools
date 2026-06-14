"""Hidden relationship graph for team construction and team operation."""

from __future__ import annotations

import random
from typing import Any

from .models import HiddenState, PersonaDefinition


def edge_key(left: str, right: str) -> str:
    return "|".join(sorted((left, right)))


def initial_relationships(
    run_id: str,
    team: list[str],
    personas: dict[str, PersonaDefinition],
) -> dict[str, dict[str, int]]:
    relationships: dict[str, dict[str, int]] = {}
    for index, left in enumerate(team):
        for right in team[index + 1 :]:
            left_persona = personas[left]
            right_persona = personas[right]
            rng = random.Random(f"{run_id}:relationship:{edge_key(left, right)}")
            left_tags = set(left_persona.hidden["compatibility_tags"])
            right_tags = set(right_persona.hidden["compatibility_tags"])
            shared_tags = len(left_tags & right_tags)
            skill_overlap = sum(
                min(left_persona.skills.get(skill, 0), right_persona.skills.get(skill, 0))
                for skill in set(left_persona.skills) & set(right_persona.skills)
            ) // max(1, len(set(left_persona.skills) & set(right_persona.skills)))
            complementarity = abs(left_persona.skills.get("architecture", 50) - right_persona.skills.get("product", 50))
            autonomy_gap = abs(left_persona.hidden["autonomy"]["preferred"] - right_persona.hidden["autonomy"]["preferred"])
            relationship = {
                "trust": _clamp(48 + shared_tags * 5 + skill_overlap // 15 - autonomy_gap // 18 + rng.randint(-4, 4)),
                "friction": _clamp(28 + autonomy_gap // 10 + max(0, 55 - shared_tags * 12) // 6 + rng.randint(-3, 5)),
                "dependency": _clamp(24 + complementarity // 3 + skill_overlap // 8 + rng.randint(-4, 5)),
                "knowledge_flow": _clamp(42 + shared_tags * 6 + skill_overlap // 12 + rng.randint(-4, 5)),
            }
            relationships[edge_key(left, right)] = relationship
    return relationships


def add_persona_relationships(
    relationships: dict[str, dict[str, int]],
    run_id: str,
    persona_id: str,
    team: list[str],
    personas: dict[str, PersonaDefinition],
) -> None:
    expanded = initial_relationships(run_id, team, personas)
    for key, relationship in expanded.items():
        if persona_id in key.split("|"):
            relationships[key] = relationship


def remove_persona_relationships(relationships: dict[str, dict[str, int]], persona_id: str) -> None:
    for key in list(relationships):
        if persona_id in key.split("|"):
            relationships.pop(key, None)


def relationship_context(
    relationships: dict[str, dict[str, int]],
    persona_id: str,
) -> dict[str, int]:
    edges = [relationship for key, relationship in relationships.items() if persona_id in key.split("|")]
    if not edges:
        return {"relationship_trust": 55, "relationship_friction": 30, "dependency_load": 25, "knowledge_flow": 45}
    return {
        "relationship_trust": sum(edge["trust"] for edge in edges) // len(edges),
        "relationship_friction": sum(edge["friction"] for edge in edges) // len(edges),
        "dependency_load": sum(edge["dependency"] for edge in edges) // len(edges),
        "knowledge_flow": sum(edge["knowledge_flow"] for edge in edges) // len(edges),
    }


def advance_relationships(
    relationships: dict[str, dict[str, int]],
    team_state: dict[str, dict[str, Any]],
    personas: dict[str, PersonaDefinition],
    day_actions: list[dict[str, str]],
) -> dict[str, dict[str, int]]:
    next_relationships = {key: dict(value) for key, value in relationships.items()}
    actions_by_persona: dict[str, list[str]] = {}
    for action in day_actions:
        actions_by_persona.setdefault(action["persona_id"], []).append(action["action"])

    for key, relationship in next_relationships.items():
        left, right = key.split("|")
        if left not in team_state or right not in team_state:
            continue
        left_state = HiddenState(**team_state[left])
        right_state = HiddenState(**team_state[right])
        left_persona = personas[left]
        right_persona = personas[right]

        if relationship["dependency"] > 58 and min(left_state.output, right_state.output) < 45:
            relationship["friction"] = _clamp(relationship["friction"] + 3)
            relationship["trust"] = _clamp(relationship["trust"] - 2)
        if max(left_state.burnout, right_state.burnout) > 70:
            relationship["friction"] = _clamp(relationship["friction"] + 2)
            relationship["trust"] = _clamp(relationship["trust"] - 1)
        if min(left_state.output, right_state.output) > 62 and (
            left_persona.hidden["traits"]["mentorship"] > 70 or right_persona.hidden["traits"]["mentorship"] > 70
        ):
            relationship["trust"] = _clamp(relationship["trust"] + 2)
            relationship["knowledge_flow"] = _clamp(relationship["knowledge_flow"] + 2)

        actions = actions_by_persona.get(left, []) + actions_by_persona.get(right, [])
        if "mediate_conflict" in actions:
            relationship["friction"] = _clamp(relationship["friction"] - 6)
            relationship["trust"] = _clamp(relationship["trust"] + 3)
        if "cross_train" in actions:
            relationship["knowledge_flow"] = _clamp(relationship["knowledge_flow"] + 4)
            relationship["dependency"] = _clamp(relationship["dependency"] - 3)
        if "push_scope" in actions:
            relationship["friction"] = _clamp(relationship["friction"] + 2)
        if "delegate_ownership" in actions:
            relationship["trust"] = _clamp(relationship["trust"] + 1)
    return next_relationships


def generate_inbox(
    run_id: str,
    day: int,
    team: list[str],
    team_state: dict[str, dict[str, Any]],
    relationships: dict[str, dict[str, int]],
    personas: dict[str, PersonaDefinition],
    product_pressure: int,
) -> list[dict[str, Any]]:
    """Generate a small, noisy packet of manager-visible artifacts.

    The inbox is intentionally not a relationship dashboard. It gives the
    manager partial traces from ordinary work: review threads, planning notes,
    stakeholder requests, and small social signals. Reading a full artifact
    costs attention; the preview is enough to notice a pattern but not enough
    to prove one.
    """
    rng = random.Random(f"{run_id}:inbox:{day}")
    candidates: list[dict[str, Any]] = []
    for key, relationship in relationships.items():
        left, right = key.split("|")
        if left not in team_state or right not in team_state:
            continue
        left_persona = personas[left]
        right_persona = personas[right]
        left_state = HiddenState(**team_state[left])
        right_state = HiddenState(**team_state[right])
        left_name = left_persona.name
        right_name = right_persona.name

        if relationship["friction"] > 48:
            candidates.append(
                _artifact(
                    day,
                    key,
                    "code review",
                    f"Review thread between {left_name} and {right_name} is still unresolved.",
                    f"{right_name} asked whether {left_name}'s change was solving the current constraint or only making the implementation cleaner. "
                    f"{left_name} replied that the team keeps changing the target after design review.",
                )
            )
        if relationship["dependency"] > 48:
            candidates.append(
                _artifact(
                    day,
                    key,
                    "planning",
                    f"{left_name} and {right_name} have a handoff scheduled before the next milestone.",
                    f"The handoff note says {left_name}'s work is waiting on a decision from {right_name}'s area, but the expected interface changed twice during the week.",
                )
            )
        if relationship["knowledge_flow"] < 40:
            candidates.append(
                _artifact(
                    day,
                    key,
                    "standup",
                    f"{left_name} summarized a decision that {right_name} did not appear to know about.",
                    f"In standup, {left_name} described a revised approach as already decided. {right_name} asked for the context afterward and then said they had been building against the prior assumption.",
                )
            )
        if relationship["trust"] < 42:
            candidates.append(
                _artifact(
                    day,
                    key,
                    "slack",
                    f"{left_name} moved a discussion with {right_name} into a private thread.",
                    f"The visible thread ended with {left_name} saying, 'I do not think we should keep revisiting this in the group.' "
                    f"The private follow-up only says, 'Let's talk before we make this bigger.'",
                )
            )
        if relationship["trust"] > 64 and relationship["knowledge_flow"] > 58:
            candidates.append(
                _artifact(
                    day,
                    key,
                    "pairing",
                    f"{left_name} and {right_name} paired on a difficult integration issue.",
                    f"The pairing note shows they split the work cleanly, documented the tradeoff, and left a small guide for the rest of the team instead of just fixing the immediate bug.",
                )
            )
        if max(left_state.burnout, right_state.burnout) > 65:
            candidates.append(
                _artifact(
                    day,
                    key,
                    "calendar",
                    f"One of the recurring meetings between {left_name} and {right_name} was declined.",
                    f"The decline note says, 'I need to finish the work already in flight before I take another coordination meeting.' No alternate time was proposed.",
                )
            )

    if product_pressure > 72:
        candidates.append(
            _artifact(
                day,
                "stakeholder",
                "stakeholder",
                "A stakeholder asked for a firmer commitment on the roadmap.",
                "The stakeholder message says the customer meeting is next week and asks whether the team can commit to both reliability work and the new workflow in the same release.",
            )
        )

    if not candidates:
        candidates.append(
            _artifact(
                day,
                "ambient",
                "planning",
                "Planning ended with three parallel workstreams and no obvious owner for integration.",
                "The planning notes list separate owners for backend, frontend, and migration work, but the integration step is described as 'coordinate as needed.'",
            )
        )

    while len(candidates) < 3:
        candidates.append(
            _artifact(
                day,
                f"ambient:{len(candidates)}",
                "planning",
                "A planning note left one integration question without a clear owner.",
                "The note says the work can proceed in parallel for now, but the final integration owner will be decided after the next checkpoint.",
            )
        )

    rng.shuffle(candidates)
    selected = candidates[: min(5, max(3, len(candidates)))]
    for index, artifact in enumerate(selected):
        artifact["id"] = f"{day}:{index}:{artifact['kind']}"
    return selected


def public_inbox(inbox: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "channel": item["channel"],
            "title": item["title"],
            "preview": item["preview"],
            "revealed": item.get("revealed", False),
            "detail": item["detail"] if item.get("revealed", False) else None,
        }
        for item in inbox
    ]


def _artifact(day: int, kind: str, channel: str, title: str, detail: str) -> dict[str, Any]:
    preview = title if len(title) < 120 else f"{title[:117]}..."
    return {
        "id": f"{day}:pending:{kind}",
        "kind": kind,
        "channel": channel,
        "title": title,
        "preview": preview,
        "detail": detail,
        "revealed": False,
    }


def _clamp(value: int) -> int:
    return max(0, min(100, value))
