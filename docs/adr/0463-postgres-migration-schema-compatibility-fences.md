# ADR 0463: PostgreSQL migration schema-compatibility fences

- Status: accepted
- Date: 2026-08-09
- Decision owner: ReconForge execution owner

## Context

The live PostgreSQL migration path exposed two compatibility defects that
static contracts did not catch. Migration `0078_pg_close_scope` assumed every
close table had `created_at`, although runs and child-line tables deliberately
predate that column. The `0069_pg_close_ppa_links` downgrade used a trigger name
that did not match the trigger created by its upgrade. A live replay also
showed that impairment-row positional fallbacks were one column out of date
after hierarchy columns were appended.

## Decision

Make the hierarchy-index migration inspect the actual table columns and use a
stable `(tenant_id, organization_id, legal_entity_id, id)` fallback where
`created_at` is absent. Align the PPA downgrade with its upgrade trigger name,
and correct the impairment positional decode indices while retaining the
hybrid row's named access path.

## Rationale and boundaries

The change is additive and preserves existing schemas, immutable records, and
RLS semantics. It prevents a fresh or upgraded PostgreSQL database from
failing solely because an older close table lacks a timestamp, and it keeps
replay verification tied to the persisted row contract. It does not claim
hosted CI, multi-node PostgreSQL, backup/restore, provider, or production
readiness.

## Reversibility

Reverting the helper, downgrade spelling, and decode indices restores the
previous code but would reintroduce the observed live failures. No migration
or external system is changed by the code change itself; the schema migration
remains linear and reversible.

## Verification

The local Docker PostgreSQL 16.14 instance upgrades from `0061_pg_writeback_intents`
to `0081_pg_prof_invoice`, the Alembic round-trip contract passes, and the live
close plus impairment/deferred-tax/PPA/ownership replay suites pass. Static
close-migration contracts and the repository/tree Gitleaks scans also pass.
