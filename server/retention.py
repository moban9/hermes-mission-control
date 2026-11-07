"""14-day retention pruning for Mission Control's own database.

The spec pins retention at **14 days** for events + snapshots.  Nothing pruned
them before (only ``tokens.prune`` existed, for guest viewer tokens), so the
``mc.db`` grew unbounded — one full snapshot every 30s.  This module deletes
rows older than ``MC_RETENTION_DAYS`` (default 14) from ``snapshots``,
``events`` and ``approvals``, and reports before/after counts per table.

Idempotent and safe to call repeatedly, so it can run from a cron (either the
CLI below, or ``POST /v1/admin/prune`` on the live server).

    cd server && ../.venv/bin/python retention.py            # real prune
    cd server && ../.venv/bin/python retention.py --dry-run  # preview only
"""

from __future__ import annotations

import os
import time

import db

RETENTION_DAYS = int(os.environ.get("MC_RETENTION_DAYS", "14"))


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def prune(days: int | None = None, now: float | None = None,
          dry_run: bool = False) -> dict:
    """Delete rows older than ``days`` and report before/deleted per table.

    * ``snapshots``  — ``captured_at`` (REAL unix epoch)
    * ``events``     — ``ts`` (TEXT ISO-8601 UTC; lexicographic == chronological)
    * ``approvals``  — ``requested_at`` (REAL unix epoch)

    Returns a report dict; a real run commits, ``dry_run`` only counts.
    """
    days = RETENTION_DAYS if days is None else int(days)
    now = time.time() if now is None else float(now)
    cutoff = now - days * 86400.0
    cutoff_iso = _iso(cutoff)

    report: dict = {
        "days": days,
        "cutoff": cutoff,
        "cutoff_iso": cutoff_iso,
        "dry_run": dry_run,
        "tables": {},
    }

    with db.mc_lock():
        con = db.open_mc()
        try:
            # snapshots: captured_at REAL
            before = con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            if dry_run:
                deleted = con.execute(
                    "SELECT COUNT(*) FROM snapshots WHERE captured_at < ?",
                    (cutoff,),
                ).fetchone()[0]
            else:
                deleted = con.execute(
                    "DELETE FROM snapshots WHERE captured_at < ?", (cutoff,)
                ).rowcount
            report["tables"]["snapshots"] = {
                "before": before, "deleted": deleted, "after": before - deleted,
            }

            # events: ts TEXT (ISO UTC) — string order equals time order
            before = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            if dry_run:
                deleted = con.execute(
                    "SELECT COUNT(*) FROM events WHERE ts < ?", (cutoff_iso,)
                ).fetchone()[0]
            else:
                deleted = con.execute(
                    "DELETE FROM events WHERE ts < ?", (cutoff_iso,)
                ).rowcount
            report["tables"]["events"] = {
                "before": before, "deleted": deleted, "after": before - deleted,
            }

            # approvals: requested_at REAL
            before = con.execute("SELECT COUNT(*) FROM approvals").fetchone()[0]
            if dry_run:
                deleted = con.execute(
                    "SELECT COUNT(*) FROM approvals WHERE requested_at < ?",
                    (cutoff,),
                ).fetchone()[0]
            else:
                deleted = con.execute(
                    "DELETE FROM approvals WHERE requested_at < ?", (cutoff,)
                ).rowcount
            report["tables"]["approvals"] = {
                "before": before, "deleted": deleted, "after": before - deleted,
            }

            if not dry_run:
                con.commit()
        finally:
            con.close()

    report["total_deleted"] = sum(t["deleted"] for t in report["tables"].values())
    return report


def _fmt_report(report: dict) -> str:
    lines = [
        f"retention {report['days']} days — cutoff {report['cutoff_iso']}"
        f"{' (dry-run)' if report['dry_run'] else ''}",
    ]
    for table, t in report["tables"].items():
        lines.append(
            f"  {table:10s} before={t['before']:>6}  deleted={t['deleted']:>6}  "
            f"after={t['after']:>6}"
        )
    lines.append(f"  {'total':10s}                  deleted={report['total_deleted']:>6}")
    return "\n".join(lines)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Mission Control retention prune")
    ap.add_argument("--days", type=int, default=RETENTION_DAYS)
    ap.add_argument("--dry-run", action="store_true", help="count only, delete nothing")
    ap.add_argument("--db", default=None, help="override MC_DB (for tests)")
    a = ap.parse_args()

    if a.db:
        db.MC_DB = a.db
    report = prune(days=a.days, dry_run=a.dry_run)
    print(_fmt_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
