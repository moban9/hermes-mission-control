# Meridian bounded review — approvals v1.3.0 and redaction §3

**Reviewer:** Meridian, Data Architect  
**Scope:** design-only re-check of approvals v1.3 §§1–5/7–8 and the newly appended redaction v1.1 §3.  
**Verdict:** **NEEDS_CHANGES for data-team readiness; no build authorization.** The corrected data/API contract closes the three v1.2 data blockers at design level and the isolated checker passes. Section 6 remains a separate **OPEN operator decision**; it is not treated as a failure of the bounded checks or as approval of the whole contract.

## Evidence, exact artifacts, and limits

Read the complete original review `t_be6379a8/approvals-v1.2.0-meridian-review.md` (three blockers: ambiguous unbounded/current read shape, SQL terminal-field bypass, and missing Bronze lineage/checkpoint/growth plan). Re-ran from `/opt/data/hermes-mission-control`: `python3 docs/check-approvals-v1.3.0.py` returned exit 0 and **151 expected SQL rejections**. It reports artifact/schema/ref parity; terminal-state, snapshot rollback, notification, representative redaction-hook, duplicate-key/size and 101-pending fixtures. Capacity is explicitly only a logical planning envelope: 1,720,000 bytes/event; 1.72 GB/day at 1,000 events; 17.2 GB/day at 10,000 events; 516 GB/30 days before indexes/WAL/backups.

Local SHA-256 (matches the issuance handoff):

| Artifact | SHA-256 |
|---|---|
| `approvals-ux-v1.3.0-amendment.md` | `85da309ce7c3644127cca4b4372f4ccbd4152ede743fb39f0e8c126fe5cbe06a` |
| `approvals-ux-v1.3.0.openapi.json` | `17667dc1f028da9acf9657d696fc9093bbe7606114161d9287ec931dbc370087` |
| `approvals-attention-v1.3.0.sql` | `aa530b41b4c5f1405d41024eba4986e5c07d0403e9ce41fbb3dc08f2c40d591d` |
| `approvals-presentation-v1.3.0.schema.json` | `abdedc5a185f624f504948eab42391d6d68bdc50f2c62474e03936b9f42e1fe8` |
| `check-approvals-v1.3.0.py` | `a5920c7347b5fc63405e2d0a524622810efa5f501e7ebe1c1b12b0b0e5996c1a` |
| `approvals-v1.3.0-validation.txt` | `756545b11048d7aab2ff62b56e84dfe5126c1e0e34be0bb8141224737984cb61` |
| `redaction-contract-v1.1.0.md` | `d9cad0810bb88efa7624126b7e9bd8f9a8c01351faf0203edbc143acc6a32c99` |

The parent ZIP file hash is `d3320fac8d99b37c17512003e6b5240a113d717946fa8377401fddebe57c7297`; manifest hash is `207ddc46ebe21a27e04bda39103d8a24aac629b64a0fc12eb92b7e5658f0a4b0`. **ZIP member listing/content verification could not be completed:** `unzip`/`zipinfo`/`bsdtar`/`7z` are unavailable and unattended arbitrary Python execution is blocked. The issuance manifest lists seven members and records GET 200, PUT 204, byte equality for all seven, and the per-file hashes above; that is issuer evidence, not my independent inspection of ZIP members.

## Section verdicts

| Scope | Verdict | Data/API assessment |
|---|---|---|
| §1 redaction / write boundary | **PASS (contract); runtime gate remains** | Clear upstream raw-source immutability versus scrubbed MC-owned derived persistence; scrub before first durable write plus fresh canonical egress validation; strict parse, typed identity preservation and fail-closed unsafe keys/identities. Matches CEO shared redaction rule; no competing policy. Hook is explicitly mandatory but not installed/runtime-tested. |
| §2 domain, immutability, state correspondence | **PASS (fixture scope)** | Latest-per-request ledger, frozen terminal fields with only enumerated telemetry exceptions, direct UPDATE/DELETE rejection, semantic retry rejection, typed state↔ledger snapshot parity and transaction rollback are defined and exercised in SQLite fixtures. Not proof against production adapter/connection behavior. |
| §3 reads, pagination, replay | **PASS (contract); handler gate remains** | Current is latest event/request at pinned seq; list is default 100/max 200 seq-seek pages pinned to S/T/filter/limit; exact any-status GET returns one object; bounded 100-pending + 100-terminal snapshot is distinct from page. State↔SSE and exact↔approval parity are correctly limited to equal seq/clock. OpenAPI/checker make 405/Allow, JSON 415 and pre-stream errors explicit. Cursor execution, auth and concurrency have not been run against a handler. |
| §4 notification lifecycle | **PASS (design/isolated SQL fixtures)** | Mutually exclusive stage fields, immutable stages, at-most-once semantics, request-local dead-process reconciliation, reservation/terminal race and delayed result are made explicit. No actual outbound, crash, concurrency or notification runtime canary. |
| §5 Bronze, capacity and archive | **PASS (contract completeness); NEEDS_CHANGES for readiness evidence** | Exact already-scrubbed source-row grain, stable instance/epoch, run and `_source`/`_ingested_at` metadata, durable post-write hash checkpoint, replay/dedup/fork halt independent of UI cap are specified. Snapshot growth is bounded and quantified; performance/capacity gates and non-destructive verified archive/restore are explicit. The 17.2 GB/day 10× estimate is logical, not measured; no consumer, benchmark, free-space proof or restore was executed. No source deletion or delta switch is authorized. |
| §6 signed capability | **OPEN — operator decision** | Intentionally pending; neither branch is selected/designed. Keep as an explicit independent build blocker, not as a reason to skip these findings and not as a full-contract pass. |
| §7 changelog / blocker disposition | **PASS** | Prior three blockers are addressed at contract level and limits remain candid. The §6 hold is not downgraded. |
| §8 verification/release gate | **PASS (scope statement)** | Correctly distinguishes fixture evidence from runtime acceptance and preserves A1–A12 and independent gates. This review does not certify any of them. |
| Shared redaction v1.1 §3 addendum only | **PASS (bounded text check)** | Newly appended clause states CEO-approved exception: upstream raw source unchanged; MC-owned derived approval presentation/history/state/audit scrubbed before first durable write and revalidated at egress; original identity/type/metric protections persist. Read back vault note contains this §3. §§1–2 and control fixture were not reopened or independently retested. |

## Remaining blockers / disposition

1. **Data-team readiness is not certified:** actual pagination handler, Bronze consumer/checkpoint restart/fork handling, API/SSE/notification runtime canaries, target-volume throughput and capacity, and isolated archive/restore evidence remain unexecuted. Keep deployment/build gated on these acceptance items; do not convert the planning estimate into a 10× certification.
2. **§6 remains OPEN pending Randy/operator decision and its bounded reviewed amendment.** No selected adapter branch is implied.
3. **ZIP members not independently enumerated** in this environment; parent ZIP SHA and issuer manifest were verified as text/hash evidence only.

No production-scale certification, runtime edit, dependency addition, migration, deployment, publication, or build authorization is granted.

## Vault mirror verification

Read back the six contract companions under `Architecture/Mission Control/contracts/` and the shared note at `Architecture/Mission Control/Redaction Boundary v1.1.0.md`. The six companion mirror content/byte sizes are consistent with local files and the issuer manifest; the amendment readback is byte-identical by its 28,210-byte size and matching manifest SHA. The redaction readback reports 15,174 bytes and matching SHA. Readbacks also confirmed the v1.3 text and §3 addendum, respectively. The manifest records GET 200/byte_equal=true for all seven; no vault writes were made in this review.
