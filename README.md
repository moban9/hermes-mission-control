# Hermes Mission Control

A real-time dashboard of what Hermes and its 17 bots are doing — agents, tasks,
the event stream, tool calls, throughput, cost, alerts, replay — plus a real
memory panel and an approval queue that routes to Discord.

Two real data paths, neither fabricated:
- **Path B (read-only):** the server reads Hermes' own `state.db` files (one per
  profile) + `kanban.db` and derives the dashboard state. No hooks, no writes.
- **Path A (hooks):** `emitter/plugin/` registers Hermes' own plugin hooks
  (`pre_llm_call`, `pre_api_request`, `post_api_request`, `pre_tool_call`,
  `post_tool_call`) to emit real context/usage/tool events and to gate risky
  tools with a real approval loop.

## Docs
- [The dashboard — panels, screenshot, functionality](docs/dashboard.md)
- [State map — path B](docs/state-map.md)
- [Hooks contract — path A](docs/hooks.md)
- [Deploy](docs/deploy.md)

![Mission Control dashboard](docs/dashboard.png)

## What it does

Reads, read-only, one `state.db` per profile (17 total) plus the shared
`kanban.db`, reduces them into a single JSON state shape, and serves it over a
small REST/SSE API. Snapshots are persisted every 30s to a *separate* Mission
Control database so the dashboard can replay history. It can never corrupt or
block an agent run: every Hermes connection is opened `file:<path>?mode=ro` with
`PRAGMA query_only=ON`, and a dashboard outage cannot touch an agent.

## Layout

```
server/
  app.py            FastAPI app: routes, SSE, 30s snapshotter, viewer token
  reducer.py        derives live state (agents, tasks, events, usage, cost)
  alerts.py         stuck / offline / error-burst / budget-risk rules
  db.py             read-only Hermes/kanban connections + writable MC db
  schema.sql        MC db schema (snapshots, alerts, approvals, commands, events)
  settings.py       env + shared .env resolution (tokens, Discord, memory dir)
  memory.py         real memory-file reader (path B: MEMORY.md/USER.md facts)
  live.py           in-memory path-A merge (context/usage/tool/state overlay)
  discord.py        async approval notifier -> #planning (background, redacting)
  requirements.txt  fastapi, uvicorn[standard], pydantic
emitter/
  mc_emitter.py     batched, non-blocking, redacting client (real HTTP to the MC)
  plugin/           the Hermes plugin — real hooks -> the emitter (path A)
web/
  index.html        the dashboard UI (exact Appendix A prototype, live data)
tests/
  smoke.py          end-to-end smoke test (real data, HTTP only, stdlib only)
  path_a_test.py    path-A test: events ingest + idempotency + approval round-trip
```

## Run

```bash
cd /opt/data/hermes-mission-control
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt

# single worker (uvicorn default), no Docker:
cd server
MC_VIEWER_TOKEN="change-me" ../.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
```

`uvicorn app:app` must be run from the `server/` directory (the modules import
each other as top-level modules). `--workers` must stay at its default `1`:
in-memory state (the snapshot cache) is single-worker by design.

## Endpoints

| Route | Auth | Returns |
|---|---|---|
| `GET /healthz` | none | `{"ok": true}` |
| `GET /v1/state` | token | full derived state |
| `GET /v1/stream` | token (query param `?token=`) | SSE: `snapshot` then `activity`/`approval` on change |
| `GET /v1/snapshots` | token | compact replay projection, oldest→newest |
| `POST /v1/events` | ingest token (`Bearer`) | `{"accepted": N, "duplicates": M}` (idempotent by event `id`) |
| `GET /v1/approvals` | token | `{"approvals": [...]}` (pending) |
| `POST /v1/approvals/{id}` | token | decision `{"decision": "approved"\|"denied"}`; 409 if already decided |
| `GET /v1/approvals/{id}/wait?timeout=25` | ingest token (`Bearer`) | `{"status": "pending"\|"approved"\|"denied"}` long-poll |
| `POST /v1/agents/{id}/command` | token | `501` with the exact reason — agent control has no write path into Hermes in this build |
| `GET /v1/approvals/{id}/decide?decision=…&sig=…` | signed HMAC (no token) | one-click Approve/Deny; HTML confirmation page |
| `POST /v1/admin/prune` | token | retention prune; `{days, tables:{snapshots/events/approvals:{before,deleted,after}}}` |

The viewer token is read from `MC_VIEWER_TOKEN`; when set, the read/decision
`/v1/*` routes require it via `?token=` or `Authorization: Bearer`. The ingest
token is `MC_INGEST_TOKEN` and gates `POST /v1/events` + the approval long-poll.
Leave either unset to disable that gate (local/dev only). `/healthz` stays open.

## Dashboard (web/)

`server/app.py` mounts `web/` at `/` (same process, no build step), so once the
server is running, open `http://<host>:8000/`. The page is a single
`web/index.html` (plain HTML/CSS/vanilla JS):

- Prompts for the viewer token on first load; keeps it in `sessionStorage` and
  never embeds it in the page. Wrong token → re-prompt on the 401.
- On load it fetches `/v1/state`, then opens `/v1/stream` (SSE) and re-renders
  on every `snapshot`/`activity` event.
- Panels: KPI row, 17-agent grid, task pipeline, live event stream, throughput,
  daily cost forecast, top tools, and alerts. Connection badge shows
  `Live` / `Reconnecting` plus the age of the last event.

## State shape (matches `docs/state-map.md` panel mapping)

- `agents` — one entry per profile (CEO + 16 bots): `name`, `model`, `status`
  (`online`/`stuck`/`offline`), `last_activity_at`, `last_activity_age_s`,
  `last_activity_description`, `title`, `current_action` (latest `tool_name`),
  `session_count`, `message_count`, `tool_call_count`, `tokens`
  (input/output/cache_read/cache_write/reasoning/total), `cost_usd`, plus
  path-A/path-B `memory` (real MEMORY.md/USER.md facts), and (when the plugin
  is emitting) `context`, `usage`, `state`, `live_tool_counts`, `tool_stats`.
- `memory` — the CEO's real memory files (top-level): `facts` + `user_facts`,
  each fact carrying the file's `mtime` (facts are not individually timestamped).
- `approvals` — the pending approval queue (agent, action, risk, status, …).
- `kpis` — totals (agents online/stuck, sessions, messages, tool calls, tokens,
  cost) + task pipeline counts.
- `tasks` — from `kanban.db` (id, title, assignee, status, priority, timestamps).
- `events` — recent `messages` stream (ts, agent, role, tool_name, text preview).
- `tool_counts` — `messages.tool_name` counts across all profiles.
- `throughput` — per-model `session_model_usage` rollups + total API calls.
- `cost_forecast` — last-14-day daily cost + today's spend vs `budget_usd`.
- `alerts` — see below.

## Alerts

| kind | rule (defaults) |
|---|---|
| `stuck_agent` | open session, active within the last 30 min, now silent > 90s |
| `agent_offline` | owns a `running` kanban task but silent > 30s |
| `error_burst` | 3+ task-failure events in 5 min |
| `budget_risk` | today's cost > daily budget (`MC_DAILY_BUDGET_USD`, default `10`) |

A "stuck" agent must have been active recently (engagement window, default 30
min): stale open sessions — bots whose work finished days ago but were never
finalized — read as `offline`, not `stuck`. Thresholds are env-configurable.

## Discord Approve/Deny

`discord.py::notify_approval` posts the approval to `#planning` with two
**signed one-click links** — `✅ Approve` / `⛔ Deny` — that land on
`GET /v1/approvals/{id}/decide`. The signature is an HMAC over
`request_id + decision` (key `MC_APPROVAL_SIGNING_KEY`, else the ingest token,
else the viewer token), so a third party who sees the message can't forge a
decision for a different approval or a different outcome.

Interactive **buttons** are not possible in this build: the notifier posts via a
webhook (which cannot receive interactions), and Hermes already owns the single
gateway connection for `DISCORD_BOT_TOKEN` (Discord allows one gateway session
per token). The signed link is the honest fallback — the links only work while
the approval is still pending and need `MC_DASHBOARD_URL` to point at the
publicly-reachable MC server (not `localhost`) for them to work "from anywhere".

## Retention (14 days)

`server/retention.py` deletes snapshots/events/approvals older than
`MC_RETENTION_DAYS` (default **14**) and reports `before`/`deleted`/`after`
per table. Idempotent and safe to call repeatedly:

```bash
cd server && ../.venv/bin/python retention.py            # prune now
cd server && ../.venv/bin/python retention.py --dry-run  # preview only

# or from cron, against the live server (viewer auth):
curl -X POST "http://<host>:8000/v1/admin/prune?token=$VIEWER" -H 'Content-Type: application/json' -d '{"days":14}'
```

## Config (env)

| Var | Default |
|---|---|
| `MC_VIEWER_TOKEN` | `""` (auth off) |
| `MC_INGEST_TOKEN` | `""` (ingest auth off) |
| `MC_HERMES_STATE_DB` | `/opt/data/state.db` |
| `MC_PROFILES_DIR` | `/opt/data/profiles` |
| `MC_KANBAN_DB` | `/opt/data/kanban.db` |
| `MC_DB` | `./data/mc.db` (writable MC state) |
| `MC_MEMORIES_DIR` | `/opt/data/memories` (CEO memory files) |
| `MC_ENV_FILE` | `/opt/data/.env` (shared-env fallback) |
| `MC_DISCORD_BOT_TOKEN` / `MC_DISCORD_CHANNEL_ID` | from `DISCORD_BOT_TOKEN` / `DISCORD_HOME_CHANNEL` |
| `MC_DISCORD_WEBHOOK_URL` | `""` (use bot token+channel unless set) |
| `MC_DASHBOARD_URL` | `http://localhost:8000/` (link in the approval DM) |
| `MC_APPROVAL_SIGNING_KEY` | ingest token, else viewer token (signs one-click Approve/Deny links) |
| `MC_RETENTION_DAYS` | `14` (prune snapshots/events/approvals older than this) |
| `MC_DAILY_BUDGET_USD` | `10` |
| `MC_ONLINE_AFTER_S` / `MC_STUCK_AFTER_S` / `MC_OFFLINE_AFTER_S` | `30` / `90` / `30` |
| `MC_STUCK_ENGAGEMENT_WINDOW_S` | `1800` |
| `MC_ERROR_BURST_THRESHOLD` / `MC_ERROR_BURST_WINDOW_S` | `3` / `300` |
| `MC_SNAPSHOT_INTERVAL_S` | `30` |
| `MC_SSE_POLL_INTERVAL_S` | `2` |

## Test

```bash
cd /opt/data/hermes-mission-control
MC_VIEWER_TOKEN="change-me" .venv/bin/python tests/smoke.py --url http://127.0.0.1:8000

# path A (events + approvals + Discord) — needs a running server and both tokens:
MC_VIEWER_TOKEN=... MC_INGEST_TOKEN=... .venv/bin/python tests/path_a_test.py --url http://127.0.0.1:8010

# spec-gap close (retention + signed links + agent-control 501) — unit checks
# run standalone; add --url + tokens for the HTTP checks:
.venv/bin/python tests/spec_gaps_test.py
```

`tests/smoke.py` reads real data (no fixtures) and asserts: `/healthz`, 17
populated agents, non-zero cost/messages/tasks/tools/events, snapshots, and that
the SSE stream opens and emits on new activity. `--watch` mode exits as soon as
an `activity` event arrives (pair it with a real kanban heartbeat to trigger).
