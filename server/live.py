"""Live path-A state overlay.

Holds the in-memory merge of ingested emitter events, keyed by ``agent_id``.
The reducer reads a deep copy via :func:`snapshot` and folds it into the agent
cards in ``/v1/state``.  A monotonic ``version`` counter lets the SSE loop (and
the snapshot fingerprint) detect that path-A state changed.

Merge semantics per event type (all data is the emitter's real payload):

* ``context.snapshot`` -> latest context snapshot (messages, tools,
  approx_input_tokens, max_tokens, model, …).
* ``llm.usage``        -> cumulative input/output tokens + latest latency_ms /
  context_length / finish_reason / model.
* ``tool.call``        -> per-tool invocation counts (start) and ok/duration
  (end); every tool.call also appends an event-stream row.
* ``agent.state``      -> latest agent state blob.

Nothing here touches the network or the filesystem; it is pure, thread-safe
in-memory state.  A restart drops it (path B data is unaffected — that lives in
Hermes' own dbs / memory files).
"""

from __future__ import annotations

import copy
import threading
import time
from datetime import datetime

_LOCK = threading.Lock()
_VERSION = 0
_AGENTS: dict[str, dict] = {}

# Bounded length of the per-agent recent tool-call stream.
_RECENT_TOOL_CALLS_MAX = 100

_CTX_FIELDS = (
    "session_id", "task_id", "model", "provider",
    "messages", "tools", "approx_input_tokens", "max_tokens",
)
_USAGE_ACCUM = ("input_tokens", "output_tokens")
_USAGE_LATEST = (
    "latency_ms", "context_length", "model", "provider",
    "finish_reason", "session_id", "task_id",
)


def version() -> int:
    with _LOCK:
        return _VERSION


def bump() -> None:
    """Signal that path-A state changed (e.g. an approval decision)."""
    global _VERSION
    with _LOCK:
        _VERSION += 1


def parse_ts(ts) -> float | None:
    """Best-effort parse of the emitter's ISO ts (or a numeric ts) to unix."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    try:
        s = str(ts)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return None


def _blank_agent() -> dict:
    return {
        "context": None,
        "usage": None,
        "state": None,
        "tool_counts": {},
        "tool_stats": {},
        "recent_tool_calls": [],
    }


def _merge_context(prev, data, ts):
    out = dict(prev or {})
    for k in _CTX_FIELDS:
        if k in data:
            out[k] = data[k]
    out["updated_at"] = ts
    return out


def _merge_usage(prev, data, ts):
    out = dict(prev or {})
    for k in _USAGE_ACCUM:
        v = data.get(k)
        if isinstance(v, (int, float)):
            out[k] = int(out.get(k) or 0) + int(v)
    for k in _USAGE_LATEST:
        if k in data and data[k] is not None:
            out[k] = data[k]
    out["calls"] = int(out.get("calls") or 0) + 1
    out["last_seen"] = ts
    return out


def _merge_tool(agent: dict, data, ts, agent_id):
    tool = data.get("tool") or "unknown"
    phase = data.get("phase")
    counts = agent["tool_counts"]
    stats = agent["tool_stats"]

    if phase == "start":
        counts[tool] = counts.get(tool, 0) + 1
        st = stats.setdefault(tool, {"calls": 0, "ok": 0, "fail": 0, "total_duration_ms": 0.0})
        st["calls"] += 1
    elif phase == "end":
        # An end without a matching start still lands a row + a count.
        if counts.get(tool) is None:
            counts[tool] = 1
        st = stats.setdefault(tool, {"calls": 0, "ok": 0, "fail": 0, "total_duration_ms": 0.0})
        if data.get("ok") is True:
            st["ok"] += 1
        else:
            st["fail"] += 1
        dur = data.get("duration_ms")
        if isinstance(dur, (int, float)):
            st["total_duration_ms"] += float(dur)

    agent["recent_tool_calls"].append({
        "ts": ts,
        "agent": agent_id,
        "tool": tool,
        "phase": phase,
        "duration_ms": data.get("duration_ms"),
        "ok": data.get("ok"),
        "session_id": data.get("session_id"),
        "task_id": data.get("task_id"),
    })
    del agent["recent_tool_calls"][:-_RECENT_TOOL_CALLS_MAX]


def _merge_state(prev, data, ts):
    out = dict(prev or {})
    out.update(data)
    out["updated_at"] = ts
    return out


def merge_event(ev: dict) -> None:
    """Merge one accepted event into the live overlay."""
    global _VERSION
    agent_id = ev.get("agent_id") or "unknown"
    etype = ev.get("type")
    data = ev.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    ts = parse_ts(ev.get("ts")) or time.time()

    with _LOCK:
        a = _AGENTS.setdefault(agent_id, _blank_agent())
        if etype == "context.snapshot":
            a["context"] = _merge_context(a["context"], data, ts)
        elif etype == "llm.usage":
            a["usage"] = _merge_usage(a["usage"], data, ts)
        elif etype == "tool.call":
            _merge_tool(a, data, ts, agent_id)
        elif etype == "agent.state":
            a["state"] = _merge_state(a["state"], data, ts)
        _VERSION += 1


def snapshot() -> dict[str, dict]:
    """Deep copy of the whole live overlay (for the reducer)."""
    with _LOCK:
        return copy.deepcopy(_AGENTS)
