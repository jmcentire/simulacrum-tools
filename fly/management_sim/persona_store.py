"""Persona file loading and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import PersonaDefinition


PERSONA_DIR = Path(__file__).parent / "personas"
REQUIRED_HIDDEN_KEYS = {
    "traits",
    "mastery",
    "autonomy",
    "purpose",
    "energy",
    "friction",
    "compatibility_tags",
    "friction_tags",
}
REQUIRED_PUBLIC_KEYS = {"seniority", "interview", "motivation", "ambition"}


class PersonaStore:
    def __init__(self, persona_dir: Path = PERSONA_DIR):
        self.persona_dir = persona_dir
        self._cache: dict[str, PersonaDefinition] = {}

    def load_all(self) -> list[PersonaDefinition]:
        if not self._cache:
            for path in sorted(self.persona_dir.glob("*.json")):
                persona = self._load_file(path)
                self._cache[persona.id] = persona
        return list(self._cache.values())

    def get(self, persona_id: str) -> PersonaDefinition:
        if not self._cache:
            self.load_all()
        try:
            return self._cache[persona_id]
        except KeyError as exc:
            raise ValueError(f"unknown persona {persona_id!r}") from exc

    def public_summaries(self, persona_ids: list[str]) -> list[dict[str, Any]]:
        return [self.get(persona_id).public_summary() for persona_id in persona_ids]

    def _load_file(self, path: Path) -> PersonaDefinition:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError(f"persona file {path.name} is not an object")
        missing = {
            "schema_version",
            "id",
            "name",
            "role",
            "salary_cents",
            "backfill_fund_cents",
            "skills",
            "visible",
            "hidden",
        } - payload.keys()
        if missing:
            raise ValueError(f"persona file {path.name} missing keys: {sorted(missing)}")
        visible = payload["visible"]
        hidden = payload["hidden"]
        if not isinstance(visible, dict) or REQUIRED_PUBLIC_KEYS - visible.keys():
            raise ValueError(f"persona file {path.name} has incomplete visible profile")
        if not isinstance(hidden, dict) or REQUIRED_HIDDEN_KEYS - hidden.keys():
            raise ValueError(f"persona file {path.name} has incomplete hidden profile")
        if payload["id"] != path.stem:
            raise ValueError(f"persona id {payload['id']!r} does not match filename {path.stem!r}")
        return PersonaDefinition(
            schema_version=int(payload["schema_version"]),
            id=str(payload["id"]),
            name=str(payload["name"]),
            role=str(payload["role"]),
            salary_cents=int(payload["salary_cents"]),
            backfill_fund_cents=int(payload["backfill_fund_cents"]),
            skills={str(k): int(v) for k, v in payload["skills"].items()},
            visible=visible,
            hidden=hidden,
        )
