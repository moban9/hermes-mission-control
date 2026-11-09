# Seal independent review — approvals v1.3.0 §6 Option A

**Verdict: PASS — bounded security/policy review of the exact §6 amendment set only.** This is not an overall v1.3 approval, build authorization, implementation certification, or runtime acceptance. No implementation was reviewed or authorized.

## Reviewed scope and result

Reviewed the produced §6 amendment, isolated OpenAPI companion, checker, validation evidence, exact-set manifest and vault-readback receipt; read CEO disposition §§3, 5 and 6. The amendment defines A01–A10 as fixture-observable assertions in §6.3 (lines 60–73), covering: no URL signature on any decision route; opaque canonical single-use short-TTL link; body-only signature recomputed against capability record; GET read-only/POST mutation; cap-bound double-submit CSRF; single use, TTL ≤300 seconds and constant-time comparison; authenticated replay 409 with existing result; no-referrer and query/body/path log hygiene; hashed-only persistent capability identity; and explicit retirement of HEAD `server/discord.py::_decision_url` semantics. Checker output reports PASS A01–A10 and 77 expected negative rejections, exit 0. This is static/synthetic evidence, not runtime proof.

No weakening found: §6 lines 40, 42, 75 and 79 retain dual scrub before first durable MC-owned derived write and at each egress, preserve upstream raw sources unchanged, and permit only one creation-time push with no retries, scheduler, sweep, refresh or renewal. Policy/credential material is omitted rather than persisted then scrubbed. CEO §8 policy is retained.

The original amendment’s full bytes are unchanged: frozen baseline hash `85da309ce7c3644127cca4b4372f4ccbd4152ede743fb39f0e8c126fe5cbe06a`; checker states all seven frozen hashes and entire original prose (including §§1–5/7–8) are byte-identical. §7/§8 limitations remain explicit: static/schema/synthetic only, no runtime evidence, and A1–A12, readiness, capacity and restore gates remain unproven. No bounded-PASSed prose was silently rewritten.

Additions are enumerated in §6 amendment §9–15 and hash-listed: amendment document; isolated additive Option A OpenAPI paths/logical private schemas (no SQL DDL); checker/test; validation output; resulting hash manifest; vault-readback evidence. No changes to Meridian-passed §3 reads/pagination, §4 notification lifecycle/API/DB, existing SQL objects, approval schema, source exports, or ingestion interfaces are specified. Therefore this amendment does not trigger Meridian’s conditional API/DB re-review on the stated boundary; CEO may route if it determines a broader data-interface impact.

The exact listed set is internally described as 12 manifest entries (seven frozen baseline artifacts, four section-6 additions, and CEO authority); manifest and readback receipt are separately hashed in the issuance handoff to avoid recursive self-hashes. Issuance evidence reports all 14 evidence-set files byte-equal on vault readback. The listed section-6 companion artifacts and manifest/readback receipt hashes are reproduced below from the issued hash set and handoff; the recorded vault receipt reports HTTP 200 readbacks and byte equality.

## Exact reviewed SHA-256 set

### Frozen baseline and authority (12-entry manifest)

| Artifact | SHA-256 |
|---|---|
| `docs/approvals-ux-v1.3.0-amendment.md` | `85da309ce7c3644127cca4b4372f4ccbd4152ede743fb39f0e8c126fe5cbe06a` |
| `docs/approvals-ux-v1.3.0.openapi.json` | `17667dc1f028da9acf9657d696fc9093bbe7606114161d9287ec931dbc370087` |
| `docs/approvals-attention-v1.3.0.sql` | `aa530b41b4c5f1405d41024eba4986e5c07d0403e9ce41fbb3dc08f2c40d591d` |
| `docs/approvals-presentation-v1.3.0.schema.json` | `abdedc5a185f624f504948eab42391d6d68bdc50f2c62474e03936b9f42e1fe8` |
| `docs/check-approvals-v1.3.0.py` | `a5920c7347b5fc63405e2d0a524622810efa5f501e7ebe1c1b12b0b0e5996c1a` |
| `docs/approvals-v1.3.0-validation.txt` | `756545b11048d7aab2ff62b56e84dfe5126c1e0e34be0bb8141224737984cb61` |
| `docs/redaction-contract-v1.1.0.md` | `d9cad0810bb88efa7624126b7e9bd8f9a8c01351faf0203edbc143acc6a32c99` |
| `docs/approvals-v1.3.0-ceo-disposition.md` | `c16f44c9808fb6ef268f33db60bfe8a353c58914252759be845cbe5baf157acd` |
| `docs/approvals-v1.3.0-section6-option-a.md` | `78a4f1ab5ba9d2e77251c35f19c680c7b1191ffe87893c090a7b7de4747d3371` |
| `docs/approvals-v1.3.0-section6-option-a.openapi.json` | `d180c0c28566b63e524cb6f10dc56ea21c39abf575c2b1ad3b66891a1c752053` |
| `docs/check-approvals-v1.3.0-section6.py` | `4e65c583635188ed3e96b252701af03c3b00c9dbe02a875535fcd1f1f062cdad` |
| `docs/approvals-v1.3.0-section6-validation.txt` | `eeaad435dfda9820d0df89460eabd59b559cf4fa14e3b054f8256c8d8594799c` |
| `docs/approvals-v1.3.0-section6-hashes.json` | `1cba176791f43d78e40be48653834a3f2e1421f189e67fcfb2b6d6db8feafe4c` |
| `docs/approvals-v1.3.0-section6-vault-readback.json` | `dbdce6e1fa26655a65b8ac3c1def8db55861a2f551481d200115388a1268fe73` |

The first eight rows are frozen baseline/authority entries; rows 9–12 are section-6 additions. Final four rows above include the amendment, OpenAPI, checker, and validation; the two evidence files are the manifest and separate readback receipt. Total exact set: 14.

## Verification and limits

- Re-ran `python3 docs/check-approvals-v1.3.0-section6.py`: exit 0; reported 77 expected Option A rejections, 151 baseline SQL rejections, PASS A01–A10, and no runtime certification.
- Read the amendment, OpenAPI, hash manifest, validation output, vault receipt and CEO disposition directly. Issuance manifest records 12 entries; receipt records 13 readbacks (the 12 manifest entries plus manifest), each `readback_status: 200` and `byte_equal: true`; receipt self-hash is separate. Issuance handoff reports receipt hash `dbdce6e1fa26655a65b8ac3c1def8db55861a2f551481d200115388a1268fe73` and all 14 evidence files byte-equal.
- This review does not substitute for real handler/browser/DB/WAL/log/transport/race/crash/comparator-spy evidence, Meridian readiness, CEO exact-set disposition, hook review, or Randy’s explicit build release.

**No changes requested at this bounded scope.**
