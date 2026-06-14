#!/usr/bin/env python3
"""Generate one-time Simulacrum signup codes and optionally sync Fly secrets.

Usage:
    python3 scripts/generate_signup_codes.py --count 10
    python3 scripts/generate_signup_codes.py --count 10 --sync-fly
"""

from __future__ import annotations

import argparse
import secrets
import string
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CODES_FILE = ROOT / "signup_codes.txt"
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_code() -> str:
    chunks = ["".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(3)]
    return f"SIM-{'-'.join(chunks)}"


def read_codes(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.strip().startswith("#")]


def append_codes(path: Path, count: int) -> list[str]:
    existing = set(read_codes(path))
    generated: list[str] = []
    while len(generated) < count:
        code = generate_code()
        if code not in existing:
            generated.append(code)
            existing.add(code)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for code in generated:
            handle.write(f"{code}\n")
    return generated


def sync_fly_secret(app: str, codes: list[str]) -> None:
    subprocess.run(
        ["fly", "secrets", "set", "--app", app, f"SIGNUP_CODES={','.join(codes)}"],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate one-time Simulacrum signup codes.")
    parser.add_argument("--count", type=int, default=10, help="Number of codes to generate.")
    parser.add_argument("--codes-file", type=Path, default=DEFAULT_CODES_FILE, help="Gitignored raw-code file.")
    parser.add_argument("--sync-fly", action="store_true", help="Sync all raw codes into the Fly SIGNUP_CODES secret.")
    parser.add_argument("--app", default="simulacrum-jmc", help="Fly app name for --sync-fly.")
    args = parser.parse_args()

    if args.count < 1:
        parser.error("--count must be at least 1")

    generated = append_codes(args.codes_file, args.count)
    print(f"Generated {len(generated)} signup codes:")
    for code in generated:
        print(code)

    if args.sync_fly:
        sync_fly_secret(args.app, read_codes(args.codes_file))
        print(f"Synced {len(read_codes(args.codes_file))} raw codes to Fly app {args.app}.")
        print("The app will seed new hashes on restart; existing used codes remain one-time use.")
    else:
        print("Not synced to Fly. Re-run with --sync-fly before issuing these codes in production.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
