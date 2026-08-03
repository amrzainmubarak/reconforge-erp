# ADR 0263: Fail closed on unproven HA/DR verification

- **Status:** Accepted
- **Date:** 2026-08-03

## Decision

Extend the HA/DR operational-profile contract with explicit verification
booleans for independent failure domains, quorum or witness fencing, automatic
failover, backup/restore integrity, repeated integrity, observed RPO/RTO, and
production SLO evidence. A profile may use `status: verified` only when every
gate is true; otherwise it remains `partial`.

## Boundary

The retained Docker report remains `partial`: it has repeated synchronous
backup/restore and RPO/RTO evidence, but one host, a manual controller, and no
quorum/witness or automatic failover. This gate prevents documentation drift;
it does not manufacture multi-host runtime evidence.

## Reversibility

The change is additive to the evidence schema and profile. Removing the fields
would not alter runtime, migrations, or deployment behavior.
