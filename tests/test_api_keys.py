import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fly"))

import auth  # noqa: E402
import db  # noqa: E402


class ApiKeyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        db.DEFAULT_DB_PATH = Path(self.tempdir.name) / "sim.db"
        db.init_db()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_mint_and_authenticate_creates_user(self):
        raw = auth.create_api_key("partner@example.com", label="partner")
        self.assertTrue(raw.startswith(auth.API_KEY_PREFIX))
        user, remaining = auth.authenticate_api_key(raw)
        self.assertEqual(user["email"], "partner@example.com")
        self.assertEqual(remaining, auth.API_CAP_PER_WINDOW - 1)

    def test_pre_provisioned_key_value(self):
        raw = auth.create_api_key("partner@example.com", raw_key="sim-preprovisioned-key-value")
        self.assertEqual(raw, "sim-preprovisioned-key-value")
        user, _ = auth.authenticate_api_key("sim-preprovisioned-key-value")
        self.assertEqual(user["email"], "partner@example.com")
        with self.assertRaises(ValueError):
            auth.create_api_key("partner@example.com", raw_key="short")

    def test_existing_user_is_reused(self):
        first = auth.create_api_key("partner@example.com")
        second = auth.create_api_key("partner@example.com")
        user_a, _ = auth.authenticate_api_key(first)
        user_b, _ = auth.authenticate_api_key(second)
        self.assertEqual(user_a["id"], user_b["id"])

    def test_invalid_and_revoked_keys_rejected(self):
        self.assertIsNone(auth.authenticate_api_key(None))
        self.assertIsNone(auth.authenticate_api_key("sk-sim-not-a-real-key"))
        raw = auth.create_api_key("partner@example.com")
        key_id = auth.list_api_keys("partner@example.com")[0]["id"]
        self.assertTrue(auth.revoke_api_key(key_id))
        self.assertIsNone(auth.authenticate_api_key(raw))
        self.assertFalse(auth.revoke_api_key(key_id))

    def test_daily_cap_and_window_reset(self):
        raw = auth.create_api_key("partner@example.com", daily_cap=2)
        _, remaining = auth.authenticate_api_key(raw)
        self.assertEqual(remaining, 1)
        _, remaining = auth.authenticate_api_key(raw)
        self.assertEqual(remaining, 0)
        with self.assertRaises(auth.ApiKeyRateLimited):
            auth.authenticate_api_key(raw)

        # Peek does not consume and never raises on an exhausted key.
        user, remaining = auth.authenticate_api_key(raw, consume=False)
        self.assertEqual(remaining, 0)
        self.assertEqual(user["email"], "partner@example.com")

        # Age the window past 24h; the cap resets.
        with db.connect() as conn:
            conn.execute(
                "UPDATE api_keys SET window_start = ?",
                (db.utc_now() - auth.API_WINDOW_SECONDS - 1,),
            )
        _, remaining = auth.authenticate_api_key(raw)
        self.assertEqual(remaining, 1)


if __name__ == "__main__":
    unittest.main()
