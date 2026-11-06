"""Memory-file reader (path B — real files, no hooks, no fabrication).

Each profile keeps two memory files: ``MEMORY.md`` (the agent's own notes) and
``USER.md`` (its model of the user).  Facts are separated by the ``§`` marker
and are NOT individually timestamped — so the only honest "age" is the file's
mtime, which is exposed per fact rather than invented per-fact.

CEO lives at ``MC_MEMORIES_DIR`` (``/opt/data/memories``); the 16 bots at
``<profiles_dir>/<name>/memories``.
"""

from __future__ import annotations

import os
import threading
import time

# Cache: path -> (mtime, facts).  Re-reads only when the file mtime changes.
_CACHE: dict[str, tuple[float, list[str]]] = {}
_CACHE_LOCK = threading.Lock()


def _split(path: str) -> tuple[list[str], float | None]:
    """Return (facts, mtime) for one file; ([] , None) if unreadable."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return [], None

    with _CACHE_LOCK:
        hit = _CACHE.get(path)
        if hit is not None and hit[0] == mtime:
            return hit[1], mtime

    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return [], None

    facts = [f.strip() for f in raw.split("§")]
    facts = [f for f in facts if f.strip()]

    with _CACHE_LOCK:
        _CACHE[path] = (mtime, facts)
    return facts, mtime


def _iso(mtime: float | None) -> str | None:
    if not mtime:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mtime))


def read_agent_memory(memories_dir: str, profiles_dir: str, name: str,
                      now: float) -> dict:
    """One agent's memory: facts + user facts, each carrying the file mtime."""
    if name == "ceo":
        base = memories_dir
    else:
        base = os.path.join(profiles_dir, name, "memories")

    mem_facts, mem_mtime = _split(os.path.join(base, "MEMORY.md"))
    user_facts, user_mtime = _split(os.path.join(base, "USER.md"))

    def _wrap(facts: list[str], mtime: float | None) -> list[dict]:
        return [
            {
                "text": t,
                "mtime": mtime,
                "mtime_iso": _iso(mtime),
                "age_s": round(now - mtime, 1) if mtime else None,
            }
            for t in facts
        ]

    return {
        "facts": _wrap(mem_facts, mem_mtime),
        "user_facts": _wrap(user_facts, user_mtime),
        "facts_mtime": mem_mtime,
        "user_facts_mtime": user_mtime,
    }
