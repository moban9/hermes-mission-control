"""Redaction for anything Mission Control serves over HTTP.

Randy's rule: the dashboard must never expose credentials or IP addresses —
it is shown to guests with a read-only token, and the CEO's own memory notes
contain pod IPs and env-key names.

This is applied at the API boundary (app.py), not in the browser: client-side
redaction is theatre, because anyone can read the raw JSON.
"""

from __future__ import annotations

import re
from typing import Any

IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
IPV6 = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b")
# our own guest token shape and common vendor token shapes
TOKEN = re.compile(
    r"\b(?:mc-[a-z]-[A-Za-z0-9_\-]{8,}"
    r"|sk-[A-Za-z0-9_\-]{12,}"
    r"|(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{20,}"
    r"|xox[baprs]-[A-Za-z0-9\-]{10,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})\b"
)
# FOO_KEY=value / TOKEN=value inside prose
ENV_ASSIGN = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\s*=\s*([^\s,;'\")\]]+)")
# bare credential-ish names, e.g. OBSIDIAN_API_KEY, MC_INGEST_TOKEN
KEY_NAME = re.compile(r"([A-Z][A-Z0-9_]{1,})_(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)S?")
# key: value prose
SECRET_PAIR = re.compile(
    r"(?i)\b(password|passwd|passphrase|secret|api[_\s-]?key|token|bearer)\b"
    r"\s*[:=]\s*\S+"
)
# userinfo in a URL, e.g. https://user:pass@host
URL_USERINFO = re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.\-]*://)[^\s/@]+@")
# dotenv file paths and bare mentions
ENV_PATH = re.compile(r"(/[\w./\-]*\.env[\w.]*)")
ENV_WORD = re.compile(r"(?<![\w.])\.env\b")
# webhooks and DSNs carry their secret in the URL path
WEBHOOK = re.compile(
    r"\b(https?://(?:discord(?:app)?\.com/api/webhooks|hooks\.slack\.com/services"
    r"|api\.telegram\.org/bot)[^\s'\"<>)]*)"
)
CRED_ENV_NAME = re.compile(
    r"\b([A-Z][A-Z0-9_]{2,}_(?:WEBHOOK_URL|WEBHOOK|DSN|HOOK_URL|URL_KEY|CONNECTION_STRING))\b"
)


def scrub_text(text: str) -> str:
    """Redact IPs, credentials, tokens and env references from one string."""
    if not isinstance(text, str) or not text:
        return text
    out = URL_USERINFO.sub(r"\1", text)
    out = TOKEN.sub("[redacted-token]", out)
    out = WEBHOOK.sub("[redacted-webhook]", out)
    out = ENV_ASSIGN.sub(lambda m: f"{m.group(1)}=[redacted]", out)
    out = KEY_NAME.sub(lambda m: f"[redacted-key-name]", out)
    out = CRED_ENV_NAME.sub("[redacted-key-name]", out)
    out = SECRET_PAIR.sub(lambda m: f"{m.group(1)}: [redacted]", out)
    out = IPV4.sub("[ip]", out)
    out = IPV6.sub("[ip]", out)
    out = ENV_PATH.sub("[env-file]", out)
    out = ENV_WORD.sub("[env-file]", out)
    return out


def scrub_obj(obj: Any) -> Any:
    """Recursively scrub every string in a JSON-able structure."""
    if isinstance(obj, str):
        return scrub_text(obj)
    if isinstance(obj, dict):
        return {k: scrub_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub_obj(v) for v in obj]
    return obj
