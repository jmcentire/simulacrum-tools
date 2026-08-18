---
name: simulacrum
description: Run an idea, plan, claim, draft, or question past the Jeremy-simulacrum for Jeremy-style engagement. Use proactively when forming a categorical claim, locking in a frame, asserting a criterion, drafting a pitch, or asking "what would Jeremy think." A classifier dispatches each turn between a generalist branch (autobiographical/factual recall, optional) and a specialist branch (content generation, critique, suggestion, adversarial framing, multi-turn continuation). Returns substantive moves — refuses malformed premises, demands criteria, produces concrete worked examples, drafts and revises content.
disable-model-invocation: false
argument-hint: "<your idea/claim/question>"
---

# /simulacrum — Run ideas past the Jeremy-simulacrum

Local CLI wrapper. Two-phase dispatch: a classifier routes each turn to either the recall branch (OpenAI fine-tune; optional) or the content/adversarial branch (Anthropic claude-sonnet-4-6).

## How to invoke

Single-turn (most common):

```bash
./run.py "Every team needs a strong manager."
echo "Code quality means readable, working, deployable code." | ./run.py
```

Multi-turn dialog — save prior turns as JSON, pass via `--history`:

```bash
echo '[["Interlocutor","Initial claim"],["Jeremy","First pushback"]]' > /tmp/dialog.json
./run.py --history /tmp/dialog.json "Their counter-claim"
```

Or stream history from stdin:

```bash
cat dialog.json | ./run.py --history-stdin "Follow-up question"
```

## What you get back

Plain text on stdout — the simulacrum's response. May be:
- Terse ("I reject your premise." / "What does X mean here?")
- Substantive demolition of a flawed framing
- Direct engagement when the question is well-formed

If the input is genuinely well-formed, the simulacrum engages directly rather than force-pushing back. The contrarian mode is selective.

## When to use

- About to assert a categorical claim. Run it past first.
- Have a draft argument and want the strongest counter.
- Locking in a frame and want verification it isn't malformed.
- Stress-testing a definition or criterion before committing.
- Architecture review — the simulacrum demands the constraint envelope before critiquing.

## When NOT to use

- Direct factual recall about Jeremy's projects (without the generalist branch configured) — the specialist alone may give Jeremy-shaped but not factually accurate answers. Configure the generalist (see Configuration) or check primary sources.
- Casual / social conversation.
- When you want a *measured / polite* second opinion — the simulacrum is sharp by design.

## Configuration

Anthropic API key lookup (first non-empty value wins):

1. `WANDER_ANTHROPIC_API_KEY` (preferred billing account)
2. `SIM_ANTHROPIC_API_KEY`
3. `ANTHROPIC_API_KEY`
4. `JMC_ANTHROPIC_API_KEY`

The classifier and specialist default to `claude-sonnet-4-6`. Override both
with `SIMULACRUM_MODEL`, or one with `SIMULACRUM_CLASSIFIER_MODEL` and
`SIMULACRUM_SPECIALIST_MODEL`.

Optional env vars (enables the generalist branch — better autobiographical recall):

- `OPENAI_API_KEY` — for the fine-tune call
- `GENERALIST_MODEL` — fine-tune model ID, e.g. `ft:gpt-4o-mini-2024-07-18:personal:my-simulacrum:abc123`

Data file lookup (first match wins):

1. `$SIMULACRUM_DATA` env var
2. `./adversarial_pairs_annotated.json` alongside `run.py`
3. `../fly/data/adversarial_pairs_annotated.json` (sibling of the `skill/` directory in this repo)

## Diagnostics

By default the dispatch decision is written to stderr (e.g. `[phase=SPECIALIST agent=v9.1 mode=A]`) so callers can see which branch fired. Pass `--quiet` to suppress.

## Cost

~$0.02–$0.03 per invocation: 1 Anthropic classifier call + 1 agent call (Anthropic for SPECIALIST or OpenAI fine-tune for GENERALIST). Anthropic prompt caching is not yet wired in this CLI; see `fly/agents/specialist.py` in this repo for an example with caching enabled.

## Customizing for a different subject

This skill ships configured for Jeremy McEntire. To repoint at a different person:

1. Replace `adversarial_pairs_annotated.json` with annotated Q/A pairs in your subject's voice (see `PRIMER.md` at the repo root for the recipe).
2. Edit `SPECIALIST_TEMPLATE` and `GENERALIST_PROMPT` in `run.py` to substitute the subject's name, bio, and project glossary.
3. Optionally fine-tune a small OpenAI model on autobiographical Q/A pairs in your subject's voice and set `GENERALIST_MODEL`.
