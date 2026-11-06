"""Database access for Mission Control.

Two kinds of SQLite connections live here:

* Read-only connections to Hermes' own state.db files (one per profile) and to
  the shared kanban.db.  These are opened with ``file:<path>?mode=ro`` and
  ``PRAGMA query_only=ON`` so Mission Control can *never* write into Hermes.
* A single writable Mission Control database (``MC_DB``) that holds snapshots
  and alerts.  This is a brand-new file that Hermes never touches.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time

# --- Paths (all overridable via env for tests / alternate deployments) -----
HERMES_STATE_DB = os.environ.get("MC_HERMES_STATE_DB", "/opt/data/state.db")
HERMES_PROFILES_DIR = os.environ.get("MC_PROFILES_DIR", "/opt/data/profiles")
KANBAN_DB = os.environ.get("MC_KANBAN_DB", "/opt/data/kanban.db")

_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
MC_DB = os.environ.get(
    "MC_DB", os.path.join(os.path.dirname(_SERVER_DIR), "data", "mc.db")
)

SCHEMA_PATH = os.path.join(_SERVER_DIR, "schema.sql")

# The 16 bot profiles, plus the CEO whose state.db lives at the root.
BOT_NAMES = [
    "atlas", "byline", "cask", "keel", "kestrel", "keystone", "ledger",
    "meridian", "nimbus", "piston", "prism", "quill", "relay", "sable",
    "seal", "vera",
]

# Serializes all writes to the writable MC database (snapshot + alert inserts).
_mc_write_lock = threading.Lock()


def mc_lock():
    """Context manager guarding writes to the MC database."""
    return _mc_write_lock


def profiles() -> list[tuple[str, str]]:
    """Return the ordered ``(profile_name, state_db_path)`` pairs.

    CEO first, then the 16 bot profiles.  This list drives the ``agents``
    panel (17 agents total).
    """
    out: list[tuple[str, str]] = [("ceo", HERMES_STATE_DB)]
    for name in BOT_NAMES:
        out.append((name, os.path.join(HERMES_PROFILES_DIR, name, "state.db")))
    return out


def open_ro(path: str) -> sqlite3.Connection:
    """Open a Hermes/kanban SQLite file strictly read-only.

    ``mode=ro`` makes SQLite refuse writes at the engine level; ``query_only``
    adds a second, belt-and-braces guard.  A missing file yields a connection
    whose queries return nothing rather than raising, so the dashboard stays up
    even if one profile db is absent.
    """
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    return con


def open_mc() -> sqlite3.Connection:
    """Open the writable Mission Control database (WAL mode)."""
    os.makedirs(os.path.dirname(MC_DB), exist_ok=True)
    con = sqlite3.connect(MC_DB, timeout=10.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA foreign_keys = ON")
    return con


def open_mc_ro() -> sqlite3.Connection:
    """Open the MC database read-only (for the reducer's pending-approvals read).

    Raises ``sqlite3.OperationalError`` if the file does not exist yet; callers
    should tolerate that (treat as "no data").
    """
    con = sqlite3.connect(f"file:{MC_DB}?mode=ro", uri=True, timeout=5.0)
    con.row_factory = sqlite3.Row
    return con


def init_mc_db() -> None:
    """Create the MC database and its tables if they don't exist."""
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        schema = fh.read()
    with _mc_write_lock:
        con = open_mc()
        try:
            con.executescript(schema)
            con.commit()
        finally:
            con.close()


# --- Path-A event / approval persistence ------------------------------------

def insert_event(con: sqlite3.Connection, ev: dict) -> int:
    """Insert one emitter event; returns the rowcount (1 new, 0 duplicate)."""
    data = ev.get("data")
    data_json = json.dumps(data) if data is not None else None
    cur = con.execute(
        "INSERT OR IGNORE INTO events (id, ts, run_id, agent_id, type, data) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ev.get("id"), ev.get("ts"), ev.get("run_id"),
         ev.get("agent_id"), ev.get("type"), data_json),
    )
    return cur.rowcount


def insert_approval(con: sqlite3.Connection, request_id: str, agent: str,
                    kind: str, payload: dict, requested_at: float) -> int:
    """Insert a pending approval; rowcount 0 if that request_id already exists."""
    cur = con.execute(
        "INSERT OR IGNORE INTO approvals "
        "(request_id, agent, kind, payload_json, status, requested_at) "
        "VALUES (?, ?, ?, ?, 'pending', ?)",
        (request_id, agent, kind, json.dumps(payload), requested_at),
    )
    return cur.rowcount


def _iso(ts: float | None) -> str | None:
    if not ts:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _approval_dict(row: sqlite3.Row) -> dict:
    """Canonical API shape for an approval row (DB 'rejected' -> API 'denied')."""
    payload = {}
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except (ValueError, TypeError):
        payload = {}
    status = row["status"]
    if status in ("rejected", "cancelled"):
        status = "denied"
    return {
        "id": row["id"],
        "request_id": row["request_id"],
        "agent": row["agent"],
        "kind": row["kind"],
        "action": payload.get("action", ""),
        "risk": payload.get("risk", "med"),
        "status": status,
        "requested_at": row["requested_at"],
        "requested_at_iso": _iso(row["requested_at"]),
        "decided_at": row["decided_at"],
        "decided_by": row["decided_by"],
    }


def _find_approval(con: sqlite3.Connection, identifier: str) -> sqlite3.Row | None:
    """Resolve an approval by request_id first, then numeric id."""
    row = con.execute(
        "SELECT * FROM approvals WHERE request_id = ?", (identifier,)
    ).fetchone()
    if row is None and str(identifier).isdigit():
        row = con.execute(
            "SELECT * FROM approvals WHERE id = ?", (int(identifier),)
        ).fetchone()
    return row


def get_approval(identifier: str) -> dict | None:
    """Return one approval (any status) as the canonical dict, or None."""
    try:
        con = open_mc_ro()
    except Exception:
        return None
    try:
        row = _find_approval(con, identifier)
        return _approval_dict(row) if row is not None else None
    finally:
        con.close()


def list_pending_approvals() -> list[dict]:
    """Pending approvals, newest first (for /v1/state.approvals + GET)."""
    try:
        con = open_mc_ro()
    except Exception:
        return []
    try:
        rows = con.execute(
            "SELECT * FROM approvals WHERE status = 'pending' "
            "ORDER BY requested_at DESC, id DESC"
        ).fetchall()
    finally:
        con.close()
    return [_approval_dict(r) for r in rows]


def decide_approval(identifier: str, status: str, decided_by: str,
                    now: float) -> dict | None:
    """Set a pending approval to ``status``; returns the updated row, or None
    if not found.  Raises ``LookupError`` if already decided (409 upstream)."""
    with mc_lock():
        con = open_mc()
        try:
            row = _find_approval(con, identifier)
            if row is None:
                return None
            if row["status"] != "pending":
                raise LookupError(f"approval already {row['status']}")
            con.execute(
                "UPDATE approvals SET status = ?, decided_at = ?, decided_by = ? "
                "WHERE id = ?",
                (status, now, decided_by, row["id"]),
            )
            con.commit()
            updated = _find_approval(con, identifier)
            return _approval_dict(updated) if updated is not None else None
        finally:
            con.close()
