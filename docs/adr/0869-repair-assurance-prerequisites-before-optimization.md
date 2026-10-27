# ADR0869: Repair assurance prerequisites before optimization

Date: 2026-10-25. Status: accepted for the bounded development repair.

## Context

Source `7af61cddb1fc96a3f5f348257c772206171572c1` declares all engineering gates
passed, but current production-bound regressions reproduce unauthorized leave
withdrawal, partially persisted entitlement transitions, invented ledger links,
fabricated browser financial results, and unsafe XML entity processing. The
current authorization-inventory gate also fails. Historical tests, in-test
implementations and dictionary workloads cannot qualify a successor release.

## Decision

Keep one checkout at `F:\reconforge-erp`, use an `amr/` branch, preserve earlier
evidence and repair these prerequisites before optimization or competitor claims.
Use authenticated identity for self-service leave ownership, insert-only request
creation, and one locked transaction for each read/validate/write transition.
SQLite serializes writers before reads; PostgreSQL locks request then balance.
Session touches finalize only transactions they own, including zero-row races.
Public HCM domain count inputs reject non-integers before payroll-affecting arithmetic;
no silent coercion of bool, float, Decimal or text.

Require an explicit Finance Core result with a real identifier before linking a
source or emitting a posting event. This does not qualify posting atomicity or
wire previously disconnected production APIs. Browser failures must expose no
invented results. Server results are scoped to the current session and validated;
source-less statement/MPS generation and client-only assistant approvals remain
unavailable. XML ingestion rejects DTDs, entities and external declarations using
the already-declared defusedxml dependency. Register the existing migration0152
without changing its SQL or adding unreviewed schemas.

Independent QA owns the HCM regressions; the lead implements the product repair.
Different agents review engineering and UI fixes. Automated review is bounded
engineering evidence, with no external certification implication.

## Compatibility and rollback

Existing endpoint names and successful response shapes remain. Unauthorized
withdrawal returns403; duplicate request IDs return409. DTD-bearing XML now raises
a safe ValueError. Missing/malformed Finance Core references fail before source
mutation. These are intentional tightening of unsafe behavior, with regressions.
Future helper audit actions change from `milestone_gl_posted` and
`profit_in_stock_gl_posted` to `milestone_gl_linked` and
`profit_in_stock_gl_linked`, carrying observed `finance_entry_status`. Historical
audit rows remain unchanged; action-name consumers need to recognize the new
names. Draft creation does not imply human validation/approval. No database
data migration, license change, deployment or main-branch write.

Revert the individual repair commits on the feature branch if necessary; preserve
the tests and negative evidence for investigation. Such a revert reopens known
defects and must not be used to qualify a release. The migration registry change
requires no SQL downgrade: migration0152 itself is unchanged.

## Acceptance boundary

See [current assurance record](../execution/ASSURANCE_2026-10-25.md). All six global
gates remain open until current-source release evidence exists. No throughput,
usability-study, WCAG-conformance, statutory, security-certification or competitor
advantage is inferred from these repairs.
