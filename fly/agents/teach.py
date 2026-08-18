"""Teach-mode agent: adult professional coaching with hidden planning passes.

Teach mode is intentionally separate from the review/pushback agent. Review
asks whether a framing is malformed. Teach asks what the learner needs next.

The learner sees one Jeremy-like response. Internally, the agent runs a small
loop:

    observe learner state -> choose target/intervention -> draft response
    -> audit draft -> revise once if needed

This is deliberately lightweight. Persistent user context can calibrate
pressure and examples, but a separate no-profile epistemic gate decides whether
the learner's current claim warrants correction or challenge.
"""

from __future__ import annotations

import json
import re
from typing import Any

import anthropic

from anthropic_config import DEFAULT_ANTHROPIC_MODEL, anthropic_api_key
from .specialist import PROFESSIONAL_REGISTER, SAILOR_REGISTER
from .user_model import detect_pressure_mismatch

DEFAULT_MODEL = DEFAULT_ANTHROPIC_MODEL

INTERVENTIONS = (
    "validate_safety",
    "amplify",
    "reframe",
    "anchor",
    "challenge",
    "let_fail",
    "back_off",
    "summarize_win",
    "reflection",
    "direct_answer",
)

CANONICAL_PATTERNS = """Canonical teaching patterns:

1. A learner says they do not want a kind of work but could do it because it
   seems important. Do not immediately interrogate them as weak or lazy. They
   may be drifting into obligation. Use validate_safety or permission first.
   Distinguish understanding a dependency from owning the work forever.

2. A learner has already discovered a better abstraction. Do not swat it down
   with failure-mode questions just because those exist. Use amplify. Extend the
   insight. Example: an engineer builds a DSL that makes integrations more
   deterministic; the useful move is to notice that AI lets us reshape the
   problem, not merely solve the same problem faster.

3. A learner is stuck in an abstraction that creates unnecessary machinery.
   Use reframe. Replace state machines, queues, and orchestration jargon with a
   concrete representation that makes the flow obvious. Example: bucket ->
   process one step -> move to next bucket; content-addressable ID makes
   recovery direct.

4. A learner raises a politically risky concern about code ownership, authority,
   or a senior person's behavior. Use validate_safety before challenge. Make it
   clear the concern is legitimate and that they are not being punished for
   noticing it. Then move toward the system-level constraint.

5. A learner asks for a metric in a messy system. Do not pick a metric. Use an
   anchor: legibility is a lossy projection; Goodhart's law turns indicators into
   targets; correlation is not causation; hidden variables matter. Help them use
   metrics as indicators, not truth.

6. A learner offers a compelling narrative with weak evidence. Use challenge.
   Ask what would falsify it, what observable evidence would differ from simpler
   explanations, and whether reporting intensity is being confused with base
   rate."""

EXECUTION_RULES = """Execution rules:
- validate_safety: explicitly acknowledge the legitimacy or risk of what they
  said before pushing on it.
- amplify: name the good insight they already have, then extend it one level.
- reframe: give a concrete alternate representation, not a lecture about the old
  one.
- anchor: provide one durable principle or analogy and apply it to their case.
- challenge: ask a precise question that forces a causal or evidentiary test.
- let_fail: do not rescue immediately; define the bounded consequence.
- back_off: summarize and reduce pressure.
- summarize_win: name the movement they just made.
- reflection: ask them to articulate their own model, but give enough context
  that the question is useful.
- direct_answer: answer plainly, then point at the underlying principle."""


def _dialog_text(dialogue: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"[{role}]: {text}" for role, text in dialogue)


def _canonical_hint(dialogue: list[tuple[str, str]]) -> dict[str, str] | None:
    """Seed router from the first six hand-labeled teaching episodes.

    This is intentionally small and explicit. It gives the planner a strong
    prior for patterns where the right move is not challenge.
    """
    if not dialogue:
        return None
    text = dialogue[-1][1].lower()

    if "not really" in text and "important" in text and ("could do" in text or "if necessary" in text):
        return {
            "intervention": "validate_safety",
            "reason": "learner is drifting into obligation; distinguish dependency from ownership",
            "target": "help them separate understanding a dependency from owning unwanted work",
        }
    if ("dsl" in text or "one-shot" in text or "oneshot" in text) and (
        "integration" in text or "fixture" in text or "deterministic" in text
    ):
        return {
            "intervention": "amplify",
            "reason": "learner is already discovering a better abstraction; extend it rather than attack it",
            "target": "show that AI lets us reshape the problem into something more direct, deterministic, and testable",
        }
    if "license number" in text or ("state machine" in text and "pipeline" in text):
        return {
            "intervention": "reframe",
            "reason": "learner is trapped in an abstraction that likely creates unnecessary machinery",
            "target": "replace state-machine thinking with a bucket/assembly-line/content-addressable representation",
        }
    if "not anti-ai" in text and ("merged without approval" in text or "endpoint" in text):
        return {
            "intervention": "validate_safety",
            "reason": "learner is raising a politically risky concern before discussing system controls",
            "target": "make the concern safe, then shift from AI fear to ownership and review boundaries",
        }
    if "metric" in text and "search" in text:
        return {
            "intervention": "anchor",
            "reason": "learner is asking for a metric in a messy system; teach legibility, Goodhart, causality",
            "target": "teach metrics as lossy indicators rather than truth",
        }
    if "podcast" in text and ("breach" in text or "mythos" in text):
        return {
            "intervention": "challenge",
            "reason": "learner is offering a compelling narrative with weak evidence",
            "target": "separate narrative plausibility from falsifiable evidence",
        }
    return None


def _parse_json(text: str) -> dict[str, Any]:
    """Best-effort JSON extraction from model output."""
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


class TeachAgent:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.client = anthropic.Anthropic(api_key=anthropic_api_key())
        self.model = model

    def _json_pass(self, instruction: str, payload: str) -> dict[str, Any]:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=900,
            temperature=0.2,
            system=instruction,
            messages=[{"role": "user", "content": payload}],
        )
        return _parse_json(resp.content[0].text)

    def _text_pass(self, system: str, payload: str, temperature: float) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": payload}],
        )
        return resp.content[0].text.strip()

    def _observe(
        self,
        dialogue: list[tuple[str, str]],
    ) -> dict[str, Any]:
        instruction = """You are the hidden psychological observer inside an
adult professional coach. Infer the learner state probabilistically from the
dialog only. Do not diagnose clinically. Do not invent facts.

Return JSON with:
- confidence: low|medium|high
- trust: low|medium|high
- agency: low|medium|high
- defensiveness: low|medium|high
- cognitive_load: low|medium|high
- pressure_tolerance: low|medium|high
- protecting: short phrase
- emerging_insight: short phrase or null
- sticking_points: array of short phrases
- needs: array chosen from safety, validation, challenge, reframe, anchor,
  reflection, directness, time, win, permission, experiment
- evidence: array of short observations grounded in the dialog

The goal is not to label the person. The goal is to estimate what they need
next in this conversation."""
        return self._json_pass(instruction, _dialog_text(dialogue))

    def _epistemic_gate(self, dialogue: list[tuple[str, str]]) -> dict[str, Any]:
        instruction = """You are the epistemic gate for an adult professional
coach. You receive only the current dialog, never the stored user profile.
Decide whether the learner's current claim contains a grounded error,
unsupported causal leap, false binary, or malformed framing that warrants
correction or challenge. Do not infer incompetence from style, brevity, or past
history. If the claim is plausible but under-specified, say no and ask for the
missing criterion instead.

Return JSON with:
- correction_warranted: true|false
- confidence: low|medium|high
- claim_under_test: short phrase
- reason: short grounded sentence
- safe_next_move: one of reflection, ask_for_criteria, challenge, reframe, direct_answer
"""
        return self._json_pass(instruction, _dialog_text(dialogue))

    def _plan(
        self,
        dialogue: list[tuple[str, str]],
        state: dict[str, Any],
        epistemic_gate: dict[str, Any],
        user_model: dict[str, Any] | None = None,
        session_summary: str = "",
    ) -> dict[str, Any]:
        hint = _canonical_hint(dialogue)
        instruction = f"""You are the hidden strategist for an adult professional
coach. Pick one highest-value target for the next turn. Do not try to fix every
problem. The learner should leave more able to think for themselves, not merely
with an answer.

Available intervention types:
- validate_safety: make it safe to state a risky concern or acknowledge a real
  emotion before applying pressure.
- amplify: strengthen an insight the learner is already discovering.
- reframe: replace a bad abstraction with a better representation.
- anchor: provide one durable principle, analogy, or invariant.
- challenge: interrogate an assumption, criterion, causal chain, or false axis.
- let_fail: allow a bounded mistake or exploration because the consequence is
  educational and reversible.
- back_off: reduce pressure, summarize, or give time when the learner is
  overloaded.
- summarize_win: name a useful movement so it consolidates.
- reflection: ask the learner to articulate their own model.
- direct_answer: answer directly when missing information is the bottleneck.

Return JSON with:
- target: one short sentence
- intervention: one of {list(INTERVENTIONS)}
- pressure: low|medium|high
- why_now: short sentence
- do_not_do: short sentence
- exit_condition: short sentence

Do not choose challenge by default. If the learner is already circling a good
insight, prefer amplify or anchor. If the learner is taking social or political
risk, prefer validate_safety before challenge.
The user profile may calibrate pressure and examples, but it may not determine
whether the learner is wrong. Only the EPISTEMIC GATE may justify challenge
because of a claim error. Delivery feedback can change phrasing, pacing, or
example type; it cannot suppress a correction that the gate says is warranted.

{CANONICAL_PATTERNS}"""
        hint_text = json.dumps(hint) if hint else "none"
        payload = (
            f"CANONICAL CUE ROUTER:\n{hint_text}\n\nSTATE:\n{json.dumps(state)}\n\n"
            f"EPISTEMIC GATE:\n{json.dumps(epistemic_gate)}\n\n"
            f"USER MODEL (hypothesis only):\n{json.dumps(user_model or {})}\n\n"
            f"SESSION SUMMARY:\n{session_summary}\n\nDIALOG:\n{_dialog_text(dialogue)}"
        )
        plan = self._json_pass(instruction, payload)
        if hint and hint["intervention"] in INTERVENTIONS:
            plan["intervention"] = hint["intervention"]
            plan["why_now"] = hint["reason"]
            if hint.get("target"):
                plan["target"] = hint["target"]
        if (
            plan.get("intervention") == "challenge"
            and not epistemic_gate.get("correction_warranted")
        ):
            safe_move = epistemic_gate.get("safe_next_move", "reflection")
            plan["intervention"] = safe_move if safe_move in INTERVENTIONS else "reflection"
            plan["pressure"] = "medium"
            plan["why_now"] = "The current claim is under-specified rather than grounded-wrong; ask for the missing criterion."
            plan["target"] = "make the learner articulate the criterion or causal chain before challenging it"
            plan["do_not_do"] = "do not treat prior user patterns as evidence that this claim is wrong"
            plan["exit_condition"] = "the learner states a falsifiable criterion, boundary, or concrete mechanism"
        mismatch = detect_pressure_mismatch(dialogue)
        if mismatch:
            plan["intervention"] = "back_off"
            plan["pressure"] = "low"
            plan["why_now"] = f"Current-session mismatch: {mismatch}"
            plan["target"] = "reduce pressure, summarize the current insight, and give the learner room to continue"
            plan["do_not_do"] = "do not pile on more questions or force a conclusion"
            plan["exit_condition"] = "the learner re-engages with a concrete attempt or asks a specific question"
        return plan

    def _draft(
        self,
        dialogue: list[tuple[str, str]],
        state: dict[str, Any],
        plan: dict[str, Any],
        epistemic_gate: dict[str, Any],
        register_mode: str,
        temperature: float,
        user_model: dict[str, Any] | None = None,
        session_summary: str = "",
    ) -> str:
        register = SAILOR_REGISTER if register_mode == "sailor" else PROFESSIONAL_REGISTER
        system = f"""You are Jeremy McEntire in teach mode. You are coaching an
adult professional to think better, not solving their problem for them.

{register}

Use the selected intervention, but do not mention the intervention name, hidden
state, or internal planner. Keep one coherent voice. Be concrete. Prefer a
worked example, causal chain, counterexample, or better abstraction over generic
advice. Do not default to enterprise best practices. Do not reward jargon.
Sometimes answer directly, but only when missing information is the bottleneck.
Leave the learner agency and room to think.

Selected plan:
{json.dumps(plan)}

Observed state:
{json.dumps(state)}

Epistemic gate from current dialog only:
{json.dumps(epistemic_gate)}

Known user model, used only to calibrate pressure and examples:
{json.dumps(user_model or {})}

Session summary:
{session_summary}

{EXECUTION_RULES}
"""
        payload = f"Current dialog:\n\n{_dialog_text(dialogue)}\n\n[Jeremy McEntire]: "
        return self._text_pass(system, payload, temperature)

    def _audit(
        self,
        dialogue: list[tuple[str, str]],
        state: dict[str, Any],
        plan: dict[str, Any],
        draft: str,
    ) -> dict[str, Any]:
        instruction = """You are the hidden adversarial auditor for a teaching
response. Check whether the draft:
- answered too early or removed useful struggle
- used generic advice instead of the learner's actual situation
- picked the wrong axis or missed the load-bearing constraint
- applied too much or too little pressure
- ignored an emerging insight that should be amplified
- failed to leave agency or a plausible next step

Intervention-specific checks:
- If plan.intervention is reframe, the draft must offer a concrete alternate
  representation before asking diagnostic questions.
- If plan.intervention is amplify, the draft must name and extend the learner's
  insight before introducing risk or failure modes.
- If plan.intervention is validate_safety, the first sentence must make the
  concern, risk, or emotional reality legitimate before challenging it.
- If plan.intervention is anchor, the draft must provide one durable principle
  or analogy, not only questions.

Return JSON with:
- verdict: pass|revise
- reasons: array of short grounded reasons
- revision_directives: array of short instructions if revise, else []

Be strict, but do not demand revision merely because the answer could be longer."""
        payload = (
            f"STATE:\n{json.dumps(state)}\n\nPLAN:\n{json.dumps(plan)}\n\n"
            f"DIALOG:\n{_dialog_text(dialogue)}\n\nDRAFT:\n{draft}"
        )
        return self._json_pass(instruction, payload)

    def _revise(
        self,
        dialogue: list[tuple[str, str]],
        state: dict[str, Any],
        plan: dict[str, Any],
        draft: str,
        audit: dict[str, Any],
        register_mode: str,
        temperature: float,
    ) -> str:
        register = SAILOR_REGISTER if register_mode == "sailor" else PROFESSIONAL_REGISTER
        system = f"""You are Jeremy McEntire in teach mode. Revise the draft
using the auditor's directives. Keep the response concise, concrete, and in one
coherent voice.

{register}

Do not reveal the audit or internal roles. Do not add generic teaching language.
Preserve learner agency.
"""
        payload = (
            f"STATE:\n{json.dumps(state)}\n\nPLAN:\n{json.dumps(plan)}\n\n"
            f"DIALOG:\n{_dialog_text(dialogue)}\n\nDRAFT:\n{draft}\n\n"
            f"AUDIT:\n{json.dumps(audit)}\n\n[Jeremy McEntire]: "
        )
        return self._text_pass(system, payload, temperature)

    def utterance(
        self,
        dialogue: list[tuple[str, str]],
        temperature: float = 0.7,
        register_mode: str = "professional",
        user_model: dict[str, Any] | None = None,
        session_summary: str = "",
    ) -> dict[str, Any]:
        state = self._observe(dialogue)
        epistemic_gate = self._epistemic_gate(dialogue)
        plan = self._plan(
            dialogue,
            state,
            epistemic_gate,
            user_model=user_model,
            session_summary=session_summary,
        )
        draft = self._draft(
            dialogue,
            state,
            plan,
            epistemic_gate,
            register_mode,
            temperature,
            user_model=user_model,
            session_summary=session_summary,
        )
        audit = self._audit(dialogue, state, plan, draft)
        text = draft
        if audit.get("verdict") == "revise":
            text = self._revise(
                dialogue,
                state,
                plan,
                draft,
                audit,
                register_mode,
                temperature,
            )
        return {
            "text": text,
            "agent": "teach",
            "phase": "TEACH",
            "mode": plan.get("intervention", "unknown"),
            "mode_reason": plan.get("why_now", ""),
            "register": register_mode,
            "state": state,
            "epistemic_gate": epistemic_gate,
            "plan": plan,
            "audit": audit,
        }
