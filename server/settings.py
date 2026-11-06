"""Mission Control configuration.

Resolves settings from the process environment first, then from the shared
``/opt/data/.env`` (``MC_ENV_FILE``) as a fallback.  This lets the server pick
up ``DISCORD_BOT_TOKEN`` / ``DISCORD_HOME_CHANNEL`` (which live in the shared
.env) without re-declaring them in the launch command, while still allowing
every value to be overridden per-process.

No third-party dotenv dependency: the .env format used here is simple
``KEY=value`` lines, parsed inline.
"""

from __future__ import annotations

import os

ENV_FILE = os.environ.get("MC_ENV_FILE", "/opt/data/.env")


def _load_dotenv(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                    val = val[1:-1]
                env[key] = val
    except OSError:
        pass
    return env


_DOTENV = _load_dotenv(ENV_FILE)


def get(name: str, default: str = "") -> str:
    """Process env wins; fall back to the shared .env; then ``default``."""
    if name in os.environ:
        return os.environ[name]
    return _DOTENV.get(name, default)


# --- Auth -------------------------------------------------------------------
# Viewer token gates the dashboard / read endpoints (off when empty, dev only).
VIEWER_TOKEN = get("MC_VIEWER_TOKEN", "")
# Ingest token gates the emitter's event/approval long-poll endpoints.
INGEST_TOKEN = get("MC_INGEST_TOKEN", "")

# --- Discord notifier -------------------------------------------------------
# Prefer an explicit webhook (channel baked in); otherwise bot token + channel.
DISCORD_WEBHOOK_URL = get("MC_DISCORD_WEBHOOK_URL", "")
DISCORD_BOT_TOKEN = get("MC_DISCORD_BOT_TOKEN", "") or get("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = get("MC_DISCORD_CHANNEL_ID", "") or get("DISCORD_HOME_CHANNEL", "")

# --- Dashboard link (put in the approval notification so Randy can decide) --
DASHBOARD_URL = get("MC_DASHBOARD_URL", "http://localhost:8000/")

# --- Memory files (path B) --------------------------------------------------
MEMORIES_DIR = get("MC_MEMORIES_DIR", "/opt/data/memories")
