import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fly"))

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-dummy")
os.environ.setdefault("SIMULACRUM_DB", str(ROOT / ".pytest_cache" / "modes-test.db"))

from fastapi import HTTPException  # noqa: E402

import app  # noqa: E402


def _req(register=None, mode=None):
    return app.ChatRequest(dialog=[app.DialogTurn(role="user", text="hi")], register=register, mode=mode)


class ResolveModesTests(unittest.TestCase):
    def test_defaults_when_nothing_set(self):
        self.assertEqual(app._resolve_modes(_req(), None, None), ("professional", "review"))

    def test_cookies_apply_when_no_body_override(self):
        self.assertEqual(app._resolve_modes(_req(), "sailor", "teach"), ("sailor", "teach"))

    def test_body_overrides_cookies(self):
        register, mode = app._resolve_modes(_req(register="sailor", mode="teach"), "professional", "review")
        self.assertEqual((register, mode), ("sailor", "teach"))

    def test_invalid_cookies_fall_back_silently(self):
        self.assertEqual(app._resolve_modes(_req(), "pirate", "argue"), ("professional", "review"))

    def test_explicit_invalid_values_are_client_errors(self):
        with self.assertRaises(HTTPException) as ctx:
            app._resolve_modes(_req(register="pirate"), None, None)
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(HTTPException) as ctx:
            app._resolve_modes(_req(mode="argue"), None, None)
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
