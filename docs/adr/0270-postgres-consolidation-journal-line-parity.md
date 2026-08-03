# ADR 0270: PostgreSQL consolidation journal-line parity

- **Status**: Accepted for the bounded P4-FIN-002 slice
- **Date**: 2026-08-03
- **Decision**: Persist the verified consolidation control-journal lines and
  committed effect lines in PostgreSQL, matching the existing SQLite
  lifecycle boundary. Store exact minor units plus canonical decimal text,
  tenant-scope every row with forced RLS, and reject updates/deletes through a
  database trigger. Reads must replay the JSONB worksheet and compare the
  persisted line and effect digests before exposing a run.
- **Compatibility**: Alembic `0057_pg_consol_journal_lines` adds the columns
  and child tables. Rows created before this migration remain readable through
  a compatibility reader; a later governed effect transition materializes the
  exact verified lines. No existing CLI/API name or SQLite schema changes.
- **Rationale**: Persisting only a worksheet digest and effect metadata left
  PostgreSQL weaker than SQLite: journal/effect line lineage could not be
  independently queried, balanced, or tamper-checked. A canonical child-row
  model makes replay, tenant isolation, and append-only evidence explicit
  without pretending to be a statutory ledger.
- **Verification**: Focused schema/migration/registry contracts and the
  SQLite/PostgreSQL adapter suites pass locally. CI run `30786172958` passed
  the implementation, and final documentation-bound CI run `30786555699`
  passed the live PostgreSQL contract under the non-privileged role, proving
  lifecycle replay, effect-line cardinality, tenant isolation, and update
  refusal at the final head.
- **Boundary**: This is synthetic control-journal persistence parity only. It
  does not implement acquisition accounting, goodwill/equity method, statutory
  consolidation, live rates, ERP/bank write-back, HA/DR, distributed scale,
  or production readiness.
