"""SQLite persistence for authenticated Simulacrum and management simulation.

The app is intentionally small enough to run on one Fly machine, but the data
model is append-friendly: authentication state, user memory, simulation runs,
events, and assessor reports all survive process restarts.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).parent
DEFAULT_DB_PATH = Path(
    os.environ.get("SIMULACRUM_DB", str(Path.home() / ".simulacrum" / "simulacrum.db"))
)
SIGNUP_CODES_FILE = Path(os.environ.get("SIGNUP_CODES_FILE", str(ROOT.parent / "signup_codes.txt")))


def _secret() -> bytes:
    return os.environ.get("SIMULACRUM_TOKEN", "local-dev-secret").encode()


def hash_value(value: str) -> str:
    return hmac.new(_secret(), value.encode(), hashlib.sha256).hexdigest()


def utc_now() -> int:
    return int(time.time())


def new_id() -> str:
    return uuid.uuid4().hex


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DEFAULT_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL,
                last_login_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS signup_codes (
                id TEXT PRIMARY KEY,
                code_hash TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL,
                reserved_at INTEGER,
                reserved_email TEXT,
                consumed_at INTEGER,
                consumed_by_user_id TEXT,
                FOREIGN KEY(consumed_by_user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS magic_links (
                id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                purpose TEXT NOT NULL,
                signup_code_id TEXT,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                consumed_at INTEGER,
                FOREIGN KEY(signup_code_id) REFERENCES signup_codes(id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                revoked_at INTEGER,
                last_seen_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                key_hash TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                daily_cap INTEGER,
                window_start INTEGER,
                window_count INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                last_used_at INTEGER,
                revoked_at INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                run_id TEXT,
                kind TEXT NOT NULL,
                subject TEXT NOT NULL,
                content TEXT NOT NULL,
                importance INTEGER NOT NULL DEFAULT 50,
                source TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                register_mode TEXT NOT NULL,
                summary_text TEXT,
                turn_count INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS chat_turns (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                turn_number INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(session_id, turn_number),
                FOREIGN KEY(session_id) REFERENCES chat_sessions(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS user_models (
                user_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                observed_turns INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS sim_runs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                mission TEXT NOT NULL,
                budget_cents INTEGER NOT NULL,
                phase TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                completed_at INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS sim_events (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(run_id) REFERENCES sim_runs(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS sim_state_snapshots (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                persona_id TEXT NOT NULL,
                week INTEGER NOT NULL,
                state_hash TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(run_id, persona_id, week),
                FOREIGN KEY(run_id) REFERENCES sim_runs(id)
            );

            CREATE TABLE IF NOT EXISTS sim_artifacts (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                persona_id TEXT NOT NULL,
                week INTEGER NOT NULL,
                report_text TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                state_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(run_id, persona_id, week),
                FOREIGN KEY(run_id) REFERENCES sim_runs(id)
            );

            CREATE TABLE IF NOT EXISTS sim_conversation_turns (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                persona_id TEXT NOT NULL,
                week INTEGER NOT NULL,
                turn_number INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                state_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(run_id, persona_id, week, turn_number),
                FOREIGN KEY(run_id) REFERENCES sim_runs(id)
            );

            CREATE TABLE IF NOT EXISTS sim_assessments (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                report_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(run_id) REFERENCES sim_runs(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE INDEX IF NOT EXISTS idx_sessions_token_hash ON sessions(token_hash);
            CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_magic_links_token_hash ON magic_links(token_hash);
            CREATE INDEX IF NOT EXISTS idx_magic_links_email ON magic_links(email);
            CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
            CREATE INDEX IF NOT EXISTS idx_memories_user_id ON memories(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions(user_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_chat_turns_session_id ON chat_turns(session_id, turn_number ASC);
            CREATE INDEX IF NOT EXISTS idx_chat_turns_user_id ON chat_turns(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_sim_runs_user_id ON sim_runs(user_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_sim_events_run_id ON sim_events(run_id, created_at ASC);
            CREATE INDEX IF NOT EXISTS idx_sim_state_snapshots_run ON sim_state_snapshots(run_id, week, persona_id);
            CREATE INDEX IF NOT EXISTS idx_sim_artifacts_run ON sim_artifacts(run_id, week, persona_id);
            CREATE INDEX IF NOT EXISTS idx_sim_conversation_turns_run ON sim_conversation_turns(run_id, week, persona_id, turn_number);
            """
        )
    seed_signup_codes()


def seed_signup_codes() -> int:
    raw = os.environ.get("SIGNUP_CODES", "")
    codes: list[str] = []
    if raw:
        codes.extend(code.strip() for code in raw.replace(",", "\n").splitlines())
    if SIGNUP_CODES_FILE.exists():
        codes.extend(line.strip() for line in SIGNUP_CODES_FILE.read_text().splitlines())
    codes = [code for code in codes if code and not code.startswith("#")]
    if not codes:
        return 0

    inserted = 0
    with connect() as conn:
        for code in codes:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO signup_codes
                    (id, code_hash, created_at)
                VALUES (?, ?, ?)
                """,
                (new_id(), hash_value(code), utc_now()),
            )
            inserted += cur.rowcount
    return inserted


def json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def json_loads(value: str | None) -> Any:
    return json.loads(value) if value else None
