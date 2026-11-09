# Seal bounded re-check — Approvals v1.3.0

Reviewer: Seal (Data Governance & Quality)  
Verdict: **PASS — changed design sections §§1–5/7–8 only**. This is not approval of the full contract, implementation, build, migration, or deployment. Signed-capability §6 remains an OPEN operator blocker by explicit ruling; neither option is selected or designed.

## Scope and evidence

Read the authoritative `docs/approvals-v1.2.0-seal-review.md`, the v1.3 amendment and companion artifacts, the issuance validation transcript, and redaction contract §3. Re-ran `python3 docs/check-approvals-v1.3.0.py`: exit 0; it reports 151 expected negative SQL rejections. Inspected all seven exact artifact hashes below against the issuance handoff/manifest values. The manifest records successful vault PUT/GET and byte-equality for all seven; vault readback confirmed all seven paths, content sizes and versions, and inspected full contents for the amendment, SQL, validation transcript and redaction boundary §3. Hashes and sizes match the manifest. `redaction-contract-v1.1.0.md` hash is consistent with §3 appended-only scope. Original §§1–2 are preserved by the issued artifact/manifest, not reopened in this review.

| Artifact | SHA-256 |
|---|---|
| approvals-ux-v1.3.0-amendment.md | `85da309ce7c3644127cca4b4372f4ccbd4152ede743fb39f0e8c126fe5cbe06a` |
| approvals-ux-v1.3.0.openapi.json | `17667dc1f028da9acf9657d696fc9093bbe7606114161d9287ec931dbc370087` |
| approvals-attention-v1.3.0.sql | `aa530b41b4c5f1405d41024eba4986e5c07d0403e9ce41fbb3dc08f2c40d591d` |
| approvals-presentation-v1.3.0.schema.json | `abdedc5a185f624f504948eab42391d6d68bdc50f2c62474e03936b9f42e1fe8` |
| check-approvals-v1.3.0.py | `a5920c7347b5fc63405e2d0a524622810efa5f501e7ebe1c1b12b0b0e5996c1a` |
| approvals-v1.3.0-validation.txt | `756545b11048d7aab2ff62b56e84dfe5126c1e0e34be0bb8141224737984cb61` |
| redaction-contract-v1.1.0.md (§3 appended) | `d9cad0810bb88efa7624126b7e9bd8f9a8c01351faf0203edbc143acc6a32c99` |

## Findings — changed design only

- **Redaction / ownership — PASS (design).** CEO-adopted distinction is explicit: upstream raw source files/snapshots/reducer/cache/queues remain untouched; MC-owned approval presentation/history/state/audit are scrubbed before their first durable write, including WAL/staging/audit/log surfaces, then revalidated at each egress. Mandatory per-writer-connection `mc_approval_safe_json` registration fails closed if missing; no permissive fallback or unsafe-key normalization. Malformed input, identities, diagnostics and all four persistence/API/SSE/notification surfaces have stated reject/close/suppress handling. §3 is the sole shared-policy addition; existing §1–2 identity/type behavior remains authority. A7 remains an implementation gate, not certified by fixtures.
- **Terminal immutability — PASS (isolated fixture/design).** DDL rejects direct UPDATE/DELETE and same-status terminal payload edits; checker exercises all four terminal statuses, multiple decision/presentation fields and semantically identical terminal retries. Only first-seen once and permitted monotone notification telemetry are allowed, and cannot rewrite terminal action. No application-level runtime proof.
- **Snapshot/state and transaction — PASS (isolated fixture/design).** Stored typed state correspondence uses symmetric `json_tree` comparison and includes array positions via full keys. Tests reject missing/stale/extra snapshots and demonstrate rollback across history, generated claim and audit. This is isolated SQLite fixture evidence, not an installed DB/migration proof.
- **Notification — PASS (contract/fixture).** Attempt, outcome, suppression and failure fields are distinct; quiet-hours/unconfigured/terminal suppression, pre-I/O attempt reservation, no retry/scheduler/sweep, crash loss/unknown, request-local no-send reconciliation after proving creator death, and terminal-dispatch races are specified. Late result telemetry cannot alter terminal action. Guarantees are at-most-once attempt, not exactly-once delivery; never hold DB lock during I/O. The fixture covers listed lifecycle classes, but actual concurrent/runtime delivery is untested.
- **Companion consistency / bounds — PASS (artifact/fixture).** Checker passed parity, status/alias confinement, local refs, page/state separation, explicit 405/415 and signed hold. Snapshot 100+100 is separate from default-100/max-200 pinned list pages; >100 pending fixture retained all 101 in ledger and set truncation. Bronze lineage/checkpoint and non-destructive archive requirements are explicit, with capacity estimate clearly labeled planning-only.
- **Signed capability — OPEN, separately recorded.** §6 is intentionally pending; neither retain/harden nor retire is selected or designed. This does not block the bounded verdict on changed sections, but blocks full-contract/build approval pending operator amendment and graph gates.

## Limits and remaining gates

No JSON Schema meta-validator was installed; no dependency was added. The checker uses a scoped schema assertion evaluator and representative inspected scrubber classes, not complete shared-policy validation. No actual API/SSE/log/outbound runtime, full A7 canaries, pagination handler, Bronze consumer, migration/cutover, browser/destination confirmation, A1–A12, throughput/capacity/restore benchmark, or production DB was tested. The stated capacity envelope (1.72 GB/day at 1,000 events/day; 17.2 GB/day at 10,000; 516 GB/30 days) is a logical planning bound, not measured readiness. These remain downstream gates; this PASS is not build authorization.

No runtime or access changes, deployment, publication, deletion, or new dependency was made.
