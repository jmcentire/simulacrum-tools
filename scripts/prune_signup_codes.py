#!/usr/bin/env python3
"""Prune signup_codes.txt down to codes that are still valid in the live DB.

"Valid" means: the code was seeded into the `signup_codes` table and has not
been consumed (redeemed at signup). Usage is tracked only in the database
(`consumed_at`), never in the raw-code file -- so this is the only way to tell
which hand-out codes are still usable.

Because code hashes are HMAC-keyed by SIMULACRUM_TOKEN, this script needs both
the production DB and that secret. Two ways to run it:

  A) On the Fly machine (it already has the DB + secret):
       fly ssh console -a simulacrum-jmc
       # upload your codes first, e.g. via `fly ssh sftp shell` -> put
       python3 scripts/prune_signup_codes.py --db /data/simulacrum.db --codes /tmp/signup_codes.txt --write

  B) Locally, after fetching the DB and the token:
       fly ssh console -a simulacrum-jmc -C "printenv SIMULACRUM_TOKEN"
       fly ssh sftp get /data/simulacrum.db ./prod.db -a simulacrum-jmc
       SIMULACRUM_TOKEN=<token> python3 scripts/prune_signup_codes.py \
           --db ./prod.db --codes signup_codes.txt --write

Without --write it only reports; with --write it rewrites the codes file
(keeping a .bak) to contain just the still-valid codes.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import sqlite3
import sys
from pathlib import Path


def hash_value(value: str, secret: bytes) -> str:
    return hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()


def read_codes(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--codes", type=Path, default=Path(__file__).resolve().parents[1] / "signup_codes.txt")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("SIMULACRUM_DB", str(Path.home() / ".simulacrum" / "simulacrum.db"))),
    )
    parser.add_argument("--write", action="store_true", help="Rewrite the codes file with only valid codes.")
    parser.add_argument(
        "--drop-unknown",
        action="store_true",
        help="Also drop codes not present in the DB. Default keeps them, since freshly "
        "generated codes are 'not in DB' until you sync + restart (sync first, then prune).",
    )
    args = parser.parse_args()

    secret = os.environ.get("SIMULACRUM_TOKEN")
    if not secret:
        print("error: SIMULACRUM_TOKEN must be set (the HMAC key used to hash codes).", file=sys.stderr)
        return 2
    if not args.db.exists():
        print(f"error: DB not found at {args.db}", file=sys.stderr)
        return 2
    if not args.codes.exists():
        print(f"error: codes file not found at {args.codes}", file=sys.stderr)
        return 2

    secret_bytes = secret.encode()
    codes = read_codes(args.codes)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    valid: list[str] = []
    consumed: list[str] = []
    unknown: list[str] = []
    reserved: list[str] = []

    for code in codes:
        row = conn.execute(
            "SELECT consumed_at, reserved_at FROM signup_codes WHERE code_hash = ?",
            (hash_value(code, secret_bytes),),
        ).fetchone()
        if row is None:
            unknown.append(code)
        elif row["consumed_at"] is not None:
            consumed.append(code)
        else:
            valid.append(code)
            if row["reserved_at"] is not None:
                reserved.append(code)

    unknown_action = "drop" if args.drop_unknown else "kept (not yet synced?)"
    print(f"checked {len(codes)} codes against {args.db}")
    print(f"  valid (kept):     {len(valid)}")
    print(f"  consumed (drop):  {len(consumed)}")
    print(f"  not in DB ({unknown_action}): {len(unknown)}")
    if reserved:
        print(f"  (of valid, {len(reserved)} are reserved mid-signup but not yet consumed)")
    for code in consumed:
        print(f"    consumed:  {code}")
    for code in unknown:
        print(f"    not-in-db: {code}")

    # Reserved-but-not-consumed codes are still valid (the hold may expire), so keep them.
    # Codes absent from the DB are kept by default: freshly generated codes read as
    # "not in DB" until they are synced and the app restarts. Sync first, then prune.
    keep = list(valid) if args.drop_unknown else list(valid) + list(unknown)
    if args.write:
        backup = args.codes.with_suffix(args.codes.suffix + ".bak")
        backup.write_text(args.codes.read_text())
        args.codes.write_text("".join(f"{code}\n" for code in keep))
        print(f"wrote {len(keep)} codes to {args.codes} (backup at {backup})")
    else:
        print("dry run -- re-run with --write to rewrite the codes file.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
