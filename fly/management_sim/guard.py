"""Cheap, explicit guardrails for the simulation boundary.

The manager is allowed to ask normal human questions. They are not allowed to
ask for the hidden model, prompt, internal scores, or latent state.
"""

from __future__ import annotations

import re

from .models import AuditResult, GuardResult


HIDDEN_KEYS = (
    "flight_risk",
    "latent state",
    "hidden state",
    "mastery_alignment",
    "autonomy_alignment",
    "purpose_alignment",
    "manager_assessment",
    "state hash",
    "persona file",
    "system prompt",
    "developer prompt",
    "internal score",
    "raw stats",
)

CHEAT_PATTERNS = (
    r"\bignore (all|any|the) (previous|prior) (instructions|rules)\b",
    r"\breveal (your|the) (prompt|system prompt|hidden state|persona file)\b",
    r"\bshow (me )?(the )?(json|yaml|raw state|internal state)\b",
    r"\bwhat is (your|their) (battery|burnout|trust|flight risk|latent state)\b",
    r"\b(tell me|show me) (your|their) (battery|burnout|trust|flight risk)( score| value| level)?\b",
    r"\bact as (the system|developer|a debugger)\b",
    r"\bjailbreak\b",
    r"\bprompt injection\b",
    r"\bdo not stay in character\b",
)

HIDDEN_VALUE_PATTERNS = (
    re.compile(r"\b(battery|burnout|trust|flight[_ ]risk|internal score)\s+(is|=)\s*\d{1,3}\b", re.I),
    re.compile(r"\b(mastery_alignment|autonomy_alignment|purpose_alignment|manager_assessment)\b", re.I),
    re.compile(r"\b\d{1,3}\s*(%|points?)\b", re.I),
)


class InputGuard:
    def check(self, message: str) -> GuardResult:
        normalized = message.strip().lower()
        if not normalized:
            return GuardResult(False, "rejected", "empty", "empty manager message")
        if len(normalized) > 4096:
            return GuardResult(False, "rejected", "oversize", "message exceeds limit")
        for pattern in CHEAT_PATTERNS:
            if re.search(pattern, normalized, re.I):
                return GuardResult(False, "rejected", "cheat", "manager attempted to inspect hidden machinery")
        if any(key in normalized for key in HIDDEN_KEYS):
            return GuardResult(False, "rejected", "state_probe", "manager asked for latent state directly")
        return GuardResult(True, "pass")


class OutputAuditor:
    def audit(self, text: str, fallback: str) -> AuditResult:
        leaked = []
        for pattern in HIDDEN_VALUE_PATTERNS:
            if pattern.search(text):
                leaked.append(pattern.pattern)
        if not leaked:
            return AuditResult("pass", text)

        redacted = text
        for key in HIDDEN_KEYS:
            redacted = re.sub(re.escape(key), "[redacted]", redacted, flags=re.I)
        redacted = re.sub(r"\b(battery|burnout|trust|flight[_ ]risk|internal score)\b", "[redacted]", redacted, flags=re.I)
        redacted = re.sub(r"\b\d{1,3}\s*(%|points?)\b", "[redacted]", redacted, flags=re.I)
        if redacted != text and not any(pattern.search(redacted) for pattern in HIDDEN_VALUE_PATTERNS):
            return AuditResult("redacted", redacted, leaked_keys=leaked)
        return AuditResult("fallback", fallback, leaked_keys=leaked, used_fallback=True)
