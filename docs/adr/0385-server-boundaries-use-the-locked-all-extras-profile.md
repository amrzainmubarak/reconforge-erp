# ADR 0385: Server-boundaries uses the locked all-extras profile

- **Status**: Accepted
- **Date**: 2026-08-06
- **Decision owners**: ReconForge maintainers

## Context

The live `server-boundaries` matrix exercises more than the PostgreSQL/server
adapter. Its selected parity and API tests cover metrics observability,
WebAuthn/MFA, signed packs, federation helpers, and connector boundaries. A
server-only install can therefore collect or execute a different dependency
surface from the matrix it is supposed to verify.

## Decision

Install the universal locked resolution with
`uv sync --locked --all-extras --no-editable --python 3.12` before the live
server-boundaries tests. This reuses the repository lock and explicit extras
(`observability`, `mfa`, `federation`, `connectors`, `backup`, and `server`)
instead of adding ad-hoc CI-only packages. The workflow contract test fails if
the step narrows back to a partial profile.

## Boundary

This closes dependency-profile drift and prevents missing-import collection
failures in the hosted live matrix. It does not prove the hosted run is green,
native PostgreSQL backup/restore availability, provider interoperability,
security provenance, or production readiness; a fresh hosted run remains
required.

## Rollback

Restore the prior install command and remove the contract test, ADR, manifest
entry, and execution evidence. No runtime data or schema migration is changed.
