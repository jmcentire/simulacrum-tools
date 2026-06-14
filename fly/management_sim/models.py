"""Typed domain objects for the management simulator."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PersonaDefinition:
    schema_version: int
    id: str
    name: str
    role: str
    salary_cents: int
    backfill_fund_cents: int
    skills: dict[str, int]
    visible: dict[str, Any]
    hidden: dict[str, Any]

    def public_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "salary_cents": self.salary_cents,
            "backfill_fund_cents": self.backfill_fund_cents,
            "skills": self.skills,
            **self.visible,
        }


@dataclass
class HiddenState:
    persona_id: str
    week: int
    battery: int
    burnout: int
    trust: int
    morale: int
    flight_risk: int
    load: int
    mastery_alignment: int
    autonomy_alignment: int
    purpose_alignment: int
    atrophy: int
    manager_assessment: int
    known_hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PublicTeamSignal:
    persona_id: str
    name: str
    role: str
    report: str
    visible_flags: list[str]


@dataclass
class GuardResult:
    passed: bool
    verdict: str
    category: str | None = None
    detail: str | None = None


@dataclass
class AuditResult:
    verdict: str
    text: str
    leaked_keys: list[str] = field(default_factory=list)
    retried: bool = False
    used_fallback: bool = False


@dataclass
class AssessmentAxis:
    score: int
    evidence: list[str]
    assumptions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "evidence": self.evidence, "assumptions": self.assumptions}


@dataclass
class AssessmentReport:
    person_traits: AssessmentAxis
    team_dynamics: AssessmentAxis
    product_complications: AssessmentAxis
    crisis_outcomes: AssessmentAxis
    highest_value_next_move: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "person_traits": self.person_traits.to_dict(),
            "team_dynamics": self.team_dynamics.to_dict(),
            "product_complications": self.product_complications.to_dict(),
            "crisis_outcomes": self.crisis_outcomes.to_dict(),
            "highest_value_next_move": self.highest_value_next_move,
        }
