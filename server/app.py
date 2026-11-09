"""Mission Control server — FastAPI app exposing live, derived Hermes state.

Run (single worker, no Docker):

    cd server && uvicorn app:app --host 0.0.0.0 --port 8000

Endpoints:
    GET /healthz       liveness probe -> {"ok": true}
    GET /v1/state      full derived state (agents, tasks, events, kpis, alerts)
    GET /v1/stream     Server-Sent Events; emits on new activity (query token)
    GET /v1/snapshots  replay snapshots persisted by the 30s snapshotter

All reads against Hermes are ``mode=ro``.  The only writes are to Mission
Control's own MC database (snapshots).  In-memory state assumes a single
worker (uvicorn default).
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import urllib.parse
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import db
import discord
import live
import redact
import reducer
import retention
import settings
import signing
import tokens

VIEWER_TOKEN = settings.VIEWER_TOKEN
INGEST_TOKEN = settings.INGEST_TOKEN
SNAPSHOT_INTERVAL_S = float(os.environ.get("MC_SNAPSHOT_INTERVAL_S", "30"))

# Agent-control endpoint: the actions we accept (all 501 today) and the known
# agent ids (CEO + the 16 bot profiles), resolved once at import.
_VALID_COMMANDS = frozenset({"pause", "resume", "compact"})
_KNOWN_AGENTS = frozenset(name for name, _ in db.profiles())
_AGENT_CONTROL_501 = (
    "agent control (pause/resume/compact) is not available in this build: "
    "Mission Control has no write path into Hermes (its state.db reads are "
    "strictly read-only by design), and the Hermes gateway exposes no "
    "externally-addressable pause/resume/compact control — /pause and /compress "
    "are in-session commands only, and the gateway control socket serves only "
    "lifecycle verbs (identify/status/rescan/session-ticket)"
)

# Static dashboard (web/) is served at "/" from the same process.  Mounted
# last so the API routes above win on exact matches; everything else falls
# through to the SPA (index.html).
_WEB_DIR = os.environ.get(
    "MC_WEB_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web"),
)
SSE_POLL_INTERVAL_S = float(os.environ.get("MC_SSE_POLL_INTERVAL_S", "2"))
SSE_KEEPALIVE_S = float(os.environ.get("MC_SSE_KEEPALIVE_S", "15"))


class _AppState:
    """In-memory state shared by the snapshotter and the API (single worker)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.latest: dict | None = None      # {"state": ..., "ts": ...}
        self.running = threading.Event()
        self.running.set()


STATE = _AppState()


def _auth(
    token: str | None = Query(default=None),
    authorization: str | None = Header(default=None),
) -> str:
    """Authenticate the legacy viewer token or a live read-only guest."""
    if not VIEWER_TOKEN:
        return "anonymous"
    provided = token
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if provided == VIEWER_TOKEN:
        return "owner"
    identity = tokens.principal(provided)
    if identity:
        return identity
    raise HTTPException(status_code=401, detail="invalid, expired, or missing viewer token")


def _require_owner(principal: str = Depends(_auth)) -> str:
    if principal != "owner":
        raise HTTPException(status_code=403, detail="read-only token")
    return principal


def _bearer(authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _require_ingest(authorization: str | None = Header(default=None)) -> None:
    """Gate the emitter's ingest + approval long-poll endpoints.

    Requires ``Authorization: Bearer MC_INGEST_TOKEN``.  Off (dev only) when the
    token is unset, mirroring the viewer-token behaviour.
    """
    if not INGEST_TOKEN:
        return
    if _bearer(authorization) != INGEST_TOKEN:
        raise HTTPException(status_code=401, detail="invalid or missing ingest token")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# --- SSE broadcast broker ---------------------------------------------------
# Approval requests/decisions are pushed to every connected SSE client as an
# ``approval`` event (matching the dashboard's onSSEApproval handler), so the
# panel updates live without a full state re-reduce.  A thread-safe queue fan-out
# bridges the sync ingest/decision handlers into the async SSE generators.
_SSE_SUBSCRIBERS: set[asyncio.Queue] = set()
_SSE_SUB_LOCK = threading.Lock()
_SSE_LOOP: asyncio.AbstractEventLoop | None = None


def _subscribe_sse() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    with _SSE_SUB_LOCK:
        _SSE_SUBSCRIBERS.add(q)
    return q


def _unsubscribe_sse(q: asyncio.Queue) -> None:
    with _SSE_SUB_LOCK:
        _SSE_SUBSCRIBERS.discard(q)


def broadcast_sse(event: str, data: dict) -> None:
    """Push an SSE event to every connected client (thread-safe, best-effort)."""
    loop = _SSE_LOOP
    if loop is None or loop.is_closed():
        return

    def _put() -> None:
        with _SSE_SUB_LOCK:
            subs = list(_SSE_SUBSCRIBERS)
        for q in subs:
            try:
                q.put_nowait((event, data))
            except asyncio.QueueFull:
                pass

    try:
        loop.call_soon_threadsafe(_put)
    except RuntimeError:
        pass


def _approval_sse(ap: dict) -> dict:
    """Shape the dashboard's onSSEApproval handler consumes."""
    return {
        "id": ap.get("id"),
        "request_id": ap.get("request_id"),
        "agent": ap.get("agent"),
        "text": ap.get("action", ""),
        "risk": ap.get("risk", "med"),
        "status": ap.get("status", "pending"),
        "requested_at": ap.get("requested_at"),
    }


def _snapshot_once() -> None:
    """Reduce state, persist a snapshot, and cache it in memory."""
    try:
        state = reducer.reduce_state()
        fingerprint = json.dumps(reducer.activity_fingerprint())
        with db.mc_lock():
            con = db.open_mc()
            try:
                con.execute(
                    "INSERT INTO snapshots (captured_at, state_json, fingerprint) "
                    "VALUES (?, ?, ?)",
                    (state["generated_at"], json.dumps(state), fingerprint),
                )
                con.commit()
            finally:
                con.close()
        with STATE.lock:
            STATE.latest = {"state": state, "ts": time.time()}
    except Exception as exc:  # never let the snapshotter take the app down
        print(f"[mc] snapshot error: {exc}", flush=True)


def _snapshot_loop() -> None:
    """Background thread: snapshot every SNAPSHOT_INTERVAL_S seconds.

    Sleeps in 1s slices so a shutdown is noticed within ~1s (the ``running``
    event is cleared on lifespan exit).
    """
    while STATE.running.is_set():
        for _ in range(int(SNAPSHOT_INTERVAL_S)):
            if not STATE.running.is_set():
                return
            time.sleep(1.0)
        if STATE.running.is_set():
            _snapshot_once()


async def _sse_gen():
    """Yield a snapshot + pending approvals, then activity/approval events."""
    q = _subscribe_sse()
    try:
        last_fp = await asyncio.to_thread(reducer.activity_fingerprint)
        state = await asyncio.to_thread(reducer.reduce_state)
        yield _sse("snapshot", redact.scrub_obj(state))

        # Replay the current pending approvals so the panel populates on load.
        for ap in state.get("approvals", []):
            yield _sse("approval", _approval_sse(ap))

        last_keepalive = time.time()
        while True:
            # 1. Drain any broadcast events (approval requested/decided).
            drained = False
            while True:
                try:
                    ev, data = q.get_nowait()
                except asyncio.QueueEmpty:
                    break
                yield _sse(ev, data)
                drained = True
            if drained:
                last_keepalive = time.time()
                continue

            # 2. Poll the path-A/B fingerprint for a full state change.
            await asyncio.sleep(SSE_POLL_INTERVAL_S)
            fp = await asyncio.to_thread(reducer.activity_fingerprint)
            if fp != last_fp:
                last_fp = fp
                state = await asyncio.to_thread(reducer.reduce_state)
                yield _sse("activity", redact.scrub_obj(state))
                last_keepalive = time.time()
            elif time.time() - last_keepalive >= SSE_KEEPALIVE_S:
                yield ": ping\n\n"
                last_keepalive = time.time()
    finally:
        _unsubscribe_sse(q)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _SSE_LOOP
    db.init_mc_db()
    _snapshot_once()  # seed the cache + first snapshot immediately
    thread = threading.Thread(target=_snapshot_loop, daemon=True)
    thread.start()
    _SSE_LOOP = asyncio.get_running_loop()
    try:
        yield
    finally:
        STATE.running.clear()
        _SSE_LOOP = None


app = FastAPI(title="Mission Control", version="1.0.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/v1/state")
def v1_state(_auth: None = Depends(_auth)) -> dict:
    # Reuse the cached state if it's very fresh, otherwise reduce live.
    with STATE.lock:
        cached = STATE.latest
    if cached and (time.time() - cached["ts"]) < 2.0:
        return redact.scrub_obj(cached["state"])
    state = reducer.reduce_state()
    with STATE.lock:
        STATE.latest = {"state": state, "ts": time.time()}
    return redact.scrub_obj(state)


def _replay_projection(state: dict) -> dict:
    """Compact per-snapshot projection for the client's replay (H) panel.

    Strips the heavy parts of a snapshot (events, tool counts, per-model usage)
    and keeps only what the client needs to rebuild an H entry plus the
    tokens-per-second series: per-agent status/session/title, and the small set
    of KPI counters (done, cost, cumulative tokens).
    """
    agents = state.get("agents", [])
    kpis = state.get("kpis", {})
    return {
        "captured_at": state.get("generated_at"),
        "agents": [
            {
                "name": a.get("name"),
                "status": a.get("status"),
                "session_id": a.get("active_session_id"),
                "title": a.get("title"),
            }
            for a in agents
        ],
        "done": kpis.get("tasks_done", 0),
        "cost": kpis.get("total_cost_usd", 0.0),
        "input_tokens": kpis.get("total_input_tokens", 0),
        "output_tokens": kpis.get("total_output_tokens", 0),
    }


@app.get("/v1/snapshots")
def v1_snapshots(_auth: None = Depends(_auth)) -> dict:
    con = db.open_mc()
    try:
        rows = con.execute(
            "SELECT captured_at, state_json FROM snapshots "
            "ORDER BY captured_at DESC LIMIT 120"
        ).fetchall()
    finally:
        con.close()
    out = []
    for r in reversed(rows):  # oldest -> newest, ready for a chronological H
        try:
            out.append(_replay_projection(json.loads(r["state_json"])))
        except Exception:
            continue
    return {"snapshots": redact.scrub_obj(out)}


@app.get("/v1/stream")
def v1_stream(_auth: None = Depends(_auth)) -> StreamingResponse:
    return StreamingResponse(
        _sse_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _handle_approval_requested(ev: dict) -> None:
    """Persist an approval.requested event, fire Discord, and broadcast SSE."""
    data = ev.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    request_id = data.get("approval_id") or ev.get("id")
    agent = ev.get("agent_id") or "unknown"
    action = data.get("action") or ""
    risk = data.get("risk") or "med"
    kind = data.get("kind") or "tool_call"
    requested_at = live.parse_ts(ev.get("ts")) or time.time()

    with db.mc_lock():
        con = db.open_mc()
        try:
            db.insert_approval(
                con, request_id, agent, kind,
                {"action": action, "risk": risk, "kind": kind},
                requested_at,
            )
            con.commit()
        finally:
            con.close()

    # Never block ingest on Discord (background thread inside notifier).
    discord.notify_approval(agent, action, risk, request_id=request_id)

    ap = db.get_approval(request_id)
    if ap:
        broadcast_sse("approval", _approval_sse(ap))



_AGENT_CACHE: dict[str, str] = {}


def _resolve_agent(session_id: str | None) -> str | None:
    """Map a Hermes session id to the profile that owns it (read-only)."""
    if not session_id:
        return None
    if session_id in _AGENT_CACHE:
        return _AGENT_CACHE[session_id]
    import sqlite3
    for name, path in db.profiles():
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3.0)
            try:
                row = con.execute("SELECT profile_name FROM sessions WHERE id=?",
                                  (session_id,)).fetchone()
            finally:
                con.close()
        except Exception:
            continue
        if row:
            who = row[0] or name
            _AGENT_CACHE[session_id] = who
            return who
    return None

@app.post("/v1/events")
def v1_events(payload: Any = Body(...),
              authorization: str | None = Header(default=None)) -> dict:
    """Ingest an emitter event batch.  Idempotent by event ``id``."""
    _require_ingest(authorization)
    events = payload if isinstance(payload, list) else [payload]

    accepted = 0
    duplicates = 0
    accepted_events: list[dict] = []
    with db.mc_lock():
        con = db.open_mc()
        try:
            for ev in events:
                if not isinstance(ev, dict) or not ev.get("id"):
                    continue
                if str(ev.get("agent_id") or "").lower() in ("", "none", "agent", "unknown"):
                    _d = ev.get("data") if isinstance(ev.get("data"), dict) else {}
                    ev["agent_id"] = _resolve_agent(ev.get("session_id") or _d.get("session_id"))
                if db.insert_event(con, ev) > 0:
                    accepted += 1
                    accepted_events.append(ev)
                else:
                    duplicates += 1
            con.commit()
        finally:
            con.close()

    for ev in accepted_events:
        live.merge_event(ev)
        if ev.get("type") == "approval.requested":
            _handle_approval_requested(ev)

    return {"accepted": accepted, "duplicates": duplicates}


@app.get("/v1/agents/stuck")
def v1_agents_stuck(_auth: None = Depends(_auth)) -> dict:
    """Diagnose agents whose open session or kanban card disagrees with reality."""
    import sqlite3
    now = time.time()
    tasks: dict[str, list] = {}
    try:
        kc = sqlite3.connect(f"file:{db.KANBAN_DB}?mode=ro", uri=True, timeout=5.0)
        try:
            for r in kc.execute("SELECT assignee,status,title,block_kind,last_failure_error "
                                "FROM tasks WHERE status IN ('running','blocked','ready')"):
                tasks.setdefault(r[0] or "", []).append(
                    {"status": r[1], "title": r[2] or "", "block_kind": r[3],
                     "error": r[4] or ""})
        finally:
            kc.close()
    except Exception:
        pass

    out = []
    for name, path in db.profiles():
        who = "ceo" if name == "ceo" else name
        sess = None
        try:
            sc = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3.0)
            try:
                sess = sc.execute("SELECT id, last_activity_at, last_activity_description "
                                  "FROM sessions WHERE ended_at IS NULL "
                                  "ORDER BY last_activity_at DESC LIMIT 1").fetchone()
            finally:
                sc.close()
        except Exception:
            pass

        age_min = round((now - (sess[1] or 0)) / 60.0, 1) if sess else None
        cards = tasks.get(who, [])
        running = [c for c in cards if c["status"] == "running"]
        blocked = [c for c in cards if c["status"] == "blocked"]

        if blocked:
            verdict = "blocked"
            c = blocked[0]
            reason = f"{len(blocked)} blocked card(s): {c['title'][:70]}"
            if c["block_kind"]:
                reason += f" [{c['block_kind']}]"
            if c["error"]:
                reason += f" — {c['error'][:90]}"
        elif running and (age_min is None or age_min > 10):
            verdict = "stuck"
            reason = f"card running but no activity for {age_min or 0:.0f} min: {running[0]['title'][:60]}"
        elif running:
            verdict = "working"
            reason = f"running: {running[0]['title'][:60]}"
        elif sess and age_min is not None and age_min > 10:
            verdict = "stale-session"
            reason = f"session left open, no activity for {age_min:.0f} min, no open card"
        else:
            verdict = "idle"
            reason = "no open session"

        out.append({"agent": who, "verdict": verdict, "reason": reason,
                    "open_session": bool(sess), "idle_min": age_min,
                    "cards": len(cards)})

    order = {"stuck": 0, "blocked": 1, "stale-session": 2, "working": 3, "idle": 4}
    out.sort(key=lambda a: order.get(a["verdict"], 9))
    return {"checked_at": now, "agents": out,
            "needs_attention": [a for a in out if a["verdict"] in ("stuck", "blocked", "stale-session")]}


@app.post("/v1/agents/stuck/resolve")
def v1_agents_stuck_resolve(body: dict | None = Body(default=None),
                             _auth: str = Depends(_require_owner)) -> dict:
    """Close stale sessions so agents stop reading as stuck.

    Only sessions that are open, idle beyond ``min_idle_min`` (default 30) and
    belong to an agent with no running kanban card are touched.  Everything else
    is reported and left alone — an active worker must never lose its session.
    """
    import sqlite3
    body = body or {}
    try:
        min_idle = float(body.get("min_idle_min", 30))
    except Exception:
        min_idle = 30.0
    dry = bool(body.get("dry_run"))
    now = time.time()

    running_agents = set()
    try:
        kc = sqlite3.connect(f"file:{db.KANBAN_DB}?mode=ro", uri=True, timeout=5.0)
        try:
            for r in kc.execute("SELECT assignee FROM tasks WHERE status='running'"):
                if r[0]:
                    running_agents.add(r[0])
        finally:
            kc.close()
    except Exception:
        pass

    repaired, skipped = [], []
    for name, path in db.profiles():
        who = "ceo" if name == "ceo" else name
        try:
            sc = sqlite3.connect(path, timeout=7.0)
            try:
                rows = sc.execute(
                    "SELECT id, last_activity_at FROM sessions "
                    "WHERE ended_at IS NULL ORDER BY last_activity_at DESC").fetchall()
                for sid, last in rows:
                    idle_min = (now - (last or 0)) / 60.0
                    if idle_min < min_idle:
                        skipped.append({"agent": who, "session": sid[:16],
                                        "why": f"active {idle_min:.0f} min ago"})
                        continue
                    if who in running_agents:
                        skipped.append({"agent": who, "session": sid[:16],
                                        "why": "agent has a running card"})
                        continue
                    if not dry:
                        sc.execute("UPDATE sessions SET ended_at=?, end_reason='mc_reconciled' "
                                   "WHERE id=? AND ended_at IS NULL", (now, sid))
                if not dry:
                    sc.commit()
            finally:
                sc.close()
            if not dry:
                repaired.extend({"agent": who, "session": r[0][:16]} for r in rows
                                if (now - (r[1] or 0)) / 60.0 >= min_idle
                                and who not in running_agents)
        except Exception as exc:
            skipped.append({"agent": who, "why": f"write failed: {exc}"[:120]})

    return {"ok": True, "dry_run": dry, "closed": repaired, "skipped": skipped,
            "min_idle_min": min_idle}


@app.get("/v1/approvals")
def v1_approvals(_auth: None = Depends(_auth)) -> dict:
    """Pending approvals (viewer auth)."""
    return {"approvals": db.list_pending_approvals()}


def _log_decision(identifier: str, status: str, decided_by: str,
                  exc: str | None = None) -> None:
    """Append every decision to a line-per-decision log (attribution)."""
    try:
        import os as _os
        path = _os.path.join(_os.path.dirname(__file__), "..", "logs", "decisions.log")
        _os.makedirs(_os.path.dirname(path), exist_ok=True)
        with open(path, "a") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\t"
                     f"{identifier}\t{status}\t{decided_by}"
                     f"{'\t' + exc if exc else ''}\n")
    except Exception:
        pass


@app.post("/v1/approvals/{identifier}")
def v1_approval_decide(identifier: str, body: dict = Body(...),
                       _auth: str = Depends(_require_owner)) -> dict:
    """Record an approval decision (viewer auth).  409 if already decided."""
    decision = str((body or {}).get("decision") or (body or {}).get("status") or "").strip().lower()
    if decision in ("approve", "approved", "yes"):
        status = "approved"
    elif decision in ("deny", "denied", "reject", "rejected", "no"):
        status = "rejected"
    else:
        raise HTTPException(status_code=400, detail="decision must be 'approved' or 'denied'")

    decided_by = str((body or {}).get("decided_by") or "viewer-token").strip()
    try:
        updated = db.decide_approval(identifier, status, decided_by, time.time())
    except LookupError as exc:
        _log_decision(identifier, status, decided_by, exc=str(exc))
        raise HTTPException(status_code=409, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="approval not found")
    _log_decision(identifier, status, decided_by)

    live.bump()  # fold into the SSE activity fingerprint
    broadcast_sse("approval", _approval_sse(updated))
    return updated


_APPROVE_WORDS = ("approve", "approved", "yes")
_DENY_WORDS = ("deny", "denied", "reject", "rejected", "no")


def _decision_page(message: str, ok: bool, code: int = 200) -> HTMLResponse:
    """Tiny confirmation page for the signed one-click decision links."""
    color = "#22d3ee" if ok else "#f43f5e"
    glyph = "&#10003;" if ok else "&#10007;"
    body = (
        "<!doctype html><meta charset='utf-8'><title>Mission Control</title>"
        "<body style='font-family:system-ui;background:#0b0f1a;color:#e6e6e6;"
        "display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
        "<div style='text-align:center;padding:24px'>"
        f"<div style='font-size:52px'>{glyph}</div>"
        f"<div style='color:{color};font-size:22px;max-width:480px'>{message}</div>"
        "</div></body>"
    )
    return HTMLResponse(body, status_code=code)


@app.get("/v1/approvals/{identifier}/decide")
def v1_approval_decide_confirm(identifier: str, decision: str = Query(...),
                               sig: str = Query(...)) -> HTMLResponse:
    """Show the decision so the click is deliberate.

    A GET must never change state: Discord (and mail clients, previewers)
    fetch links automatically, and an earlier version let the unfurl bot
    approve requests seconds after they were posted.
    """
    raw = (decision or "").strip().lower()
    if raw not in _APPROVE_WORDS and raw not in _DENY_WORDS:
        return _decision_page("Decision must be 'approved' or 'denied'.",
                              ok=False, code=400)
    if not signing.verify(identifier, raw, sig):
        return _decision_page("Invalid or expired approval link.", ok=False, code=403)

    ap = db.get_approval(identifier) or {}
    label = "Approve" if raw in _APPROVE_WORDS else "Deny"
    body = f"""<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{label} this action?</title>
<style>body{{font:15px/1.5 system-ui;background:#0b0e17;color:#e6e8ee;display:grid;
place-items:center;height:100vh;margin:0}}form{{background:#151926;padding:28px;border-radius:16px;
border:1px solid #6a4fd8;max-width:460px;width:calc(100% - 32px)}}
b{{color:#9be7ff}}button{{margin-top:18px;padding:11px 20px;border-radius:10px;border:0;
background:{'#2f9e5f' if label=='Approve' else '#c0392b'};color:#fff;font:600 15px system-ui;
cursor:pointer}}</style>
<form method="post" action="/v1/approvals/{identifier}/decide">
<h2 style="margin:0 0 10px">{label} this action?</h2>
<div>Agent: <b>{ap.get('agent','')}</b></div>
<div style="margin-top:6px;word-break:break-word">{ap.get('action','') or '(no action recorded)'}</div>
<input type="hidden" name="decision" value="{raw}">
<input type="hidden" name="sig" value="{sig}">
<button type="submit">{label}</button>
</form>"""
    return HTMLResponse(body)


@app.post("/v1/approvals/{identifier}/decide")
async def v1_approval_decide(identifier: str, request: Request) -> HTMLResponse:
    """Apply a signed decision submitted from the confirmation form.

    Parsed by hand: python-multipart is not installed on this host, and a
    dependency just for two form fields is not worth it.
    """
    form = urllib.parse.parse_qs((await request.body()).decode("utf-8", "replace"))
    decision = (form.get("decision") or [""])[0]
    sig = (form.get("sig") or [""])[0]
    raw = (decision or "").strip().lower()
    if raw in _APPROVE_WORDS:
        status = "approved"
    elif raw in _DENY_WORDS:
        status = "rejected"
    else:
        return _decision_page("Decision must be 'approved' or 'denied'.", ok=False, code=400)

    if not signing.verify(identifier, raw, sig):
        return _decision_page("Invalid or expired approval link.", ok=False, code=403)

    try:
        updated = db.decide_approval(identifier, status, "discord-link", time.time())
    except LookupError as exc:
        return _decision_page(f"Approval already {exc}.", ok=False, code=409)
    if updated is None:
        return _decision_page("Approval not found.", ok=False, code=404)

    live.bump()
    broadcast_sse("approval", _approval_sse(updated))
    label = "Approved" if status == "approved" else "Denied"
    return _decision_page(f"{label} \u2014 {updated.get('agent','')} {updated.get('action','')}",
                          ok=True)


@app.get("/v1/approvals/{request_id}/wait")
async def v1_approval_wait(request_id: str, timeout: int = 25,
                           authorization: str | None = Header(default=None)) -> dict:
    """Long-poll the approval decision (ingest-token auth, the emitter waits here).

    Returns ``{"status": "pending"|"approved"|"denied"}``.  "pending" also covers
    the brief window before the approval.requested event has been processed.
    """
    _require_ingest(authorization)
    timeout = max(1, min(int(timeout), 120))
    deadline = time.time() + timeout
    while True:
        ap = db.get_approval(request_id)
        status = ap["status"] if ap else "pending"
        if status != "pending":
            return {"status": status}
        remaining = deadline - time.time()
        if remaining <= 0:
            return {"status": "pending"}
        await asyncio.sleep(min(0.5, remaining))


# Mount the static dashboard last: /healthz, /v1/state, /v1/stream and
# /v1/snapshots are registered above and match first; any other path is served
# from web/ (index.html for "/").
@app.middleware("http")
async def _no_cache_html(request, call_next):
    """Never let a browser reuse a stale dashboard.

    The page is a single self-contained HTML file; a cached copy silently runs
    old JS (controls appear dead after a fix). HTML gets no-store, everything
    else must revalidate.
    """
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    else:
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="dashboard")