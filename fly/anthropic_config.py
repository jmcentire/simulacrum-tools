"""Shared Anthropic model and API-key configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULT_ANTHROPIC_MODEL = (
    os.environ.get("SIMULACRUM_MODEL", "").strip() or "claude-sonnet-4-6"
)

# Which environment variables hold the Anthropic key, in preference order.
# The default is the vendor-standard name. An operator who bills through
# differently named variables configures the ordered list as machine data,
# never repo data:
#   1. SIMULACRUM_ANTHROPIC_API_KEY_ENV="FIRST_NAME,SECOND_NAME"
#      (env var / Fly secret), or
#   2. {"anthropic_api_key_env": ["FIRST_NAME", "SECOND_NAME"]} in
#      $XDG_CONFIG_HOME/simulacrum/config.json (default ~/.config/...).
# See config.example.json at the repo root.
DEFAULT_ANTHROPIC_API_KEY_ENV_VARS: tuple[str, ...] = ("ANTHROPIC_API_KEY",)
API_KEY_ENV_OVERRIDE = "SIMULACRUM_ANTHROPIC_API_KEY_ENV"


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(base) if base else Path.home() / ".config"
    return root / "simulacrum" / "config.json"


def anthropic_api_key_env_vars() -> tuple[str, ...]:
    """Return the ordered env-var names to try for the Anthropic key."""
    override = os.environ.get(API_KEY_ENV_OVERRIDE, "")
    names = tuple(n.strip() for n in override.split(",") if n.strip())
    if names:
        return names
    path = config_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"simulacrum: cannot read config {path}: {exc}") from exc
        configured = data.get("anthropic_api_key_env") if isinstance(data, dict) else None
        if configured is not None:
            if not (
                isinstance(configured, list)
                and all(isinstance(n, str) and n.strip() for n in configured)
            ):
                raise RuntimeError(
                    f"simulacrum: {path}: anthropic_api_key_env must be a list of "
                    "environment variable names"
                )
            if configured:
                return tuple(n.strip() for n in configured)
    return DEFAULT_ANTHROPIC_API_KEY_ENV_VARS


def anthropic_api_key(*, required: bool = True) -> str | None:
    """Resolve the Anthropic key from the first configured env var that is set."""
    names = anthropic_api_key_env_vars()
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    if required:
        raise RuntimeError(
            f"Set {' or '.join(names)} (variable names are configurable via "
            f"{API_KEY_ENV_OVERRIDE})."
        )
    return None
