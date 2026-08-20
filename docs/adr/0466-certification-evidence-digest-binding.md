# ADR 0466: Bind close certifications to the replay-verified evidence bundle

- Status: accepted
- Date: 2026-08-09
- Decision owner: ReconForge execution owner

## Context

The consolidation-close adapters already build a canonical, replay-verified
`close_bundle` digest. Certification metadata recorded maker-checker state, but
the record itself did not say which exact close evidence had been reviewed.
That left a reviewed metadata row unable to prove that it still referred to the
same worksheet, management statement, journal, effects, and attached evidence.

## Decision

Add an additive `evidence_digest` field to SQLite migration 37 and PostgreSQL
Alembic revision `0082_pg_cert_evidence`. Close certification preparation and
review compute the digest server-side from the replay-verified close bundle;
callers cannot supply a financial digest for a close run. Reads recompute the
bundle and fail closed when the persisted certification digest differs. Generic
approval certifications retain an empty digest for compatibility, while any
non-empty value must be a lowercase SHA-256 digest. PostgreSQL and SQLite
guards keep the digest immutable after preparation and preserve maker-checker
separation.

## Boundaries

This binds a certification record to ReconForge's local control-journal and
management-evidence bundle. It is not a legal signature, statutory close,
external audit opinion, compliance certification, or ERP posting proof.

## Reversibility

SQLite migration 37 is additive. PostgreSQL downgrade refuses to discard any
non-empty certification binding before removing the column and restoring the
prior trigger definition. Re-preparation is required for legacy empty-digest
records before they can be read through the consolidation certification path.

## Verification

Focused SQLite, PostgreSQL, API, bundle, approval, and Alembic contract tests
pass. A local PostgreSQL 16.14 non-privileged run passes the consolidation
certification lifecycle and tenant-scoped approval certification gate. Full
local quality/security/package gates remain required before this slice is
promoted in the execution state.
