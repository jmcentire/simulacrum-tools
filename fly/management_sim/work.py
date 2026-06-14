"""Work-state model for execution, closure, detail, and decision-making."""

from __future__ import annotations

import random
from typing import Any

from .models import HiddenState, PersonaDefinition


WORK_STYLE_OVERRIDES = {
    # Strong architecture / strong interview signal, but the work often stays
    # elegant and unfinished unless somebody forces closure.
    "xavier": {"thoughtfulness": 94, "closure": 56, "detail": 68, "tracking": 44, "decision_force": 88},
    "theo": {"thoughtfulness": 96, "closure": 46, "detail": 52, "tracking": 38, "decision_force": 82},
    "mira": {"thoughtfulness": 92, "closure": 50, "detail": 54, "tracking": 42, "decision_force": 64},
    "cara": {"thoughtfulness": 82, "closure": 62, "detail": 60, "tracking": 58, "decision_force": 72},
    # Good collaborators who can build consensus but may wait too long for a
    # hard decision if nobody else owns it.
    "faye": {"decision_force": 40},
    "omar": {"decision_force": 38},
    "jules": {"decision_force": 42},
    "wren": {"decision_force": 44},
    "tariq": {"decision_force": 40},
    "zoe": {"decision_force": 28},
    "hana": {"decision_force": 31},
}


WORK_TEMPLATES = [
    {"id": "workflow", "title": "Workflow builder", "skill": "product", "priority": 3, "needs_decision": True, "needs_detail": True, "needs_tracking": True},
    {"id": "reliability", "title": "Reliability hardening", "skill": "infra", "priority": 3, "needs_decision": False, "needs_detail": True, "needs_tracking": True},
    {"id": "migration", "title": "Migration service", "skill": "backend", "priority": 3, "needs_decision": True, "needs_detail": True, "needs_tracking": True},
    {"id": "frontend", "title": "Frontend shell", "skill": "frontend", "priority": 2, "needs_decision": False, "needs_detail": False, "needs_tracking": True},
    {"id": "quality", "title": "Quality automation", "skill": "quality", "priority": 2, "needs_decision": False, "needs_detail": True, "needs_tracking": False},
]


def work_style(persona: PersonaDefinition) -> dict[str, int]:
    traits = persona.hidden.get("traits", {})
    skills = persona.skills
    style = {
        "thoughtfulness": _average(skills.get("architecture", 50), skills.get("product", 50), traits.get("ambiguity_tolerance", 50)),
        "closure": _average(traits.get("reliability", 50), skills.get("quality", 50), skills.get("quality", 50)),
        "detail": _average(skills.get("quality", 50), traits.get("reliability", 50)),
        "tracking": _average(traits.get("reliability", 50), traits.get("mentorship", 50), skills.get("quality", 50)),
        "decision_force": _average(traits.get("autonomy_need", 50), traits.get("ambiguity_tolerance", 50), 100 - traits.get("collaboration", 50)),
    }
    style.update(WORK_STYLE_OVERRIDES.get(persona.id, {}))
    return style


def initial_workstreams(team: list[str], personas: dict[str, PersonaDefinition]) -> list[dict[str, Any]]:
    workstreams: list[dict[str, Any]] = []
    available_team = [persona_id for persona_id in team if persona_id in personas]
    if not available_team:
        return workstreams
    for template in WORK_TEMPLATES:
        owner = max(available_team, key=lambda persona_id: personas[persona_id].skills.get(template["skill"], 0))
        workstreams.append(
            {
                **template,
                "owner_id": owner,
                "state": "scoped",
                "age": 0,
                "blocked_reason": "",
                "rework": 0,
                "handoff_debt": 0,
                "decision_debt": 0,
                "pivot_applied": False,
                "completion": 18,
            }
        )
    return workstreams


def advance_workstreams(
    workstreams: list[dict[str, Any]],
    team: list[str],
    team_state: dict[str, dict[str, Any]],
    personas: dict[str, PersonaDefinition],
    day_actions: list[dict[str, str]],
    seed: str,
    active_events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    next_workstreams = [dict(item) for item in workstreams]
    rng = random.Random(seed)
    available_team = [persona_id for persona_id in team if persona_id in personas and persona_id in team_state]
    styles = {persona_id: work_style(personas[persona_id]) for persona_id in available_team}
    team_decision_force = max((style["decision_force"] for style in styles.values()), default=0)
    team_detail = max((style["detail"] for style in styles.values()), default=0)
    team_tracking = max((style["tracking"] for style in styles.values()), default=0)
    action_by_persona = {item["persona_id"]: item["action"] for item in day_actions}
    event_kinds = {event.get("kind") for event in active_events or [] if event.get("status") == "active"}
    dependency_leave_ids = {
        event.get("affected_persona_id")
        for event in active_events or []
        if event.get("status") == "active" and event.get("kind") == "dependency_leave"
    }

    for item in next_workstreams:
        item["age"] = min(365, item.get("age", 0) + 1)
        owner_id = item["owner_id"]
        if owner_id not in team:
            replacement_id = _best_replacement(item, available_team, personas)
            if not replacement_id:
                item["state"] = "blocked"
                item["blocked_reason"] = "The previous owner left and nobody has picked up the context."
                continue
            item["owner_id"] = replacement_id
            item["handoff_debt"] = max(item.get("handoff_debt", 0), 2)
            if item["state"] in {"done", "maintenance"}:
                item["state"] = "maintenance"
                item["blocked_reason"] = "The previous owner left. The new owner is carrying the system, but the maintenance context is thinner."
            else:
                item["state"] = "blocked"
                item["completion"] = max(22, item["completion"] - 8)
                item["blocked_reason"] = "The previous owner left. The new owner is reconstructing the context before work can continue."
            continue

        if item.get("handoff_debt", 0) > 0:
            item["handoff_debt"] -= 1

        owner_state = HiddenState(**team_state[owner_id])
        owner_style = styles[owner_id]
        manager_action = action_by_persona.get(owner_id, "")
        closure = owner_style["closure"] + (5 if manager_action == "delegate_ownership" else 0) + (3 if manager_action == "clarify_scope" else 0)
        detail = owner_style["detail"] + (4 if manager_action == "cross_train" else 0)
        tracking = owner_style["tracking"] + (3 if manager_action == "increase_checkins" else 0)
        energy = owner_state.battery - owner_state.burnout // 2

        if item["state"] != "blocked":
            item["blocked_reason"] = ""
        if "scope_pivot" in event_kinds and item["id"] in {"workflow", "frontend"} and not item.get("pivot_applied", False):
            item["pivot_applied"] = True
            item["rework"] = item.get("rework", 0) + 1
            item["state"] = "rework"
            item["completion"] = max(28, item["completion"] - 12)
            item["blocked_reason"] = "The roadmap pivot invalidated part of the prior plan; the team is re-cutting the slice."
            continue
        if owner_id in dependency_leave_ids and item["state"] not in {"done", "maintenance"}:
            item["state"] = "blocked"
            item["handoff_debt"] = max(item.get("handoff_debt", 0), 2)
            item["blocked_reason"] = "The owner is out and the team is reconstructing the missing context."
            continue

        if item["state"] == "scoped":
            if item["needs_decision"] and team_decision_force < 55:
                item["state"] = "blocked"
                item["decision_debt"] = item.get("decision_debt", 0) + 1
                item["blocked_reason"] = (
                    "The team keeps discussing the tradeoff but nobody closes the decision."
                    if item["decision_debt"] < 3
                    else "The decision has been deferred for three weeks; the team is waiting for a manager call."
                )
                continue
            item["state"] = "in_progress"
            item["completion"] = max(item["completion"], 28)

        if item["state"] == "blocked":
            reason = item["blocked_reason"].lower()
            if "decision" in reason:
                can_unblock = manager_action in {"clarify_scope", "delegate_ownership", "cross_train"} or team_decision_force >= 58
            elif "checklist" in reason or "follow-up" in reason:
                can_unblock = manager_action in {"increase_checkins", "delegate_ownership", "clarify_scope"} or team_tracking >= 60
            elif "context" in reason or "owner is out" in reason:
                can_unblock = manager_action in {"cross_train", "delegate_ownership", "clarify_scope"} or item.get("handoff_debt", 0) <= 0
            elif "review keeps" in reason:
                can_unblock = manager_action in {"coach_directly", "cross_train", "delegate_ownership"}
            else:
                can_unblock = manager_action in {"clarify_scope", "delegate_ownership", "cross_train"}
            if can_unblock:
                item["state"] = "in_progress"
                item["completion"] = max(item["completion"], 30)
            else:
                if item["needs_decision"] and "decision" in item["blocked_reason"].lower():
                    item["decision_debt"] = item.get("decision_debt", 0) + 1
                    if item["decision_debt"] >= 3:
                        item["blocked_reason"] = "The decision has been deferred for three weeks; the team is waiting for a manager call."
                continue

        if item["state"] == "in_progress":
            progress = max(2, (closure + energy + owner_state.output) // 28 + rng.randint(-2, 3))
            if closure < 58 and item["completion"] > 62:
                progress = max(1, progress - 4)
                item["blocked_reason"] = "The implementation is mostly there, but the last cleanup and packaging work keeps slipping."
            item["completion"] = min(88, item["completion"] + progress)
            if item["completion"] >= 62:
                item["state"] = "review"

        if item["state"] == "review":
            if item["needs_detail"] and max(detail, team_detail) < 66:
                item["state"] = "rework"
                item["rework"] += 1
                item["blocked_reason"] = "Review found missing edge cases and unfinished operational details."
                continue
            if item["needs_tracking"] and max(tracking, team_tracking) < 60:
                item["state"] = "blocked"
                item["blocked_reason"] = "Nobody has the checklist, status, or follow-up context needed to release it cleanly."
                continue
            item["completion"] = min(100, item["completion"] + 15 + rng.randint(0, 8))
            if item["completion"] >= 100:
                item["state"] = "done"

        if item["state"] == "rework":
            if item["rework"] >= 3 and detail < 64 and manager_action not in {"coach_directly", "cross_train"}:
                item["state"] = "blocked"
                item["blocked_reason"] = "Review keeps finding the same class of problem; this needs a manager call or a different owner."
            elif detail >= 64 or manager_action in {"coach_directly", "cross_train"}:
                item["state"] = "review"
                item["completion"] = max(55, item["completion"] - 8)
            else:
                item["blocked_reason"] = "The same missing detail keeps returning in a slightly different form."

        if item["state"] == "done" and item["age"] > 5:
            item["state"] = "maintenance"
            item["completion"] = 100

    return next_workstreams


def work_pressure(workstreams: list[dict[str, Any]]) -> int:
    pressure = 0
    for item in workstreams:
        if item["state"] == "blocked":
            pressure += 4 + item.get("priority", 1)
        elif item["state"] == "rework":
            pressure += 3 + item.get("priority", 1)
        elif item["state"] == "review":
            pressure += 1 + item.get("priority", 1)
        pressure += max(0, item["age"] - 4) // 2
        pressure += item.get("handoff_debt", 0)
        pressure += item.get("decision_debt", 0)
    return pressure


def work_artifacts(workstreams: list[dict[str, Any]], personas: dict[str, PersonaDefinition]) -> list[dict[str, str]]:
    artifacts: list[dict[str, str]] = []
    for item in workstreams:
        owner = personas.get(item["owner_id"])
        owner_name = owner.name if owner else "The previous owner"
        if item["state"] == "blocked":
            artifacts.append(
                {
                    "channel": "project board",
                    "title": f"{item['title']} has not moved this week.",
                    "detail": f"{owner_name}'s work is still blocked. {item['blocked_reason'] or 'The next decision has not been made.'}",
                }
            )
        elif item["state"] == "rework":
            artifacts.append(
                {
                    "channel": "review",
                    "title": f"{item['title']} came back from review again.",
                    "detail": f"{owner_name}'s work re-opened after review. {item['blocked_reason'] or 'The implementation is missing operational detail.'}",
                }
            )
        elif item["state"] == "review" and item["age"] > 4:
            artifacts.append(
                {
                    "channel": "release",
                    "title": f"{item['title']} is nearly done but has not shipped.",
                    "detail": f"{owner_name}'s work is in review with no clear release owner. It is technically coherent, but the final checklist and rollout work are still open.",
                }
            )
    return artifacts[:3]


def public_workstreams(workstreams: list[dict[str, Any]], personas: dict[str, PersonaDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "owner": personas[item["owner_id"]].name if item["owner_id"] in personas else "Unassigned",
            "state": item["state"],
            "completion": item["completion"],
        }
        for item in workstreams
    ]


def _average(*values: int) -> int:
    if not values:
        return 0
    return round(sum(values) / len(values))


def _best_replacement(item: dict[str, Any], team: list[str], personas: dict[str, PersonaDefinition]) -> str | None:
    if not team:
        return None
    skill = item["skill"]
    return max(team, key=lambda persona_id: personas[persona_id].skills.get(skill, 0))
