# Seal independent governance/write-path review — approvals v1.2.0

Reviewer: Seal (Data Governance & Quality)  
Scope: independent design review only; no implementation or build/release approval.  
Verdict: **NEEDS CHANGES before consolidated contract approval**. CEO-fixed rulings and the amendment remain the authority; findings identify enforceability gaps, not alternate policy.

## Evidence and execution

Reviewed amendment, OpenAPI, SQL DDL, presentation schema, checker, and validation transcript. Independently ran `python3 docs/check-approvals-v1.2.0.py` from the Mission Control repository: exit 0. It reports status parity, refs/schema equality, isolated SQLite DDL checks, and batch rollback. Its stated limit is no API/SSE/redaction/notification runtime tests, no JSON Schema meta-validator; historical truncated Python excerpt remains unverifiable. No runtime, production database, permission, or migration changes made.

SHA-256 (independently computed for reviewed inputs):

- amendment: `06084850e7230301b8a1834790adf9db4986f67eb814ea7f3de60c8eca944d41`
- OpenAPI: `117459e76d837918a288434e1199995870d1583eeb74378b0507f3b333f03762`
- SQL: `fd28db4c65ee6ad3b30c2fd681702656eb9a3ad0867d526a6762240f5d5ca688`
- presentation schema: `77265cd79deb2e3fcb58b0cdfa78c8cef2c1a1c9badff8786af96893da0d5a32`
- checker: `c01301bd0095272ede9c8b9af34f3ba2affeb71491581ef07202c73cc739a990`
- validation transcript: `20c8d3ea6257390d50439e453bec0fb22091bbe83d4f6a1e3d6a350958e1714c`

## Criterion findings

| Criterion | Verdict | Review |
|---|---|---|
| Canonical status/legacy alias ownership | PASS (design) | Amendment is sole semantic authority; ordered five-state vocabulary matches artifact enums and rejected→denied alias is confined to input mapping. |
| Canonical ID / numeric alias outcomes | PASS (design) | Request ID is canonical; zero/multiple alias matches yield distinct 409 codes and match counts; never first-row selection. Runtime/auth-order proof remains downstream. |
| Redaction before durable ingress and all four surfaces | **FAIL — blocking** | Prose mandates scrub-before-first-insert and raw-byte checks across persistence/API/SSE/notify, with keys/errors/logs covered. Executable SQL only comments that strings must be scrubbed; no enforcement hooks or canary tests exist. `IngestEvent` validates shape but string fields accept unredacted values; annotations/schema are not proof. A caller bypassing the adapter can INSERT raw JSON directly, and broad JSON columns accept it. No verified raw-data ingress, dictionary-key, diagnostic-log, error or outbound path exists in design tests. Require a testable adapter boundary and A7 negative fixtures inspecting DB/log bytes, raw HTTP/SSE and outbound captures, including nested values/keys and malformed-input errors, before implementation acceptance. |
| Actor binding / cancellation | PASS (normative; implementation unproven) | Owner withdrawal vs authenticated owned worker death and no timeout-as-death are clearly distinguished. OpenAPI explicitly forbids arbitrary ingest-token cancellation. A4 must prove identities and 403 behavior; no runtime evidence. |
| Terminal immutability / decision fields | **FAIL — blocking SQL gap** | DDL trigger forbids changing terminal *status* to another status and freezes creation/deadline, but does not freeze `decided_at`, `decided_by`, terminal/expiry reason, or immutable terminal record fields while retaining the same terminal status. Its acceptance test checks status overwrite only. Also UPDATE/DELETE triggers do not constrain `state_json` correspondence. Require terminal-record comparison/invariant enforcement in validated write adapter and tests for same-status tampering, plus state snapshot equality. |
| Batch atomicity | PASS (isolated design fixture only) | Checker demonstrates a simple invalid SQL insert rollback with zero new ledger rows. It does not establish all affected tables, dispatch/SSE side-effects, or application validation-before-transaction; A3 remains required. |
| Append-only history/projection | PASS with material limitation | Triggers reject UPDATE/DELETE; view selects highest approval seq. Full state snapshots and one-transaction projection discipline are normative only: schema accepts `{}` state_json and does not prove contents equal ledger-derived state. No explicit retention/archival migration implementation; amendment correctly exempts immutable history from prior 14-day sweep and labels DDL new-table design, not production migration. Require tests for snapshot/projection correspondence and additive/backfill/rollback plan before cutover; never treat this as permission to modify installed DBs. |
| SSE ordering, replay, GET parity | PASS (design; untested) | Global committed sequence, complete stored snapshots, Last-Event-ID replay and explicit GET parity are specified. SQL cannot enforce event publication order/watermark race; A6 and raw stream evidence mandatory. |
| Notification at-most-once and audit distinction | PASS (contract intent; unresolved audit implementation) | Unique immutable claim before I/O, no retry/catch-up, suppression distinct from delivery outcome, crash uncertainty fail-closed are explicit. SQL has no immutable per-outcome ledger trigger/model beyond comments and approval JSON history; checker only tests duplicate claim and destructive claim writes. Require A8/A9 proving crash-after-claim, after-I/O-before-result, restart, concurrency, quiet boundaries, no second attempt, and immutable separate suppression/outcome audit events. Do not call this exactly-once delivery. |
| Error/log/identifier redaction | **FAIL — evidence gap** | Normative contract forbids raw echoes and demands auth before lookup, but there are no executable error/log fixtures. Alias reason is explicit and redacted by prose; runtime safety is not established. Included in the blocking redaction gap. |
| Migration/cutover scope | PASS (scope boundary) | Explicitly additive new v12 local tables, import scrub/repair rules, no production migration or Hermes DB writes; complete cutover/rollback remains downstream. Historical excerpt is correctly excluded as evidence. |

## Required disposition

Kestrel should retain three blocking findings: (1) demonstrate and enforce raw-ingress redaction before any persistence, with all four exposure surfaces including keys/errors/logs; (2) freeze terminal decision/reason fields and prove full state snapshot equivalence, not merely status; (3) add auditable immutable notification outcome/suppression transitions and prove no-retry crash windows. Keep A1–A12, schema meta-validation, runtime/browser tests, destination/operator confirmation, and migration review as downstream gates. This is a design review only; it does not authorize build, deploy, access changes, or data migration.
