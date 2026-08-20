# ADR 0336: PostgreSQL close runs bind replay-verified intercompany evidence

- **Status:** Accepted
- **Date:** 2026-08-05

## Decision

Add an immutable PostgreSQL link between a prepared consolidation-close run and
one or more persisted intercompany-elimination artifacts. The link stores the
artifact result digest, the exact matched elimination identifiers, the count of
unresolved source groups, and its own digest under forced tenant RLS.

Before a run moves from `Prepared` to `Approved`, every worksheet elimination
whose type is `intercompany_transaction` must be covered by exactly one linked
artifact. The adapter replays the artifact, checks workspace, period, currency,
proposal fields, source digests, and link digest in the same transaction. The
evidence is exposed in the run detail and included in the additive close-bundle
digest. No statutory/legal-book posting or external ERP/bank write-back is
introduced.

## Rationale

Persisting a proposal and persisting a close journal separately leaves a gap:
the close reviewer cannot prove that the journal line came from the exact
source artifact that was prepared. A digest-bound link closes that provenance
gap without inventing accounting treatment or allowing mutable evidence.

## Consequences and limits

- `0064_pg_close_ic_links` is a forward migration with a data-loss refusing
  downgrade.
- Attachment is server-profile only, requires `finance_core.manage`, and is
  allowed only while the close run is `Prepared`.
- Unresolved intercompany groups remain visible and do not become eliminations.
- This is a bounded control-journal/evidence integration. It does not prove
  statutory consolidation, legal-book posting, live provider interoperability,
  write-back, HA/DR, throughput, compliance, certification, or production
  readiness.

## Rollback

Stop using the new attachment route and roll back only before any link rows are
created. The migration refuses downgrade once evidence exists; operational
rollback is therefore forward-compatible disablement, not destructive erasure.
