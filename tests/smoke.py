"""End-to-end smoke test for the Mission Control server.

Reads REAL data (no fixtures).  Talks HTTP only, stdlib only.

Usage (run while the server is up):

    python tests/smoke.py --url http://127.0.0.1:8000

    # SSE watch mode: exit as soon as an 'activity' event arrives (or timeout)
    python tests/smoke.py --watch --sse-seconds 30
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error


def _build_url(base: str, path: str, token: str) -> str:
    url = base.rstrip("/") + path
    if token:
        sep = "&" if "?" in url else "?"
        url += f"{sep}token={token}"
    return url


def get_json(url: str, timeout: float = 30.0):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
        return resp.status, json.loads(body)


def read_sse(url: str, seconds: float, stop_on_event: str | None = None):
    """Read an SSE stream for up to `seconds`, collecting parsed events.

    Returns (events, timed_out).  If `stop_on_event` is set, returns as soon as
    that event name is observed.
    """
    req = urllib.request.Request(
        url, headers={"Accept": "text/event-stream", "Cache-Control": "no-cache"}
    )
    resp = urllib.request.urlopen(req, timeout=30)
    events = []
    event = None
    data_lines = []
    deadline = time.time() + seconds
    timed_out = True

    def flush():
        nonlocal event, data_lines
        if event is not None:
            events.append({"event": event, "data": "\n".join(data_lines)})
            event = None
            data_lines = []

    while time.time() < deadline:
        try:
            line = resp.readline()
        except (TimeoutError, OSError):
            break
        if not line:
            break
        text = line.decode("utf-8", "replace").rstrip("\n")
        if text == "":
            flush()
        elif text.startswith(":"):
            continue  # SSE comment / ping
        elif text.startswith("event:"):
            event = text[6:].strip()
        elif text.startswith("data:"):
            data_lines.append(text[5:].strip())
        if stop_on_event and any(e["event"] == stop_on_event for e in events):
            timed_out = False
            break
    flush()
    if any(e["event"] == stop_on_event for e in events):
        timed_out = False
    return events, timed_out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("MC_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--token", default=os.environ.get("MC_VIEWER_TOKEN", ""))
    ap.add_argument("--sse-seconds", type=float, default=12.0)
    ap.add_argument("--watch", action="store_true", help="watch SSE and exit on activity")
    args = ap.parse_args()

    token = args.token
    failures = []

    def check(label: str, cond: bool, detail=""):
        status = "PASS" if cond else "FAIL"
        print(f"[{status}] {label}{(' — ' + detail) if detail else ''}")
        if not cond:
            failures.append(label)

    # 1. healthz
    status, body = get_json(_build_url(args.url, "/healthz", token))
    check("GET /healthz", status == 200 and body == {"ok": True}, f"{status} {body}")

    # 2. state
    status, body = get_json(_build_url(args.url, "/v1/state", token))
    agents = body.get("agents", [])
    kpis = body.get("kpis", {})
    check("GET /v1/state returns 17 agents", len(agents) == 17, f"got {len(agents)}")
    names = sorted(a["name"] for a in agents)
    check(
        "agents span CEO + 16 bots",
        names[0] == "atlas" and names[-1] == "vera" and "ceo" in names,
        ",".join(names[:4]) + "...",
    )
    populated = sum(1 for a in agents if a["session_count"] > 0)
    check("agents populated from real state.db", populated == 17, f"{populated}/17 have sessions")
    check("real cost present", kpis.get("total_cost_usd", 0) > 0, f"${kpis.get('total_cost_usd'):.2f}")
    check("real messages present", kpis.get("total_messages", 0) > 0, f"{kpis.get('total_messages')} msgs")
    check("tasks present", kpis.get("tasks_total", 0) > 0, f"{kpis.get('tasks_total')} tasks")
    check("tool counts present", len(body.get("tool_counts", {})) > 0, f"{len(body.get('tool_counts', {}))} tools")
    check("events present", len(body.get("events", [])) > 0, f"{len(body.get('events', []))} events")
    check("alerts key present", isinstance(body.get("alerts"), list), f"{len(body.get('alerts', []))} alerts")

    print("\nagents:")
    for a in agents:
        print(f"  {a['name']:10s} {a['status']:8s} model={a['model']} "
              f"sessions={a['session_count']:3d} cost=${a['cost_usd']:.2f} "
              f"action={a['current_action']}")
    print(f"\nkpis: {json.dumps(kpis)}")

    # 3. snapshots
    status, body = get_json(_build_url(args.url, "/v1/snapshots", token))
    snaps = body.get("snapshots", [])
    check("GET /v1/snapshots returns a list", isinstance(snaps, list), f"{len(snaps)} snapshots")

    # 4. SSE opens and emits a snapshot
    if args.watch:
        events, timed_out = read_sse(
            _build_url(args.url, "/v1/stream", token),
            args.sse_seconds,
            stop_on_event="activity",
        )
        got_snapshot = any(e["event"] == "snapshot" for e in events)
        got_activity = any(e["event"] == "activity" for e in events)
        check("SSE opened (snapshot event)", got_snapshot)
        check("SSE emitted on new activity", got_activity, "timed out" if timed_out else "ok")
        for e in events:
            if e["event"] == "activity":
                data = json.loads(e["data"])
                print(f"\nactivity event: generated_at={data.get('generated_at_iso')} "
                      f"agents={len(data.get('agents', []))}")
    else:
        events, timed_out = read_sse(
            _build_url(args.url, "/v1/stream", token), args.sse_seconds
        )
        got_snapshot = any(e["event"] == "snapshot" for e in events)
        check("SSE opened (snapshot event)", got_snapshot, f"{len(events)} events")
        if got_snapshot:
            snap = next(e for e in events if e["event"] == "snapshot")
            data = json.loads(snap["data"])
            check("SSE snapshot has 17 agents", len(data.get("agents", [])) == 17)

    print("\n" + ("ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
