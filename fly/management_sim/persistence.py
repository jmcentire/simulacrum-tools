"""Persistence helpers for management simulation state and artifacts."""

from __future__ import annotations

import hashlib
from typing import Any

import db

from .models import HiddenState


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def create_run(user_id: str, mission: str, budget_cents: int, state: dict[str, Any]) -> None:
    now = db.utc_now()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO sim_runs
                (id, user_id, mission, budget_cents, phase, state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (state["run_id"], user_id, mission, budget_cents, state["phase"], db.json_dumps(state), now, now),
        )


def archive_active_runs(user_id: str) -> None:
    now = db.utc_now()
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE sim_runs
            SET completed_at = ?, updated_at = ?
            WHERE user_id = ? AND completed_at IS NULL
            """,
            (now, now, user_id),
        )


def load_active_run(user_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT state_json FROM sim_runs
            WHERE user_id = ? AND completed_at IS NULL
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    return db.json_loads(row["state_json"]) if row else None


def save_run(user_id: str, state: dict[str, Any]) -> None:
    now = db.utc_now()
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE sim_runs
            SET phase = ?, state_json = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (state["phase"], db.json_dumps(state), now, state["run_id"], user_id),
        )


def append_event(run_id: str, user_id: str, event_type: str, payload: dict[str, Any]) -> None:
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO sim_events (id, run_id, user_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (db.new_id(), run_id, user_id, event_type, db.json_dumps(payload), db.utc_now()),
        )


def list_events(run_id: str, user_id: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT event_type, payload_json, created_at
            FROM sim_events
            WHERE run_id = ? AND user_id = ?
            ORDER BY created_at ASC
            """,
            (run_id, user_id),
        ).fetchall()
    return [{"event_type": row["event_type"], "payload": db.json_loads(row["payload_json"]), "created_at": row["created_at"]} for row in rows]


def save_snapshot(run_id: str, state: HiddenState, state_hash: str) -> None:
    with db.connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO sim_state_snapshots
                (id, run_id, persona_id, week, state_hash, state_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (db.new_id(), run_id, state.persona_id, state.week, state_hash, db.json_dumps(state.to_dict()), db.utc_now()),
        )


def save_artifact(run_id: str, persona_id: str, week: int, report_text: str, content_hash: str, state_hash: str) -> None:
    with db.connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO sim_artifacts
                (id, run_id, persona_id, week, report_text, content_hash, state_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (db.new_id(), run_id, persona_id, week, report_text, content_hash, state_hash, db.utc_now()),
        )


def list_artifacts(run_id: str, week: int) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT persona_id, report_text, content_hash, state_hash, created_at
            FROM sim_artifacts
            WHERE run_id = ? AND week = ?
            ORDER BY persona_id ASC
            """,
            (run_id, week),
        ).fetchall()
    return [dict(row) for row in rows]


def list_turns(run_id: str, persona_id: str, week: int) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT turn_number, role, content, created_at
            FROM sim_conversation_turns
            WHERE run_id = ? AND persona_id = ? AND week = ?
            ORDER BY turn_number ASC
            """,
            (run_id, persona_id, week),
        ).fetchall()
    return [dict(row) for row in rows]


def save_turn_pair(
    run_id: str,
    persona_id: str,
    week: int,
    manager_turn_number: int,
    manager_message: str,
    persona_message: str,
    state_hash: str,
) -> None:
    now = db.utc_now()
    with db.connect() as conn:
        conn.execute("BEGIN")
        try:
            conn.execute(
                """
                INSERT INTO sim_conversation_turns
                    (id, run_id, persona_id, week, turn_number, role, content, content_hash, state_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (db.new_id(), run_id, persona_id, week, manager_turn_number, "manager", manager_message, hash_text(manager_message), state_hash, now),
            )
            conn.execute(
                """
                INSERT INTO sim_conversation_turns
                    (id, run_id, persona_id, week, turn_number, role, content, content_hash, state_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (db.new_id(), run_id, persona_id, week, manager_turn_number + 1, "persona", persona_message, hash_text(persona_message), state_hash, now),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
