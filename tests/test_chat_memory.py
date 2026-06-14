import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fly"))

import chat_memory  # noqa: E402
import db  # noqa: E402
from agents.user_model import compact_profile, detect_pressure_mismatch  # noqa: E402
from engineer_scenarios import load_scenarios, public_scenarios  # noqa: E402


class ChatMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db.DEFAULT_DB_PATH = Path(self.tempdir.name) / "sim.db"
        db.init_db()
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO users (id, email, created_at, last_login_at) VALUES (?, ?, ?, ?)",
                ("user-1", "user-1@example.com", db.utc_now(), db.utc_now()),
            )

    def tearDown(self):
        self.tempdir.cleanup()

    def test_session_turns_and_profile_persist(self):
        session = chat_memory.create_session("user-1", "teach", "professional")
        chat_memory.append_turn(session["id"], "user-1", "user", "I want to understand why this design keeps growing.")
        chat_memory.append_turn(session["id"], "user-1", "assistant", "What constraint is actually forcing the growth?")
        turns = chat_memory.list_turns(session["id"], "user-1")
        self.assertEqual([turn["role"] for turn in turns], ["user", "assistant"])
        self.assertEqual(turns[-1]["turn_number"], 2)
        self.assertEqual(chat_memory.count_user_turns(session["id"], "user-1"), 1)

        profile = {
            "confidence": "medium",
            "interaction_patterns": ["asks for constraints before implementation"],
            "pressure_preference": "medium",
            "example_preferences": ["worked examples"],
            "active_threads": ["architecture simplification"],
            "delivery_feedback": [],
            "next_best_moves": ["ask for the cost of the abstraction"],
            "evidence": ["asked why the design grew"],
        }
        stored = chat_memory.save_profile("user-1", profile, observed_turns=1)
        loaded = chat_memory.get_profile("user-1")
        self.assertEqual(stored["interaction_patterns"], loaded["interaction_patterns"])
        self.assertEqual(loaded["observed_turns"], 1)

    def test_profile_refresh_cadence(self):
        profile = chat_memory.get_profile("user-1")
        self.assertTrue(chat_memory.profile_needs_refresh(profile, 1))
        stored = chat_memory.save_profile("user-1", profile, observed_turns=4)
        self.assertFalse(chat_memory.profile_needs_refresh(stored, 5))
        self.assertTrue(chat_memory.profile_needs_refresh(stored, 8))

    def test_compact_profile_contains_observable_fields(self):
        profile = {
            "confidence": "high",
            "interaction_patterns": ["responds to concrete counterexamples"],
            "pressure_preference": "high",
            "example_preferences": ["systems examples"],
            "active_threads": ["roadmap scope"],
            "delivery_feedback": ["concrete examples landed better than abstractions"],
            "next_best_moves": ["ask for a falsifiable criterion"],
            "evidence": ["used a concrete example"],
            "forbidden": "not returned",
        }
        compact = compact_profile(profile)
        self.assertNotIn("forbidden", compact)
        self.assertNotIn("blind_spots", compact)
        self.assertEqual(compact["pressure_preference"], "high")

    def test_pressure_mismatch_is_detected(self):
        dialogue = [
            ("Interlocutor", "I have been thinking through this for a while and I cannot tell whether the complexity is real or self-inflicted."),
            ("Jeremy", "What would make the complexity necessary?"),
            ("Interlocutor", "I don't know."),
        ]
        self.assertIsNotNone(detect_pressure_mismatch(dialogue))

    def test_engineer_scenarios_are_rich_and_public_view_is_safe(self):
        scenarios = load_scenarios()
        self.assertGreaterEqual(len(scenarios), 30)
        self.assertGreaterEqual(len({scenario["category"] for scenario in scenarios}), 8)
        for scenario in scenarios:
            self.assertIn("targets", scenario)
            self.assertIn("failure_modes", scenario)
        public = public_scenarios()
        self.assertEqual(len(public), len(scenarios))
        self.assertNotIn("targets", json.dumps(public))
        self.assertNotIn("failure_modes", json.dumps(public))


if __name__ == "__main__":
    unittest.main()
