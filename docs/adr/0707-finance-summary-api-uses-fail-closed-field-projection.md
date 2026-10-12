# ADR 0707: Finance Summary API Uses Fail-Closed Field Projection

- **Date**: 2026-08-27
- **Status**: Accepted
- **Context**: Finance Core exposes summary responses through three compatible
  boundaries: local SQLite, tenant-scoped PostgreSQL Finance Core, and a
  bounded legacy PostgreSQL ledger adapter. The shapes differ, and direct
  serialization or branch-specific hand-built dictionaries could allow future
  fields to cross the disclosure boundary inconsistently.
- **Decision**: Apply one deliberate union allowlist to all three summary
  shapes. Project nested source metadata through its own allowlist, preserve
  the known Finance Core and legacy ledger count fields, and drop unknown
  fields before serialization.
- **Verification**: Field-access tests cover Finance Core and legacy fields,
  nested source projection, and future fields. The server Finance Core route
  contract injects an unknown summary field and proves it is absent. Focused
  and full release-quality gates are required for the evidence record.
- **Compatibility**: This changes response disclosure only. It does not alter
  posting, validation, ledger arithmetic, scope checks, persistence, or
  authorization behavior.
- **Rollback**: Revert E-1047 code, tests, this ADR, the manifest entry, and
  execution metadata together. Do not restore unbounded summary serialization
  without an approved compatibility allowlist.
