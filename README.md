# Simulacrum

A cognitive simulacrum of [Jeremy McEntire](https://perardua.dev) — an AI agent that thinks like Jeremy on novel situations, not just writes like him on familiar ones.

> A simulacrum is a model of someone's *cognitive moves* — the specific patterns of thought they apply to novel situations. It is NOT a style-transfer of their writing voice. The two get conflated; they are not the same problem.

**Live demo:** [simulacrum.tools](https://simulacrum.tools)
**Docs:** [jmcentire.github.io/simulacrum](https://jmcentire.github.io/simulacrum)

## What this repo contains

- **`fly/`** — a deployable FastAPI service. Run it on Fly.io (or anywhere that runs Python) and chat with the simulacrum through a web UI. Invite-code signup plus magic-link sessions, cookie-based rate limiting, optional Cloudflare Turnstile invisible bot-check, light/dark theme, review vs teach mode, professional vs sailor register toggle, two-phase classifier dispatch, and an authenticated management simulator.
- **`skill/`** — a local CLI wrapper (`run.py`) that wraps the same logic for command-line / pipe-into / agent-tool use. Designed to drop into [Claude Code skills](https://docs.claude.com/en/docs/claude-code/skills).
- **`skills/get-advice/`** — a Claude Code plugin skill that packages the specialist-mode Jeremy prompt directly, so Claude can invoke `/simulacrum:get-advice` without the local CLI wrapper.
- **`PRIMER.md`** — recipe for building a simulacrum like this for a different subject. Worked-through advice from 8 architectural iterations, including what works (annotated few-shot, two-phase dispatch) and what doesn't (graph retrieval, multi-substrate ensembles, behavior dispatchers).

## How it works (brief)

Two-phase dispatch:

1. **Classifier** (Anthropic claude-sonnet-4-6) labels each turn as GENERALIST (purely autobiographical/factual recall) or SPECIALIST (everything else — opinion, suggestion, drafting, critique, adversarial framing, multi-turn continuation).
2. **Dispatch:**
   - GENERALIST → fine-tuned OpenAI model (optional; only fires if `GENERALIST_MODEL` is configured)
   - SPECIALIST → Anthropic claude-sonnet-4-6 + 11 annotated few-shot pairs + a Mode-A operationalized-criterion sub-classifier

The system prompt also carries two load-bearing meta-rules: **assumption-interrogation** (before applying conventional advice, identify the assumption it depends on and check whether it holds in this context) and **architecture-review posture** (when reviewing existing systems, identify the constraint envelope first; demand it if missing; don't alternative-shop).

The specialist alone (no fine-tune) handles the bulk of useful conversations. The generalist branch is purely a recall accelerator for autobiographical questions.

## Access and anti-abuse posture

The deployment is invite-only. Users sign up with a one-time code, then verify
every browser session with a magic link. Defenses are layered:

1. **Cookie-based 20-message rolling 24h cap** — HMAC-signed cookie carries timestamps; server reads/updates per request; no server-side state. Cleared cookies just bump the user to the next layer.
2. **Cloudflare Turnstile (invisible)** — server-side token verification on every `/chat` call. Activated by setting `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET` env vars; skipped silently if unset (local dev).
3. **Cloudflare edge** (recommended in front) — Bot Fight Mode, per-IP rate limiting, DDoS absorption.
4. **Provider-side budget cap** — set a daily spend cap on your Anthropic key in the Anthropic console. The ultimate floor.

Generate more one-time invite codes with:

```bash
python3 scripts/generate_signup_codes.py --count 10 --sync-fly
```

The script appends raw codes to the gitignored `signup_codes.txt` file and
updates the Fly `SIGNUP_CODES` secret. The app stores only hashed codes in
SQLite, so issued codes remain one-time use.

## Quick start (local CLI)

```bash
git clone https://github.com/jmcentire/simulacrum-tools.git
cd simulacrum/skill
ln -s ../fly/data/adversarial_pairs_annotated.json .
pip install anthropic openai
export WANDER_ANTHROPIC_API_KEY=sk-ant-...  # preferred when available
# Portable fallback: export ANTHROPIC_API_KEY=sk-ant-...
./run.py "Every team needs a strong manager."
```

## Quick start (Claude Code plugin)

```bash
git clone https://github.com/jmcentire/simulacrum-tools.git
claude --plugin-dir ./simulacrum
```

Then invoke `/simulacrum:get-advice` with an idea, plan, claim, draft, or architecture question.

## Quick start (Fly deployment)

```bash
cd simulacrum/fly
fly launch --no-deploy --copy-config        # rename the app — pick something unique
fly secrets set WANDER_ANTHROPIC_API_KEY="$WANDER_ANTHROPIC_API_KEY"
fly secrets set SIMULACRUM_TOKEN=$(openssl rand -hex 32)
# Optional — enable invisible Turnstile bot-check:
fly secrets set TURNSTILE_SITE_KEY=0x4...
fly secrets set TURNSTILE_SECRET=0x4...
# Optional — enable the fine-tuned generalist branch:
fly secrets set OPENAI_API_KEY=sk-...
fly secrets set GENERALIST_MODEL=ft:gpt-4o-mini-...
fly deploy
```

Visit `https://<your-app>.fly.dev/`, sign in, then use chat or the management
simulator. Per-browser cap is 20 messages per rolling 24 hours.

## Customizing for a different subject

This is configured as Jeremy's simulacrum. To build one for someone else:

1. Read `PRIMER.md` end to end. Skip nothing.
2. Source a corpus of the subject's *adversarial dialog* — moments where they refused, demolished, or derived. Skip their casual / polite / fiction content.
3. Identify their cognitive move taxonomy by reading the corpus.
4. Generate ~25 net-new probe questions across recall / position / disposition / adversarial dimensions. Have the subject answer them themselves — that's gold-standard.
5. Annotate 5-10 canonical Q/A pairs with the WHY structure (what was the flaw, what move was applied, what general pattern). Replace `fly/data/adversarial_pairs_annotated.json`.
6. Edit `fly/agents/specialist.py` and `fly/agents/generalist.py` to swap the subject's name, bio, and project glossary.
7. Score against the held-out 25. Iterate where the system regresses.

## What's in the data

`fly/data/adversarial_pairs_annotated.json` ships with 11 hand-curated Q/A pairs (5 from a Claude Web conversation about AI/manipulation, 6 from the conversation that built this repo). Each pair is annotated with the cognitive move it teaches. No raw transcripts, no auto-mined extracts, no PII for collaborators.

## License

MIT. See `LICENSE`.

## Acknowledgments

- Park et al. 2024, [*Generative Agent Simulations of 1,000 People*](https://arxiv.org/abs/2411.10109) — the architecture this implementation is closest to.
- Park et al. 2023, [*Generative Agents: Interactive Simulacra of Human Behavior*](https://arxiv.org/abs/2304.03442) — the prior Smallville paper; the conceptual foundation.
- Anthropic's claude-sonnet-4-6 — the current substrate for the annotated-few-shot approach.
- The conversation with Claude (Anthropic) that built this iteration. The 11 canonical pairs are the artifact of that work.
