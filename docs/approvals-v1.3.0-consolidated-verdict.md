# Approvals v1.3.0 — consolidated bounded verdict and build hold

Owner: Kestrel. Gate: `t_18d27b47`; build: `t_2434c6c7`. **Overall verdict: NEEDS_CHANGES / HOLD; no final approval and no build, implementation, deployment or publication authorization.**

## Evidence boundary and exact reviewer findings

This consolidation uses the verified evidence packet from `t_32fe989a` (verified 2026-11-09 20:08 WIB). It records bounded findings only; it is not final gate approval.

- Seal `t_1ebf41bf`, `docs/approvals-v1.3.0-seal-bounded-review.md`: **PASS — changed design §§1–5/7–8 only**. §6 is OPEN; no full contract/build/runtime approval. Scope is design and isolated fixtures, not installed enforcement.
- Meridian `t_5b02a054`, `docs/approvals-v1.3.0-meridian-bounded-review.md`: **NEEDS_CHANGES FOR DATA-TEAM READINESS**. §§1–5/7–8 pass at the expressly stated contract/fixture level, and shared redaction v1.1 §3 passes its bounded text check, but actual handler, Bronze, runtime, capacity and restore evidence is missing. Preserve the negative overall readiness verdict; it is not a second overall PASS. §6 remains independently OPEN. §§1–2 and the redaction control fixture were not reopened.
- Thus the common changed-section design finding is bounded PASS only; it cannot override Meridian's readiness verdict or release the build. Route these concrete findings to the CEO for disposition and coordination with Keystone, the sole contract owner; no duplicate architecture contract. The reviewers describe the data design as complete at contract level, so do not misrepresent missing runtime evidence as an identified wording defect. CEO must disposition sequencing of the readiness evidence without weakening the build hold or inventing a pre-build runtime result.

## Verified candidate hashes (SHA-256)

Locally recalculated against issuance manifest and both review artifacts; all seven match:

| Artifact | SHA-256 |
|---|---|
| approvals-ux-v1.3.0-amendment.md | `85da309ce7c3644127cca4b4372f4ccbd4152ede743fb39f0e8c126fe5cbe06a` |
| approvals-ux-v1.3.0.openapi.json | `17667dc1f028da9acf9657d696fc9093bbe7606114161d9287ec931dbc370087` |
| approvals-attention-v1.3.0.sql | `aa530b41b4c5f1405d41024eba4986e5c07d0403e9ce41fbb3dc08f2c40d591d` |
| approvals-presentation-v1.3.0.schema.json | `abdedc5a185f624f504948eab42391d6d68bdc50f2c62474e03936b9f42e1fe8` |
| check-approvals-v1.3.0.py | `a5920c7347b5fc63405e2d0a524622810efa5f501e7ebe1c1b12b0b0e5996c1a` |
| approvals-v1.3.0-validation.txt | `756545b11048d7aab2ff62b56e84dfe5126c1e0e34be0bb8141224737984cb61` |
| redaction-contract-v1.1.0.md | `d9cad0810bb88efa7624126b7e9bd8f9a8c01351faf0203edbc143acc6a32c99` |

Kestrel independently reran `python3 docs/check-approvals-v1.3.0.py`: exit 0, 151 expected SQL rejections. Issuer's manifest records seven vault PUT 204 / GET 200 byte-equal mirrors. Seal and Meridian report their bounded readbacks; Meridian could not independently inspect ZIP members. This consolidation did not independently inspect ZIP members or independently re-verify the seven candidate mirrors. Checker is isolated design/fixture evidence, not runtime validation; no JSON Schema meta-validator was installed, and the inspected scrubber fixtures cover representative classes only.

## Open gates and CEO escalation

1. **§6 candidate status: PENDING OPERATOR DECISION; neither branch is designed.** The frozen candidate at lines 115–119 literally says `PENDING OPERATOR DECISION — section intentionally absent` and `Neither retain/harden nor retire is selected or designed`. Separately, the later CEO ruling `t_861cf00f` records Randy's Option A choice at 17:52:02 WIB. Therefore the historical candidate status is pending, but the operator choice is resolved; do not claim the decision itself remains pending or ask Randy to decide again. The ruling does not amend §6, design an adapter, or certify implementation. No signed branch is designed here.
2. Keystone `t_4cd8463b` issued a design candidate; its checker exit 0 and 151 expected isolated SQL rejections are not release approval, runtime, or deployment certification. Keystone is sole contract owner and must issue one bounded amendment for the selected option and obtain independent review; then explicit final approval for the exact resulting hash set is required. Do not infer authorization from completed cards or create a competing contract.
3. Separately retained bounded-hook review/disposition remains required; archived `t_508a98ba` is not evidence of acceptance.
4. Meridian's readiness NEEDS_CHANGES: provide real pagination handler; Bronze consumer/checkpoint restart, deduplication and fork handling; API/SSE/notification runtime canaries; target throughput, capacity and free-space proof; isolated archive/restore. Route these concrete findings to CEO for sole-owner coordination and explicit evidence sequencing. Preserve runtime A1–A12, complete-policy DB/WAL/log/API/SSE/outbound canaries including A7, destination and actual browser notification evidence, migration/cutover, and 10× performance/restore gates. No planning estimate is measured production readiness.
5. Meridian review mirror at the exact expected vault path `Architecture/Mission Control/contracts/approvals-v1.3.0-meridian-bounded-review.md` returned File not found. Its local review exists per handoff; do not claim that review is mirrored. This does not imply no alternate path exists, and does not affect the seven candidate mirrors verified byte-equal.

The adopted policy remains dual scrub before first durable write and at each egress for MC-owned credential-bearing derived approval data; raw upstream sources remain unchanged. One creation-time push, no retries/scheduler/sweep. The real dependency `t_18d27b47` → `t_2434c6c7` holds Piston. Gate remains blocked, not complete, pending explicit prerequisites and CEO disposition. No final gate approval, implementation/deploy authorization, or release of build `t_2434c6c7` or Piston.

qa: rejected — final approval blocked by missing independently reviewed Option A amendment, Meridian readiness needs changes, separately retained bounded-hook disposition, and exact-set final approval.
Produced by: Ledger · Based on bounded source reviews by Seal and Meridian; this consolidation has not received independent review.
