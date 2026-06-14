"""Hidden team-construction metrics used to test build decisions under stress."""

from __future__ import annotations

from typing import Any

from .models import PersonaDefinition


CRITICAL_SKILLS = ("architecture", "backend", "frontend", "infra", "product", "quality")


def team_structure(
    team: list[str],
    personas: dict[str, PersonaDefinition],
    relationships: dict[str, dict[str, int]],
    phase: str,
) -> dict[str, int]:
    if not team:
        return {"coverage": 0, "redundancy": 0, "bus_factor": 0, "phase_fit": 0, "cohesion": 0}

    coverage_values = []
    redundancy_counts = []
    for skill in CRITICAL_SKILLS:
        values = sorted((personas[persona_id].skills.get(skill, 0) for persona_id in team), reverse=True)
        coverage_values.append(values[0] if values else 0)
        redundancy_counts.append(sum(1 for value in values if value >= 68))

    coverage = sum(coverage_values) // len(coverage_values)
    redundancy = sum(min(100, count * 45) for count in redundancy_counts) // len(redundancy_counts)
    unique_holders = sum(1 for count in redundancy_counts if count == 1)
    bus_factor = max(0, 100 - unique_holders * 18)

    if phase == "build":
        fit_values = [
            (
                persona.hidden["traits"]["ambiguity_tolerance"]
                + persona.hidden["autonomy"]["preferred"]
                + persona.skills.get("product", 50)
                + persona.skills.get("architecture", 50)
            )
            // 4
            for persona in (personas[persona_id] for persona_id in team)
        ]
    else:
        fit_values = [
            (
                persona.hidden["traits"]["reliability"]
                + persona.hidden["traits"]["mentorship"]
                + persona.skills.get("quality", 50)
                + persona.skills.get("infra", 50)
            )
            // 4
            for persona in (personas[persona_id] for persona_id in team)
        ]
    phase_fit = sum(fit_values) // len(fit_values)

    edges = list(relationships.values())
    cohesion = 55
    if edges:
        cohesion = max(0, min(100, (sum(edge["trust"] for edge in edges) - sum(edge["friction"] for edge in edges)) // len(edges) + 50))

    return {
        "coverage": coverage,
        "redundancy": redundancy,
        "bus_factor": bus_factor,
        "phase_fit": phase_fit,
        "cohesion": cohesion,
    }


def structure_pressure(structure: dict[str, int]) -> int:
    return (
        max(0, 65 - structure["coverage"]) // 8
        + max(0, 55 - structure["redundancy"]) // 8
        + max(0, 55 - structure["bus_factor"]) // 10
        + max(0, 58 - structure["phase_fit"]) // 10
        + max(0, 45 - structure["cohesion"]) // 10
    )
