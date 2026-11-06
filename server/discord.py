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
import re
import threading
import urllib.request

import settings

_SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|Bearer\s+\S+|api[_-]?key\s*[=:]\s*\S+|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{10,})",
    re.I,
)

_MAX_ACTION_LEN = 500


def redact(text) -> str:
    if text is None:
        return ""
    return _SECRET.sub("[redacted]", str(text))


def _post(url: str, payload: dict, headers: dict | None = None) -> None:
    data = json.dumps(payload).encode("utf-8")
    # Discord rejects the default Python-urllib User-Agent with 403; a real one
    # is required for bot-token calls.
    hdrs = {"Content-Type": "application/json", "User-Agent": "MissionControl/1.0 (DiscordBot)"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    urllib.request.urlopen(req, timeout=10).read()


def notify_approval(agent: str, action: str, risk: str) -> str:
    """Queue an async Discord notification; returns the message text built.

    Never blocks the caller for more than the time it takes to build the string;
    the actual HTTP send happens on a daemon thread.
    """
    agent_s = redact(agent) or "unknown"
    action_s = redact(action) or "(no action)"
    if len(action_s) > _MAX_ACTION_LEN:
        action_s = action_s[:_MAX_ACTION_LEN] + "…"
    risk_s = redact(risk) or "med"
    dash = settings.DASHBOARD_URL.rstrip("/") + "/"

    msg = (
        "**Approval requested**\n"
        f"Agent: `{agent_s}`\n"
        f"Action: `{action_s}`\n"
        f"Risk: `{risk_s}`\n"
        f"Decide in the panel: {dash}"
    )

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
            print(f"[mc] discord notify failed: {exc}", flush=True)

    threading.Thread(target=_run, daemon=True).start()
    return msg
