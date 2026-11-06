# State Map — Path B (read-only)

Confirmed by Phase 0 recon on 2026-11-06. Hermes' own `state.db` already carries
everything Mission Control needs. **No emitter hooks required for v1** — read-only,
zero risk to the 16 live bots.

## Sources (one state.db per profile)
- CEO: `/opt/data/state.db`
- Bots: `/opt/data/profiles/<name>/state.db` (atlas, cask, keel, kestrel, keystone,
  ledger, meridian, nimbus, piston, prism, quill, relay, sable, seal, vera, byline)

## Tables that matter

### `sessions` — one row per session (drives agent cards + task pipeline + cost)
Columns used: `id, source, profile_name, model, started_at, ended_at,
last_activity_at, message_count, tool_call_count, input_tokens, output_tokens,
cache_read_tokens, cache_write_tokens, reasoning_tokens, estimated_cost_usd,
cost_status, title, last_activity_description`

### `messages` — full transcript (drives event stream + tool calls + current action)
Columns used: `session_id, role (user|assistant|tool), content, tool_name,
timestamp, token_count`
Recon snapshot: **10,744 messages / 118 sessions** in the CEO db.

### `session_model_usage` — per-session-per-model (drives throughput + model mix + cost)
Columns used: `session_id, model, billing_provider, api_call_count, input_tokens,
output_tokens, cache_read_tokens, estimated_cost_usd, first_seen, last_seen`

### `kanban.db` (separate, `/opt/data/kanban.db`)
Drives the task pipeline (queued/running/done/failed + per-task progress).

## Panel → source mapping

| Dashboard panel | Source |
|---|---|
| KPI row | derived from sessions + session_model_usage |
| Agent network | sessions (profile_name, last_activity_at, model, last_activity_description) |
| Task pipeline | kanban.db + sessions.title |
| Agent cards | sessions + latest messages.tool_name (current action) |
| Event stream | messages (role, tool_name, timestamp) |
| Throughput (tokens/s, latency) | session_model_usage + sessions tokens |
| Tool calls | messages.tool_name counts |
| Alerts (stuck/offline/error burst) | derived: no activity > 30s, task.failed bursts |
| Cost forecast | sessions.estimated_cost_usd + daily history |
| Replay | periodic snapshots of derived state |
| Approval queue | **Path A only** — deferred to v2 |

## Path A (future, optional)
Emitter SDK hooks (model client + tool dispatcher + lifecycle) for richer real-time
events and the approval/control channel. Not needed for v1. Revisit only if the
read-only view proves insufficient.

## Security
- Read-only access to state.db (`file:<path>?mode=ro`).
- Viewer token for the dashboard; a separate read-only token for guests.
- No writes back into Hermes. Dashboard outage cannot break an agent run.
