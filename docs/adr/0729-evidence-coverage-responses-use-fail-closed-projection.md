# ADR 0729: Evidence Coverage Responses Use Fail-Closed Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: The evidence coverage route returned adapter dictionaries
  directly. Its summary and per-object counts cross a governed evidence API
  boundary and must not inherit future repository fields implicitly.
- **Decision**: Apply a central recursive projection to coverage summary fields
  and per-object requirement/link counts for both SQLite and PostgreSQL route
  paths. Malformed object collections fail closed with a bounded API error.
- **Verification**: Field-access, PostgreSQL-shaped API, and local SQLite route
  tests inject future summary/object fields and prove they do not escape. Full
  regression and release gates are recorded before closure.
- **Compatibility**: Preserve tenant/workspace identity, coverage counts,
  percentage, and explainable object-level requirement counts.
- **Rollback**: Revert E-1069 code, tests, this ADR, the manifest entry, and
  execution metadata together; do not restore direct coverage serialization.
