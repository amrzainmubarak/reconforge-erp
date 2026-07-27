# ADR 0064: Pin a Scoped OWASP ASVS 5.0.0 Mapping

- Status: Accepted
- Date: 2026-07-25
- Scope: official ASVS version/source identity, all-chapter selected-requirement mapping, evidence statuses, and assurance boundary

## Context

P0-SEC-003 requires a latest-stable ASVS mapping that distinguishes
implemented, partial, planned, and not-applicable requirements without a
compliance claim. ASVS is externally versioned and its `master` release changes
continuously. Mapping mutable content or relying on remembered 4.x identifiers
would make the result irreproducible.

The stable ASVS 5.0.0 source contains 345 requirements across 17 chapters. A
credible full verification would require deployed configuration, runtime and
adversarial evidence beyond this repository. Marking hundreds of requirements
planned or passed without that analysis would create paper assurance and a
large generated artifact with little review value.

## Decision

1. Pin OWASP ASVS 5.0.0, released 2025-05-30, at official release tag
   `v5.0.0_release` and commit
   `5cf9b032440be53ce345ab3c130fda46ba1ce7a2`.
2. Pin the official English CSV at 105,100 bytes and SHA-256
   `98c8fe911b9edb403af8ee05d3ce8201ecac2659e313b053890a62847cdcf680`.
   Record OWASP project/release/source URLs and CC BY-SA 4.0 attribution.
3. Exclude the automatically regenerated `master` Bleeding Edge release.
   OWASP explicitly directs production use to the stable release; its changing
   assets are not a reproducible baseline.
4. Use OWASP's version-qualified reference form
   `v<version>-<chapter>.<section>.<requirement>`. Store identifiers/levels and
   ReconForge assessments without copying full upstream requirement prose.
5. Cover all 17 chapters with exact official chapter names/counts, but map only
   55 high-relevance requirements. Declare the remaining 290 `unassessed`; that
   state conveys no implementation, failure, plan, applicability, or assurance
   conclusion.
6. Define four mapped statuses: narrowly scoped `implemented`, incomplete
   `partial`, evidence-insufficient `planned`, and capability-conditioned
   `not_applicable`. Every mapped item has a scope, owner, assessment, residual
   gap/limitation, and next action. Implemented/partial items require existing
   code and test evidence; planned/not-applicable items must not borrow evidence.
7. Require not-applicable entries to name a reassessment trigger. The absence of
   XML, GraphQL, WebSocket, self-contained token, OAuth/OIDC, or WebRTC surfaces
   is not permanent architectural permission to ignore those chapters.
8. Validate the closed mapping, stable-source pin, chapter counts, selected
   IDs/levels, status summary, owner/evidence paths, assurance wording, and
   readable all-chapter view in offline repository tests.
9. Do not assign an ASVS level or use the mapping as compliance, certification,
   audit, penetration-test, secure-product, or release-readiness evidence.

## Consequences

- The mapping is reproducible against one official stable source and cannot
  silently drift to Bleeding Edge content.
- Four implemented statuses are deliberately narrow API/session header and
  session-lifecycle scopes. They do not make their chapters or application
  generally implemented.
- Material gaps in file abuse handling, password policy/recovery, ABAC, TLS,
  secret management, dependency provenance, and security logging remain visible.
- The 290 unassessed requirements make the coverage limit measurable instead
  of letting selected evidence imply full ASVS verification.
- P0-SEC-003 can close for this scoped mapping. A future full independent ASVS
  verification remains separate work and cannot be inferred from closure.

## Rollback

Retain schema-v1 and the pinned source identity. A newer stable ASVS release
requires a versioned successor with reverified source digest, chapter counts,
ID/level fixture, mappings, readable view, and migration note. Do not repoint
this mapping to `master`, erase unassessed counts, broaden implemented scopes,
or relabel a planned/not-applicable item without new evidence and review.
