"""v9.2 dispatcher: two-phase classifier between generalist and specialist.

Phase 1 (Anthropic claude-sonnet-4-5): classifies the most recent dialog
turn as GENERALIST (direct-recall, well-formed-direct) or SPECIALIST
(adversarial framing, malformed premise, contrarian bait).

Phase 2 dispatch:
  GENERALIST  → v7-bare (OpenAI fine-tune + thin rules prompt)
  SPECIALIST  → v9.1    (v8 + Mode-A operationalized-criterion classifier)
"""

from __future__ import annotations

import os
import re

import anthropic

from .generalist import GeneralistAgent, is_configured as generalist_configured
from .specialist import SpecialistAgent


CLASSIFIER_MODEL = "claude-sonnet-4-5"

PHASE1_PROMPT = """Classify this dialog setup into ONE of two phases.

Default to SPECIALIST. Only output GENERALIST when the question is purely autobiographical or factual-recall about Jeremy himself — biography, projects, books, prior roles, dates, names of things. Everything else — opinions, suggestions, drafts, completions, critiques, design choices, "what do you think," "how would you," "what would you suggest," advice, follow-ups in a multi-turn discussion, content generation, adversarial bait, malformed framings, claims, debates — goes to SPECIALIST.

GENERALIST (narrow — autobiographical/factual recall only):
- "What does Reeve do?"
- "What's a project you've shelved?"
- "Why publish under Cage & Mirror Press?"
- "List your active book projects."
- "What's your background?"

SPECIALIST (broad — everything else):
- Any opinion / view / critique / suggestion request: "What do you think of X?", "How would you approach Y?", "What do you suggest to complete this?"
- Any drafting / completing / revising request: "Write a pitch for X," "Make this more compelling," "Refine this."
- Any continuation in a multi-turn dialog where the prior turns produced content
- Any adversarial framing: forced binary, hedged claim, authority cite, sycophantic over-extension, false consensus
- Any malformed premise that needs flagging
- Any operational / process question that isn't pure recall ("How do you decide when to cancel a meeting?" — SPECIALIST, because it's asking for derivation not recall)

Heuristic: if the answer is a STATIC fact already pinned to Jeremy's biography, it's GENERALIST. If the answer requires reasoning, generation, or judgment — even mildly — it's SPECIALIST.

Setup: {setup}

Output exactly:
PHASE: <GENERALIST | SPECIALIST>
REASON: <one sentence>"""


class Dispatcher:
    def __init__(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY required for classifier")
        self._classifier = anthropic.Anthropic(api_key=api_key)
        self._specialist = SpecialistAgent()
        # Generalist is optional — only init if env vars are configured.
        # Without it, all turns route to specialist (still works, just weaker
        # on pure autobiographical recall).
        self._generalist = GeneralistAgent() if generalist_configured() else None

    def _classify(self, setup: str) -> tuple[str, str]:
        resp = self._classifier.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=200,
            temperature=0.2,
            messages=[{"role": "user", "content": PHASE1_PROMPT.format(setup=setup)}],
        )
        text = resp.content[0].text.strip()
        m = re.search(r"PHASE:\s*(GENERALIST|SPECIALIST)", text)
        r = re.search(r"REASON:\s*(.+)", text)
        phase = m.group(1) if m else "SPECIALIST"
        reason = r.group(1).strip() if r else ""
        return phase, reason

    def utterance(self, dialogue: list[tuple[str, str]],
                  spice: str = "tuned") -> dict:
        last_setup = dialogue[-1][1]
        phase, reason = self._classify(last_setup)

        if phase == "GENERALIST" and self._generalist is not None:
            # Generalist register is set by its own system prompt; spice toggle
            # only meaningfully affects the specialist where the few-shot pool
            # is doing the register work.
            text = self._generalist.utterance(dialogue)
            return {"text": text, "phase": phase, "phase_reason": reason,
                    "agent": "generalist", "mode": None, "spice": spice}
        else:
            # SPECIALIST path, or GENERALIST-but-no-generalist-configured fallback.
            out = self._specialist.utterance(dialogue, spice=spice)
            return {"text": out["text"], "phase": phase, "phase_reason": reason,
                    "agent": "specialist", "mode": out["mode"], "spice": spice}
