# Mission Control redaction policy

**Status:** Current operational policy; the versioned contract is normative. This page summarizes the boundary and evidence bar, not a replacement for the contract.

## Boundary

Apply redaction to untrusted free text in every public projection, after projection and before serialization. Do not change canonical stored values. The versioned contract defines the exact markers and detailed behavior; follow it rather than inventing replacements here.

Always redact or remove:

- IPv4 and IPv6 literals, including compressed and bracketed forms.
- Credential-shaped tokens and other bearer credentials.
- Webhook URLs carrying credentials.
- Private-key blocks and headers.
- Credential-bearing headers and assignments; credential-bearing URL userinfo and secret-bearing URLs.
- Sensitive user-controlled map keys when exposed, under an explicitly reviewed, deterministic representation. Do not rename closed-schema keys or silently rename arbitrary keys; see the contract's map-key rule.

Never redact ordinary nonsecret prose, the public hostname `mission.onendo.cloud`, agent names, IDs, timestamps, or harmless values such as `status=running`. Preserve schema keys and useful surrounding context. Redaction is a presentation boundary, not a change to source records, authorization, or schemas.

## Where the rule applies

Cover every installed route that emits free text, not just reducer output: state (cached and live), snapshots, stream/SSE initial state and all event paths, approvals and decision responses, agent diagnostics, events, and task detail when installed, plus newly added free-text routes such as pipeline endpoints. Exercise real route/ASGI behavior with guest authentication and authorized owner branches as applicable. **Reducer-only tests are not sufficient evidence:** route serializers, caches, SSE replay/queues, and error paths can bypass a reducer.

## Evidence required for an acceptance claim

An acceptance claim must be backed by all of the following:

1. Adversarial tests with synthetic sentinels for secret classes and edge forms, asserting the sensitive value is absent.
2. Genuine route tests with guest authentication, exercising the actual route/auth dependency and relevant branches; report method, route, principal, branch/event, and status. A denied request does not prove authorized output was scrubbed.
3. Unchanged-controls assertions proving nonsecret prose, names, IDs, timestamps, harmless status values, structure, and useful context remain unchanged where required.
4. Independent planted-sentinel leakage detectors, separate from the implementation's redaction patterns. Do not claim absence based only on the same patterns used to redact.

The versioned contract specifies the route matrix, adversarial cases, controls, and required reporting. Do not call a missing route a pass; identify it as not implemented. Do not buffer an unbounded SSE stream to test it.

## Governance: relaxation requires Randy

**Randy is the sole approver of any redaction relaxation.** No implementer may approve their own exception. Silence, historical behavior, technical convenience, or an implementation detail is not approval; there are no silent or implied exceptions.

To request a relaxation, record the exact data class and route/surface, the proposed scope and duration, why the current rule cannot meet the need, exposure and mitigation, and tests that prove both the exception boundary and unchanged controls. Submit that request to Randy for an explicit decision. Until the decision is recorded, the existing policy remains in force.

Record Randy's explicit decision, rationale, exact scope, approver, and effective and expiry/review dates in a durable decision record linked from this policy. No exception takes effect before that record exists. At expiry, the default is return to this policy; any extension requires a newly recorded explicit approval. This approval rule governs policy relaxation; it does not silently authorize deployment or unrelated authentication changes.

## Open decision — signed capability links

**Decision pending; do not silently disable the approved signed flow.** The approval link's `_decision_url` `sig` query value is a bearer capability and therefore secret-bearing. The literal no-secret-in-served-URL requirement conflicts with a functioning signed capability URL. While the decision is pending, preserve the approved flow; do not silently remove, rewrite, or invalidate its links, and do not claim the URL secrecy acceptance gate has passed. Continue independent redaction work and report this unresolved gate honestly.

See the [signed-capability decision brief](signed-capability-decision-v1.0.0.md) (decision card `t_8271b6c9`). It lays out the two choices for Randy: retain signed links with an explicitly scoped, recorded exception and hardening, or authorize their replacement with a public dashboard URL and existing owner-authenticated POST. The brief itself is a request, not approval. Randy alone decides; no option is implied by this policy.

## Document safety check

This page uses only synthetic descriptions and contains no sample credentials, live payloads, or literal IP addresses. Checked with the repository's secret-pattern scan and whitespace validation before staging:

```sh
! rg -n -i '(\b[0-9]{1,3}\.){3}[0-9]{1,3}\b|-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(sk_live|ghp_|xox[baprs]-)[A-Za-z0-9_-]{8,}' docs/redaction.md && git diff --check -- docs/redaction.md
```

Result: exit code 0 (no matches; clean diff check). The scan is a practical check, not proof that every possible secret format can be detected.

## Normative references

- [Redaction boundary contract v1.0.0](redaction-contract-v1.0.0.md) — normative technical contract, including transport, route matrix, tests, and acceptance requirements.
- Obsidian: `Architecture/Mission Control/Redaction Boundary v1.0.0.md` — versioned architecture mirror of the same boundary.
- [Signed-capability decision brief v1.0.0](signed-capability-decision-v1.0.0.md) — open decision record; not an approval.
