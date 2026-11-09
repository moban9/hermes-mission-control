"""Discord notifier for Mission Control approvals.

Fires a message to the #planning channel when an agent requests an approval, so
Randy can open the dashboard and decide.  Runs in a background thread and never
raises into (or blocks) the ingest path — a Discord outage must not stall event
ingestion.

Send path: a webhook URL if configured, otherwise the bot token + channel id
(Discord REST ``POST /channels/{id}/messages``).  The action text is redacted
defensively (the emitter already redacts, but the server does its own pass).
"""

from __future__ import annotations

import json
import html
import threading
import urllib.request
from urllib.error import HTTPError
from urllib.parse import urlsplit

import settings
import signing
import redact as redact_policy

_MAX_ACTION_LEN = 500


def redact(text) -> str:
    return redact_policy.scrub_text("" if text is None else str(text))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post(url: str, payload: dict, headers: dict | None = None) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("unsafe notification URL")
    data = json.dumps(payload).encode("utf-8")
    # Discord rejects the default Python-urllib User-Agent with 403; a real one
    # is required for bot-token calls.
    hdrs = {"Content-Type": "application/json", "User-Agent": "MissionControl/1.0 (DiscordBot)"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        opener.open(req, timeout=10).read()
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise ValueError("notification redirect refused") from None
        raise


def _decision_url(request_id: str, decision: str) -> str | None:
    """Signed one-click URL for a decision, or None when no signing key is set."""
    if not signing.available():
        return None
    base = settings.DASHBOARD_URL.rstrip("/")
    sig = signing.sign(request_id, decision)
    return f"{base}/v1/approvals/{request_id}/decide?decision={decision}&sig={sig}"


def notify_approval(agent: str, action: str, risk: str,
                    request_id: str | None = None) -> str:
    """Queue an async Discord notification; returns the message text built.

    Never blocks the caller for more than the time it takes to build the string;
    the actual HTTP send happens on a daemon thread.

    Interactive Approve/Deny *buttons* are not available to this build: the
    notifier posts via a webhook (which cannot receive interactions), and Hermes
    already owns the single gateway connection for ``DISCORD_BOT_TOKEN`` (Discord
    allows one gateway session per token).  The honest fallback is two
    **signed one-click links** that land on ``GET /v1/approvals/{id}/decide``.
    """
    agent_s = html.escape(redact(agent) or "unknown")
    action_s = html.escape(redact(action) or "(no action)")
    if len(action_s) > _MAX_ACTION_LEN:
        action_s = action_s[:_MAX_ACTION_LEN] + "…"
    risk_s = html.escape(redact(risk) or "med")
    dash = settings.DASHBOARD_URL.rstrip("/") + "/"

    lines = [
        "**Approval requested**",
        f"Agent: `{agent_s}`",
        f"Action: `{action_s}`",
        f"Risk: `{risk_s}`",
    ]

    if request_id:
        approve = _decision_url(request_id, "approved")
        deny = _decision_url(request_id, "denied")
        if approve and deny:
            lines.append("")
            lines.append(f"✅ [Approve]({approve})  ·  ⛔ [Deny]({deny})")
        else:
            lines.append("")
            lines.append(f"Decide in the panel: {dash}")
    else:
        lines.append(f"Decide in the panel: {dash}")

    msg = "\n".join(lines)

    webhook = settings.DISCORD_WEBHOOK_URL
    token = settings.DISCORD_BOT_TOKEN
    channel = settings.DISCORD_CHANNEL_ID

    def _run() -> None:
        try:
            if webhook:
                _post(webhook, {"content": msg})
            elif token and channel:
                url = f"https://discord.com/api/v10/channels/{channel}/messages"
                _post(url, {"content": msg}, headers={"Authorization": f"Bot {token}"})
            else:
                print("[mc] discord notify skipped: no webhook/token/channel", flush=True)
        except Exception as exc:  # never let Discord take the app down
            print(f"[mc] discord notify failed ({type(exc).__name__})", flush=True)

    threading.Thread(target=_run, daemon=True).start()
    return msg
