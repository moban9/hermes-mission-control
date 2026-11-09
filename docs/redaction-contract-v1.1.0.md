# MC redaction boundary contract v1.1.0

Status: additive clarification for t_5a79aebf; pending Meridian's bounded review of sections 1 and 2 only. Owner: Keystone. Implementer: Piston. This is design evidence, NOT runtime acceptance, deployment permission, or an authentication/policy exception.

This amendment incorporates [v1.0.0](redaction-contract-v1.0.0.md) in full. Only the ambiguity resolved in sections 1 and 2 is superseded; all confidentiality classes, markers, route coverage, independent detection, redirects, logging, idempotence, authorization and acceptance requirements remain mandatory. Existing OpenAPI/event schemas remain authoritative: no endpoint, successful-response field, persistence schema or dependency is added. The signed-capability decision remains separately owned by Randy (t_8271b6c9); this amendment MUST NOT disable or replace that approved flow or claim the URL secrecy gate passes.

## 1. Source versus projection versus serialization — normative

### 1.1 Domain and ownership

```mermaid
flowchart LR
  S[Canonical sources and persisted snapshots: raw] --> R[Reducer and replay projection: raw]
  R --> C[Internal state cache: raw]
  R --> B[Per-response or per-event egress boundary]
  C --> B
  A[Approval records and raw event queues] --> B
  B --> P[Scrubbed public presentation copy]
  P --> J[JSON or SSE serialization]
  P --> H[HTML escaping then HTML serialization]
```

“Raw” means unchanged by this redaction policy, not that sources bypass normal parsing, access controls, validation or existing reducer selection. A reducer projection is NOT a scrubbed public presentation.

- Source readers MUST read canonical values without applying presentation redaction. Stored records, source files and persisted snapshots MUST NOT be rewritten by redaction.
- Reducer/replay projections and the internal state cache MUST retain raw values under their existing selection rules. Redaction MUST NOT mutate their objects, nested containers, source records or event queues in place. Source snapshots and cache contents MUST NOT be replaced with a previously scrubbed presentation.
- The egress boundary MUST be the only layer that performs this policy's redaction. It MUST derive a separate public presentation copy after selection/projection and immediately before serialization. `server/redact.py` is the canonical policy implementation; endpoint, SSE, notifier and logging adapters MUST use that same policy, not weaker parallel patterns. “Only” names a logical security layer, not a single HTTP route or one function call for the entire process.
- Every authorized dynamic-data emission MUST cross that boundary, regardless of owner/guest, cached/live/historical/error branch, or transport. JSON, each SSE event, dynamic HTML, notification fields and diagnostic logs are separate egress adapters. Each MUST enforce the policy before it emits data. Credentials intentionally supplied to the configured authentication/delivery destination are not display text; this does not authorize forwarding them on redirects or logging them. The separate signed-capability decision remains unresolved by this contract.
- At inspected source, `v1_state` cached/live, `v1_snapshots` after replay projection, and SSE `snapshot`/`activity` already call the scrubber. This is a location observation, NOT evidence that all rules pass. Approvals, queued events and any other unsanitized egress MUST NOT be treated as covered because the reducer or another endpoint was tested.
- SSE initial `snapshot`, changed-state `activity`, approval replay and queued requested/decided events MUST invoke the same canonical presentation policy before their individual `_sse` serialization. Approval replay and queue MUST use the same approval field selection and presentation adapter. Event names, IDs, ordering and successful payload schemas MUST remain unchanged. Producers MUST NOT pre-scrub queue records. Implementations MUST NOT buffer the complete/unbounded stream; a failure MUST NOT yield a partial unsafe event.
- New endpoints MUST register their dynamic-data serialization boundary and actual route test before acceptance. A raw projection MUST NOT be returned directly. Static literals need no text substitution; framework errors, redirects and validation echoes with dynamic content still need safe egress handling.

### 1.2 Closed keys, dynamic keys and fail-closed behavior

Closed-schema field names MUST remain byte-identical. Arbitrary user-controlled map keys are data, NOT schema names: known exposed surfaces include `tool_counts`, `agents[].live_tool_counts`, `agents[].tool_stats`, unrestricted `agents[].state`, and nested context/message/tool objects. Implementers MUST NOT claim such maps are absent or inspect only values.

The boundary MUST inspect dynamic keys recursively. Safe dynamic keys MUST remain identical. If a dynamic key contains forbidden material, the adapter MUST fail closed for that response/event before any affected payload bytes are serialized; it MUST NOT rename the key, merge colliding entries, drop individual entries, change numeric metrics, or substitute a new map representation. For HTTP, use the existing generic failure channel with fixed non-sensitive text (HTTP 500, `{"detail":"Internal Server Error"}`), not a successful altered payload. For SSE, close the stream before the affected event; do not invent a new event schema. Notification delivery MUST be suppressed on such failure; diagnostics MUST contain only a fixed bounded failure code, never the unsafe key/value. Canonical objects remain unchanged. This deliberately sacrifices availability for confidentiality and schema/metric integrity. A future safe map representation/removal requires explicit schema-owner review; it is NOT approved here.

## 2. Identity and typed-control preservation — normative

### 2.1 Invariants and classification

- Task IDs (`t_*`), request/session/event IDs, agent/profile names, relationship IDs, closed-schema keys, valid canonical timestamp fields, validated enum values, numeric metrics, booleans and nulls MUST NOT be rewritten, normalized, truncated, case-folded or type-coerced by redaction. In particular a timestamp MUST NOT be parsed/reformatted by the scrubber, and a request ID MUST NOT be replaced with a marker and used as a join/dedup key.
- Identity/enum/timestamp classification MUST follow the existing schema and validated source field, not a blanket exemption for any string under a key named `id`, `agent`, `status` or `timestamp`. Free text containing credential/IP syntax MUST still be scrubbed. Unknown/malformed source strings MUST NOT become trusted identifiers/enums merely because the UI expects that type.
- If an identity field contains forbidden material, or a canonical typed timestamp/enum is invalid or would be changed by the redaction policy, the egress adapter MUST fail closed as in 1.2 rather than leak it, redact it into a different identity, normalize it, or relax a rule. Ordinary valid identifiers and typed controls MUST pass unchanged. This is not a new source write-validation rule or migration.
- A valid non-sensitive ISO timestamp MUST remain byte-identical, including its timezone spelling, offset and fractional precision. A timestamp-shaped string with an embedded secret in free text is NOT a timestamp field: redact the sensitive substring while preserving safe surrounding text. The same malformed value in a typed timestamp field MUST trigger the fail-closed rule; stored canonical values MUST remain untouched. Clock components such as `05:14:00` MUST NOT be misclassified as IPv6 merely by punctuation. IPv6 candidates MUST be verified independently with stdlib `ipaddress` during acceptance, including compressed/full/loopback/bracketed cases.
- Numeric values MUST retain value and JSON number type; booleans MUST remain booleans, not numeric stand-ins. Preservation assertions compare decoded field values/types and UTF-8 string bytes, not JSON whitespace/key-order formatting. Arrays, relationships and metric values MUST remain unchanged on successful output.

### 2.2 Exact unchanged-control fixture

The following synthetic JSON fixture defines expected output equal to input. Every string value MUST survive byte-identical; closed keys, nested structure, list order and scalar types MUST remain unchanged. Test it both through the policy and actual authorized HTTP/SSE emission; scrub twice MUST equal scrub once. Safe free-text assignments are not secret `NAME=value` cases: credential-bearing assignments MUST still be removed.

```json
{
  "task_id": "t_43f53b7b",
  "request_id": "req_redaction_control_001",
  "session_id": "session-control-001",
  "agent": "keystone",
  "profile": "meridian",
  "timestamp": "2026-11-09T05:14:00Z",
  "timestamp_offset": "2026-11-09T12:14:00+07:00",
  "timestamp_fraction": "2026-11-09T05:14:00.123456Z",
  "status": "pending",
  "status_controls": ["running", "approved", "denied", "cancelled"],
  "public_host": "mission.onendo.cloud",
  "public_url": "https://mission.onendo.cloud/v1/state",
  "prose": "Keystone reviews the task.",
  "harmless_assignment": "status=running",
  "context": "https://[ip]:27124 (bridge-only, self-signed)",
  "metrics": {"count": 7, "ratio": 0.25, "zero": 0, "negative": -1},
  "enabled": false,
  "missing": null
}
```

Fixture labels do not introduce schema fields or approve a status vocabulary; test adapters MUST place these controls into existing schema-appropriate fields. Existing API contracts own actual field names and enum membership.

### 2.3 Adversarial fixture and required assertions

All values below are synthetic test material, not live credentials. Each sensitive input MUST change, and the entire planted sensitive substring MUST be absent from emitted text. Tests MUST assert exact expected output using v1.0.0 markers, plus independent sentinel absence; `input != output` alone is insufficient. For token/name/IP/webhook/env cases use respectively `[redacted-token]`, `[redacted-key-name]`, `[ip]`, `[redacted-webhook]`, `[env-file]`. Preserve safe surrounding ports, hostnames and prose. v1.0.0 owns other existing marker semantics and private-key-marker documentation.

| Class | Synthetic input / test construction | Required outcome |
|---|---|---|
| IPv4 | `192.0.2.24` | `[ip]` |
| IPv6 | `::1`, `2001:db8::24`, `2001:0db8:0000:0000:0000:0000:0000:0024` | Each literal becomes `[ip]`; independently validate the inputs with `ipaddress` |
| Bracketed IPv6 | `https://[2001:db8::24]:27124 (bridge-only, self-signed)` | Exactly `https://[ip]:27124 (bridge-only, self-signed)` |
| Guest/vendor tokens | `mc-g-SYNTHETIC_SENTINEL_001`, `sk-SYNTHETIC_SENTINEL_002`, `ghp_SYNTHETICSENTINEL000000000003`, `AKIAABCDEFGHIJKLMNOP`, `xoxb-SYNTHETIC-SENTINEL-004` | Each entire token becomes `[redacted-token]` |
| JWT | `eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzeW50aGV0aWMifQ.c3ludGhldGljX3NpZ25hdHVyZQ` | Entire token becomes `[redacted-token]` |
| Assignment | `NAME=SYNTHETIC_SENTINEL_005`, `OBSIDIAN_API_KEY=SYNTHETIC_SENTINEL_006` | Values absent, including quoted/multiline forms; credential name scrubbed when applicable |
| Credential names | `SERVICE_KEY`, `SERVICE_TOKEN`, `SERVICE_SECRET`, `SERVICE_PASSWORD` | Each becomes `[redacted-key-name]`; closed schema keys are not this free-text case |
| Webhooks | `https://discord.com/api/webhooks/123/SYNTHETIC_SENTINEL_007`, `https://hooks.slack.com/services/T000/B000/SYNTHETIC_SENTINEL_008`, `https://api.telegram.org/bot123:SYNTHETIC_SENTINEL_009/sendMessage` | Each entire URL becomes `[redacted-webhook]` |
| URL userinfo | `https://synthetic-user:SYNTHETIC_SENTINEL_010@mission.onendo.cloud/path` | Userinfo removed, exactly `https://mission.onendo.cloud/path` |
| Dotenv | `/srv/app/.env.production`, `.env` | Each becomes `[env-file]` |
| Private key/header | Complete synthetic PEM/SSH private-key header, body sentinel and footer | No header/body secret material survives; stable documented marker; keep v1.0.0 full-block coverage |
| Credential headers | Synthetic Authorization Bearer/Basic and Cookie values | No credential survives; retain existing header/redirect acceptance |
| Timestamp-shaped prose | `2026-11-09T05:14:00Z sk-SYNTHETIC_SENTINEL_011` | Exactly `2026-11-09T05:14:00Z [redacted-token]` in free text; reject whole emission if supplied as a typed timestamp |
| Identity collision | Token-shaped request ID or credential-shaped agent name | Fail closed; MUST NOT substitute an identity marker or emit the raw identity |
| Dynamic-key collision | Map with `SERVICE_TOKEN`, `[redacted-key-name]`, and `safe_tool` as distinct keys | Fail closed; no renaming/merging, no secret key in errors/logs, source map unchanged |

Bare harmless uppercase words are not credentials solely because they are uppercase. This does not relax credential-bearing `NAME=value`, suffix-name, token, header, private-key or URL rules. Every previous adversarial class MUST still be tested, including escaped/nested strings and maps. An invalid/corrupt semantic control MUST NOT be used to weaken confidentiality.

## Review and downstream evidence

Meridian's re-check is bounded to sections 1 and 2: confirm layer ownership, no bypass for SSE/replay/queues, map-key fail-closed compatibility, byte-identical controls, timestamp/identity collision behavior, and no policy weakening. The original review t_c711fb1a is preserved; no blanket prior approval is claimed. Piston build t_4f315c0f and tests t_d58baa6d MUST wait for that re-check. Runtime failures or implementation gaps remain Piston's work, not a reason to rewrite the approved semantics here.

Contract checks only: verify this amendment retains v1.0.0 unchanged, parse the control JSON and validate timestamp/IP/JWT fixture shapes with stdlib, and read back the exact vault mirror. Passing those checks does NOT assert the current scrubber, routes or live system pass acceptance.
