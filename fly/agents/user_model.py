"""Compact probabilistic user model for Teach and Review modes."""

from __future__ import annotations

import json
import re
from typing import Any

import anthropic

from anthropic_config import DEFAULT_ANTHROPIC_MODEL, anthropic_api_key

DEFAULT_MODEL = DEFAULT_ANTHROPIC_MODEL


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}


def compact_profile(profile: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "confidence",
        "interaction_patterns",
        "pressure_preference",
        "example_preferences",
        "active_threads",
        "delivery_feedback",
        "next_best_moves",
    )
    list_fields = {
        "interaction_patterns",
        "example_preferences",
        "active_threads",
        "delivery_feedback",
        "next_best_moves",
    }
    return {key: profile.get(key, [] if key in list_fields else "") for key in keys}


class UserModelService:
    def __init__(self, model: str = DEFAULT_MODEL, client: Any | None = None):
        api_key = anthropic_api_key(required=False)
        self.client = client or (anthropic.Anthropic(api_key=api_key) if api_key else None)
        self.model = model

    def _json_pass(self, instruction: str, payload: str) -> dict[str, Any]:
        if not self.client:
            return {}
        response = self.client.messages.create(
            model=self.model,
            max_tokens=900,
            temperature=0.2,
            system=instruction,
            messages=[{"role": "user", "content": payload}],
        )
        return _parse_json(response.content[0].text)

    def summarize_session(self, prior_summary: str, turns: list[tuple[str, str]]) -> str:
        if not self.client or not turns:
            return prior_summary
        dialog = "\n\n".join(f"[{role}]: {text}" for role, text in turns[-16:])
        instruction = """Summarize an ongoing professional coaching conversation.
Keep only durable context that matters for the next turn: the user's current
goal, the key unresolved question, the best insight already found, and the
remaining tension. Do not include private speculation or labels. Return plain
text under 900 characters."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            temperature=0.2,
            system=instruction,
            messages=[
                {
                    "role": "user",
                    "content": f"PRIOR SUMMARY:\n{prior_summary}\n\nRECENT TURNS:\n{dialog}",
                }
            ],
        )
        return response.content[0].text.strip()[:900]

    def refresh_profile(
        self,
        prior_profile: dict[str, Any],
        session_summary: str,
        turns: list[tuple[str, str]],
    ) -> dict[str, Any]:
        if not self.client:
            return prior_profile
        dialog = "\n\n".join(f"[{role}]: {text}" for role, text in turns[-12:])
        instruction = """You are the hidden observer inside an adult engineering
coach. Build a compact, probabilistic profile from actual conversation evidence.
Do not diagnose clinically. Do not invent facts. Treat the prior profile as a
hypothesis that can be corrected.

Return JSON with:
- confidence: low|medium|high
- interaction_patterns: array of observable short phrases
- pressure_preference: low|medium|high
- example_preferences: array of observable short phrases
- active_threads: array of short phrases
- delivery_feedback: array of short phrases about framing, pacing, or examples
- next_best_moves: array of short phrases
- evidence: array of short evidence statements grounded in recent turns

The profile is used only to calibrate pressure, examples, and intervention
timing. Store observable interaction patterns, not competence assessments,
diagnoses, or domain-specific claims about what the user cannot do. It must
never be used to assume the user's claim is correct or incorrect.
delivery_feedback must describe delivery-method experiments only, such as
"concrete counterexample landed better than abstract principle." Do not record
"user rejected correction" as feedback, and never use delivery feedback to
suppress a future correction."""
        payload = (
            f"PRIOR PROFILE:\n{json.dumps(prior_profile)}\n\n"
            f"SESSION SUMMARY:\n{session_summary}\n\n"
            f"RECENT TURNS:\n{dialog}"
        )
        profile = self._json_pass(instruction, payload)
        return profile or prior_profile


def detect_pressure_mismatch(dialogue: list[tuple[str, str]]) -> str | None:
    """Return a short reason when the current session needs immediate de-escalation."""
    user_turns = [text.strip().lower() for role, text in dialogue if role.lower() in {"interlocutor", "user"}]
    if len(user_turns) < 2:
        return None
    recent = user_turns[-1]
    prior = user_turns[-2]
    short = len(recent) < 48
    evasive = any(
        phrase in recent
        for phrase in (
            "i don't know",
            "not sure",
            "whatever",
            "fine",
            "doesn't matter",
            "i guess",
            "never mind",
        )
    )
    if short and evasive and len(prior) > 100:
        return "recent response became short and evasive after a longer attempt"
    if recent in {"idk", "no idea", "fine"}:
        return "recent response collapsed into a minimal answer"
    return None
