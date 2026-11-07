"""Spec-gap close tests for Mission Control (retention, signed links, control).

Covers the three items from Randy's locked spec that were missing:

1. ``POST /v1/agents/{id}/command`` — honest 501 (no write path into Hermes).
2. Signed one-click Approve/Deny links (``GET /v1/approvals/{id}/decide``) — the
   fallback for Discord where interactive buttons are impossible in this build.
3. 14-day retention prune of snapshots/events/approvals.

Runs standalone (no server) for the retention/signing units; add ``--url`` plus
``MC_VIEWER_TOKEN`` / ``MC_INGEST_TOKEN`` / ``MC_APPROVAL_SIGNING_KEY`` to also
exercise the HTTP endpoints against a live server.

    .venv/bin/python tests/spec_gaps_test.py
    .venv/bin/python tests/spec_gaps_test.py --url http://127.0.0.1:8010
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "server"))


def _req(url, method="GET", body=None, headers=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Accept": "application/json"}
    if body is not None:
        h["Content-Type"] = "application/json"
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def unit_checks(failures: list[str]) -> None:
    import db
    import discord
    import retention
    import settings
    import signing

    def check(label, cond, detail=""):
        print(f"[{'PASS' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
        if not cond:
            failures.append(label)

    # --- retention: seed a temp DB, prune exactly the old rows ---------------
    tmp = tempfile.mkdtemp(prefix="mc_ret_")
    db.MC_DB = os.path.join(tmp, "mc.db")
    db.init_mc_db()

    now = time.time()
    old = now - 30 * 86400.0
    recent = now - 1 * 86400.0
    old_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(old))
    recent_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(recent))

    con = db.open_mc()
    con.execute("INSERT INTO snapshots (captured_at, state_json, fingerprint) VALUES (?,?,?)", (old, "{}", "old"))
    con.execute("INSERT INTO snapshots (captured_at, state_json, fingerprint) VALUES (?,?,?)", (recent, "{}", "recent"))
    con.execute("INSERT INTO events (id, ts, agent_id, type, data) VALUES (?,?,?,?,?)",
                ("old", old_iso, "piston", "tool.call", "{}"))
    con.execute("INSERT INTO events (id, ts, agent_id, type, data) VALUES (?,?,?,?,?)",
                ("new", recent_iso, "piston", "tool.call", "{}"))
    con.execute("INSERT INTO approvals (request_id, agent, kind, payload_json, status, requested_at) VALUES ('old-ap','piston','tool_call','{}','approved',?)", (old,))
    con.execute("INSERT INTO approvals (request_id, agent, kind, payload_json, status, requested_at) VALUES ('new-ap','piston','tool_call','{}','pending',?)", (recent,))
    con.commit()
    con.close()

    rep = retention.prune(days=14, now=now)
    check("prune deletes exactly the old rows",
          all(rep["tables"][t]["deleted"] == 1 for t in ("snapshots", "events", "approvals")),
          f"deleted={ {t: rep['tables'][t]['deleted'] for t in rep['tables']} }")
    check("prune keeps recent rows",
          all(rep["tables"][t]["after"] == 1 for t in ("snapshots", "events", "approvals")))
    check("prune is idempotent", retention.prune(days=14, now=now)["total_deleted"] == 0)
    check("dry-run deletes nothing",
          retention.prune(days=14, now=now, dry_run=True)["tables"]["snapshots"]["deleted"] == 0)

    # --- signing --------------------------------------------------------------
    settings.APPROVAL_SIGNING_KEY = "spec-gap-test-key"
    rid = "req-abc-123"
    sig = signing.sign(rid, "approved")
    check("signature verifies", signing.verify(rid, "approved", sig))
    check("wrong decision rejected", not signing.verify(rid, "denied", sig))
    check("wrong signature rejected", not signing.verify(rid, "approved", "deadbeef"))
    check("wrong request rejected", not signing.verify("other", "approved", sig))

    # --- discord message carries signed links --------------------------------
    msg = discord.notify_approval("piston", "terminal: echo hi", "high", request_id=rid)
    check("discord message has signed Approve/Deny links",
          "/v1/approvals/req-abc-123/decide?decision=approved&sig=" in msg
          and "/v1/approvals/req-abc-123/decide?decision=denied&sig=" in msg,
          msg.splitlines()[-1][:80])


def http_checks(base: str, viewer: str, ingest: str, key: str,
                failures: list[str]) -> None:
    import settings
    import signing
    settings.APPROVAL_SIGNING_KEY = key or ingest or viewer

    def check(label, cond, detail=""):
        print(f"[{'PASS' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
        if not cond:
            failures.append(label)

    vq = f"?token={viewer}" if viewer else ""

    # 1. agent command — honest 501
    s, b = _req(f"{base}/v1/agents/piston/command{vq}", "POST", {"action": "compact"})
    check("agent command returns 501 with reason", s == 501 and "no write path" in b, f"{s}")
    s, _ = _req(f"{base}/v1/agents/piston/command{vq}", "POST", {"action": "frobnicate"})
    check("agent command 400 on bad action", s == 400, f"{s}")
    s, _ = _req(f"{base}/v1/agents/does-not-exist/command{vq}", "POST", {"action": "pause"})
    check("agent command 404 on unknown agent", s == 404, f"{s}")

    # 2. signed one-click decide
    rid = f"spec-gap-{int(time.time())}"
    ev = {"id": f"ev-{rid}", "ts": "2026-11-07T00:00:00.000Z", "run_id": "spec-gap",
          "agent_id": "piston", "type": "approval.requested",
          "data": {"approval_id": rid, "action": "terminal: echo hi", "risk": "high", "kind": "tool_call"}}
    ih = {"Authorization": f"Bearer {ingest}"} if ingest else {}
    s, b = _req(f"{base}/v1/events", "POST", [ev], ih)
    check("ingest approval.requested", s == 200, f"{s} {b}")

    sig = signing.sign(rid, "approved")
    s, b = _req(f"{base}/v1/approvals/{rid}/decide?decision=approved&sig={sig}")
    check("signed decide approves", s == 200 and "Approved" in b, f"{s}")
    s, b = _req(f"{base}/v1/approvals/{rid}/wait?timeout=1", "GET", None, ih)
    check("emitter wait sees approved", s == 200 and "approved" in b, f"{s} {b}")
    s, _ = _req(f"{base}/v1/approvals/{rid}/decide?decision=approved&sig=deadbeef")
    check("bad signature rejected (403)", s == 403, f"{s}")
    s, _ = _req(f"{base}/v1/approvals/{rid}/decide?decision=denied&sig={signing.sign(rid, 'denied')}")
    check("re-decide rejected (409)", s == 409, f"{s}")

    # 3. prune endpoint
    s, b = _req(f"{base}/v1/admin/prune{vq}", "POST", {"days": 14})
    check("prune endpoint returns per-table counts", s == 200 and "snapshots" in b, f"{s}")
    s, _ = _req(f"{base}/v1/admin/prune", "POST", {})
    check("prune endpoint 401 without auth", s == 401, f"{s}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None, help="server URL (skips HTTP checks if unset)")
    a = ap.parse_args()

    failures: list[str] = []
    print("== unit checks (retention + signing + discord) ==")
    unit_checks(failures)

    if a.url:
        print("\n== HTTP checks ==")
        http_checks(
            a.url.rstrip("/"),
            os.environ.get("MC_VIEWER_TOKEN", ""),
            os.environ.get("MC_INGEST_TOKEN", ""),
            os.environ.get("MC_APPROVAL_SIGNING_KEY", ""),
            failures,
        )

    print("\n" + ("ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
