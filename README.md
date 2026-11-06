# Mission Control — server core

Read-only Mission Control for the Hermes bot org: a FastAPI server that derives a
live dashboard view (agents, tasks, events, cost, alerts) straight from Hermes'
existing SQLite databases. **No emitter hooks, no writes into Hermes.**

Path B per `docs/state-map.md`.

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
  schema.sql        MC db schema (snapshots, alerts + Path-A approvals/commands)
  requirements.txt  fastapi, uvicorn[standard], pydantic
tests/
  smoke.py          end-to-end smoke test (real data, HTTP only, stdlib only)
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
| `GET /v1/stream` | token (query param `?token=`) | SSE: `snapshot` then `activity` on change |
| `GET /v1/snapshots` | token | list of persisted snapshots (`id`, `captured_at`) |

The viewer token is read from `MC_VIEWER_TOKEN`; when set, all `/v1/*` routes
require it via `?token=` or `Authorization: Bearer`. Leave it unset to disable
auth (local/dev only). `/healthz` stays open.

## State shape (matches `docs/state-map.md` panel mapping)

- `agents` — one entry per profile (CEO + 16 bots): `name`, `model`, `status`
  (`online`/`stuck`/`offline`), `last_activity_at`, `last_activity_age_s`,
  `last_activity_description`, `title`, `current_action` (latest `tool_name`),
  `session_count`, `message_count`, `tool_call_count`, `tokens`
  (input/output/cache_read/cache_write/reasoning/total), `cost_usd`.
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

## Config (env)

| Var | Default |
|---|---|
| `MC_VIEWER_TOKEN` | `""` (auth off) |
| `MC_HERMES_STATE_DB` | `/opt/data/state.db` |
| `MC_PROFILES_DIR` | `/opt/data/profiles` |
| `MC_KANBAN_DB` | `/opt/data/kanban.db` |
| `MC_DB` | `./data/mc.db` (writable MC state) |
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
```

`tests/smoke.py` reads real data (no fixtures) and asserts: `/healthz`, 17
populated agents, non-zero cost/messages/tasks/tools/events, snapshots, and that
the SSE stream opens and emits on new activity. `--watch` mode exits as soon as
an `activity` event arrives (pair it with a real kanban heartbeat to trigger).
