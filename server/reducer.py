"""Reducer: derive the live Mission Control state from Hermes' raw databases.

Read-only.  Aggregates one state.db per profile (17 total) plus the shared
kanban.db, and shapes the result to match the panel mapping in
``docs/state-map.md``:

    agents        <- sessions
    tasks         <- kanban.db tasks
    events        <- messages (role, tool_name, timestamp)
    tool_counts   <- messages.tool_name counts
    throughput    <- session_model_usage + sessions tokens
    cost_forecast <- sessions.estimated_cost_usd + daily history
    kpis / alerts <- derived
"""

from __future__ import annotations

import os
import time

import db
import alerts
import live as live_mod
import memory as memory_mod
import settings

# How many recent events to surface in /v1/state.
EVENT_LIMIT = int(os.environ.get("MC_EVENT_LIMIT", "300"))

# Status thresholds (seconds of silence).
ONLINE_AFTER_S = float(os.environ.get("MC_ONLINE_AFTER_S", "30"))

_EVENT_COLS = ("id", "session_id", "role", "tool_name", "timestamp")


def _now_iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _live_tool_stats(stats: dict) -> dict:
    """Derive per-tool averages from the live overlay's raw counters."""
    out = {}
    for tool, st in (stats or {}).items():
        calls = int(st.get("calls") or 0)
        total = float(st.get("total_duration_ms") or 0.0)
        out[tool] = {
            "calls": calls,
            "ok": int(st.get("ok") or 0),
            "fail": int(st.get("fail") or 0),
            "total_duration_ms": total,
            "avg_duration_ms": round(total / calls, 2) if calls else None,
        }
    return out


def reduce_agent(name: str, path: str, now: float) -> dict:
    """Build one agent card from a single profile's state.db."""
    try:
        con = db.open_ro(path)
    except Exception:
        con = None

    agent: dict = {
        "name": name,
        "model": None,
        "status": "offline",
        "last_activity_at": None,
        "last_activity_age_s": None,
        "last_activity_description": "",
        "title": None,
        "current_action": None,
        "active_session_id": None,
        "active_session_started_at": None,
        "session_count": 0,
        "message_count": 0,
        "tool_call_count": 0,
        "tokens": {
            "input": 0, "output": 0, "cache_read": 0,
            "cache_write": 0, "reasoning": 0, "total": 0,
        },
        "cost_usd": 0.0,
        "actual_cost_usd": 0.0,
    }

    if con is None:
        return agent

    try:
        agg = con.execute(
            """
            SELECT COUNT(*)                                          AS session_count,
                   COALESCE(SUM(message_count), 0)                   AS message_count,
                   COALESCE(SUM(tool_call_count), 0)                 AS tool_call_count,
                   COALESCE(SUM(input_tokens), 0)                    AS input_tokens,
                   COALESCE(SUM(output_tokens), 0)                   AS output_tokens,
                   COALESCE(SUM(cache_read_tokens), 0)               AS cache_read,
                   COALESCE(SUM(cache_write_tokens), 0)              AS cache_write,
                   COALESCE(SUM(reasoning_tokens), 0)                AS reasoning,
                   COALESCE(SUM(estimated_cost_usd), 0)              AS cost_usd,
                   COALESCE(SUM(actual_cost_usd), 0)                 AS actual_cost_usd,
                   MAX(last_activity_at)                             AS last_activity_at
            FROM sessions
            """
        ).fetchone()

        latest = con.execute(
            """
            SELECT id, model, title, last_activity_at, last_activity_description,
                   started_at, ended_at
            FROM sessions
            ORDER BY last_activity_at DESC NULLS LAST, started_at DESC
            LIMIT 1
            """
        ).fetchone()

        cur_action = con.execute(
            """
            SELECT tool_name FROM messages
            WHERE tool_name IS NOT NULL AND tool_name != ''
            ORDER BY timestamp DESC, id DESC LIMIT 1
            """
        ).fetchone()

        active = con.execute(
            """
            SELECT id, started_at, last_activity_at FROM sessions
            WHERE ended_at IS NULL
            ORDER BY last_activity_at DESC LIMIT 1
            """
        ).fetchone()
    finally:
        con.close()

    inp = int(agg["input_tokens"] or 0)
    out = int(agg["output_tokens"] or 0)
    agent["session_count"] = int(agg["session_count"] or 0)
    agent["message_count"] = int(agg["message_count"] or 0)
    agent["tool_call_count"] = int(agg["tool_call_count"] or 0)
    agent["tokens"] = {
        "input": inp,
        "output": out,
        "cache_read": int(agg["cache_read"] or 0),
        "cache_write": int(agg["cache_write"] or 0),
        "reasoning": int(agg["reasoning"] or 0),
        "total": inp + out,
    }
    agent["cost_usd"] = round(float(agg["cost_usd"] or 0.0), 6)
    agent["actual_cost_usd"] = round(float(agg["actual_cost_usd"] or 0.0), 6)

    if latest is not None:
        agent["model"] = latest["model"]
        agent["title"] = latest["title"]
        agent["last_activity_description"] = latest["last_activity_description"] or ""
        agent["last_activity_at"] = latest["last_activity_at"]

    if cur_action is not None:
        agent["current_action"] = cur_action["tool_name"]

    if active is not None:
        agent["active_session_id"] = active["id"]
        agent["active_session_started_at"] = active["started_at"]
        agent["_active_session_last_activity_at"] = active["last_activity_at"]

    last = agent["last_activity_at"]
    if last is not None:
        agent["last_activity_age_s"] = round(max(0.0, now - float(last)), 3)

    # Status: online within the window; "stuck" if the agent's open session was
    # active recently (within the engagement window) but has now gone silent
    # past the stuck threshold; otherwise offline (idle/finished).
    age = agent["last_activity_age_s"]
    active_last = agent.get("_active_session_last_activity_at")
    active_age = (
        round(max(0.0, now - float(active_last)), 3)
        if active_last is not None
        else None
    )
    if age is None:
        agent["status"] = "offline"
    elif age <= ONLINE_AFTER_S:
        agent["status"] = "online"
    elif (
        active_age is not None
        and active_age > alerts.STUCK_AFTER_S
        and active_age <= alerts.STUCK_ENGAGEMENT_WINDOW_S
    ):
        agent["status"] = "stuck"
    else:
        agent["status"] = "offline"

    agent.pop("_active_session_last_activity_at", None)

    return agent


def reduce_tasks() -> tuple[list[dict], dict]:
    """Return (task list, task KPI counters) from kanban.db."""
    con = db.open_ro(db.KANBAN_DB)
    try:
        rows = con.execute(
            """
            SELECT id, title, assignee, status, priority, created_at,
                   started_at, completed_at, block_kind, consecutive_failures,
                   workspace_path,
                   (SELECT group_concat(parent_id) FROM task_links WHERE child_id = tasks.id) AS parent_ids,
                   (SELECT COUNT(*) FROM task_links WHERE parent_id = tasks.id) AS child_count
            FROM tasks ORDER BY created_at DESC
            """
        ).fetchall()
    finally:
        con.close()

    queued_statuses = {"todo", "ready", "triage", "scheduled"}
    tasks = []
    kpi = {
        "tasks_total": 0, "tasks_queued": 0, "tasks_running": 0,
        "tasks_done": 0, "tasks_blocked": 0, "tasks_failed": 0,
    }
    for r in rows:
        st = r["status"] or ""
        kpi["tasks_total"] += 1
        if st in queued_statuses:
            kpi["tasks_queued"] += 1
        if st == "running":
            kpi["tasks_running"] += 1
        if st == "done":
            kpi["tasks_done"] += 1
        if st == "blocked" or r["block_kind"]:
            kpi["tasks_blocked"] += 1
        if (r["consecutive_failures"] or 0) > 0:
            kpi["tasks_failed"] += 1
        tasks.append({
            "id": r["id"],
            "title": r["title"],
            "assignee": r["assignee"],
            "status": st,
            "priority": r["priority"],
            "created_at": r["created_at"],
            "started_at": r["started_at"],
            "completed_at": r["completed_at"],
            "block_kind": r["block_kind"],
            "parent_id": r["parent_ids"],
            "child_count": r["child_count"] or 0,
        })
    return tasks, kpi


def reduce_events(now: float, limit: int = EVENT_LIMIT) -> list[dict]:
    """Recent message stream across every profile, newest first."""
    per_db = 200
    merged: list[dict] = []
    for name, path in db.profiles():
        try:
            con = db.open_ro(path)
        except Exception:
            continue
        try:
            rows = con.execute(
                """
                SELECT id, session_id, role, tool_name, timestamp, content
                FROM messages
                ORDER BY timestamp DESC, id DESC LIMIT ?
                """,
                (per_db,),
            ).fetchall()
        finally:
            con.close()
        for r in rows:
            text = _preview(r["content"])
            merged.append({
                "ts": r["timestamp"],
                "agent": name,
                "session_id": r["session_id"],
                "role": r["role"],
                "tool_name": r["tool_name"],
                "text": text,
            })
    merged.sort(key=lambda e: (e["ts"] or 0,), reverse=True)
    return merged[:limit]


def reduce_tool_counts() -> dict[str, int]:
    """Total tool_name invocation counts across every profile."""
    counts: dict[str, int] = {}
    for _, path in db.profiles():
        try:
            con = db.open_ro(path)
        except Exception:
            continue
        try:
            rows = con.execute(
                """
                SELECT tool_name, COUNT(*) AS n FROM messages
                WHERE tool_name IS NOT NULL AND tool_name != ''
                GROUP BY tool_name
                """
            ).fetchall()
        finally:
            con.close()
        for r in rows:
            counts[r["tool_name"]] = counts.get(r["tool_name"], 0) + int(r["n"])
    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))


def reduce_usage() -> dict:
    """Per-model usage + throughput from session_model_usage across profiles."""
    models: dict[str, dict] = {}
    total_api_calls = 0
    for _, path in db.profiles():
        try:
            con = db.open_ro(path)
        except Exception:
            continue
        try:
            rows = con.execute(
                """
                SELECT model, billing_provider, api_call_count, input_tokens,
                       output_tokens, cache_read_tokens, cache_write_tokens,
                       reasoning_tokens, estimated_cost_usd, first_seen, last_seen
                FROM session_model_usage
                """
            ).fetchall()
        finally:
            con.close()
        for r in rows:
            model = r["model"] or "unknown"
            m = models.setdefault(model, {
                "model": model,
                "billing_provider": r["billing_provider"],
                "api_calls": 0, "input_tokens": 0, "output_tokens": 0,
                "cache_read_tokens": 0, "cache_write_tokens": 0,
                "reasoning_tokens": 0, "cost_usd": 0.0,
                "first_seen": None, "last_seen": None,
            })
            m["api_calls"] += int(r["api_call_count"] or 0)
            m["input_tokens"] += int(r["input_tokens"] or 0)
            m["output_tokens"] += int(r["output_tokens"] or 0)
            m["cache_read_tokens"] += int(r["cache_read_tokens"] or 0)
            m["cache_write_tokens"] += int(r["cache_write_tokens"] or 0)
            m["reasoning_tokens"] += int(r["reasoning_tokens"] or 0)
            m["cost_usd"] += float(r["estimated_cost_usd"] or 0.0)
            m["first_seen"] = _earlier(m["first_seen"], r["first_seen"])
            m["last_seen"] = _later(m["last_seen"], r["last_seen"])
            total_api_calls += int(r["api_call_count"] or 0)

    for m in models.values():
        m["cost_usd"] = round(m["cost_usd"], 6)

    model_list = sorted(models.values(), key=lambda m: m["output_tokens"], reverse=True)
    return {
        "api_calls": total_api_calls,
        "models": model_list,
    }


def _tz():
    """Local day boundary for cost reporting (default: Randy's WIB)."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(os.environ.get("MC_TZ", "Asia/Jakarta"))
    except Exception:
        from datetime import timezone, timedelta
        return timezone(timedelta(hours=7))


def _local_day(ts: float) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(float(ts), _tz()).strftime("%Y-%m-%d")


def reduce_daily_cost() -> list[dict]:
    """Daily estimated cost across every profile, newest first.

    A session's cost is spread **pro-rata over its own [started_at,
    last_activity_at] window** rather than dumped on its final day, and each
    slice is bucketed by the LOCAL calendar day (MC_TZ, default Asia/Jakarta).
    Sessions that never overlapped a day boundary land entirely on their start
    day.  Invariant: sum(daily cost) == sum(session cost).
    """
    daily: dict[str, dict] = {}
    for _, path in db.profiles():
        try:
            con = db.open_ro(path)
        except Exception:
            continue
        try:
            rows = con.execute(
                "SELECT started_at, last_activity_at, estimated_cost_usd FROM sessions"
            ).fetchall()
        except Exception:
            rows = []
        finally:
            con.close()

        for r in rows:
            cost = float(r["estimated_cost_usd"] or 0.0)
            start_ts = r["started_at"] or r["last_activity_at"]
            if not start_ts:
                continue
            end_ts = r["last_activity_at"] or start_ts
            if end_ts < start_ts:
                end_ts = start_ts

            span = end_ts - start_ts
            day = _local_day(start_ts)
            entry = daily.setdefault(day, {"date": day, "sessions": 0, "cost_usd": 0.0})
            entry["sessions"] += 1
            if span <= 0 or cost <= 0:
                entry["cost_usd"] += cost
                continue

            # walk the window in day-sized chunks and allocate by overlap
            cursor = start_ts
            while cursor <= end_ts:
                chunk_end = min(end_ts, cursor + 86400.0)
                overlap = chunk_end - cursor
                share = cost * (overlap / span) if span else cost
                d = _local_day(cursor)
                e = daily.setdefault(d, {"date": d, "sessions": 0, "cost_usd": 0.0})
                e["cost_usd"] += share
                cursor = chunk_end + 0.001

    out = sorted(daily.values(), key=lambda e: e["date"], reverse=True)
    for e in out:
        e["cost_usd"] = round(e["cost_usd"], 6)
    return out


def reduce_failure_events(now: float, window_s: float | None = None) -> list[dict]:
    """Task-failure events from kanban.db within the burst window."""
    window_s = window_s if window_s is not None else alerts.ERROR_BURST_WINDOW_S
    cutoff = now - window_s
    con = db.open_ro(db.KANBAN_DB)
    try:
        q = ",".join("?" * len(alerts.FAILURE_EVENT_KINDS))
        rows = con.execute(
            f"""
            SELECT task_id, kind, created_at, payload
            FROM task_events
            WHERE kind IN ({q}) AND created_at >= ?
            ORDER BY created_at DESC
            """,
            (*alerts.FAILURE_EVENT_KINDS, cutoff),
        ).fetchall()
    finally:
        con.close()
    return [
        {"task_id": r["task_id"], "kind": r["kind"], "ts": r["created_at"]}
        for r in rows
    ]


def activity_fingerprint() -> tuple:
    """Cheap change detector: a value that changes when any watched source does.

    Used by the SSE loop to decide whether to do a full (expensive) reduce.
    Combines the highest message timestamp and session activity across all
    profile dbs with the highest kanban event id / task created_at.
    """
    max_msg_ts = 0.0
    max_last_act = 0.0
    for _, path in db.profiles():
        try:
            con = db.open_ro(path)
        except Exception:
            continue
        try:
            max_msg_ts = max(
                max_msg_ts,
                float(con.execute("SELECT COALESCE(MAX(timestamp),0) FROM messages").fetchone()[0] or 0.0),
            )
            max_last_act = max(
                max_last_act,
                float(con.execute("SELECT COALESCE(MAX(last_activity_at),0) FROM sessions").fetchone()[0] or 0.0),
            )
        finally:
            con.close()

    try:
        k = db.open_ro(db.KANBAN_DB)
        try:
            max_evt = int(k.execute("SELECT COALESCE(MAX(id),0) FROM task_events").fetchone()[0] or 0)
            max_task = int(k.execute("SELECT COALESCE(MAX(created_at),0) FROM tasks").fetchone()[0] or 0)
        finally:
            k.close()
    except Exception:
        max_evt = max_task = 0

    return (
        round(max_msg_ts, 4), round(max_last_act, 4), max_evt, max_task,
        live_mod.version(),
    )


def reduce_state(now: float | None = None, budget_usd: float | None = None) -> dict:
    """Full derived state.  The single entry point for the API + snapshots."""
    now = now if now is not None else time.time()
    budget_usd = budget_usd if budget_usd is not None else float(
        os.environ.get("MC_DAILY_BUDGET_USD", "10.0")
    )

    agents = [reduce_agent(name, path, now) for name, path in db.profiles()]

    # Path B memory (real files) + path A live overlay (ingested events).
    names = [name for name, _ in db.profiles()]
    memory_by_name = {
        n: memory_mod.read_agent_memory(
            settings.MEMORIES_DIR, db.HERMES_PROFILES_DIR, n, now
        )
        for n in names
    }
    live_agents = live_mod.snapshot()
    for agent in agents:
        name = agent["name"]
        agent["memory"] = memory_by_name.get(name)
        la = live_agents.get(name)
        if la:
            agent["context"] = la.get("context")
            agent["usage"] = la.get("usage")
            agent["state"] = la.get("state")
            agent["live_tool_counts"] = dict(la.get("tool_counts") or {})
            agent["tool_stats"] = _live_tool_stats(la.get("tool_stats"))
            agent["recent_tool_calls"] = list(la.get("recent_tool_calls") or [])

    tasks, task_kpi = reduce_tasks()
    events = reduce_events(now)
    tool_counts = reduce_tool_counts()
    usage = reduce_usage()
    daily = reduce_daily_cost()
    failure_events = reduce_failure_events(now)
    approvals = db.list_pending_approvals()

    today = _local_day(now)
    today_cost = sum(d["cost_usd"] for d in daily if d["date"] == today)

    total_cost = sum(a["cost_usd"] for a in agents)
    total_input = sum(a["tokens"]["input"] for a in agents)
    total_output = sum(a["tokens"]["output"] for a in agents)
    total_cache_read = sum(a["tokens"]["cache_read"] for a in agents)
    total_reasoning = sum(a["tokens"]["reasoning"] for a in agents)
    total_messages = sum(a["message_count"] for a in agents)
    total_tool_calls = sum(a["tool_call_count"] for a in agents)
    total_sessions = sum(a["session_count"] for a in agents)

    kpis = {
        "total_agents": len(agents),
        "online_agents": sum(1 for a in agents if a["status"] == "online"),
        "stuck_agents": sum(1 for a in agents if a["status"] == "stuck"),
        "total_sessions": total_sessions,
        "active_sessions": sum(1 for a in agents if a["active_session_id"]),
        "total_messages": total_messages,
        "total_tool_calls": total_tool_calls,
        "total_cost_usd": round(total_cost, 6),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cache_read_tokens": total_cache_read,
        "total_reasoning_tokens": total_reasoning,
        **task_kpi,
    }

    alert_list = alerts.evaluate(
        agents=agents,
        tasks=tasks,
        failure_events=failure_events,
        now=now,
        budget_usd=budget_usd,
        today_cost_usd=today_cost,
    )

    return {
        "generated_at": now,
        "generated_at_iso": _now_iso(now),
        "agents": agents,
        "memory": memory_by_name.get("ceo"),
        "approvals": approvals,
        "kpis": kpis,
        "tasks": tasks,
        "events": events,
        "tool_counts": tool_counts,
        "throughput": usage,
        "cost_forecast": {
            "daily": daily,
            "today_usd": round(today_cost, 6),
            "budget_usd": budget_usd,
        },
        "alerts": alert_list,
    }


def _preview(content: str, max_len: int = 160) -> str:
    if content is None:
        return ""
    text = " ".join(str(content).split())
    return text[:max_len] + ("…" if len(text) > max_len else "")


def _earlier(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def _later(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)
