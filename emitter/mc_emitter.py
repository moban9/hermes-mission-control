"""Mission Control emitter — batched, non-blocking, secret-redacting client.

Never blocks Hermes, never raises into Hermes, batches events, redacts secrets.
Used by the mission-control plugin hooks (pre/post llm + tool call) to push real
events to the MC API. Path A (real hooks), not a read-the-db poll.
"""
import atexit
import json
import os
import queue
import re
import threading
import time
import urllib.request
import uuid
from server.redact import scrub_url_query

URL = os.getenv("MC_URL", "http://127.0.0.1:8010").rstrip("/")
TOKEN = os.environ.get("MC_INGEST_TOKEN", "")
RUN_ID = os.getenv("MC_RUN_ID", time.strftime("run_%Y-%m-%d_") + uuid.uuid4().hex[:4])
_AGENT = os.getenv("MC_AGENT_ID", "")
_q: "queue.Queue[dict]" = queue.Queue(maxsize=5000)
_SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|Bearer\s+\S+|api[_-]?key\s*[=:]\s*\S+)", re.I)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Reject redirects; sanitize defensively before urllib could follow."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        for name in list(req.headers) + list(req.unredirected_hdrs):
            if re.search(r"(?i)(authorization|cookie|credential|token|secret|key)", name):
                req.remove_header(name)
                req.unredirected_hdrs.pop(name, None)
        # Scrub before any redirect-target processing; redirects are never followed.
        scrub_url_query(newurl)
        raise urllib.error.HTTPError(None, code, "redirect refused", headers, None)


_opener = urllib.request.build_opener(_NoRedirect())


def _urlopen(request, timeout):
    """Open without redirects; never expose URL or credentials in diagnostics."""
    return _opener.open(request, timeout=timeout)


def _ulid() -> str:
    return f"{int(time.time()*1000):012x}{uuid.uuid4().hex[:14]}".upper()


def _clean(o):
    if isinstance(o, str):
        return _SECRET.sub("[redacted]", o)[:2000]
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o][:50]
    return o


def emit(type_: str, agent_id: str | None = None, **data):
    """Queue an event. Drops on full — never blocks the agent."""
    try:
        _q.put_nowait({
            "id": _ulid(),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time()*1000)%1000:03d}Z",
            "run_id": RUN_ID,
            "agent_id": agent_id or _AGENT or None,
            "type": type_,
            "data": _clean(data),
        })
    except queue.Full:
        pass


def _post(batch):
    req = urllib.request.Request(
        f"{URL}/v1/events",
        data=json.dumps(batch).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
    )
    for delay in (0.5, 2, 5):
        try:
            _urlopen(req, timeout=5).read()
            return
        except Exception:
            time.sleep(delay)


def _worker():
    while True:
        batch = [_q.get()]
        t_end = time.time() + 0.5
        while len(batch) < 100 and time.time() < t_end:
            try:
                batch.append(_q.get(timeout=0.1))
            except queue.Empty:
                pass
        _post(batch)


threading.Thread(target=_worker, daemon=True).start()
atexit.register(lambda: time.sleep(0.6))


def request_approval(agent_id: str, action: str, risk: str, timeout_s: int = 900) -> bool:
    """Blocks only this agent's tool call, not Hermes. Deny on timeout."""
    aid = uuid.uuid4().hex
    emit("approval.requested", agent_id, approval_id=aid, action=action, risk=risk)
    end = time.time() + timeout_s
    while time.time() < end:
        try:
            req = urllib.request.Request(
                f"{URL}/v1/approvals/{aid}/wait?timeout=25",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            status = json.loads(_urlopen(req, timeout=30).read())["status"]
            if status != "pending":
                return status == "approved"
        except Exception:
            time.sleep(2)
    return False
