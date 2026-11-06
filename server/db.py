"""Database access for Mission Control.

Two kinds of SQLite connections live here:

* Read-only connections to Hermes' own state.db files (one per profile) and to
  the shared kanban.db.  These are opened with ``file:<path>?mode=ro`` and
  ``PRAGMA query_only=ON`` so Mission Control can *never* write into Hermes.
* A single writable Mission Control database (``MC_DB``) that holds snapshots
  and alerts.  This is a brand-new file that Hermes never touches.
"""

from __future__ import annotations

import os
import sqlite3
import threading

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
