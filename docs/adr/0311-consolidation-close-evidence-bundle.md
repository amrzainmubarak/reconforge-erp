# ADR 0311: Bind one consolidation close to one evidence bundle

- Status: accepted
- Date: 2026-08-04
- Scope: replay-verifiable close evidence indexing

## Context

The SQLite and PostgreSQL close adapters already replay-check the worksheet,
translation lineage, management statement, journal lines, and committed
effects. Consumers still had to correlate those independently returned
artifacts and could accidentally combine digests from different runs.

## Decision

Add `consolidation-close-bundle-v1`, a pure domain manifest produced only after
the repository replay checks succeed. It binds workspace, period, run status,
worksheet/translation/management-statement/journal digests, and sorted effect
digests into one canonical bundle digest. Both close adapters expose the
bundle in replay-verified run details. The bundle is additive and does not
create a posting path or change lifecycle transitions.

## Evidence boundary

This is local-control-journal and management-only evidence. It proves
cross-artifact identity, canonical ordering, and tamper refusal; it is not a
statutory statement, external ledger posting, provider acknowledgement,
write-back, or production assurance.

## Rollback

Remove the bundle module, adapter projections, focused tests, manifest entry,
and this ADR. Existing persisted close rows remain readable because the bundle
is derived at read time and no migration is introduced.
