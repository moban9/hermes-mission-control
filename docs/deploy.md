# Deploy — Mission Control

Minimal footprint on the always-on Hermes pod (no new VM, no Docker). One
`uvicorn` process + a SQLite file, plus a reverse proxy / tunnel for access.

## Pieces

| Piece | Where | Cost |
|---|---|---|
| MC API + dashboard (`server/app.py`, `web/`) | this pod, one uvicorn process | negligible |
| MC SQLite (`data/mc.db`) | this pod | negligible |
| Hermes hooks (the plugin) | each profile's `plugins/` | none (in-process) |
| Public access | a Cloudflare quick tunnel (preview) → later `mission.onendo.cloud` | none / domain only |

The POC GCP VM is **not** part of this deployment.

## Run locally

```bash
cd hermes-mission-control/server
MC_VIEWER_TOKEN=$(cat ../.viewer_token) \
MC_INGEST_TOKEN=$(cat ../.ingest_token) \
MC_DAILY_BUDGET_USD=10 \
../.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8010
```

Generate the two tokens once and keep them out of git:

```bash
openssl rand -hex 32 > ../.ingest_token   # Hermes → MC   (write)
openssl rand -hex 32 > ../.viewer_token   # operator → MC (read + decide)
chmod 600 ../.ingest_token ../.viewer_token
```

They must be different. The ingest token stays on the pod with the plugin; the
viewer token is what the dashboard prompts for.

## Install the plugin into the profiles

For each profile (`/opt/data/profiles/<name>/`), copy `emitter/plugin/` to
`<profile>/plugins/hermes-mission-control/` and add it to `plugins.enabled` in that
profile's `config.yaml`. Set `MC_URL` + `MC_INGEST_TOKEN` + `MC_AGENT_ID=<name>` in
the profile `.env` so the emitter knows where to post. Restart the profile's gateway
for the hooks to load.

A hook only fires in the profile that runs the turn, so install it everywhere to
cover the fleet.

## Public access

- **Preview (current):** `cloudflared tunnel --url http://127.0.0.1:8010` → a
  `*.trycloudflare.com` URL. Temporary; dies with the process.
- **Permanent:** `mission.onendo.cloud` via a named Cloudflare tunnel or a host
  reverse proxy. Pending the operator's A/B choice.

## Persistence

The MC process must survive a session end. Options on this pod (no systemd):
an s6 service, or a small watchdog cron that re-launches `uvicorn` if it is down.
The MC DB (`data/mc.db`) is gitignored and persists across restarts.

## Verify

```bash
curl -s http://127.0.0.1:8010/healthz          # {"ok":true}
curl -s "http://127.0.0.1:8010/v1/state?token=$VIEWER" | head -c 200
```

Open the dashboard, enter the viewer token, confirm Live + real data.
