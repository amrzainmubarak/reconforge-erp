# ADR 0141: Evidence-registry application boundary

- Status: Accepted
- Date: 2026-07-28

## Decision

Move the complete evidence registry behind a typed application port and SQLite
adapter. Define the byte-store result as a read-only structural protocol so the
Application layer imports no provider implementation. Re-export the historical
storage constants, verification result, and service from the Platform facade.

For registration with an immediate governed-object link, append link audit and
outbox rows without committing. Commit the registry row, link, both audit rows,
and both outbox rows only through the final registration audit boundary.

## Consequences

Local and explicit S3-compatible storage, retention references, checksum
verification, redaction, coverage, and drill-down remain compatible. Failure of
either audit cannot leave partial lineage. PostgreSQL adapter convergence and
independent retention/tamper operation remain later gates.
