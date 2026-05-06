# Simulacrum — Fly.io deployment

FastAPI service exposing the simulacrum via a web UI. Two-phase classifier dispatch.

## Setup

```bash
fly launch --no-deploy --copy-config         # rename the app — pick something unique
fly secrets set ANTHROPIC_API_KEY=sk-ant-...
fly secrets set ALLOWED_USERNAME=your-username   # case-insensitive; whoever can log in
fly secrets set SIMULACRUM_TOKEN=$(openssl rand -hex 32)   # session HMAC key

# Optional — enables the generalist branch (better autobiographical recall):
fly secrets set OPENAI_API_KEY=sk-proj-...
fly secrets set GENERALIST_MODEL=ft:gpt-4o-mini-2024-07-18:personal:my-simulacrum:abc123

fly deploy
```

Without `OPENAI_API_KEY` + `GENERALIST_MODEL`, the dispatcher routes everything to the specialist. Still works; weaker on pure autobiographical recall.

## Endpoints

| Path | Method | Auth | Purpose |
|---|---|---|---|
| `/` | GET | cookie | UI |
| `/login` | GET / POST | none | Login form / submission |
| `/logout` | GET | cookie | Clear session cookie |
| `/chat` | POST | cookie | Send dialog, get response |
| `/spice` | POST | cookie | Set tuned/spicy register cookie |
| `/healthz` | GET | none | Health + config status |

## Spice modes

The simulacrum ships with two register profiles, swappable per-user via UI toggle:

- **tuned** (default): sharp without being mean. Profanity is escalation only — reserved for sustained bad-faith engagement. First responses are measured-but-rigorous.
- **spicy**: original v8 register. Profanity as default refusal posture. Some users want to argue with the bastard.

Both modes preserve the cognitive moves (assumption-interrogation, architecture-review posture, etc.). Only the *register* differs.

## Observability

The chat response includes diagnostic fields: `phase` (GENERALIST/SPECIALIST), `agent` (specialist/generalist), `mode` (Mode-A / DEFAULT for the specialist's sub-classifier), `spice` (current register profile).

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
│   └── generalist.py         # OpenAI fine-tune (optional)
├── data/
│   └── adversarial_pairs_annotated.json    # 11 canonical few-shot pairs
└── static/
    └── index.html            # chat UI
```
