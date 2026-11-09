# CEO disposition — approvals v1.3 readiness findings and contract gate

**Task:** `t_561720ac` · **Gate:** `t_18d27b47` · **Build:** `t_2434c6c7` · **Contract owner:** Keystone
**Issued:** 2026-11-09, 20:15 WIB (run 376 start; container clock is UTC, WIB = UTC+7) by Mo (CEO)
**Status: DISPOSITION ONLY. The build hold stands. This document authorizes no build, no implementation, no deployment, no publication, and grants no PASS.**

---

## 1. Inputs dispositioned (exact artifacts)

| Artifact | What it says | Status here |
|---|---|---|
| `docs/approvals-v1.3.0-consolidated-verdict.md` (6,345 bytes; producer: Ledger, **not independently reviewed**) | Overall NEEDS_CHANGES / HOLD; five open gate items | Read in full; used as the routing record, not as authority |
| `v13-bounded-evidence-packet.md` (`t_32fe989a` attachment, 7,413 bytes; verified 20:08 WIB) | Seven candidate SHA-256 match local, ZIP members and vault mirrors byte-equal; ZIP `d3320fac…`, manifest `207ddc46…` | Read in full; hash set relied on as *the* exact candidate set |
| Seal `t_1ebf41bf` → `docs/approvals-v1.3.0-seal-bounded-review.md` | **PASS — changed design §§1–5/7–8 only**; §6 OPEN; no full contract/build/runtime approval | Accepted at that scope only |
| Meridian `t_5b02a054` → `docs/approvals-v1.3.0-meridian-bounded-review.md` | §§1–5/7–8 + shared redaction §3 pass at contract/fixture scope; **overall data-team readiness NEEDS_CHANGES** | **Upheld, see §2** |
| `docs/approvals-ux-v1.3.0-amendment.md` (SHA-256 `85da309ce7c3644127cca4b4372f4ccbd4152ede743fb39f0e8c126fe5cbe06a`), §5 lines 101–113, §6 lines 115–119, §8 lines 136–140 | §6 literally `PENDING OPERATOR DECISION — section intentionally absent`; §5 sets capacity/archive gates; §8 preserves A1–A12 and adds the runtime test list | Read directly, quoted below |
| CEO ruling `t_861cf00f` (17:52:02 WIB) | Randy chose **Option A** for signed decision capabilities | **Resolved** — do not ask again |

The seven verified candidate hashes (`approvals-ux-v1.3.0-amendment.md` `85da309c…`, `.openapi.json` `17667dc1…`, `approvals-attention-v1.3.0.sql` `aa530b41…`, `approvals-presentation-v1.3.0.schema.json` `abdedc5a…`, `check-approvals-v1.3.0.py` `a5920c73…`, `approvals-v1.3.0-validation.txt` `756545b1…`, `redaction-contract-v1.1.0.md` `d9cad081…`) remain valid **only for the artifacts they cover**. They are not a standing approval of a §6 amendment that does not yet exist.

---

## 2. Disposition 1 — Meridian's readiness NEEDS_CHANGES is UPHELD, and sequenced after the build

**Ruling: UPHELD, not downgraded, not converted to PASS, not treated as a §6 issue.** Seal's bounded PASS and Meridian's §1–5/7–8 contract-level passes describe design/fixture scope; they do not and cannot override a readiness verdict about unexecuted runtime evidence. No one may cite the completed review cards as an overall PASS.

**Why the verdict is correct:** the six items Meridian names are unexecuted. None of them has been produced. I am not asserting any of them as complete, partially complete, or implied by planning figures.

**Why they are not a contract-gate blocker:** the contract itself already places them on an implemented artifact, not on the text:

- §8 line 138 already requires, as verification-gate items: "Bronze crash-before-checkpoint/dedupe/fork; 10× capacity/restore fixture" and preserves A1–A12.
- §5 line 111: the benchmark runs "**Before production at 10×**", against the target disks with the worst-size fixture — a condition on deployment, not on contract wording.
- §5 line 113: archive verification is an isolated restore ("Restore into an isolated store, replay C=0 through H, verify snapshot/exact/audit parity") — it requires a running system.

A pagination handler, a Bronze consumer and SSE/notification canaries cannot be exercised before they exist. Requiring them as *pre-build* conditions would deadlock the programme and would invite exactly the fabrication we are avoiding. They are therefore **post-implementation, pre-deployment** conditions.

**What that means concretely:**

1. The readiness gate is attached to the built artifact — card **`Meridian readiness acceptance gate`**, `parents=[t_2434c6c7]`.
2. Deployment, activation, cutover, and **any** claim of data-team or production-scale readiness are blocked until every item has real measured evidence and Meridian signs the verdict.
3. Until then the only supportable statement is: *"contract complete at design level; readiness unproven; `17.2 GB/day at 10,000 events` is a planning envelope, not measured capacity."*
4. One readiness item is measurable **now** and must not wait for the build: target-volume free space / capacity headroom. Read-only measurement, Relay produces, Meridian verifies — card **`Measure target approval-store volume`**.

**Explicitly forbidden:** restating Meridian's six items as "to be confirmed by design", folding them into a later contract revision as if they were wording gaps, or citing §5's 17.2 GB/day figure as a 10× certification.

---

## 3. Disposition 2 — Keystone is sole contract owner; exactly one bounded §6 amendment

**Sole owner: Keystone** (issuer of `t_4cd8463b`). No competing architecture contract, no second design card, no reviewer-authored substitute, no reviewer designing the branch in a review document.

The amendment must encode Randy's Option A ruling exactly, as a testable contract — not prose intent:

1. No signature in any URL: no `sig` in query string and no `sig` in path, for any state-changing decision route (approve/deny/ask).
2. The delivered link carries an **opaque, single-use, short-TTL capability reference only** — no signature, no secret material. Opening it renders the card.
3. The decision is an **HTTP POST carrying the signature in the request body**, re-validated server-side against the capability record.
4. POST-only; GET renders and never mutates.
5. CSRF-style double-submit token bound to the capability id.
6. Single use, TTL ≤ 5 minutes, constant-time signature comparison.
7. Reuse → **409** with the existing decision returned.
8. `Referrer-Policy: no-referrer` on the card page; query strings stripped from application logs.
9. Capability ids stored as hashes, never as reversible tokens.
10. Supersedes the implicit behaviour of `HEAD server/discord.py::_decision_url`; the redaction contract is not required to resolve this — the CEO ruling does.

**Amendment discipline (binding on Keystone, not negotiable by the reviewer):**

- **Additive only.** §§1–5/7–8 text that Seal and Meridian bounded-PASSed must remain byte-identical. If a §6 adapter genuinely requires a change inside those sections (e.g. an additive OpenAPI route or SQL object), that change is isolated, enumerated, and re-reviewed — never a silent rewrite.
- One amendment document plus the minimum additive companion/checker changes. Every produced artifact gets its own SHA-256 and a vault mirror.
- The resulting exact hash set **will differ** from the seven verified hashes. Final approval is for the resulting set, not the old one.
- **Independent review by Seal** (security/policy scope) of that exact amendment and hash set — card `Independent review — §6 Option A amendment`. Meridian re-reviews only if the amendment changes an API or DB surface Meridian previously passed.
- Keystone does not self-review, does not implement, and does not authorize the build. Completion of the amendment is not approval of it.

---

## 4. Disposition 3 — the retained bounded-hook prerequisite is NOT satisfied

**Ruling: the archived `t_508a98ba` disposition does NOT satisfy this build gate.** Kestrel asked for an explicit answer; this is it.

Facts, from the card's own history:

- Keystone round-1 review of `8c2b2c4f9ca2…` was **CHANGES REQUESTED** with three safety-critical defects: an allowlist that admitted `ls $(rm -rf x)`, literal-newline command chains, `ss -K`, `curl -XPOST`, `curl -dhello`, `date --set=now`, `git diff --output=…`; a `timeout_s=1` path that accepted a late `approved` response after 1.6006 s; and `unavailable()` writing a local rather than the global `LAST_ERROR`.
- Piston committed claimed fixes as `8928eeff6fb05fa966a9549449a6e0c974978bcb` and requested review.
- All three Keystone review runs then died on `pre_tool_call plugin callback timed out or is still running` — **no verdict was ever persisted**.
- The card was archived on a CEO close-out that accepted the commits as an **interim safety valve** to ship with the next gateway restart. The close-out also launched the `t_7136560e → t_95518061 → t_d010e9b9` park/resume v2 chain.

**Interim safety-valve acceptance is not independent review.** The gate prerequisite stays OPEN.

**What remains (bounded, no new code unless a defect is found):** one independent Keystone review of `8928eeff6fb05fa966a9549449a6e0c974978bcb` against `APPROVAL-HOOK-v1.0.0.md` in its CEO-narrowed scope, persisted as a file with exact commands, output, exit codes and elapsed times, re-testing exactly:

1. the three bypass classes (command substitution/backticks, real newlines, shell operators, unknown/mutating options, unknown verbs) through the **actual hook with a transport spy**, plus the allowed-command table (`ls`, `date`, `git status`, `git log`, `grep`), asserting each cannot bypass;
2. outer-bound enforcement on blocking transport, including a late `approved` response at the deadline;
3. global `LAST_ERROR` on both unavailable paths and the pending-deadline path.

**Not acceptable as closure:** "the card is archived", "v2 supersedes it", or a reviewer ruling on the tests alone. In particular, **v2 cannot retire the interim commit before this build**: `t_95518061` lists `t_2434c6c7` as a parent, so the superseding implementation is downstream of the very build this gate releases. A defect found here goes back to Piston as a bounded fix and a re-review; it does not trigger a rewrite.

---

## 5. Authoritative sequencing

| Step | Work | Owner | Gate effect |
|---|---|---|---|
| **S0** | One bounded §6 Option A amendment issued (additive, §§1–5/7–8 byte-preserved) | Keystone | none |
| **S0** | Independent review of that exact amendment + hash set | Seal (Meridian conditional on API/DB surface) | none |
| **S0** | Bounded independent review/disposition of hook `8928eef` | Keystone | none |
| **S0** | Read-only target-volume free-space/capacity measurement | Relay → Meridian verifies | none |
| **S0** | Mirror Meridian's review or record that no mirror exists | Meridian | artifact hygiene |
| **S1** | CEO verifies the **exact resulting hash set** and records an exact-set disposition | Mo (CEO) | Only this may complete `t_18d27b47` |
| **S2** | Release of build `t_2434c6c7` | **Randy** (explicit go-ahead) | Not given; gate completion alone does not start Piston |
| **S3** | Readiness evidence gate on the built artifact (six items + A1–A12 + canaries incl. A7 + migration/cutover + 10×) | Piston/Cask produce, Relay disk, Meridian verdict, Seal on A7 | Blocks deployment |
| **S4** | Deployment / activation | — | Blocked until S3 PASS |

No step may be compressed by citing the intent of a later step. S1 is not a formality: it is where the seven old hashes stop being sufficient.

---

## 6. Outstanding gate evidence (named, with owners)

| # | Evidence that must exist (real, measured) | Produce | Verify | When |
|---|---|---|---|---|
| 1 | §6 amendment encoding all ten Option A constraints + exact hashes + vault mirror | Keystone | Seal | S0 |
| 2 | Independent review verdict on that exact amendment/hash set | Seal | CEO | S0 |
| 3 | Persisted hook verdict on `8928eef` (bypass table, outer bound, `LAST_ERROR`) | Keystone | CEO | S0 |
| 4 | Actual seq-seek pagination handler run: default 100 / max 200, pinned S/T/filter/limit, cursor pinning, no lost concurrent updates | Piston | Meridian | S3 |
| 5 | Bronze consumer: checkpoint restart after crash-before-checkpoint, dedupe on replay, fork/epoch divergence halt, hash-mismatch quarantine | Cask | Meridian | S3 |
| 6 | API/SSE/notification runtime canaries incl. A7 across DB/WAL/log/API/SSE/outbound, plus A1–A12 | Piston | Meridian + Seal | S3 |
| 7 | 10× target-disk benchmark with worst-size fixture: p95 write commit ≤250 ms, no dropped/reordered replay, WAL/backup growth | Piston + Relay | Meridian | S3 |
| 8 | Free space for 30 days + measured overhead + two full backups | Relay | Meridian | S0 (read-only) / S3 (measured) |
| 9 | Isolated archive/restore: shard manifests, per-key hash/count readback, restore into isolated store, replay C=0→H, snapshot/exact/audit parity | Cask + Piston | Meridian | S3 |
| 10 | Migration/cutover evidence; explicit final approval of the exact resulting hash set | Piston | Mo (CEO) → Randy for build release | S1 / S3 |

---

## 7. Artifact-hygiene corrections

1. **Meridian's review vault mirror is missing** at the exact path `Architecture/Mission Control/contracts/approvals-v1.3.0-meridian-bounded-review.md`. This does not mean the review does not exist (the local file does), and it does not affect the seven candidate mirrors, which are byte-equal. Meridian must mirror it or record in writing that no mirror exists. The flag is not to be left open.
2. The consolidation did **not** independently inspect ZIP members or re-verify the seven mirrors; `t_32fe989a` did (`ZipFile.testzip()` → `None`, seven members byte-equal). Recorded as reviewed-secondhand, not as this document's own measurement.
3. This document is on disk at `docs/approvals-v1.3.0-ceo-disposition.md` and mirrored to the vault. **The repository commit was not made in this run** — terminal/git execution was gated by the approval queue in the session that issued it, and no shell command ran. Content is verified by vault readback; commit hash is not claimed.

---

## 8. What this document does not do

- It does not authorize build `t_2434c6c7`, Piston, implementation, deployment, cutover or publication.
- It does not design §6, choose adapter internals, or pre-empt Keystone.
- It does not convert any bounded review into an overall PASS, and does not release the gate.
- It does not weaken policy: dual scrub before first durable write and at each egress for MC-owned credential-bearing derived data stands; upstream raw sources remain unchanged; one creation-time push with no retries/scheduler/sweep stands; the retained bounded-hook prerequisite and the exact-final-hash requirement both remain.

---

**Produced by** Mo (CEO) · **Inputs reviewed:** consolidated verdict (Ledger; not independently reviewed), verified evidence packet (Kestrel `t_32fe989a`), Seal `t_1ebf41bf` review, Meridian `t_5b02a054` review, `approvals-ux-v1.3.0-amendment.md` §5/§6/§8, and board cards `t_18d27b47`, `t_5b02a054`, `t_861cf00f`, `t_508a98ba`, `t_95518061`, `t_d010e9b9`.

---

## 9. Card map issued with this disposition

_Appended after issue; identical block in the local and vault copies._

| Card | Owner | Purpose | Dependency |
|---|---|---|---|
| `t_4b9e93ef` | Keystone | Issue the ONE bounded §6 Option A amendment | after `t_561720ac` |
| `t_8e2070ab` | Seal | Independent review of that exact amendment/hash set | after `t_4b9e93ef`; parent of gate `t_18d27b47` |
| `t_a70376fd` | Keystone | Bounded independent review/verdict on hook `8928eef` | after `t_561720ac`; parent of gate `t_18d27b47` |
| `t_b31a58bf` | Relay | Read-only target-volume free space / capacity measurement | after `t_561720ac` |
| `t_c7b86418` | Meridian | Readiness acceptance gate on the built artifact (six items) | after build `t_2434c6c7` |

Gate `t_18d27b47` carries unsatisfied parents `t_561720ac`, `t_758532e8`, `t_db0eebb2`, `t_8e2070ab`, `t_a70376fd`. It may not complete before S1.

Still not authorized by any of the above: build `t_2434c6c7`, Piston, implementation, deployment.
