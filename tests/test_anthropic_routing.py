import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FLY = ROOT / "fly"
sys.path.insert(0, str(FLY))

import anthropic_config  # noqa: E402


ORDER_OVERRIDE = "SIMULACRUM_ANTHROPIC_API_KEY_ENV"
TEAM_ORDER = ("TEAM_ANTHROPIC_API_KEY", "OTHER_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
ALL_KEYS = {
    "TEAM_ANTHROPIC_API_KEY": "team-key",
    "OTHER_ANTHROPIC_API_KEY": "other-key",
    "ANTHROPIC_API_KEY": "generic-key",
}


def load_skill_run():
    spec = importlib.util.spec_from_file_location("simulacrum_skill_run", ROOT / "skill" / "run.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AnthropicRoutingTests(unittest.TestCase):
    def setUp(self):
        # Never read the operator's real ~/.config during tests.
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.xdg = Path(self._tmp.name)

    def env(self, **extra):
        values = {"XDG_CONFIG_HOME": str(self.xdg)}
        values.update(extra)
        return patch.dict(os.environ, values, clear=True)

    def write_config(self, payload):
        cfg = self.xdg / "simulacrum" / "config.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(payload if isinstance(payload, str) else json.dumps(payload))

    def test_fly_defaults_to_standard_key_name(self):
        with self.env(**ALL_KEYS):
            self.assertEqual(anthropic_config.anthropic_api_key(), "generic-key")

    def test_fly_order_from_env_override_with_fallbacks(self):
        for index, name in enumerate(TEAM_ORDER):
            with self.subTest(name=name):
                values = {candidate: "" for candidate in TEAM_ORDER[:index]}
                values[name] = f"{name}-value"
                values[ORDER_OVERRIDE] = ", ".join(TEAM_ORDER)
                with self.env(**values):
                    self.assertEqual(
                        anthropic_config.anthropic_api_key(),
                        f"{name}-value",
                    )

    def test_fly_order_from_config_file_and_env_precedence(self):
        self.write_config({"anthropic_api_key_env": list(TEAM_ORDER)})
        with self.env(**ALL_KEYS):
            self.assertEqual(anthropic_config.anthropic_api_key(), "team-key")
        with self.env(**ALL_KEYS, **{ORDER_OVERRIDE: "OTHER_ANTHROPIC_API_KEY"}):
            self.assertEqual(anthropic_config.anthropic_api_key(), "other-key")

    def test_fly_malformed_config_fails_loudly(self):
        self.write_config({"anthropic_api_key_env": "NOT_A_LIST"})
        with self.env(**ALL_KEYS):
            with self.assertRaisesRegex(RuntimeError, "anthropic_api_key_env"):
                anthropic_config.anthropic_api_key()

    def test_fly_missing_key_can_be_required_or_optional(self):
        with self.env():
            self.assertIsNone(anthropic_config.anthropic_api_key(required=False))
            with self.assertRaisesRegex(RuntimeError, "ANTHROPIC_API_KEY"):
                anthropic_config.anthropic_api_key()

    def test_skill_key_order_and_default_model(self):
        with patch.dict(os.environ, {}, clear=True):
            skill = load_skill_run()
        self.assertEqual(skill.DEFAULT_ANTHROPIC_MODEL, "claude-sonnet-4-6")
        self.assertEqual(skill.CLASSIFIER_MODEL, "claude-sonnet-4-6")
        self.assertEqual(skill.SPECIALIST_MODEL, "claude-sonnet-4-6")

        with self.env(**ALL_KEYS):
            self.assertEqual(skill._find_anthropic_key(), "generic-key")
        with self.env(**ALL_KEYS, **{ORDER_OVERRIDE: ",".join(TEAM_ORDER)}):
            self.assertEqual(skill._find_anthropic_key(), "team-key")
        self.write_config({"anthropic_api_key_env": ["OTHER_ANTHROPIC_API_KEY"]})
        with self.env(**ALL_KEYS):
            self.assertEqual(skill._find_anthropic_key(), "other-key")
        with self.env():
            with self.assertRaises(SystemExit):
                skill._find_anthropic_key()

    def test_every_fly_anthropic_client_uses_shared_resolver(self):
        client_files = (
            FLY / "app.py",
            FLY / "agents" / "dispatcher.py",
            FLY / "agents" / "specialist.py",
            FLY / "agents" / "teach.py",
            FLY / "agents" / "user_model.py",
            FLY / "management_sim" / "artifacts.py",
        )
        for path in client_files:
            with self.subTest(path=path.relative_to(ROOT)):
                source = path.read_text()
                self.assertIn("anthropic_api_key", source)
                self.assertNotIn('os.environ.get("ANTHROPIC_API_KEY")', source)

        dockerfile = (FLY / "Dockerfile").read_text()
        self.assertIn("COPY anthropic_config.py .", dockerfile)

    def test_public_sources_do_not_reference_retired_default(self):
        paths = (
            ROOT / "README.md",
            ROOT / "PRIMER.md",
            ROOT / "docs" / "index.html",
            ROOT / "skill" / "README.md",
            ROOT / "skill" / "SKILL.md",
            ROOT / "skill" / "run.py",
            FLY / "README.md",
            FLY / "fly.toml",
            *FLY.rglob("*.py"),
        )
        for path in paths:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertNotIn("claude-sonnet-4-5", path.read_text())

    def test_plugin_version_is_1_2_2(self):
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["version"], "1.2.2")


if __name__ == "__main__":
    unittest.main()
