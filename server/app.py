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
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

import db
import reducer

VIEWER_TOKEN = os.environ.get("MC_VIEWER_TOKEN", "")
SNAPSHOT_INTERVAL_S = float(os.environ.get("MC_SNAPSHOT_INTERVAL_S", "30"))

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
) -> None:
    """Optional viewer-token gate.  Off unless MC_VIEWER_TOKEN is set."""
    if not VIEWER_TOKEN:
        return
    provided = token
    if not provided and authorization and authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if provided != VIEWER_TOKEN:
        raise HTTPException(status_code=401, detail="invalid or missing viewer token")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


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
    """Yield an initial snapshot, then an 'activity' event on any change."""
    # Baseline fingerprint, then the initial snapshot.
    last_fp = await asyncio.to_thread(reducer.activity_fingerprint)
    state = await asyncio.to_thread(reducer.reduce_state)
    yield _sse("snapshot", state)

    last_keepalive = time.time()
    while True:
        await asyncio.sleep(SSE_POLL_INTERVAL_S)
        fp = await asyncio.to_thread(reducer.activity_fingerprint)
        if fp != last_fp:
            last_fp = fp
            state = await asyncio.to_thread(reducer.reduce_state)
            yield _sse("activity", state)
            last_keepalive = time.time()
        elif time.time() - last_keepalive >= SSE_KEEPALIVE_S:
            yield ": ping\n\n"
            last_keepalive = time.time()


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_mc_db()
    _snapshot_once()  # seed the cache + first snapshot immediately
    thread = threading.Thread(target=_snapshot_loop, daemon=True)
    thread.start()
    try:
        yield
    finally:
        STATE.running.clear()


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
        return cached["state"]
    state = reducer.reduce_state()
    with STATE.lock:
        STATE.latest = {"state": state, "ts": time.time()}
    return state


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
    return {"snapshots": out}


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


# Mount the static dashboard last: /healthz, /v1/state, /v1/stream and
# /v1/snapshots are registered above and match first; any other path is served
# from web/ (index.html for "/").
app.mount("/", StaticFiles(directory=_WEB_DIR, html=True), name="dashboard")
