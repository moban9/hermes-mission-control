"""Consistent, read-only SQLite snapshot for KPI projections.

Snapshot fields: available (bool); error (str|None); tasks, runs, blocked_events
(list[dict]); categories (mapping running/done/failed/blocked to {count,total,
 omitted,rows}); legacy_kpis (tasks_total, tasks_queued, tasks_running,
 tasks_done, tasks_blocked, tasks_failed, success_rate; integers/float or None
when unavailable); aliases (failures and failures_omitted, exact references to
the failed category rows and omitted count). An unavailable board has null
counts; an available empty board has zero counts. All rows come from one read
transaction on one guarded connection.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import sqlite3
from typing import Any


CATEGORIES = ("running", "done", "failed", "blocked")
FAILED_OUTCOMES = {"crashed", "gave_up", "timed_out", "failed", "rate_limited"}


@dataclass(frozen=True)
class Snapshot:
    available: bool
    error: str | None
    tasks: list[dict[str, Any]]
    runs: list[dict[str, Any]]
    blocked_events: list[dict[str, Any]]
    categories: dict[str, dict[str, Any]]
    legacy_kpis: dict[str, int | float | None]
    aliases: dict[str, Any]


def _unavailable(error: str) -> Snapshot:
    categories = {key: {"count": None, "total": None, "omitted": None, "rows": []} for key in CATEGORIES}
    return Snapshot(False, error, [], [], [], categories,
                    {"tasks_total": None, "tasks_queued": None, "tasks_running": None,
                     "tasks_done": None, "tasks_blocked": None, "tasks_failed": None,
                     "success_rate": None},
                    {"failures": [], "failures_omitted": None})


def open_snapshot(path: str):
    """Open a single strict read-only connection; caller must close it."""
    uri = "file:" + os.path.abspath(path) + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=0.2)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def load_snapshot(path: str | None = None) -> Snapshot:
    """Materialize task inputs and KPI/category projections in one read pass."""
    path = path or os.environ.get("MC_KANBAN_DB", "/opt/data/kanban.db")
    con = None
    try:
        con = open_snapshot(path)
        con.execute("BEGIN")
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"tasks", "task_runs", "task_events", "task_links"} <= tables:
            return _unavailable("board unavailable: schema_mismatch")
        tasks = [dict(r) for r in con.execute("""SELECT t.*, 
          (SELECT group_concat(parent_id) FROM task_links WHERE child_id=t.id) parent_ids,
          (SELECT count(*) FROM task_links WHERE parent_id=t.id) child_count
          FROM tasks t ORDER BY created_at DESC""")]
        runs = [dict(r) for r in con.execute("SELECT * FROM task_runs ORDER BY id")]
        events = [dict(r) for r in con.execute("SELECT * FROM task_events WHERE kind='blocked' ORDER BY id")]
        con.commit()
    except Exception as exc:
        msg = str(exc).lower()
        error = "board unavailable: busy" if "locked" in msg or "busy" in msg else "board unavailable: read_error"
        return _unavailable(error)
    finally:
        if con is not None:
            con.close()

    history: dict[Any, list[dict]] = {}
    for run in runs:
        history.setdefault(run.get("task_id"), []).append(run)
    latest_event: dict[Any, dict] = {}
    for event in events:
        latest_event[event.get("task_id")] = event
    grouped = {key: [] for key in CATEGORIES}
    totals = {"tasks_total": 0, "tasks_queued": 0, "tasks_running": 0, "tasks_done": 0,
              "tasks_blocked": 0, "tasks_failed": 0}
    queued = {"todo", "ready", "triage", "scheduled"}
    for task in tasks:
        status = task.get("status") or ""
        runs_for_task = history.get(task.get("id"), [])
        latest = runs_for_task[-1] if runs_for_task else None
        outcome = latest.get("outcome") if latest else None
        failed = status not in {"done", "archived"} and latest is not None and (outcome is None or outcome in FAILED_OUTCOMES)
        totals["tasks_total"] += 1
        totals["tasks_queued"] += status in queued
        totals["tasks_running"] += status == "running"
        totals["tasks_done"] += status == "done"
        totals["tasks_blocked"] += status == "blocked"
        totals["tasks_failed"] += bool(failed)
        row = {"task_id": task.get("id"), "title": task.get("title"),
               "assignee": task.get("assignee") or "Unassigned", "status": status,
               "blocked_kind": task.get("block_kind"), "current_step_key": task.get("current_step_key"),
               "latest_run_id": latest.get("id") if latest else None, "latest_outcome": outcome,
               "profile": latest.get("profile") if latest else None, "attempts": len(runs_for_task),
               "outcome_attempts": sum(1 for r in runs_for_task if outcome is not None and r.get("outcome") == outcome),
               "error": latest.get("error") if latest else None,
               "reason": (latest.get("error") if latest and isinstance(latest.get("error"), str) and latest["error"].strip() else "no reason recorded"),
               "label": (f"{outcome} ×{sum(1 for r in runs_for_task if outcome is not None and r.get('outcome') == outcome)} · {len(runs_for_task)} attempts" if outcome is not None else f"no outcome · {len(runs_for_task)} attempts"),
               "blocked_reason": {}, "timestamp": None}
        if status == "running":
            row["timestamp"] = (latest.get("started_at") if latest else None) or task.get("started_at")
            grouped["running"].append(row.copy())
        if status == "done":
            row["timestamp"] = task.get("completed_at") or (latest.get("ended_at") if latest and outcome == "completed" else None)
            grouped["done"].append(row.copy())
        if status == "blocked":
            event = latest_event.get(task.get("id"))
            row["timestamp"] = event.get("created_at") if event else None
            if event:
                try:
                    payload = json.loads(event.get("payload") or "{}")
                    row["blocked_reason"] = payload if isinstance(payload, dict) else {}
                except (TypeError, ValueError):
                    row["blocked_reason"] = {}
            row["blocked_kind"] = task.get("block_kind")
            grouped["blocked"].append(row.copy())
        if failed:
            row["timestamp"] = latest.get("ended_at")
            grouped["failed"].append(row.copy())
    denominator = totals["tasks_done"] + totals["tasks_failed"]
    totals["success_rate"] = round(totals["tasks_done"] * 100.0 / denominator, 1) if denominator else None
    categories = {}
    for key, rows in grouped.items():
        rows.sort(key=lambda r: (r["timestamp"] is None, -(r["timestamp"] or 0), str(r["task_id"])))
        selected = rows[:20]
        categories[key] = {"count": len(selected), "total": len(rows), "omitted": len(rows)-len(selected), "rows": selected}
    failed_rows = categories["failed"]["rows"]
    return Snapshot(True, None, tasks, runs, events, categories, totals,
                    {"failures": failed_rows, "failures_omitted": categories["failed"]["omitted"]})
