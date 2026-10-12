# ADR 0724: Finance Core Snapshots Use Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: The authenticated Finance Core snapshot route returned the
  PostgreSQL repository snapshot directly. The snapshot contains the source
  and summary envelopes, master-data collections, ledger entries, and nested
  entry lines; future adapter fields could cross the API boundary without
  review.
- **Decision**: Apply one central recursive projection to the snapshot root,
  source and summary envelopes, charts, accounts, dimensions, dimension values,
  journals, entries, and entry lines for both local SQLite and tenant-scoped
  PostgreSQL responses. Invalid nested shapes fail closed with a bounded API
  error.
- **Verification**: Field-access tests inject future fields at the root and
  each nested boundary. Server-shaped route tests cover PostgreSQL and local
  adapter response paths. Full regression and release gates are recorded in
  the execution evidence before the slice is closed.
- **Compatibility**: Preserve the reviewed schema version, timestamps, source
  markers, workspace, summary counts, financial master data, and ledger-entry
  fields. Unknown adapter fields are removed without changing persistence
  schemas or CLI contracts.
- **Rollback**: Revert E-1064 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct snapshot serialization.
