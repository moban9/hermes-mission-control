"""Alert derivation for Mission Control.

Pure functions: take derived state (agents, tasks, failure events) and produce
a list of alert dicts.  No I/O here — persistence to the MC ``alerts`` table is
done by the app when it snapshots.
"""

from __future__ import annotations

import os

# Silence thresholds (seconds).
ONLINE_AFTER_S = float(os.environ.get("MC_ONLINE_AFTER_S", "30"))
STUCK_AFTER_S = float(os.environ.get("MC_STUCK_AFTER_S", "90"))
OFFLINE_AFTER_S = float(os.environ.get("MC_OFFLINE_AFTER_S", "30"))
# A "stuck" agent must have been active within this window (else it's just
# idle/offline — its session was never finalized).  Keeps stale open sessions
# from being misread as "stuck".
STUCK_ENGAGEMENT_WINDOW_S = float(os.environ.get("MC_STUCK_ENGAGEMENT_WINDOW_S", "1800"))

# Error burst: N+ failures within the window.
ERROR_BURST_THRESHOLD = int(os.environ.get("MC_ERROR_BURST_THRESHOLD", "3"))
ERROR_BURST_WINDOW_S = float(os.environ.get("MC_ERROR_BURST_WINDOW_S", "300"))

# kanban task_events kinds that count as a task "failure".
FAILURE_EVENT_KINDS = frozenset({
    "crashed",
    "gave_up",
    "timed_out",
    "rate_limited",
    "completion_blocked_empty_result",
})


def evaluate(
    agents: list[dict],
    tasks: list[dict],
    failure_events: list[dict],
    now: float,
    budget_usd: float,
    today_cost_usd: float,
) -> list[dict]:
    """Evaluate all alert rules and return a list of alert dicts."""
    out: list[dict] = []

    # 1. Stuck agent: an open session that has gone silent past the threshold.
    for a in agents:
        if a.get("status") == "stuck":
            out.append(_make(
                "stuck_agent", "warning", a["name"],
                f"{a['name']} has an open session but no activity for "
                f"{a['last_activity_age_s']:.0f}s",
                {"age_s": a["last_activity_age_s"], "session_id": a.get("active_session_id")},
                now,
            ))

    # 2. Agent offline: currently owns a running task but is silent >30s.
    running_assignees = {t["assignee"] for t in tasks if t.get("status") == "running"}
    for a in agents:
        age = a.get("last_activity_age_s")
        if a["name"] in running_assignees and age is not None and age > OFFLINE_AFTER_S:
            out.append(_make(
                "agent_offline", "warning", a["name"],
                f"{a['name']} owns a running task but no activity for {age:.0f}s",
                {"age_s": age},
                now,
            ))

    # 3. Error burst: 3+ task failures within the burst window.
    if len(failure_events) >= ERROR_BURST_THRESHOLD:
        out.append(_make(
            "error_burst", "critical", None,
            f"{len(failure_events)} task failures in the last "
            f"{int(ERROR_BURST_WINDOW_S // 60)}m",
            {"failures": failure_events},
            now,
        ))

    # 4. Budget risk: today's spend already exceeds the daily budget.
    if today_cost_usd > budget_usd:
        out.append(_make(
            "budget_risk", "warning", None,
            f"today's cost ${today_cost_usd:.2f} exceeds daily budget ${budget_usd:.2f}",
            {"today_usd": today_cost_usd, "budget_usd": budget_usd},
            now,
        ))

    return out


def _make(kind: str, severity: str, agent: str | None, message: str,
          data: dict, now: float) -> dict:
    return {
        "kind": kind,
        "severity": severity,
        "agent": agent,
        "message": message,
        "data": data,
        "raised_at": now,
    }
