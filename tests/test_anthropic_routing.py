import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FLY = ROOT / "fly"
sys.path.insert(0, str(FLY))

import anthropic_config  # noqa: E402


ANTHROPIC_KEY_NAMES = (
    "WANDER_ANTHROPIC_API_KEY",
    "SIM_ANTHROPIC_API_KEY",
    "ANTHROPIC_API_KEY",
    "JMC_ANTHROPIC_API_KEY",
)


def load_skill_run():
    spec = importlib.util.spec_from_file_location("simulacrum_skill_run", ROOT / "skill" / "run.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AnthropicRoutingTests(unittest.TestCase):
    def test_fly_prefers_wander_billing_key(self):
        values = {
            "WANDER_ANTHROPIC_API_KEY": "wander-key",
            "SIM_ANTHROPIC_API_KEY": "sim-key",
            "ANTHROPIC_API_KEY": "generic-key",
            "JMC_ANTHROPIC_API_KEY": "jmc-key",
        }
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(anthropic_config.anthropic_api_key(), "wander-key")

    def test_fly_retains_portable_fallbacks(self):
        for index, name in enumerate(ANTHROPIC_KEY_NAMES):
            with self.subTest(name=name):
                values = {candidate: "" for candidate in ANTHROPIC_KEY_NAMES[:index]}
                values[name] = f"{name}-value"
                with patch.dict(os.environ, values, clear=True):
                    self.assertEqual(
                        anthropic_config.anthropic_api_key(),
                        f"{name}-value",
                    )

    def test_fly_missing_key_can_be_required_or_optional(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(anthropic_config.anthropic_api_key(required=False))
            with self.assertRaisesRegex(RuntimeError, "WANDER_ANTHROPIC_API_KEY"):
                anthropic_config.anthropic_api_key()

    def test_skill_prefers_wander_and_defaults_to_current_model(self):
        with patch.dict(os.environ, {}, clear=True):
            skill = load_skill_run()
        self.assertEqual(skill.DEFAULT_ANTHROPIC_MODEL, "claude-sonnet-4-6")
        self.assertEqual(skill.CLASSIFIER_MODEL, "claude-sonnet-4-6")
        self.assertEqual(skill.SPECIALIST_MODEL, "claude-sonnet-4-6")

        values = {
            "WANDER_ANTHROPIC_API_KEY": "wander-key",
            "SIM_ANTHROPIC_API_KEY": "sim-key",
            "ANTHROPIC_API_KEY": "generic-key",
            "JMC_ANTHROPIC_API_KEY": "jmc-key",
        }
        with patch.dict(os.environ, values, clear=True):
            self.assertEqual(skill._find_anthropic_key(), "wander-key")

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
