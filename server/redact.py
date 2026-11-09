"""Redaction for anything Mission Control serves over HTTP.

Randy's rule: the dashboard must never expose credentials or IP addresses —
it is shown to guests with a read-only token, and the CEO's own memory notes
contain pod IPs and env-key names.

Canonical entry point: ``scrub_text`` for strings and ``scrub_obj`` for JSON-like
values. HTTP, SSE, HTML, notifier and diagnostic adapters must call this policy on
a fresh presentation copy immediately before serialization; HTML callers escape
the scrubbed result. Do not mutate sources or buffer complete SSE streams.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# Candidate extraction is followed by stdlib validation to avoid treating times as IPv6.
IPV6_CANDIDATE = re.compile(r"(?<![0-9A-Za-z:])\[?[0-9A-Fa-f:]{2,}(?![0-9A-Za-z:])")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:[A-Z0-9 ]* )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9 ]* )?PRIVATE KEY-----|-----BEGIN OPENSSH PRIVATE KEY-----[\s\S]*?-----END OPENSSH PRIVATE KEY-----")
PRIVATE_KEY_HEADER = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")
AUTH_HEADER = re.compile(r"(?im)(\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*:\s*)([^\r\n]+)")
CREDENTIAL_QUERY = re.compile(r"(?i)([?&](?:sig|signature|token|access_token|api_key|key|secret|password|credential)=)[^&#\s]*")
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
    out = PRIVATE_KEY.sub("[redacted-private-key]", text)
    # Header values and credential query parameters are removed before generic
    # assignment/name rules; markers contain no credential-shaped material.
    out = AUTH_HEADER.sub(r"\1[redacted]", out)
    out = CREDENTIAL_QUERY.sub(r"\1[redacted]", out)
    out = URL_USERINFO.sub(r"\1", out)
    out = TOKEN.sub("[redacted-token]", out)
    out = WEBHOOK.sub("[redacted-webhook]", out)
    out = ENV_ASSIGN.sub(lambda m: f"{m.group(1)}=[redacted]", out)
    out = KEY_NAME.sub(lambda m: f"[redacted-key-name]", out)
    out = CRED_ENV_NAME.sub("[redacted-key-name]", out)
    out = SECRET_PAIR.sub(lambda m: f"{m.group(1)}: [redacted]", out)
    out = IPV4.sub("[ip]", out)
    def replace_ipv6(match: re.Match[str]) -> str:
        candidate = match.group(0).strip("[]")
        try:
            ipaddress.IPv6Address(candidate)
        except ipaddress.AddressValueError:
            return match.group(0)
        return "[ip]"
    out = IPV6_CANDIDATE.sub(replace_ipv6, out)
    out = out.replace("[ip]]", "[ip]")
    out = PRIVATE_KEY_HEADER.sub("[redacted-private-key]", out)
    out = ENV_PATH.sub("[env-file]", out)
    out = ENV_WORD.sub("[env-file]", out)
    return out


def scrub_url_query(url: str) -> str:
    """Redact credential-like query values while preserving ordinary URL data."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    safe = [(key, "[redacted]" if re.search(r"(?i)(?:sig|token|secret|password|credential|api[_-]?key)", key) else value) for key, value in pairs]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe), parts.fragment))


def scrub_obj(obj: Any) -> Any:
    """Recursively scrub every string in a JSON-able structure."""
    if isinstance(obj, str):
        return scrub_text(obj)
    if isinstance(obj, dict):
        return {k: scrub_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub_obj(v) for v in obj]
    return obj
