# ADR 0065: Pin Final NIST SSDF and Map Every Core Task

- Status: Accepted
- Date: 2026-07-25
- Decision owners: Release Security, Platform Security

## Context

NIST now lists SSDF 1.2 as an Initial Public Draft while SSDF 1.1 remains the
current final core publication. NIST SP 800-218A is also final, but it is a
supplemental community profile for generative AI and dual-use foundation-model
development and systems. A loose “aligned with SSDF” statement would hide
which source was used, omit tasks, and confuse repository artifacts with an
operating secure-development program.

## Decision

Adopt a closed schema-v1 mapping pinned to final NIST SP 800-218 / SSDF 1.1 and
the digests of its official PDF and Excel table. Cover all four groups, 19
practices, and 42 tasks exactly once. Every task has an architecture owner,
status, assessment, gap, and next action; positive partial evidence must link
existing repository files and tests. Review every 90 days and on material
source, SDLC, AI, or vulnerability events.

Exclude SSDF 1.2 from the normative source until NIST publishes it as final.
Record SP 800-218A as a separate required assessment before model-backed AI
capabilities are promoted. Assign no `implemented-bounded` or
`not-applicable` status in this first review: repository presence supports 28
partial tasks while 14 remain planned.

## Consequences

- Source/version drift, missing/duplicate task IDs, unsupported status totals,
  dangling owners/evidence, and claim-boundary drift fail contract tests.
- The matrix exposes release integrity, provenance, training, environment,
  vulnerability response, root-cause, and AI-profile gaps without fabricating
  operating evidence.
- This change adds governance artifacts only. It does not change runtime,
  source control, CI execution, release signing, personnel process, or incident
  response.
- The mapping establishes no NIST endorsement, SSDF conformance, secure-SDLC
  assertion, compliance, certification, or production-readiness claim.

## Compatibility and rollback

No runtime/API/schema compatibility surface changes. Preserve the v1 source
pin and use a versioned successor for a final SSDF revision or changed mapping
contract. Never repoint this artifact to a draft, erase planned/partial gaps,
or convert repository links into conformance claims. Rollback is removal of
this governance slice and its manifest/test/doc references; it cannot undo or
assert any external organizational process.
