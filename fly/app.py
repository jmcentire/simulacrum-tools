"""Two-phase simulacrum deployment: FastAPI service.

The /chat endpoint dispatches each turn between two agents:
  GENERALIST → fine-tuned model for direct-recall, autobiographical,
               well-formed-direct questions (optional — only fires if
               GENERALIST_MODEL env var is set)
  SPECIALIST → Anthropic claude-sonnet-4-5 + annotated few-shot pairs
               for adversarial framings, content generation, suggestions,
               critique, multi-turn continuation

Auth: HMAC-signed session cookie. /login accepts ALLOWED_USERNAME
(case-insensitive); no password (username is the gate).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import Cookie, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agents.dispatcher import Dispatcher
from agents.generalist import is_configured as generalist_configured

ROOT = Path(__file__).parent
STATIC = ROOT / "static"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
SECRET_KEY = os.environ.get("SIMULACRUM_TOKEN") or secrets.token_hex(32)
ALLOWED_USERNAME = os.environ.get("ALLOWED_USERNAME", "admin").lower()
SESSION_COOKIE = "simulacrum_session"
SESSION_DURATION = 7 * 24 * 3600  # 1 week

if not ANTHROPIC_API_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY env var required (specialist + classifier)")

dispatcher = Dispatcher()
print(f"dispatcher loaded — generalist={'enabled' if generalist_configured() else 'disabled (specialist-only)'}")


# ---- Session token (HMAC-signed) ----

def _make_session_token(username: str) -> str:
    expires = int(time.time()) + SESSION_DURATION
    payload = f"{username.lower()}|{expires}"
    sig = hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}|{sig}"


def _verify_session_token(token: Optional[str]) -> bool:
    if not token:
        return False
    try:
        parts = token.split("|")
        if len(parts) != 3:
            return False
        username, expires_str, sig = parts
        if int(expires_str) < int(time.time()):
            return False
        if username != ALLOWED_USERNAME:
            return False
        expected = hmac.new(
            SECRET_KEY.encode(), f"{username}|{expires_str}".encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


# ---- HTTP API ----

app = FastAPI(title="Simulacrum", version="1.0")


class DialogTurn(BaseModel):
    role: str
    text: str


class ChatRequest(BaseModel):
    dialog: list[DialogTurn]
    temperature: float = 0.7


class ChatResponse(BaseModel):
    response: str
    agent: str
    phase: str
    mode: Optional[str] = None
    spice: Optional[str] = None


def _require_auth(session: Optional[str]):
    if not _verify_session_token(session):
        raise HTTPException(status_code=401, detail="Login required")


@app.get("/login", response_class=HTMLResponse)
async def login_page(error: Optional[str] = None):
    err_html = f'<p class="error">{error}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Simulacrum — Jeremy McEntire — Login</title>
  <script>
    (function() {{
      var t = localStorage.getItem('simulacrum_theme') || 'dark';
      document.documentElement.setAttribute('data-theme', t);
    }})();
  </script>
  <style>
    :root[data-theme="dark"] {{
      --bg: #1a1a1a; --surface: #222; --text: #e8e8e8; --subtle: #888;
      --label: #aaa; --border: #333; --border-input: #444;
      --accent: #ffb86c; --accent-text: #1a1a1a; --error: #ff6c6c;
    }}
    :root[data-theme="light"] {{
      --bg: #fafafa; --surface: #ffffff; --text: #18181b; --subtle: #52525b;
      --label: #3f3f46; --border: #e4e4e7; --border-input: #d4d4d8;
      --accent: #c2410c; --accent-text: #ffffff; --error: #b91c1c;
    }}
    * {{ box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: var(--bg); color: var(--text); margin: 0; min-height: 100vh;
           display: flex; align-items: center; justify-content: center; padding: 16px; }}
    .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
            padding: 32px; width: 100%; max-width: 380px; position: relative; }}
    h1 {{ margin: 0 0 8px; font-size: 18px; font-weight: 500; }}
    .sub {{ color: var(--subtle); font-size: 13px; margin-bottom: 24px; }}
    label {{ display: block; font-size: 12px; color: var(--label);
            text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }}
    input {{ width: 100%; background: var(--bg); color: var(--text); border: 1px solid var(--border-input);
            border-radius: 4px; padding: 10px 12px; font: inherit; }}
    button.submit {{ background: var(--accent); color: var(--accent-text); border: 0; border-radius: 4px;
             padding: 10px 16px; font: inherit; font-weight: 600; cursor: pointer;
             margin-top: 16px; width: 100%; }}
    .error {{ color: var(--error); font-size: 13px; margin: 8px 0 16px; }}
    .theme-toggle {{ position: absolute; top: 12px; right: 12px;
                    background: transparent; color: var(--subtle); border: 1px solid var(--border-input);
                    border-radius: 4px; padding: 4px 10px; font: inherit; font-size: 12px;
                    cursor: pointer; }}
    .theme-toggle:hover {{ color: var(--text); border-color: var(--text); }}
  </style>
</head>
<body>
  <form class="card" method="POST" action="/login">
    <button type="button" class="theme-toggle" id="theme-toggle" aria-label="Toggle theme"></button>
    <h1>Simulacrum — Jeremy McEntire</h1>
    <p class="sub">Pitch an idea; expect pushback when warranted.</p>
    {err_html}
    <label for="username">Username</label>
    <input type="text" id="username" name="username" autocomplete="username" autofocus required />
    <button class="submit" type="submit">Continue</button>
  </form>
  <script>
    const themeToggle = document.getElementById('theme-toggle');
    function updateThemeButton() {{
      const t = document.documentElement.getAttribute('data-theme');
      themeToggle.textContent = t === 'dark' ? '☀ Light' : '☾ Dark';
    }}
    updateThemeButton();
    themeToggle.addEventListener('click', () => {{
      const cur = document.documentElement.getAttribute('data-theme');
      const next = cur === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('simulacrum_theme', next);
      updateThemeButton();
    }});
  </script>
</body>
</html>"""


@app.post("/login")
async def login_submit(username: str = Form(...)):
    if username.strip().lower() != ALLOWED_USERNAME:
        return RedirectResponse(url="/login?error=Invalid+username", status_code=303)
    token = _make_session_token(ALLOWED_USERNAME)
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie(
        SESSION_COOKIE, token,
        max_age=SESSION_DURATION, httponly=True, samesite="lax", secure=True,
    )
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@app.get("/")
async def index(simulacrum_session: Optional[str] = Cookie(None)):
    if not _verify_session_token(simulacrum_session):
        return RedirectResponse(url="/login", status_code=303)
    return FileResponse(STATIC / "index.html")


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest,
               simulacrum_session: Optional[str] = Cookie(None),
               simulacrum_spice: Optional[str] = Cookie(None)) -> ChatResponse:
    _require_auth(simulacrum_session)

    if not req.dialog:
        raise HTTPException(status_code=400, detail="empty dialog")

    spice = "spicy" if simulacrum_spice == "spicy" else "tuned"
    dialogue = [(t.role, t.text) for t in req.dialog]
    out = dispatcher.utterance(dialogue, spice=spice)
    return ChatResponse(
        response=out["text"],
        agent=out["agent"],
        phase=out["phase"],
        mode=out.get("mode"),
    )


@app.get("/healthz")
async def healthz():
    return {
        "ok": True,
        "specialist": "anthropic-fewshot",
        "generalist": "configured" if generalist_configured() else "disabled",
        "spice_modes": ["tuned", "spicy"],
    }


@app.post("/spice")
async def set_spice(spice: str = Form(...),
                    simulacrum_session: Optional[str] = Cookie(None)):
    _require_auth(simulacrum_session)
    if spice not in ("tuned", "spicy"):
        raise HTTPException(status_code=400, detail="spice must be 'tuned' or 'spicy'")
    resp = JSONResponse({"spice": spice})
    resp.set_cookie(
        "simulacrum_spice", spice,
        max_age=365 * 24 * 3600, httponly=False, samesite="lax", secure=True,
    )
    return resp


app.mount("/static", StaticFiles(directory=STATIC), name="static")
