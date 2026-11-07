"""HMAC-signed one-click approval links for Mission Control.

Randy's requirement is "approve from anywhere": the Discord notification should
let him decide without opening the dashboard or typing the viewer token.  A
Discord *webhook* cannot receive interactions, and Hermes already holds the only
gateway connection for ``DISCORD_BOT_TOKEN`` (Discord allows one gateway session
per bot token), so an interactive component flow is not available to this build.
The honest fallback is a **signed one-click URL**: the notifier mints two links
(Approve / Deny) that carry an HMAC over ``request_id + decision``, so a third
party who sees the message cannot forge a decision for a different approval or a
different outcome.

The key is derived in ``settings.py`` (``MC_APPROVAL_SIGNING_KEY``, else the
ingest token, else the viewer token).  Both the notifier and the ``/decide``
route share this module, so a signature is always produced and verified with the
same secret.
"""

from __future__ import annotations

import hashlib
import hmac

import settings


def _key() -> bytes:
    return (settings.APPROVAL_SIGNING_KEY or "").encode("utf-8")


def sign(request_id: str, decision: str) -> str:
    """Return the hex HMAC binding ``request_id`` to ``decision``."""
    msg = f"{request_id}\n{decision}".encode("utf-8")
    return hmac.new(_key(), msg, hashlib.sha256).hexdigest()


def verify(request_id: str, decision: str, sig: str | None) -> bool:
    """Constant-time check of a signature (False when no signing key is set)."""
    if not settings.APPROVAL_SIGNING_KEY or not sig:
        return False
    return hmac.compare_digest(sign(request_id, decision), str(sig))


def available() -> bool:
    """True when signed links can actually be minted/verified (a key exists)."""
    return bool(settings.APPROVAL_SIGNING_KEY)
