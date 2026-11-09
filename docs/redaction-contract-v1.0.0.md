# MC redaction boundary contract v1.0.0

Status: implementation contract for t_e8ce5f76; NOT test acceptance, deployment authorization or relaxation approval. Owner: Keystone. Implementation: Piston. Data-contract review: Meridian. Only Randy may approve policy relaxation or replacement of an approved authentication architecture.

## Domain and invariants

An internal free-text value is untrusted and potentially confidential. A public projection is a derived view, never an authorization grant and never the canonical stored value. Owner and guest projections follow the same redaction rule. Retain schema field names, object identity fields, numeric metrics, boolean/null values, ordering and task relationships. Do not modify source records or snapshots in storage. Scrub after projection and before serialization, including cached, historical, error and incremental paths. A guest has no write permissions before or after redaction.

```mermaid
erDiagram
  SOURCE_RECORD ||--o{ PUBLIC_PROJECTION : derives
  PUBLIC_PROJECTION ||--o{ TRANSPORT_RESPONSE : serializes
  REDACTION_POLICY ||--o{ PUBLIC_PROJECTION : governs
  ROUTE_TEST }o--|| TRANSPORT_RESPONSE : verifies
```

These are logical entities only: no tables, migration or new endpoint required. Existing APIs and event schemas remain unchanged; redaction is a presentation transformation. Keep the existing OpenAPI security requirements. For new task-detail routes, the existing task-detail contract still owns the response schema.

## Policy decisions

Always remove all valid IPv4 and IPv6 forms (including ::1, compressed IPv6 and URL-bracketed literals); credential-shaped tokens, JWTs, complete private-key blocks and SSH private-key headers; credentials in URL userinfo; credential assignments/names; Discord/Slack/Telegram credential-bearing webhook URLs; and dotenv references/paths. Use existing markers: [ip], [redacted-token], [redacted], [redacted-key-name], [redacted-webhook], [env-file]. Private-key marker must be stable, documented, and must not leave key body material exposed. Never rely on regexes that also underlie verification to prove absence.

Preserve ordinary prose, public hostnames such as mission.onendo.cloud, agent names, exact task IDs, ISO timestamps, non-secret URL paths, ports, and bridge-only/self-signed context. Required exact meaningful result: `https://[ip]:27124 (bridge-only, self-signed)`. Preserve harmless enum assignments such as `status=running`; do not scrub every uppercase assignment by default if it destroys non-secret controls. Scrubbing must be idempotent. Preserve structural JSON keys from closed schemas; never silently rename arbitrary dictionary keys and collide. If free-text user-controlled map keys are exposed, remove that surface or use a compatible safe representation with explicit schema-owner review; do not overlook them.

Trade-off: this is confidential public presentation, not a lossless lakehouse interface. Never ingest redacted output as canonical evidence or deduplication keys. Source identity and metrics remain intact. No owner bypass or frontend-only exception. Publish one concise operational policy at docs/redaction.md; this versioned design is its rationale, not a second competing policy.

## Transport inventory and mandatory proof

Inventory installed route registrations at test time, not only this list. Route tests must enter the ASGI app or actual HTTP transport with real auth dependency execution, not call handler functions or just assert source text. Use stdlib unittest/mock/asyncio and existing runtime dependencies; add no dependencies. A stdlib ASGI send/receive harness is acceptable. Isolate DB/cache/settings and restore globals; never mutate production data.

| Surface | Required exercised branch |
|---|---|
| GET /v1/state | fresh cache and live reduction with nested malicious memory notes |
| GET /v1/snapshots | projected historical agent title containing planted sentinel |
| GET /v1/stream | initial snapshot, changed activity, approval replay, queued approval requested and decided; bounded cancellation and subscriber cleanup |
| GET /v1/approvals | pending action/agent/reason free text |
| GET /v1/agents/stuck | returned diagnostic/session text if present |
| POST /v1/agents/stuck/resolve | guest 403; owner diagnostic text scrubbed in isolated fixture |
| POST /v1/approvals/{identifier} | guest 403; owner success/conflict projection scrubbed |
| GET/POST /v1/approvals/{identifier}/decide | authorization and HTML output, HTML escaping after scrub, no capability leakage |
| GET /v1/approvals/{request_id}/wait | reject guest; enum-only authorized response |
| POST /v1/events | reject guest; inspect authorized response for any echoed free text |
| GET /v1/tasks/{id} | when installed: malicious title/body/comments/results/errors; missing route is explicitly NOT IMPLEMENTED, never PASS |

Every other newly installed free-text endpoint (including pipeline routes) needs the same guard. Report route, method, principal, branch/event, status, seeded-sensitive-data absence, and preserved control. Authorization-denied is not proof that an authorized free-text response was scrubbed. No blanket response body middleware that buffers an unbounded SSE stream. Prefer a shared serialization primitive for SSE so queued events cannot bypass it.

## Redirect and logging security

Static inspection at baseline b7f6d95 found signed approval capabilities in discord.py::_decision_url query `sig`, urllib default redirect following in _post, raw exception printing in notify_approval, a separate weaker notifier scrubber, raw pending approvals, and unredacted SSE approval replay/queue paths. Signed capabilities are credentials even though they are not the signing key. A regex that only matches vendor API tokens does not mitigate them. app.py::_auth also supports query credentials: do not emit such links or include them in evidence.

Piston must fix concrete leak paths and test them, not merely list risks. Never forward bot Authorization headers or webhook path credentials to redirects: use a nonredirecting urllib handler and bounded safe failure diagnostics. Do not print raw URL/request/exception strings containing credentials. Notification field values must use the canonical redactor. Only send configured webhook credentials to the intended outbound destination; never return them in served payloads. Validate dashboard URL against userinfo, query, fragment, unexpected scheme/host and injected path components; use a known public dashboard URL for notification links.

The current signed-URL decision mechanism conflicts with the literal no-secret-in-served/logged-URL requirement. Do not silently replace an approved authentication architecture. Obtain Randy's sign-off for retiring signed capability links in favor of a nonsecret dashboard link and existing owner-authenticated POST, if no approved fix preserving the architecture can meet this rule. No deployment/restart/publication authorization is implied by this task. Keep unrelated redaction/test work moving while this decision is escalated. Do not mark the card security-complete with signed capability leakage left unresolved.

## Acceptance evidence

Paste complete synthetic adversarial and unchanged-control tables into the implementation card. Required adversarial cases: IPv4, all compressed/full/loopback IPv6 variants, https://user:pass@host, OBSIDIAN_API_KEY=abc123, sufficiently long synthetic sk-live and mc-g shapes, GitHub/Slack/AWS shapes, Discord/Slack/Telegram webhooks, postgres://u:p@db:5432/x, an SSH private-key block/header, a structurally valid synthetic JWT, dotenv paths, credential-name-only prose, multiline/quoted assignments and escaped strings. Assert exact output and sensitive sentinel absence, not just input != output. Add controls for prose, agent names, task t_e8ce5f76, public URL, timestamps, harmless assignments, numeric metrics, false and null. Include nested arrays/maps and idempotence.

Run existing suite unchanged: `/opt/hermes/.venv/bin/python -m unittest discover -s tests` from /opt/data/hermes-mission-control. This command uses the existing interpreter only; never inspect/edit /opt/hermes. Report exact executed command, exit code, counts and failures; no fabricated pass.

Live read-only spot check: https://mission.onendo.cloud/v1/state with an authorized guest token sent in Authorization header, never URL or printed output. Print only HTTP status, verified guest role/scope, and IP/token/webhook/key-name counts, all required zero. Use independent detection (stdlib ipaddress for IP candidates plus independent credential detectors), not solely scrubber regexes. If no authorized guest credential is available, block the live criterion; do not guess or mint a production token. Do not dump live memory notes or real adversarial secrets into reports. A live check is not deployment permission.

Meridian must review identifier preservation and presentation-versus-source separation before this design is finalized. Piston must request independent review before claiming implementation acceptance. All deployment or approved-architecture changes need explicit user approval.
