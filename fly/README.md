# Simulacrum — Fly.io deployment

FastAPI service exposing Simulacrum via a web UI plus an authenticated
management simulation module.

## Setup

```bash
fly launch --no-deploy --copy-config         # rename the app — pick something unique
fly secrets set WANDER_ANTHROPIC_API_KEY="$WANDER_ANTHROPIC_API_KEY"
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

Anthropic clients use the first non-empty key from
`WANDER_ANTHROPIC_API_KEY`, `SIM_ANTHROPIC_API_KEY`, `ANTHROPIC_API_KEY`, and
`JMC_ANTHROPIC_API_KEY`. The Wander key is therefore the billing source when
it is configured, while the generic name remains a portable fallback.

## Endpoints

| Path | Method | Auth | Purpose |
|---|---|---|---|
| `/` | GET | none / session | Product landing page, or redirect signed-in users to Review |
| `/chat-ui` | GET | session | Review / Teach chat workspace |
| `/sign-in` | GET / POST | none | Magic-link sign-in |
| `/sign-up` | GET / POST | invite code | One-time-code signup |
| `/logout` | GET | cookie | Clear session cookie |
| `/chat` | POST | cookie or API key | Send dialog, get response |
| `/register` | POST | cookie | Set professional/sailor register cookie |
| `/mode` | POST | cookie | Set review/teach chat mode |
| `/api/management-sim/*` | GET / POST | session | Management simulator |
| `/api/me` | GET | cookie or API key | Current identity (+ remaining API quota) |
| `/healthz` | GET | none | Health + config status |

### API access

Headless clients authenticate with an API key via `X-API-Key: <key>` or
`Authorization: Bearer <key>` — no cookies, Turnstile, or magic links. Keys are
per-user, HMAC-hashed at rest, and capped server-side at `API_CAP_PER_WINDOW`
requests per rolling 24h (default 200; per-key override at mint time). Mint on
the production machine so the hash uses the live `SIMULACRUM_TOKEN`:

```bash
fly ssh console -a simulacrum-jmc -C \
  "python3 /app/scripts/generate_api_key.py partner@example.com --label partner"
```

```bash
curl -s -X POST https://simulacrum-jmc.fly.dev/chat \
  -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"dialog":[{"role":"user","text":"..."}]}'
```

Pass the returned `session_id` back in subsequent requests to continue a
conversation. `--list` and `--revoke KEY_ID` manage existing keys.

Optional body fields `register` (`professional` | `sailor`) and `mode`
(`review` | `teach`) select the register and chat mode per request — they
override the browser cookies, which API clients don't carry. The response
echoes the applied `register`. Note the response's `mode` field (`A` /
`DEFAULT`) is the specialist's per-turn classifier verdict, not a setting:
adversarial engagement is elicited by the input's framing, not requested.

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
- Classifier call: ~500 input + 100 output (Anthropic claude-sonnet-4-6).

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
