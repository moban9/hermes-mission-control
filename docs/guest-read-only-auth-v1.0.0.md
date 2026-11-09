# Mission Control guest read-only hardening — v1.0.0

Status: build contract under CEO-approved t_4868c09e; implementation and independent review pending.
Author: Keystone. Implementer: Piston. Reviewer: Keystone; CEO public verification final.
Baseline checkpoint (before source changes): `4320d5eac1393064a1894e3925aa867c13b32c4a`.
Inspected source baseline: `ae1aaedecf63d059b87b3c7c067f83c5672c92ad`.
Scope: /opt/data/hermes-mission-control only. No deployments/publication, dependencies, guest_tokens migrations, or ingest/HMAC weakening.

## 1. Principal and invariants

- `_auth(...) -> str`: exact configured nonempty VIEWER_TOKEN yields `owner`; valid guest yields `guest:<label>` from the validated database row; invalid, missing, revoked or expired credentials yield existing 401.
- Preserve existing query-token / bearer parsing precedence for reads. An explicit nonempty query token takes precedence over header; do not introduce header fallback after an invalid explicit token. Check owner first.
- Guest labels are identity metadata, never authority: even label `owner` produces `guest:owner`, never `owner`. Duplicate labels remain permitted. Null/empty existing labels use `guest` as display fallback. Never return raw tokens or token hashes in HTTP responses.
- With VIEWER_TOKEN unset preserve existing anonymous developer reads, returning `anonymous`; `_require_owner` MUST reject anonymous with 403. An unconfigured secret cannot authorize writes.
- `_require_owner(principal: str = Depends(_auth)) -> str` accepts only exact `owner`. Otherwise raise HTTPException(403, detail="read-only token"). Attach it as the dependency on BOTH writes listed below. Authentication/authorization must precede handler execution, database access, logging and broadcasting, including dry_run.
- Read endpoint dependency annotations can become str; unused return values do not change response schemas.

## 2. Token storage, validation and data contract

Existing guest_tokens(token_hash PK, label, created_at, expires_at, revoked) remains unchanged. SHA-256 lookup only; no plaintext persistence. Add `tokens.principal(tok) -> str | None` (or equivalently named identity helper with this exact semantic), validating prefix/hash lookup/revoked/time and reading label in ONE lookup. Keep `tokens.check(tok) -> bool` as a backward-compatible wrapper around the same validation, not an independent rule. `_auth` calls the identity helper, not bool followed by an unchecked label lookup. Strict validity remains `now < expires_at`; equal and one second past expiry reject. SQLite errors fail closed.

No source-domain, lakehouse, event payload, database retention or API success-response schema changes. Meridian-facing ingest contract remains byte-for-byte unchanged; no new ingestion model is introduced.

## 3. Full viewer-dependency audit

AST inspection of every top-level registered route in server/app.py found these seven `_auth`-gated routes; do not rely on function-name lookup, as two different registered functions are named v1_approval_decide.

| Method | Path | Baseline behavior | Required behavior |
|---|---|---|---|
| GET | /v1/state | derived state + in-memory cache | owner/guest allowed |
| GET | /v1/snapshots | SELECT replay snapshots | owner/guest allowed |
| GET | /v1/stream | SSE subscriptions + derived reads | owner/guest allowed |
| GET | /v1/agents/stuck | read-only SQLite diagnostics | owner/guest allowed |
| POST | /v1/agents/stuck/resolve | updates sessions, even though dry_run skips UPDATE | owner only; guest 403 for dry/non-dry |
| GET | /v1/approvals | pending approvals SELECT | owner/guest allowed |
| POST | /v1/approvals/{identifier} | UNSIGNED alternate approval mutation, logs + SSE | owner only; guest 403 before lookup |

Important correction to originating report: there are TWO viewer-gated mutation paths, not one. The JSON approval route at app.py:606 is distinct from the HMAC form route at app.py:691. Required-change #3 authorizes hardening the additional mutation too. Preserve existing owner UI JSON behavior.

Not viewer-gated: GET /healthz (public); POST /v1/events (explicit ingest gate); GET /v1/approvals/{request_id}/wait (explicit ingest gate); GET /v1/approvals/{identifier}/decide (signed confirmation read); POST /v1/approvals/{identifier}/decide (HMAC-validated form). The signed POST must still reject unsigned guest AND owner token calls. A signed link is an independent capability: do not redesign or broaden HMAC here. Static dashboard mount and cache middleware are not application write routes.

Operational read-only means no caller-driven business mutation; in-memory caches/subscriptions and token-store initialization are not business writes. GETs must not approve, close sessions, mutate tasks or create events.

## 4. Wire acceptance matrix

These are EXPECTATIONS, not executed results. Piston must paste observed HTTP evidence for both tokens before review.

| Request (token only, no ingest or valid signature) | Guest | Existing owner |
|---|---|---|
| GET /v1/state | 200 | 200 |
| POST /v1/events JSON [] | 401 | 401 |
| POST /v1/approvals/x/decide form decision=approved&sig=invalid | 403 | 403 |
| POST /v1/agents/stuck/resolve JSON {dry_run:true} | 403 read-only token | 200 |
| POST /v1/agents/stuck/resolve JSON {dry_run:false} | 403 read-only token | 200 |
| POST /v1/approvals/{seeded-id} JSON {decision:approved} | 403 read-only token | 200, one actual update |

Use isolated real SQLite fixtures and real HTTP for non-dry owner writes; never close real operator sessions merely for test evidence. Snapshot fixture sessions/approvals before/after to prove guest rejection causes no changes. Owner successfully closes an eligible stale fixture session and updates a seeded pending fixture approval. Owner dry_run leaves rows unchanged. Use a valid form decision with invalid signature to exercise 403 (an empty form produces 400, not evidence of HMAC rejection).

Existing ingest and signed paths need positive controls: configured ingest credential still accepts events; valid signed decision still updates a fixture approval. Do not infer continued protection just from guest failure.

## 5. Automated regression contract

- No new dependencies. Follow existing isolated unittest/uvicorn HTTP style; explicitly isolate MC_TOKEN_DB, MC_DB, Kanban, profiles, state DB, environment-file and log outputs under the repo test-artifact directory. Never print credentials or issue real user tokens.
- Dynamically enumerate FastAPI APIRoutes and recursively inspect dependency graphs for `_auth`, including `_require_owner` nesting. Test every discovered route with both principals; report exact method/path set and assert it matches coverage. Include bounded SSE connection (read first frame then close), not an unbounded streaming test.
- No guest-accessible POST/PUT/PATCH/DELETE on this dependency family; allowlist is EMPTY. A 404/400/422 from invalid fixtures is not authorization proof: all mutating guest requests must return 403 and the explicit detail. Supply valid payloads/ids for owner controls.
- Exercise query and bearer guest credentials, owner query/bearer compatibility, invalid query with valid owner header, guest label `owner`, unknown/missing credentials and revoked credentials. Confirm read responses preserve shape.
- Expiry tests use controlled clock against real hashed SQLite rows at just-before, exactly-at and expires_at+1. Past expiry HTTP /v1/state returns 401. Verify stored value is hash, not plaintext; preserve guest_tokens schema.
- Unset viewer config: anonymous reads succeed, protected writes fail closed. Configured ingest remains separately gated.
- The dynamic mutation guard must fail if either newly protected route is changed back to Depends(_auth); demonstrate regression detection without leaving the mutation applied.
- Run focused auth suite and existing tests, record exact commands, exit codes, counts, commits and redacted HTTP response details. Do not fabricate public evidence from localhost results.

## 6. Decision Board coordination and collision handling

`t_687aff8a` explicitly requires a NEW owner credential distinct from current viewer/ingest credentials. Here `owner` is the task-mandated LEGACY name for current MC_VIEWER_TOKEN. It does NOT authorize Decision Board answering. Decision Board must extend the SAME resolver with a distinct principal (e.g. `operator`) for its separate credential, subject to its Seal gate; answer checks that distinct identity, never legacy _require_owner alone. Do not introduce that new token or principal in this patch. This preserves the mandated literal return values while avoiding viewer escalation on the upcoming board.

hotspot: server/app.py — shared with Decision Board. Security patch owns the immediate resolver and two write dependencies; Decision Board integrates after it, not concurrently. Preserve unrelated dirty logs/decisions.log and untracked web prototypes. Do not broad-stage existing working-tree changes.

## 7. Delivery and review

Piston: record/check baseline, implement and commit only scoped code/tests; paste observed matrix for BOTH credentials and full route audit into the implementation card BEFORE requesting same-card review with reviewer keystone. Keystone independently reruns checks, no self-approval by implementer. If a live restart/publication is necessary, ask CEO for explicit permission; do not deploy. CEO final public guest matrix/token handoff remains separate from local code acceptance.

Journal: Keystone performed source/AST audit and discovered the additional unsigned approval mutation. Evidence: seven dependency routes listed above and baseline checkpoint. Next step: Piston implementation, independent Keystone review, then CEO-authorized public verification. No code implementation or runtime changes performed in the design phase.
