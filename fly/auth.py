"""Authentication helpers: invite codes, magic links, and sessions."""

from __future__ import annotations

import secrets
import time
from typing import Any
from urllib.parse import quote

import httpx

import db


SESSION_COOKIE = "simulacrum_session"
MAGIC_LINK_TTL_SECONDS = int(__import__("os").environ.get("MAGIC_LINK_TTL_SECONDS", "900"))
SESSION_TTL_SECONDS = int(__import__("os").environ.get("SESSION_TTL_SECONDS", str(7 * 24 * 3600)))
API_KEY_PREFIX = "sk-sim-"
API_CAP_PER_WINDOW = int(__import__("os").environ.get("API_CAP_PER_WINDOW", "200"))
API_WINDOW_SECONDS = 24 * 3600


def _env(name: str, default: str = "") -> str:
    return __import__("os").environ.get(name, default)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _base_url() -> str:
    return _env("APP_BASE_URL", "http://127.0.0.1:8080").rstrip("/")


def _new_token() -> str:
    return secrets.token_urlsafe(32)


def find_user_by_email(email: str) -> dict[str, Any] | None:
    email = normalize_email(email)
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def find_user_by_id(user_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def reserve_signup_code(code: str, email: str) -> str | None:
    now = db.utc_now()
    reservation_cutoff = now - MAGIC_LINK_TTL_SECONDS
    code_hash = db.hash_value(code.strip())
    email = normalize_email(email)
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM signup_codes
            WHERE code_hash = ?
              AND consumed_at IS NULL
              AND (
                reserved_at IS NULL
                OR reserved_at < ?
                OR reserved_email = ?
              )
            """,
            (code_hash, reservation_cutoff, email),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            """
            UPDATE signup_codes
            SET reserved_at = ?, reserved_email = ?
            WHERE id = ?
            """,
            (now, email, row["id"]),
        )
        return row["id"]


def issue_magic_link(email: str, purpose: str, signup_code_id: str | None = None) -> tuple[str, str]:
    token = _new_token()
    now = db.utc_now()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO magic_links
                (id, token_hash, email, purpose, signup_code_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                db.new_id(),
                db.hash_value(token),
                normalize_email(email),
                purpose,
                signup_code_id,
                now,
                now + MAGIC_LINK_TTL_SECONDS,
            ),
        )
    return token, f"{_base_url()}/auth/verify?token={quote(token)}"


async def send_magic_link(email: str, link: str) -> None:
    api_key = _env("RESEND_API_KEY")
    from_address = _env("RESEND_FROM", "Simulacrum <onboarding@resend.dev>")
    subject = "Your Simulacrum sign-in link"
    text = f"Use this link to sign in to Simulacrum:\n\n{link}\n\nThis link expires in 15 minutes."
    html = f"""
    <p>Use this link to sign in to Simulacrum:</p>
    <p><a href="{link}">Sign in to Simulacrum</a></p>
    <p>This link expires in 15 minutes.</p>
    """
    if not api_key:
        print(f"[magic-link console delivery] {email}: {link}")
        return
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"from": from_address, "to": [email], "subject": subject, "text": text, "html": html},
        )
    if response.status_code >= 300:
        raise RuntimeError(f"Resend rejected magic link delivery: {response.status_code} {response.text}")


async def request_signup(email: str, code: str) -> bool:
    email = normalize_email(email)
    if not email or "@" not in email:
        return False
    signup_code_id = reserve_signup_code(code, email)
    if not signup_code_id:
        return False
    token, link = issue_magic_link(email, "signup", signup_code_id=signup_code_id)
    try:
        await send_magic_link(email, link)
    except Exception:
        with db.connect() as conn:
            conn.execute(
                "DELETE FROM magic_links WHERE token_hash = ?",
                (db.hash_value(token),),
            )
            conn.execute(
                """
                UPDATE signup_codes
                SET reserved_at = NULL, reserved_email = NULL
                WHERE id = ?
                """,
                (signup_code_id,),
            )
        raise
    return True


async def request_signin(email: str) -> bool:
    email = normalize_email(email)
    if not email or "@" not in email:
        return False
    if not find_user_by_email(email):
        return True
    token, link = issue_magic_link(email, "signin")
    await send_magic_link(email, link)
    return True


def _create_user(email: str) -> dict[str, Any]:
    now = db.utc_now()
    user = {"id": db.new_id(), "email": normalize_email(email), "created_at": now, "last_login_at": now}
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users (id, email, created_at, last_login_at) VALUES (?, ?, ?, ?)",
            (user["id"], user["email"], now, now),
        )
    return user


def _create_session(user_id: str) -> str:
    token = _new_token()
    now = db.utc_now()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions
                (id, token_hash, user_id, created_at, expires_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (db.new_id(), db.hash_value(token), user_id, now, now + SESSION_TTL_SECONDS, now),
        )
    return token


def redeem_magic_link(token: str) -> tuple[dict[str, Any] | None, str | None]:
    now = db.utc_now()
    token_hash = db.hash_value(token)
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM magic_links
            WHERE token_hash = ? AND consumed_at IS NULL AND expires_at >= ?
            """,
            (token_hash, now),
        ).fetchone()
        if not row:
            return None, None
        conn.execute("UPDATE magic_links SET consumed_at = ? WHERE id = ?", (now, row["id"]))

        email = row["email"]
        user_row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        user = dict(user_row) if user_row else None
        if row["purpose"] == "signup":
            if row["signup_code_id"]:
                conn.execute(
                    """
                    UPDATE signup_codes
                    SET consumed_at = ?, consumed_by_user_id = ?
                    WHERE id = ? AND consumed_at IS NULL
                    """,
                    (now, user["id"] if user else None, row["signup_code_id"]),
                )
            if not user:
                user = {
                    "id": db.new_id(),
                    "email": email,
                    "created_at": now,
                    "last_login_at": now,
                }
                conn.execute(
                    "INSERT INTO users (id, email, created_at, last_login_at) VALUES (?, ?, ?, ?)",
                    (user["id"], user["email"], now, now),
                )
            elif row["signup_code_id"]:
                conn.execute(
                    "UPDATE signup_codes SET consumed_by_user_id = ? WHERE id = ?",
                    (user["id"], row["signup_code_id"]),
                )
        elif not user:
            return None, None

        conn.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (now, user["id"]),
        )

    session_token = _create_session(user["id"])
    return user, session_token


class ApiKeyRateLimited(Exception):
    def __init__(self, reset_in: int):
        super().__init__(f"API key daily cap reached; resets in {reset_in}s")
        self.reset_in = reset_in


def create_api_key(
    email: str,
    label: str = "",
    daily_cap: int | None = None,
    raw_key: str | None = None,
) -> str:
    """Mint an API key for email, creating the user if needed.

    Returns the raw key — only its HMAC hash is stored. Pass raw_key to
    register a pre-provisioned key value instead of generating one.
    """
    raw = (raw_key or "").strip() or API_KEY_PREFIX + _new_token()
    if len(raw) < 16:
        raise ValueError("API key must be at least 16 characters")
    user = find_user_by_email(email) or _create_user(email)
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO api_keys (id, key_hash, user_id, label, daily_cap, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (db.new_id(), db.hash_value(raw), user["id"], label, daily_cap, db.utc_now()),
        )
    return raw


def authenticate_api_key(
    raw_key: str | None, consume: bool = True
) -> tuple[dict[str, Any], int] | None:
    """Validate a raw API key; when consume is set, take one request from its
    rolling daily window.

    Returns (user, remaining) or None when the key is unknown or revoked.
    Raises ApiKeyRateLimited when the key is over its daily cap.
    """
    if not raw_key:
        return None
    now = db.utc_now()
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT k.*, u.email
            FROM api_keys k
            JOIN users u ON u.id = k.user_id
            WHERE k.key_hash = ? AND k.revoked_at IS NULL
            """,
            (db.hash_value(raw_key),),
        ).fetchone()
        if not row:
            return None
        cap = row["daily_cap"] or API_CAP_PER_WINDOW
        window_start = row["window_start"]
        window_count = row["window_count"]
        if window_start is None or now - window_start >= API_WINDOW_SECONDS:
            window_start, window_count = now, 0
        if not consume:
            return {"id": row["user_id"], "email": row["email"]}, max(0, cap - window_count)
        if window_count >= cap:
            raise ApiKeyRateLimited(max(0, window_start + API_WINDOW_SECONDS - now))
        conn.execute(
            """
            UPDATE api_keys
            SET window_start = ?, window_count = ?, last_used_at = ?
            WHERE id = ?
            """,
            (window_start, window_count + 1, now, row["id"]),
        )
    return {"id": row["user_id"], "email": row["email"]}, cap - window_count - 1


def list_api_keys(email: str) -> list[dict[str, Any]]:
    user = find_user_by_email(email)
    if not user:
        return []
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM api_keys WHERE user_id = ? ORDER BY created_at",
            (user["id"],),
        ).fetchall()
    return [dict(row) for row in rows]


def revoke_api_key(key_id: str) -> bool:
    with db.connect() as conn:
        cur = conn.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (db.utc_now(), key_id),
        )
    return cur.rowcount > 0


def current_user(session_token: str | None) -> dict[str, Any] | None:
    if not session_token:
        return None
    now = db.utc_now()
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT s.*, u.email
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?
              AND s.revoked_at IS NULL
              AND s.expires_at >= ?
            """,
            (db.hash_value(session_token), now),
        ).fetchone()
        if not row:
            return None
        conn.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", (now, row["id"]))
    return {"id": row["user_id"], "email": row["email"]}


def revoke_session(session_token: str | None) -> None:
    if not session_token:
        return
    with db.connect() as conn:
        conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            (db.utc_now(), db.hash_value(session_token)),
        )


def session_cookie_max_age() -> int:
    return SESSION_TTL_SECONDS
