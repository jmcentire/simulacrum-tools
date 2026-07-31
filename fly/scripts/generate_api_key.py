#!/usr/bin/env python3
"""Mint, list, or revoke Simulacrum API keys.

Key hashes are HMAC-keyed by SIMULACRUM_TOKEN, so this must run in the same
environment as the app (same SIMULACRUM_TOKEN and SIMULACRUM_DB). In
production that means on the Fly machine:

    fly ssh console -a simulacrum-jmc -C \
        "python3 /app/scripts/generate_api_key.py someone@example.com --label partner"

Usage:
    generate_api_key.py EMAIL                       # mint a fresh key
    generate_api_key.py EMAIL --key RAW_KEY         # register a pre-provisioned key
    generate_api_key.py EMAIL --daily-cap 500       # per-key cap override
    generate_api_key.py EMAIL --list
    generate_api_key.py EMAIL --revoke KEY_ID
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auth  # noqa: E402
import db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Mint, list, or revoke Simulacrum API keys.")
    parser.add_argument("email", help="Account email the key belongs to (created if missing).")
    parser.add_argument("--label", default="", help="Human-readable label for the key.")
    parser.add_argument("--key", default=None, help="Register this pre-provisioned key value instead of generating one.")
    parser.add_argument("--daily-cap", type=int, default=None, help="Per-key daily request cap (default: API_CAP_PER_WINDOW env).")
    parser.add_argument("--list", action="store_true", help="List the account's keys instead of minting.")
    parser.add_argument("--revoke", metavar="KEY_ID", default=None, help="Revoke a key by id instead of minting.")
    args = parser.parse_args()

    db.init_db()

    if args.list:
        keys = auth.list_api_keys(args.email)
        if not keys:
            print(f"No API keys for {args.email}.")
            return 0
        for key in keys:
            status = "revoked" if key["revoked_at"] else "active"
            cap = key["daily_cap"] or auth.API_CAP_PER_WINDOW
            print(f"{key['id']}  {status}  label={key['label'] or '-'}  cap={cap}/day  used_window={key['window_count']}  last_used_at={key['last_used_at']}")
        return 0

    if args.revoke:
        if auth.revoke_api_key(args.revoke):
            print(f"Revoked key {args.revoke}.")
            return 0
        print(f"No active key with id {args.revoke}.", file=sys.stderr)
        return 1

    raw = auth.create_api_key(args.email, label=args.label, daily_cap=args.daily_cap, raw_key=args.key)
    if args.key:
        print(f"Registered pre-provisioned API key for {args.email} (label={args.label or '-'}).")
    else:
        print(f"API key for {args.email} (shown once, store it now):")
        print(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
