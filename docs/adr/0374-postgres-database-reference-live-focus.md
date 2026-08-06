# ADR 0374: Retain the PostgreSQL database-reference live focus

- **Date**: 2026-08-06
- **Status**: Accepted
- **Decision**: Promote the current migration-head PostgreSQL runtime check for
  the named-query database-reference connector as bounded connector evidence.
- **Verification**: A fresh PostgreSQL 17.10 database with the non-privileged
  application role passed the database-reference live suite 3/3, including
  read-only named-query execution, bounded Decimal rows, cursor/replay
  behavior, and tenant isolation; the database was removed after the run.
- **Boundary**: This is deployment-provided PostgreSQL view evidence only. It
  is not a live ERP/bank vendor connector, schema certification, write-back,
  hosted provider, HA/DR, or production interoperability claim.
- **Rollback**: Remove the evidence entry and ADR; no runtime/data rollback is
  required.
