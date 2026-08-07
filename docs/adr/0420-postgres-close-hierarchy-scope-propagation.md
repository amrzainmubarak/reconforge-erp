# ADR 0420: Preserve hierarchy scope through PostgreSQL close and approvals

- **Status:** Accepted
- **Date:** 2026-08-07
- **Scope:** PostgreSQL consolidation-close and certification approval execution

## Decision

Carry the authenticated organization, workspace, and legal-entity scope from
the server execution boundary into `PostgresConsolidationCloseRepository` and
`PostgresApprovalRepository`. Every transaction-local scope reset now restores
the complete hierarchy instead of reducing the request to tenant-only state.

## Compatibility and boundary

The constructor arguments are optional, so tenant-only callers and existing
legacy rows remain compatible. A legal entity without an organization is
rejected before database access. This slice fixes scope propagation only; the
close tables still require a separate additive hierarchy-persistence migration
before multi-entity PostgreSQL storage claims can be widened.

## Evidence

Focused tests capture all five transaction-local settings for both repositories
and reject invalid parentage. No live PostgreSQL hierarchy isolation, statutory
posting, provider write-back, HA/DR, or production-readiness claim is made.
