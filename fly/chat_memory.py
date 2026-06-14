"""Persistent chat sessions and compact user-learning profiles."""

from __future__ import annotations

from typing import Any

import db


DEFAULT_PROFILE = {
    "confidence": "low",
    "interaction_patterns": [],
    "pressure_preference": "medium",
    "example_preferences": [],
    "active_threads": [],
    "delivery_feedback": [],
    "next_best_moves": [],
    "evidence": [],
}


def create_session(user_id: str, mode: str, register_mode: str) -> dict[str, Any]:
    now = db.utc_now()
    session = {
        "id": db.new_id(),
        "user_id": user_id,
        "mode": mode,
        "register_mode": register_mode,
        "summary_text": "",
        "turn_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_sessions
                (id, user_id, mode, register_mode, summary_text, turn_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session["id"],
                user_id,
                mode,
                register_mode,
                session["summary_text"],
                session["turn_count"],
                now,
                now,
            ),
        )
    return session


def get_session(session_id: str | None, user_id: str) -> dict[str, Any] | None:
    if not session_id:
        return None
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM chat_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def list_recent_sessions(user_id: str, limit: int = 8) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM chat_sessions
            WHERE user_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def update_session(session_id: str, user_id: str, **fields: Any) -> dict[str, Any]:
    allowed = {"mode", "register_mode", "summary_text", "turn_count", "updated_at"}
    assignments = [(key, value) for key, value in fields.items() if key in allowed]
    if not assignments:
        session = get_session(session_id, user_id)
        if not session:
            raise ValueError("chat session not found")
        return session
    sql = ", ".join(f"{key} = ?" for key, _value in assignments)
    values = [value for _key, value in assignments] + [session_id, user_id]
    with db.connect() as conn:
        conn.execute(
            f"UPDATE chat_sessions SET {sql} WHERE id = ? AND user_id = ?",
            values,
        )
    session = get_session(session_id, user_id)
    if not session:
        raise ValueError("chat session not found")
    return session


def append_turn(session_id: str, user_id: str, role: str, content: str) -> dict[str, Any]:
    session = get_session(session_id, user_id)
    if not session:
        raise ValueError("chat session not found")
    turn_number = int(session["turn_count"]) + 1
    turn = {
        "id": db.new_id(),
        "session_id": session_id,
        "user_id": user_id,
        "turn_number": turn_number,
        "role": role,
        "content": content,
        "created_at": db.utc_now(),
    }
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO chat_turns
                (id, session_id, user_id, turn_number, role, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn["id"],
                session_id,
                user_id,
                turn_number,
                role,
                content,
                turn["created_at"],
            ),
        )
    update_session(
        session_id,
        user_id,
        turn_count=turn_number,
        updated_at=turn["created_at"],
    )
    return turn


def list_turns(session_id: str, user_id: str, limit: int = 80) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM chat_turns
            WHERE session_id = ? AND user_id = ?
            ORDER BY turn_number ASC
            LIMIT ?
            """,
            (session_id, user_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def count_user_turns(session_id: str, user_id: str) -> int:
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM chat_turns
            WHERE session_id = ? AND user_id = ? AND role = 'user'
            """,
            (session_id, user_id),
        ).fetchone()
    return int(row["count"]) if row else 0


def last_turn(session_id: str, user_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM chat_turns
            WHERE session_id = ? AND user_id = ?
            ORDER BY turn_number DESC
            LIMIT 1
            """,
            (session_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def get_profile(user_id: str) -> dict[str, Any]:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM user_models WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return {**DEFAULT_PROFILE, "observed_turns": 0, "updated_at": 0}
    profile = db.json_loads(row["profile_json"]) or {}
    return {
        **DEFAULT_PROFILE,
        **profile,
        "observed_turns": int(row["observed_turns"]),
        "updated_at": int(row["updated_at"]),
    }


def save_profile(user_id: str, profile: dict[str, Any], observed_turns: int) -> dict[str, Any]:
    now = db.utc_now()
    stored = {**DEFAULT_PROFILE, **profile}
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO user_models (user_id, profile_json, observed_turns, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                profile_json = excluded.profile_json,
                observed_turns = excluded.observed_turns,
                updated_at = excluded.updated_at
            """,
            (user_id, db.json_dumps(stored), observed_turns, now),
        )
        conn.execute(
            """
            INSERT INTO memories
                (id, user_id, run_id, kind, subject, content, importance, source, created_at)
            VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                db.new_id(),
                user_id,
                "teach_profile",
                "user learning profile",
                db.json_dumps(stored),
                65,
                "chat",
                now,
            ),
        )
    return {**stored, "observed_turns": observed_turns, "updated_at": now}


def profile_needs_refresh(profile: dict[str, Any], user_turn_count: int, cadence: int = 4) -> bool:
    observed = int(profile.get("observed_turns", 0))
    return user_turn_count == 1 or user_turn_count - observed >= cadence
