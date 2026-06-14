# Simulacrum — Fly.io deployment

FastAPI service exposing Simulacrum via a web UI plus an authenticated
management simulation module.

## Setup

```bash
fly launch --no-deploy --copy-config         # rename the app — pick something unique
fly secrets set ANTHROPIC_API_KEY=sk-ant-...
fly secrets set SIMULACRUM_TOKEN=$(openssl rand -hex 32)   # session HMAC key
fly secrets set RESEND_API_KEY=re_...
fly secrets set RESEND_FROM="Simulacrum <onboarding@your-domain>"
fly secrets set APP_BASE_URL=https://simulacrum.tools
fly secrets set SIGNUP_CODES="CODE-ONE,CODE-TWO,CODE-THREE"
fly secrets set SIMULACRUM_DB=/data/simulacrum.db

# Optional — enables the generalist branch (better autobiographical recall):
fly secrets set OPENAI_API_KEY=sk-proj-...
fly secrets set GENERALIST_MODEL=ft:gpt-4o-mini-2024-07-18:personal:my-simulacrum:abc123

# Create and mount persistent SQLite storage once:
fly volumes create simulacrum_data --region iad --size 1
fly volumes mount simulacrum_data /data

fly deploy
```

Without `OPENAI_API_KEY` + `GENERALIST_MODEL`, the dispatcher routes everything to the specialist. Still works; weaker on pure autobiographical recall.

## Endpoints

| Path | Method | Auth | Purpose |
|---|---|---|---|
| `/` | GET | session | Redirect to simulator |
| `/sign-in` | GET / POST | none | Magic-link sign-in |
| `/sign-up` | GET / POST | invite code | One-time-code signup |
| `/logout` | GET | cookie | Clear session cookie |
| `/chat` | POST | cookie | Send dialog, get response |
| `/register` | POST | cookie | Set professional/sailor register cookie |
| `/mode` | POST | cookie | Set review/teach chat mode |
| `/api/management-sim/*` | GET / POST | session | Management simulator |
| `/healthz` | GET | none | Health + config status |

## Register modes

The simulacrum ships with two register profiles, swappable per-user via UI toggle:

- **professional** (default): sharp without being mean. Profanity is escalation only — reserved for sustained bad-faith engagement. First responses are measured-but-rigorous.
- **sailor**: original v8 register. Profanity as default refusal posture. Some users want to argue with the bastard.

Both modes preserve the cognitive moves (assumption-interrogation, architecture-review posture, etc.). Only the *register* differs.

## Chat modes

- **review** (default): existing Sim behavior. Push back on malformed framing, bad assumptions, and generic advice.
- **teach**: hidden observer/planner/auditor loop for adult professional coaching. It chooses among validation, amplification, reframing, anchoring, challenge, reflection, direct answers, and backing off based on the learner's current state.

## Observability

The chat response includes diagnostic fields: `phase` (GENERALIST/SPECIALIST/TEACH), `agent` (specialist/generalist/teach), `mode` (Mode-A / DEFAULT for review, intervention type for teach), `register` (current register profile).

`/healthz` returns the generalist's configured/disabled state.

## Cost

- Specialist call: ~10K input tokens (prompt) + ~1K output. Anthropic prompt caching reduces input cost ~90% on warm cache (5-min TTL).
- Generalist call: ~1K input + ~500 output (fine-tuned gpt-4o-mini).
- Classifier call: ~500 input + 100 output (Anthropic claude-sonnet-4-5).

Per-turn cost: roughly $0.015 cold, $0.005 warm.

## Layout

```
fly/
├── Dockerfile
├── fly.toml                  # rename `app = ...` before deploying
├── requirements.txt
├── app.py                    # FastAPI service
├── agents/
│   ├── dispatcher.py         # phase classifier + routing
│   ├── specialist.py         # Anthropic + annotated few-shot + Mode-A
│   ├── generalist.py         # OpenAI fine-tune (optional)
│   └── teach.py              # observer -> planner -> draft -> audit loop
├── management_sim/           # authenticated management simulation module
├── data/
│   └── adversarial_pairs_annotated.json    # 11 canonical few-shot pairs
└── static/
    └── index.html            # chat UI
```
