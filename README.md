# Simulacrum

A cognitive simulacrum of [Jeremy McEntire](https://perardua.dev) — an AI agent that thinks like Jeremy on novel situations, not just writes like him on familiar ones.

> A simulacrum is a model of someone's *cognitive moves* — the specific patterns of thought they apply to novel situations. It is NOT a style-transfer of their writing voice. The two get conflated; they are not the same problem.

## What this repo contains

- **`fly/`** — a deployable FastAPI service. Run it on Fly.io (or anywhere that runs Python) and chat with the simulacrum through a web UI. HMAC-cookie auth, light/dark theme, "tuned" vs "spicy" register toggle, two-phase classifier dispatch.
- **`skill/`** — a local CLI wrapper (`run.py`) that wraps the same logic for command-line / pipe-into / agent-tool use. Designed to drop into [Claude Code skills](https://docs.claude.com/en/docs/claude-code/skills).
- **`PRIMER.md`** — recipe for building a simulacrum like this for a different subject. Worked-through advice from 8 architectural iterations, including what works (annotated few-shot, two-phase dispatch) and what doesn't (graph retrieval, multi-substrate ensembles, behavior dispatchers).

## How it works (brief)

Two-phase dispatch:

1. **Classifier** (Anthropic claude-sonnet-4-5) labels each turn as GENERALIST (purely autobiographical/factual recall) or SPECIALIST (everything else — opinion, suggestion, drafting, critique, adversarial framing, multi-turn continuation).
2. **Dispatch:**
   - GENERALIST → fine-tuned OpenAI model (optional; only fires if `GENERALIST_MODEL` is configured)
   - SPECIALIST → Anthropic claude-sonnet-4-5 + 11 annotated few-shot pairs + a Mode-A operationalized-criterion sub-classifier

The system prompt also carries two load-bearing meta-rules: **assumption-interrogation** (before applying conventional advice, identify the assumption it depends on and check whether it holds in this context) and **architecture-review posture** (when reviewing existing systems, identify the constraint envelope first; demand it if missing; don't alternative-shop).

The specialist alone (no fine-tune) handles the bulk of useful conversations. The generalist branch is purely a recall accelerator for autobiographical questions.

## Quick start (local CLI)

```bash
git clone https://github.com/jmcentire/simulacrum.git
cd simulacrum/skill
ln -s ../fly/data/adversarial_pairs_annotated.json .
pip install anthropic openai
export ANTHROPIC_API_KEY=sk-ant-...
./run.py "Every team needs a strong manager."
```

## Quick start (Fly deployment)

```bash
cd simulacrum/fly
fly launch --no-deploy --copy-config        # rename the app — pick something unique
fly secrets set ANTHROPIC_API_KEY=sk-ant-...
fly secrets set ALLOWED_USERNAME=your-username
fly secrets set SIMULACRUM_TOKEN=$(openssl rand -hex 32)
fly deploy
```

Visit `https://<your-app>.fly.dev/`, log in with the username you configured, chat.

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

- Stanford's [generative-agents](https://github.com/joonspk-research/generative_agents) (Park et al. 2023) — the starting architecture, since outgrown but credit where due.
- Anthropic's claude-sonnet-4-5 — the substrate that made the annotated-few-shot approach work.
- The conversation with Claude (Anthropic) that built this iteration. The 11 canonical pairs are the artifact of that work.
