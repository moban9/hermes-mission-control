"""Time-boxed guest viewer tokens for Mission Control.

Owner token (``MC_VIEWER_TOKEN``) never expires — it is the operator's own.
Guest tokens are minted with a TTL, stored **hashed** (sha256) in SQLite, and
rejected automatically once expired or revoked.

CLI (``python tokens.py ...``) or import:
    issue(label, days) -> (token, expires_at)
    check(token)       -> bool
    listing()          -> rows
    revoke(label_or_hash)
    prune()
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time

DB_PATH = os.environ.get("MC_TOKEN_DB", "/opt/data/cache/mc_tokens.db")


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=5)
    con.execute(
        """CREATE TABLE IF NOT EXISTS guest_tokens (
               token_hash TEXT PRIMARY KEY,
               label      TEXT,
               created_at REAL NOT NULL,
               expires_at REAL NOT NULL,
               revoked    INTEGER NOT NULL DEFAULT 0
           )"""
    )
    return con


def _hash(tok: str) -> str:
    return hashlib.sha256(tok.encode("utf-8")).hexdigest()


def issue(label: str = "guest", days: float = 1.0) -> tuple[str, float]:
    """Mint a guest token valid for ``days``. Returns (token, expires_at)."""
    tok = "mc-g-" + secrets.token_urlsafe(24)
    now = time.time()
    exp = now + float(days) * 86400.0
    with _conn() as con:
        con.execute(
            "INSERT INTO guest_tokens (token_hash, label, created_at, expires_at, revoked) VALUES (?,?,?,?,0)",
            (_hash(tok), label, now, exp),
        )
    return tok, exp


def check(tok: str | None) -> bool:
    """True only for a live guest token."""
    if not tok or not tok.startswith("mc-g-"):
        return False
    try:
        with _conn() as con:
            row = con.execute(
                "SELECT expires_at, revoked FROM guest_tokens WHERE token_hash = ?",
                (_hash(tok),),
            ).fetchone()
    except sqlite3.Error:
        return False
    if not row:
        return False
    expires_at, revoked = row
    return not revoked and time.time() < float(expires_at)


def listing() -> list[tuple]:
    with _conn() as con:
        return con.execute(
            "SELECT label, created_at, expires_at, revoked FROM guest_tokens ORDER BY created_at DESC"
        ).fetchall()


def revoke(label_or_hash: str) -> int:
    with _conn() as con:
        con.execute(
            "UPDATE guest_tokens SET revoked = 1 WHERE label = ? OR token_hash = ?",
            (label_or_hash, label_or_hash),
        )
        return con.total_changes


def prune() -> int:
    """Drop expired + revoked rows. Returns rows removed."""
    with _conn() as con:
        con.execute(
            "DELETE FROM guest_tokens WHERE expires_at < ? OR revoked = 1", (time.time(),)
        )
        return con.total_changes


def _fmt(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Mission Control guest tokens")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("issue", help="mint a guest token")
    i.add_argument("--label", default="guest")
    i.add_argument("--days", type=float, default=1.0)
    sub.add_parser("list", help="list guest tokens")
    r = sub.add_parser("revoke", help="revoke by label or hash")
    r.add_argument("target")
    sub.add_parser("prune", help="delete expired/revoked rows")
    a = ap.parse_args()

    if a.cmd == "issue":
        tok, exp = issue(a.label, a.days)
        print(f"token:   {tok}")
        print(f"label:   {a.label}")
        print(f"expires: {_fmt(exp)} ({a.days:g} day(s))")
    elif a.cmd == "list":
        rows = listing()
        if not rows:
            print("no guest tokens")
        for label, created, exp, rev in rows:
            state = "REVOKED" if rev else ("EXPIRED" if time.time() >= exp else "active")
            print(f"{label:20s} created {_fmt(created)}  expires {_fmt(exp)}  {state}")
    elif a.cmd == "revoke":
        print(f"revoked {revoke(a.target)} row(s)")
    elif a.cmd == "prune":
        print(f"pruned {prune()} row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
