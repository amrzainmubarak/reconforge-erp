# ADR0871: Persist quotation provenance and isolate Community quotation lines

Date: 2026-10-26. Status: implemented; release qualification remains open.

## Problem and evidence

Independent regression tests reproduced a missing author-provenance table and
cross-workspace line replacement for identical quotation IDs. A subsequent
fault-injection test rejected a non-atomic migration59 implementation. Historical
usernames cannot establish immutable authorship. Existing PostgreSQL0154 databases
must receive the new table through an explicit forward migration.

## Decision

- SQLite59 converts legacy lines to `(workspace_id, quote_id, line_number)`.
  Only uniquely owned rows are converted. Orphaned or collided ownership refuses
  without changing the original schema or data; recovery requires original sources.
- Canonical author provenance is insert-only, parent-bound and immutable. Historical
  quotations receive no inferred author. Existing API409 refusal remains authoritative.
- PostgreSQL0155 adds the provenance table, tenant/workspace FORCE RLS, canonical
  user/quotation foreign keys, immutable triggers and populated downgrade refusal.
  Earlier migration0153 remains unchanged by this decision.
- Schema59, marker and user_version commit atomically. Repository initialization
  uses nested savepoints and complete owned SQL statements, preserving caller work.
- Form input edits invalidate verified results and abort outstanding requests using
  the existing request lifecycle; no new cache or authentication mechanism.

## Verification and rollback

See `docs/execution/ASSURANCE_2026-10-26.md` and its raw receipt index. Independent
QA authored the defect oracles; separate lead/engineering reviewers repaired and
reviewed them. Populated SQLite migration and injected marker failure are tested.
Do not downgrade away populated author provenance. Retain original backups and use
forward recovery; the empty PostgreSQL155 downgrade is tested separately. The
program, CI, production qualification and comparative superiority remain unaccepted.
