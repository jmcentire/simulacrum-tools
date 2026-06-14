"""Engineer practice scenarios for Teach mode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parent
SCENARIOS_PATH = ROOT / "data" / "engineer_scenarios.json"


def load_scenarios() -> list[dict[str, Any]]:
    return json.loads(SCENARIOS_PATH.read_text())


def public_scenarios() -> list[dict[str, Any]]:
    return [
        {
            "id": scenario["id"],
            "category": scenario["category"],
            "difficulty": scenario["difficulty"],
            "title": scenario["title"],
            "prompt": scenario["prompt"],
        }
        for scenario in load_scenarios()
    ]


def scenario_by_id(scenario_id: str) -> dict[str, Any] | None:
    for scenario in load_scenarios():
        if scenario["id"] == scenario_id:
            return scenario
    return None
