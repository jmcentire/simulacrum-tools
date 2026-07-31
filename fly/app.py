"""Two-phase simulacrum deployment: FastAPI service.

The /chat endpoint dispatches each turn between two agents:
  GENERALIST → fine-tuned model for direct-recall, autobiographical,
               well-formed-direct questions (optional — only fires if
               GENERALIST_MODEL env var is set)
  SPECIALIST → Anthropic claude-sonnet-4-5 + annotated few-shot pairs
               for adversarial framings, content generation, suggestions,
               critique, multi-turn continuation

Authenticated access:
  1. Invite-code signup.
  2. Magic-link sign-in for every browser session.
  3. API keys (Authorization: Bearer / X-API-Key) for headless clients, with a
     server-side rolling-24h per-key cap. Mint via scripts/generate_api_key.py.
  4. Persistent SQLite storage for users, memories, simulation runs, and events.
  5. Cookie-based rolling-24h chat counter plus optional Turnstile (browser path).
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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents.dispatcher import Dispatcher
from agents.generalist import is_configured as generalist_configured
from agents.teach import TeachAgent
from agents.user_model import UserModelService, compact_profile
import auth
import chat_memory
import db
from engineer_scenarios import public_scenarios
from management_sim.router import router as management_sim_router

ROOT = Path(__file__).parent
STATIC = ROOT / "static"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
SECRET_KEY = os.environ.get("SIMULACRUM_TOKEN") or secrets.token_hex(32)
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET")
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")

COUNTER_COOKIE = "simulacrum_counter"
REGISTER_COOKIE = "simulacrum_register"
MODE_COOKIE = "simulacrum_mode"
CHAT_SESSION_COOKIE = "simulacrum_chat_session"
WINDOW_SECONDS = 24 * 3600
CAP_PER_WINDOW = int(os.environ.get("CAP_PER_WINDOW", "20"))
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") != "0"

if not ANTHROPIC_API_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY env var required (specialist + classifier)")

dispatcher = Dispatcher()
teach = TeachAgent()
user_model_service = UserModelService()
db.init_db()
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
app.include_router(management_sim_router)


class DialogTurn(BaseModel):
    role: str
    text: str


class ChatRequest(BaseModel):
    dialog: list[DialogTurn]
    session_id: Optional[str] = None
    turnstile_token: Optional[str] = None
    temperature: float = 0.7
    register: Optional[str] = None
    mode: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    agent: str
    phase: str
    mode: Optional[str] = None
    register: Optional[str] = None
    remaining: int
    session_id: str


def _current_user(session_token: Optional[str]) -> dict | None:
    return auth.current_user(session_token)


def _require_user(session_token: Optional[str]) -> dict:
    user = _current_user(session_token)
    if not user:
        raise HTTPException(status_code=401, detail="sign in required")
    return user


def _api_key_from_headers(authorization: Optional[str], x_api_key: Optional[str]) -> Optional[str]:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return (x_api_key or "").strip() or None


def _consume_api_key(raw_key: str) -> tuple[dict, int]:
    """Authenticate an API key and spend one request from its daily window."""
    try:
        keyed = auth.authenticate_api_key(raw_key)
    except auth.ApiKeyRateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail=f"API key daily cap reached. Try again in {exc.reset_in // 3600}h {(exc.reset_in % 3600) // 60}m.",
        )
    if not keyed:
        raise HTTPException(status_code=401, detail="invalid API key")
    return keyed


def _valid_register(value: Optional[str]) -> str:
    return value if value in ("professional", "sailor") else "professional"


def _valid_mode(value: Optional[str]) -> str:
    return value if value in ("review", "teach") else "review"


def _resolve_modes(req: "ChatRequest", cookie_register: Optional[str], cookie_mode: Optional[str]) -> tuple[str, str]:
    """Resolve register and chat mode: explicit request-body values win over
    cookies. Explicit invalid values are a client error, not a silent default."""
    if req.register is not None and req.register not in ("professional", "sailor"):
        raise HTTPException(status_code=400, detail="register must be 'professional' or 'sailor'")
    if req.mode is not None and req.mode not in ("review", "teach"):
        raise HTTPException(status_code=400, detail="mode must be 'review' or 'teach'")
    return (
        req.register or _valid_register(cookie_register),
        req.mode or _valid_mode(cookie_mode),
    )


def _dialog_from_turns(turns: list[dict]) -> list[tuple[str, str]]:
    return [
        ("Interlocutor" if turn["role"] == "user" else "Jeremy", turn["content"])
        for turn in turns
    ]


def _latest_user_text(req: ChatRequest) -> str:
    for turn in reversed(req.dialog):
        if turn.role.lower() in {"user", "interlocutor"}:
            return turn.text.strip()
    return ""


def _auth_page(title: str, body: str, message: str = "") -> HTMLResponse:
    return HTMLResponse(f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>{title} — Simulacrum</title>
        <style>
          body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:#1a1a1a; color:#e8e8e8; margin:0; }}
          main {{ max-width:520px; margin:80px auto; padding:28px; }}
          h1 {{ font-size:24px; font-weight:500; margin:0 0 8px; }}
          p {{ color:#a1a1aa; line-height:1.5; }}
          form {{ display:flex; flex-direction:column; gap:12px; margin-top:24px; }}
          input {{ background:#222; color:#e8e8e8; border:1px solid #444; border-radius:4px; padding:10px 12px; font:inherit; }}
          button {{ background:#ffb86c; color:#1a1a1a; border:0; border-radius:4px; padding:10px 12px; font:inherit; font-weight:700; cursor:pointer; }}
          .message {{ color:#ffb86c; font-size:13px; margin-top:12px; }}
          a {{ color:#6cb5ff; }}
        </style>
      </head>
      <body><main><h1>{title}</h1>{body}<p class="message">{message}</p></main></body>
    </html>
    """)


def _landing_page() -> HTMLResponse:
    return HTMLResponse("""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>Simulacrum</title>
        <style>
          body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:#1a1a1a; color:#e8e8e8; margin:0; }
          main { max-width:640px; margin:96px auto; padding:28px; }
          h1 { font-size:30px; font-weight:500; margin:0 0 16px; }
          p { color:#a1a1aa; line-height:1.65; font-size:16px; margin:0 0 16px; }
          .actions { margin-top:28px; display:flex; gap:12px; align-items:center; }
          a.button { background:#ffb86c; color:#1a1a1a; border-radius:4px; padding:10px 14px; font-weight:700; text-decoration:none; }
          a.contact { color:#6cb5ff; text-decoration:none; }
          a.contact:hover { text-decoration:underline; }
          .technical { margin-top:42px; padding-top:22px; border-top:1px solid #333; }
          .technical h2 { font-size:16px; font-weight:500; margin:0 0 10px; }
          .technical p { font-size:14px; line-height:1.6; margin-bottom:10px; }
          .links a { color:#6cb5ff; text-decoration:none; margin-right:10px; font-size:13px; }
          .links a:hover { text-decoration:underline; }
        </style>
      </head>
      <body><main>
        <h1>Simulacrum</h1>
        <p>Simulacrum provides software engineering architectural review, professional practice for engineers, and management simulation for software teams.</p>
        <p>It is designed to help practitioners examine assumptions, improve judgment, and understand the consequences of technical and managerial decisions.</p>
        <div class="actions">
          <a class="button" href="/sign-in">Sign in</a>
          <a class="contact" href="mailto:hello@simulacrum.tools">For access, contact hello@simulacrum.tools</a>
        </div>
        <div class="technical">
          <h2>A generative simulacrum.</h2>
          <p>Built on the architecture from Park et al.'s <em>Generative Agent Simulations of 1,000 People</em> (2024): a two-phase dispatcher routes each turn between a recall branch and an adversarial-dialog branch.</p>
          <p>Pitch an idea, propose a frame, claim something. Professional for sharp pushback when the framing has a flaw, and direct engagement when it does not.</p>
          <div class="links">
            <a href="https://arxiv.org/abs/2411.10109" target="_blank" rel="noopener">Paper</a>
            <a href="https://github.com/jmcentire/simulacrum" target="_blank" rel="noopener">Code</a>
            <a href="/privacy">Privacy</a>
            <a href="/terms">Terms</a>
          </div>
        </div>
      </main></body>
    </html>
    """)


@app.get("/")
async def index(simulacrum_session: Optional[str] = Cookie(None)):
    if not _current_user(simulacrum_session):
        return _landing_page()
    return RedirectResponse("/chat-ui")


@app.get("/chat-ui")
async def chat_ui(simulacrum_session: Optional[str] = Cookie(None)):
    if not _current_user(simulacrum_session):
        return RedirectResponse("/sign-in")
    return FileResponse(STATIC / "index.html")


@app.get("/simulator")
async def simulator_ui(simulacrum_session: Optional[str] = Cookie(None)):
    if not _current_user(simulacrum_session):
        return RedirectResponse("/sign-in")
    return FileResponse(STATIC / "simulator.html")


@app.get("/sign-in")
async def sign_in_page(simulacrum_session: Optional[str] = Cookie(None)):
    if _current_user(simulacrum_session):
        return RedirectResponse("/chat-ui")
    return _auth_page(
        "Sign in",
        """
        <p>Sign in with your email. Every browser session is verified by a magic link.</p>
        <form method="post" action="/sign-in">
          <input type="email" name="email" placeholder="you@example.com" required autofocus>
          <button type="submit">Send magic link</button>
        </form>
        <p>Need access? <a href="/sign-up">Create an account with an invite code</a>, or contact <a href="mailto:hello@simulacrum.tools">hello@simulacrum.tools</a>.</p>
        """,
    )


@app.post("/sign-in")
async def sign_in(email: str = Form(...)):
    try:
        await auth.request_signin(email)
        message = "If that email is registered, a magic link is on its way."
    except Exception:
        message = "We could not send the magic link. Try again in a moment."
    return _auth_page(
        "Check your email",
        "<p>We sent a sign-in link if the address is registered.</p><p><a href=\"/sign-in\">Back to sign in</a></p>",
        message,
    )


@app.get("/sign-up")
async def sign_up_page(simulacrum_session: Optional[str] = Cookie(None)):
    if _current_user(simulacrum_session):
        return RedirectResponse("/chat-ui")
    return _auth_page(
        "Sign up",
        """
        <p>Access is invite-only. Enter your email and a one-time code.</p>
        <form method="post" action="/sign-up">
          <input type="email" name="email" placeholder="you@example.com" required autofocus>
          <input type="text" name="code" placeholder="invite code" required>
          <button type="submit">Send verification link</button>
        </form>
        <p>Already registered? <a href="/sign-in">Sign in</a>.</p>
        """,
    )


@app.post("/sign-up")
async def sign_up(email: str = Form(...), code: str = Form(...)):
    try:
        ok = await auth.request_signup(email, code)
        message = "A verification link is on its way."
        if not ok:
            message = "That invite code is invalid, reserved, or already used."
    except Exception:
        message = "We could not send the verification link. Try again in a moment."
    return _auth_page(
        "Check your email",
        "<p>Complete sign-up from the magic link in your inbox.</p><p><a href=\"/sign-up\">Back to sign up</a></p>",
        message,
    )


@app.get("/auth/verify")
async def verify_magic_link(token: str):
    user, session_token = auth.redeem_magic_link(token)
    if not user or not session_token:
        return _auth_page(
            "Link expired",
            "<p>This link is invalid or expired.</p><p><a href=\"/sign-in\">Request a new link</a></p>",
        )
    response = RedirectResponse("/chat-ui")
    response.set_cookie(
        auth.SESSION_COOKIE,
        session_token,
        max_age=auth.session_cookie_max_age(),
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
    )
    return response


@app.get("/logout")
async def logout(simulacrum_session: Optional[str] = Cookie(None)):
    auth.revoke_session(simulacrum_session)
    response = RedirectResponse("/sign-in")
    response.delete_cookie(auth.SESSION_COOKIE)
    return response


@app.get("/privacy")
async def privacy():
    return FileResponse(STATIC / "privacy.html")


@app.get("/terms")
async def terms():
    return FileResponse(STATIC / "terms.html")


@app.post("/chat")
async def chat(req: ChatRequest,
               simulacrum_counter: Optional[str] = Cookie(None),
               simulacrum_register: Optional[str] = Cookie(None),
               simulacrum_mode: Optional[str] = Cookie(None),
               simulacrum_chat_session: Optional[str] = Cookie(None),
               simulacrum_session: Optional[str] = Cookie(None),
               cf_connecting_ip: Optional[str] = Header(None, alias="CF-Connecting-IP"),
               authorization: Optional[str] = Header(None),
               x_api_key: Optional[str] = Header(None, alias="X-API-Key")) -> JSONResponse:
    api_key = _api_key_from_headers(authorization, x_api_key)
    register_mode, chat_mode = _resolve_modes(req, simulacrum_register, simulacrum_mode)
    if not req.dialog:
        raise HTTPException(status_code=400, detail="empty dialog")
    api_remaining = 0
    if api_key:
        user, api_remaining = _consume_api_key(api_key)
    else:
        user = _require_user(simulacrum_session)

    timestamps = _read_counter(simulacrum_counter)
    if not api_key:
        if len(timestamps) >= CAP_PER_WINDOW:
            oldest = min(timestamps)
            reset_in = max(0, WINDOW_SECONDS - (int(time.time()) - oldest))
            raise HTTPException(
                status_code=429,
                detail=f"Daily message cap reached ({CAP_PER_WINDOW}). Try again in {reset_in // 3600}h {(reset_in % 3600) // 60}m.",
            )

        if not await _verify_turnstile(req.turnstile_token, cf_connecting_ip):
            raise HTTPException(status_code=403, detail="Bot check failed. Refresh and try again.")

    invalid_register = simulacrum_register is not None and simulacrum_register not in ("professional", "sailor")
    invalid_mode = simulacrum_mode is not None and simulacrum_mode not in ("review", "teach")

    session = chat_memory.get_session(req.session_id or simulacrum_chat_session, user["id"])
    if not session:
        session = chat_memory.create_session(user["id"], chat_mode, register_mode)
    else:
        session = chat_memory.update_session(
            session["id"],
            user["id"],
            mode=chat_mode,
            register_mode=register_mode,
            updated_at=db.utc_now(),
        )

    user_text = _latest_user_text(req)
    if not user_text:
        raise HTTPException(status_code=400, detail="dialog must end with a user turn")

    stored_last = chat_memory.last_turn(session["id"], user["id"])
    if not (
        stored_last
        and stored_last["role"] == "user"
        and stored_last["content"] == user_text
    ):
        chat_memory.append_turn(session["id"], user["id"], "user", user_text)

    stored_turns = chat_memory.list_turns(session["id"], user["id"], limit=80)
    dialogue = _dialog_from_turns(stored_turns[-40:])
    profile = chat_memory.get_profile(user["id"])
    user_turn_count = chat_memory.count_user_turns(session["id"], user["id"])
    session_summary = session.get("summary_text") or ""
    if chat_memory.profile_needs_refresh(profile, user_turn_count):
        try:
            session_summary = user_model_service.summarize_session(session_summary, dialogue)
            profile = user_model_service.refresh_profile(profile, session_summary, dialogue)
            profile = chat_memory.save_profile(user["id"], profile, user_turn_count)
            session = chat_memory.update_session(
                session["id"],
                user["id"],
                summary_text=session_summary,
                updated_at=db.utc_now(),
            )
        except Exception:
            # User-model calibration is additive. A failed refresh must not
            # prevent the actual coaching turn from proceeding.
            pass

    profile_context = compact_profile(profile)
    if chat_mode == "teach":
        out = teach.utterance(
            dialogue,
            temperature=req.temperature,
            register_mode=register_mode,
            user_model=profile_context,
            session_summary=session_summary,
        )
    else:
        out = dispatcher.utterance(
            dialogue,
            register_mode=register_mode,
            user_model=profile_context,
            session_summary=session_summary,
        )

    chat_memory.append_turn(session["id"], user["id"], "assistant", out["text"])

    if api_key:
        remaining = api_remaining
    else:
        timestamps.append(int(time.time()))
        remaining = max(0, CAP_PER_WINDOW - len(timestamps))

    resp = JSONResponse(ChatResponse(
        response=out["text"],
        agent=out["agent"],
        phase=out["phase"],
        mode=out.get("mode"),
        register=register_mode,
        remaining=remaining,
        session_id=session["id"],
    ).model_dump())
    if not api_key:
        resp.set_cookie(
            COUNTER_COOKIE, _write_counter(timestamps),
            max_age=WINDOW_SECONDS, httponly=True, samesite="lax", secure=COOKIE_SECURE,
        )
    if invalid_register:
        resp.set_cookie(
            REGISTER_COOKIE, register_mode,
            max_age=365 * 24 * 3600, httponly=False, samesite="lax", secure=COOKIE_SECURE,
        )
    if invalid_mode:
        resp.set_cookie(
            MODE_COOKIE, chat_mode,
            max_age=365 * 24 * 3600, httponly=False, samesite="lax", secure=COOKIE_SECURE,
        )
    resp.set_cookie(
        CHAT_SESSION_COOKIE,
        session["id"],
        max_age=365 * 24 * 3600,
        httponly=False,
        samesite="lax",
        secure=COOKIE_SECURE,
    )
    return resp


@app.get("/api/chat-session")
async def current_chat_session(
    simulacrum_chat_session: Optional[str] = Cookie(None),
    simulacrum_session: Optional[str] = Cookie(None),
):
    user = _require_user(simulacrum_session)
    session = chat_memory.get_session(simulacrum_chat_session, user["id"])
    if not session:
        return {"session": None, "turns": []}
    turns = chat_memory.list_turns(session["id"], user["id"], limit=80)
    return {
        "session": {
            "id": session["id"],
            "mode": session["mode"],
            "register_mode": session["register_mode"],
            "summary_text": session.get("summary_text") or "",
            "turn_count": session["turn_count"],
        },
        "turns": [{"role": turn["role"], "text": turn["content"]} for turn in turns],
    }


@app.post("/api/chat-session/new")
async def new_chat_session(
    simulacrum_register: Optional[str] = Cookie(None),
    simulacrum_mode: Optional[str] = Cookie(None),
    simulacrum_session: Optional[str] = Cookie(None),
):
    user = _require_user(simulacrum_session)
    session = chat_memory.create_session(
        user["id"],
        _valid_mode(simulacrum_mode),
        _valid_register(simulacrum_register),
    )
    resp = JSONResponse(
        {
            "session": {
                "id": session["id"],
                "mode": session["mode"],
                "register_mode": session["register_mode"],
                "summary_text": "",
                "turn_count": 0,
            },
            "turns": [],
        }
    )
    resp.set_cookie(
        CHAT_SESSION_COOKIE,
        session["id"],
        max_age=365 * 24 * 3600,
        httponly=False,
        samesite="lax",
        secure=COOKIE_SECURE,
    )
    return resp


@app.get("/config")
async def config():
    return {"turnstile_site_key": TURNSTILE_SITE_KEY, "cap_per_window": CAP_PER_WINDOW}


@app.get("/api/engineer-scenarios")
async def engineer_scenarios(simulacrum_session: Optional[str] = Cookie(None)):
    _require_user(simulacrum_session)
    return {"scenarios": public_scenarios()}


@app.get("/healthz")
async def healthz():
    return {
        "ok": True,
        "specialist": "anthropic-fewshot",
        "teach": "anthropic-planner-loop",
        "auth": "magic-link+api-key",
        "simulation": "management",
        "generalist": "configured" if generalist_configured() else "disabled",
        "chat_modes": ["review", "teach"],
        "register_modes": ["professional", "sailor"],
    }


def _set_register_response(register_mode: str) -> JSONResponse:
    resp = JSONResponse({"register": register_mode})
    resp.set_cookie(
        REGISTER_COOKIE, register_mode,
        max_age=365 * 24 * 3600, httponly=False, samesite="lax", secure=COOKIE_SECURE,
    )
    return resp


@app.post("/register")
async def set_register(register_mode: str = Form(...), simulacrum_session: Optional[str] = Cookie(None)):
    _require_user(simulacrum_session)
    if register_mode not in ("professional", "sailor"):
        register_mode = "professional"
    return _set_register_response(register_mode)


@app.post("/mode")
async def set_mode(mode: str = Form(...), simulacrum_session: Optional[str] = Cookie(None)):
    _require_user(simulacrum_session)
    if mode not in ("review", "teach"):
        mode = "review"
    resp = JSONResponse({"mode": mode})
    resp.set_cookie(
        MODE_COOKIE, mode,
        max_age=365 * 24 * 3600, httponly=False, samesite="lax", secure=COOKIE_SECURE,
    )
    return resp


@app.get("/api/me")
async def me(
    simulacrum_session: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    api_key = _api_key_from_headers(authorization, x_api_key)
    if api_key:
        keyed = auth.authenticate_api_key(api_key, consume=False)
        if not keyed:
            raise HTTPException(status_code=401, detail="invalid API key")
        user, remaining = keyed
        return {"user": user, "api_remaining": remaining}
    return {"user": _require_user(simulacrum_session)}


app.mount("/static", StaticFiles(directory=STATIC), name="static")
