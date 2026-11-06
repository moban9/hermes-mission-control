"""Path-A end-to-end test for Mission Control.

Exercises the real server over HTTP only (stdlib only, no fixtures):

* GET /v1/state — real memory files (CEO + per-agent) + pending approvals.
* POST /v1/events — merges a real emitter event batch; a repeat id is idempotent.
* Approval round-trip — request_approval from the real emitter -> pending row ->
  Discord message -> POST decision -> the emitter's long-poll returns the verdict.

Requires a running server.  ``MC_INGEST_TOKEN`` must match what the server was
launched with; ``MC_VIEWER_TOKEN`` likewise for the read/decision endpoints.

    MC_INGEST_TOKEN=... MC_VIEWER_TOKEN=... python tests/path_a_test.py --url http://127.0.0.1:8010
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "emitter"))


def _req(url, method="GET", body=None, headers=None, timeout=30):
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    h = {"Accept": "application/json"}
    if body is not None:
        h["Content-Type"] = "application/json"
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
        return resp.status, json.loads(raw) if raw else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("MC_URL", "http://127.0.0.1:8010"))
    ap.add_argument("--agent", default=os.environ.get("MC_AGENT_ID", "piston"))
    args = ap.parse_args()

    base = args.url.rstrip("/")
    viewer = os.environ.get("MC_VIEWER_TOKEN", "")
    ingest = os.environ.get("MC_INGEST_TOKEN", "")
    viewer_q = f"?token={viewer}" if viewer else ""

    failures = []

    def check(label, cond, detail=""):
        print(f"[{'PASS' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
        if not cond:
            failures.append(label)

    # 1. /v1/state: memory + approvals keys present, real memory files.
    status, state = _req(f"{base}/v1/state{viewer_q}")
    check("GET /v1/state 200", status == 200, f"status={status}")
    check("state has top-level memory", "memory" in state and bool(state["memory"].get("facts")))
    check("state has top-level user_facts", bool(state.get("memory", {}).get("user_facts")))
    check("state has approvals list", isinstance(state.get("approvals"), list))
    mem_agents = sum(1 for a in state.get("agents", []) if (a.get("memory") or {}).get("facts"))
    check("per-agent memory present (16+ceo)", mem_agents >= 17, f"{mem_agents} agents")

    ceo_mem = state.get("memory", {})
    if ceo_mem.get("facts"):
        f0 = ceo_mem["facts"][0]
        check("memory fact carries real file mtime (not per-fact age)",
              isinstance(f0.get("mtime"), float) and f0.get("text"))
        print(f"  ceo fact[0] (mtime={f0.get('mtime_iso')}): {f0['text'][:60]!r}")

    # 2. Ingest a real event batch + idempotency.
    ingest_h = {"Authorization": f"Bearer {ingest}"} if ingest else {}
    import uuid
    eid = lambda i: f"ev-{uuid.uuid4().hex[:12]}-{i}"
    batch = [
        {"id": eid(1), "ts": "2026-11-06T18:00:00.000Z", "run_id": "test-run",
         "agent_id": args.agent, "type": "context.snapshot",
         "data": {"model": "deepseek-v4-pro", "messages": 42, "tools": 7,
                  "approx_input_tokens": 12345, "max_tokens": 8192}},
        {"id": eid(2), "ts": "2026-11-06T18:00:01.000Z", "run_id": "test-run",
         "agent_id": args.agent, "type": "llm.usage",
         "data": {"input_tokens": 1000, "output_tokens": 300, "latency_ms": 812,
                  "context_length": 5432}},
        {"id": eid(3), "ts": "2026-11-06T18:00:02.000Z", "run_id": "test-run",
         "agent_id": args.agent, "type": "tool.call",
         "data": {"tool": "read_file", "phase": "start"}},
        {"id": eid(4), "ts": "2026-11-06T18:00:03.000Z", "run_id": "test-run",
         "agent_id": args.agent, "type": "tool.call",
         "data": {"tool": "read_file", "phase": "end", "duration_ms": 15, "ok": True}},
    ]
    status, r = _req(f"{base}/v1/events", "POST", batch, ingest_h)
    check("POST /v1/events accepted 4", status == 200 and r.get("accepted") == 4, f"{status} {r}")

    status2, r2 = _req(f"{base}/v1/events", "POST", batch, ingest_h)
    check("repeat POST idempotent (accepted 0)", status2 == 200 and r2.get("accepted") == 0,
          f"{status2} {r2}")

    # merged live state visible in /v1/state (wait out the 2s state cache)
    time.sleep(2.2)
    _, state2 = _req(f"{base}/v1/state{viewer_q}")
    agent_card = next((a for a in state2["agents"] if a["name"] == args.agent), {})
    ctx = agent_card.get("context")
    usage = agent_card.get("usage")
    check("context.snapshot merged", ctx is not None and ctx.get("model") == "deepseek-v4-pro",
          f"ctx={ctx}")
    check("llm.usage merged (cumulative tokens)", usage is not None
          and usage.get("input_tokens") == 1000 and usage.get("output_tokens") == 300,
          f"usage={usage}")
    check("tool.call merged (count)", agent_card.get("live_tool_counts", {}).get("read_file") == 1,
          f"counts={agent_card.get('live_tool_counts')}")

    # 3. Approval round-trip through the real emitter's request_approval.
    import mc_emitter  # the real client (emitter/mc_emitter.py)
    mc_emitter.URL = base
    mc_emitter.TOKEN = ingest
    import threading
    result = {}
    action = f"terminal: echo roundtrip-{int(time.time())} > /tmp/mc_roundtrip"

    def request():
        result["ok"] = mc_emitter.request_approval(
            args.agent, action, "high", timeout_s=30
        )

    t = threading.Thread(target=request, daemon=True)
    t.start()

    # Wait for the pending row to appear, then decide it.
    ap = None
    for _ in range(60):
        time.sleep(0.5)
        _, apr = _req(f"{base}/v1/approvals{viewer_q}")
        for x in apr.get("approvals", []):
            if x.get("agent") == args.agent and x.get("action") == action:
                ap = x
                break
        if ap:
            break
    check("pending row appears after request_approval", ap is not None, f"ap={ap and ap['request_id']}")

    if ap:
        d = {"decision": "approved"}
        st, dr = _req(f"{base}/v1/approvals/{ap['request_id']}{viewer_q}", "POST", d)
        check("POST decision approved", st == 200 and dr.get("status") == "approved", f"{st} {dr}")

        # 409 on re-decide
        try:
            _, dr2 = _req(f"{base}/v1/approvals/{ap['request_id']}{viewer_q}", "POST", d)
            check("re-decide returns 409", False, f"got {dr2}")
        except urllib.error.HTTPError as e:
            check("re-decide returns 409", e.code == 409, f"code={e.code}")

    t.join(timeout=35)
    check("emitter wait returned approved", result.get("ok") is True, f"ok={result.get('ok')}")

    # wait endpoint directly (already decided) returns the verdict
    _, w = _req(f"{base}/v1/approvals/{ap['request_id']}/wait?timeout=1", headers=ingest_h)
    check("wait endpoint returns approved", w.get("status") == "approved", f"{w}")

    print("\n" + ("ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILED: {failures}"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
