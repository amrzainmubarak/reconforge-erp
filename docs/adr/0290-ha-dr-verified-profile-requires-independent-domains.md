# ADR 0290: Require multiple observed failure domains for a verified HA/DR profile

- **Status:** Accepted (bounded E-339 slice)
- **Date:** 2026-08-03
- **Decision owners:** ReconForge maintainers

## Context

The HA/DR operational-profile schema already failed closed when a `verified`
profile omitted boolean evidence for quorum, automatic failover, backup/restore,
repeated integrity, RPO/RTO, or production SLO. A profile could still be
constructed with every boolean set to true while reporting only one observed
failure domain, which would weaken the independent-topology boundary.

## Decision

When `status` is `verified`, require `observed.failure_domains >= 2` in addition
to every existing verification boolean. Add a regression test that sets every
boolean true but keeps one observed domain and requires schema rejection.

## Boundary

This is a fail-closed schema and test guard. It does not create independent
hosts, quorum, automatic failover, site-loss recovery, or production SLO
evidence; the retained Docker profile remains `partial`.

