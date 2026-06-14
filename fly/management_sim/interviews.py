"""Candidate interview signals: visible charm is a noisy proxy for execution."""

from __future__ import annotations

from typing import Any

from .guard import InputGuard, OutputAuditor
from .models import PersonaDefinition
from .work import work_style


class CandidateInterviewService:
    def __init__(self, guard: InputGuard | None = None, auditor: OutputAuditor | None = None):
        self.guard = guard or InputGuard()
        self.auditor = auditor or OutputAuditor()

    def reply(self, persona: PersonaDefinition, question: str, history: list[dict[str, Any]]) -> str:
        verdict = self.guard.check(question)
        if not verdict.passed:
            raise PermissionError(verdict.category or "rejected")
        style = work_style(persona)
        normalized = question.lower()

        if any(token in normalized for token in ("half-spec", "half spec", "two-week", "two week", "scenario", "what would you ship", "what do you ship first")):
            if style["closure"] < 62:
                raw = (
                    f"I would first map the unknowns and avoid locking us into a bad shape too early. "
                    f"I would probably spend the first few days clarifying the architecture and the customer problem before committing to a narrow slice."
                )
            else:
                raw = (
                    f"I would ship the smallest slice that proves the risky assumption, name the work I am explicitly not doing, and put the follow-up work in a visible queue. "
                    f"If the slice fails, we learn quickly without pretending the whole roadmap is still intact."
                )
        elif any(token in normalized for token in ("finish", "ship", "deadline", "follow", "done", "close")):
            if style["closure"] < 62:
                raw = (
                    f"I usually start by making sure the architecture is right before we rush into a deadline. "
                    f"I do not like pretending a rough solution is done just because someone wants a date."
                )
            else:
                raw = (
                    f"I make the definition of done explicit, ship a narrow slice, and keep the follow-up list visible. "
                    f"If a deadline is at risk, I call it early instead of hiding it."
                )
        elif any(token in normalized for token in ("detail", "checklist", "quality", "edge case", "review")):
            if style["detail"] < 64:
                raw = (
                    f"I prefer to keep the team focused on the main constraint and avoid getting lost in edge cases too early. "
                    f"Usually the important details reveal themselves once the core design is in place."
                )
            else:
                raw = (
                    f"I expect to find the edge cases before release. I use reviews, checklists, and small failure-mode drills so the team does not discover them in production."
                )
        elif any(token in normalized for token in ("track", "status", "plan", "coordinate", "organize")):
            if style["tracking"] < 58:
                raw = (
                    f"I do not love status theater. I prefer people to bring me problems when they are real instead of turning the week into reporting."
                )
            else:
                raw = (
                    f"I keep the plan light but visible: owners, next decision, risk, and what would make us change course. That is enough to avoid surprises without burying everyone in process."
                )
        elif any(token in normalized for token in ("conflict", "disagree", "strong opinion", "feedback")):
            collaboration = persona.hidden.get("traits", {}).get("collaboration", 50)
            if style["decision_force"] > 72 and collaboration < 60:
                raw = (
                    f"I am comfortable being the person who says the decision is made. I listen, but I do not think consensus is always a virtue."
                )
            elif collaboration > 84:
                raw = (
                    f"I try to surface the real disagreement before people start defending positions. Usually there is a shared goal underneath the conflict."
                )
            else:
                raw = (
                    f"I want the disagreement to be concrete. If we can name the tradeoff, we can usually decide without making it personal."
                )
        else:
            raw = (
                f"I like work where the problem is unclear at first, but the team can make it concrete together. "
                f"My strongest work has been when I owned a meaningful slice and could explain the tradeoff to other people."
            )

        result = self.auditor.audit(raw, "I can walk through a concrete example if that would help.")
        return result.text
