"""Two-phase simulacrum deployment: FastAPI service.

The /chat endpoint dispatches each turn between two agents:
  GENERALIST → fine-tuned model for direct-recall, autobiographical,
               well-formed-direct questions (optional — only fires if
               GENERALIST_MODEL env var is set)
  SPECIALIST → Anthropic claude-sonnet-4-5 + annotated few-shot pairs
               for adversarial framings, content generation, suggestions,
               critique, multi-turn continuation

Open access (no login). Anti-abuse layered:
  1. Cookie-based rolling-24h message counter (HMAC-signed, no server state).
  2. Cloudflare Turnstile token verification (when TURNSTILE_SECRET is set).
  3. (Recommended) Cloudflare edge in front: proxied DNS, Bot Fight Mode, per-IP rate-limit rule.
  4. (Recommended) Provider-side daily budget cap on API keys.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Cookie, FastAPI, Form, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents.dispatcher import Dispatcher
from agents.generalist import is_configured as generalist_configured

ROOT = Path(__file__).parent
STATIC = ROOT / "static"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
SECRET_KEY = os.environ.get("SIMULACRUM_TOKEN") or secrets.token_hex(32)
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET")
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")

COUNTER_COOKIE = "simulacrum_counter"
SPICE_COOKIE = "simulacrum_spice"
WINDOW_SECONDS = 24 * 3600
CAP_PER_WINDOW = int(os.environ.get("CAP_PER_WINDOW", "20"))

if not ANTHROPIC_API_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY env var required (specialist + classifier)")

dispatcher = Dispatcher()
print(f"dispatcher loaded — generalist={'enabled' if generalist_configured() else 'disabled (specialist-only)'}")


# ---- Rolling-24h counter (HMAC-signed cookie, no server storage) ----

def _sign(payload: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _read_counter(cookie: Optional[str]) -> list[int]:
    """Parse and verify the counter cookie. Returns a list of unix timestamps
    within the last WINDOW_SECONDS. Returns [] if missing or invalid."""
    if not cookie:
        return []
    try:
        payload, sig = cookie.rsplit("|", 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return []
        if not payload:
            return []
        timestamps = [int(x) for x in payload.split(",") if x]
    except (ValueError, AttributeError):
        return []
    cutoff = int(time.time()) - WINDOW_SECONDS
    return [t for t in timestamps if t >= cutoff]


def _write_counter(timestamps: list[int]) -> str:
    payload = ",".join(str(t) for t in timestamps[-CAP_PER_WINDOW:])
    return f"{payload}|{_sign(payload)}"


async def _verify_turnstile(token: Optional[str], remote_ip: Optional[str]) -> bool:
    """Verify a Cloudflare Turnstile token. If TURNSTILE_SECRET is unset, skip
    verification and return True (local-dev / no-Turnstile mode)."""
    if not TURNSTILE_SECRET:
        return True
    if not token:
        return False
    data = {"secret": TURNSTILE_SECRET, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data=data,
            )
        return bool(r.json().get("success"))
    except Exception:
        return False


# ---- HTTP API ----

app = FastAPI(title="Simulacrum", version="1.0")


class DialogTurn(BaseModel):
    role: str
    text: str


class ChatRequest(BaseModel):
    dialog: list[DialogTurn]
    turnstile_token: Optional[str] = None
    temperature: float = 0.7


class ChatResponse(BaseModel):
    response: str
    agent: str
    phase: str
    mode: Optional[str] = None
    remaining: int


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/privacy")
async def privacy():
    return FileResponse(STATIC / "privacy.html")


@app.get("/terms")
async def terms():
    return FileResponse(STATIC / "terms.html")


@app.post("/chat")
async def chat(req: ChatRequest,
               simulacrum_counter: Optional[str] = Cookie(None),
               simulacrum_spice: Optional[str] = Cookie(None),
               cf_connecting_ip: Optional[str] = Header(None, alias="CF-Connecting-IP")) -> JSONResponse:
    if not req.dialog:
        raise HTTPException(status_code=400, detail="empty dialog")

    timestamps = _read_counter(simulacrum_counter)
    if len(timestamps) >= CAP_PER_WINDOW:
        oldest = min(timestamps)
        reset_in = max(0, WINDOW_SECONDS - (int(time.time()) - oldest))
        raise HTTPException(
            status_code=429,
            detail=f"Daily message cap reached ({CAP_PER_WINDOW}). Try again in {reset_in // 3600}h {(reset_in % 3600) // 60}m.",
        )

    if not await _verify_turnstile(req.turnstile_token, cf_connecting_ip):
        raise HTTPException(status_code=403, detail="Bot check failed. Refresh and try again.")

    spice = "spicy" if simulacrum_spice == "spicy" else "tuned"
    dialogue = [(t.role, t.text) for t in req.dialog]
    out = dispatcher.utterance(dialogue, spice=spice)

    timestamps.append(int(time.time()))
    remaining = max(0, CAP_PER_WINDOW - len(timestamps))

    resp = JSONResponse(ChatResponse(
        response=out["text"],
        agent=out["agent"],
        phase=out["phase"],
        mode=out.get("mode"),
        remaining=remaining,
    ).model_dump())
    resp.set_cookie(
        COUNTER_COOKIE, _write_counter(timestamps),
        max_age=WINDOW_SECONDS, httponly=True, samesite="lax", secure=True,
    )
    return resp


@app.get("/config")
async def config():
    return {"turnstile_site_key": TURNSTILE_SITE_KEY, "cap_per_window": CAP_PER_WINDOW}


@app.get("/healthz")
async def healthz():
    return {
        "ok": True,
        "specialist": "anthropic-fewshot",
        "generalist": "configured" if generalist_configured() else "disabled",
        "spice_modes": ["tuned", "spicy"],
    }


@app.post("/spice")
async def set_spice(spice: str = Form(...)):
    if spice not in ("tuned", "spicy"):
        raise HTTPException(status_code=400, detail="spice must be 'tuned' or 'spicy'")
    resp = JSONResponse({"spice": spice})
    resp.set_cookie(
        SPICE_COOKIE, spice,
        max_age=365 * 24 * 3600, httponly=False, samesite="lax", secure=True,
    )
    return resp


app.mount("/static", StaticFiles(directory=STATIC), name="static")
