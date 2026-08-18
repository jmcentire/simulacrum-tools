"""Shared Anthropic model and billing-key configuration."""

from __future__ import annotations

import os


DEFAULT_ANTHROPIC_MODEL = (
    os.environ.get("SIMULACRUM_MODEL", "").strip() or "claude-sonnet-4-6"
)
ANTHROPIC_API_KEY_ENV_VARS = (
    "WANDER_ANTHROPIC_API_KEY",
    "SIM_ANTHROPIC_API_KEY",
    "ANTHROPIC_API_KEY",
    "JMC_ANTHROPIC_API_KEY",
)


def anthropic_api_key(*, required: bool = True) -> str | None:
    """Resolve Anthropic billing credentials, preferring the Wander account."""
    for name in ANTHROPIC_API_KEY_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    if required:
        raise RuntimeError(
            "Set WANDER_ANTHROPIC_API_KEY (preferred) or another Anthropic API key."
        )
    return None
