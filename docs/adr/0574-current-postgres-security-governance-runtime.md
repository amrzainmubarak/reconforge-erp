# ADR 0574: Current PostgreSQL security governance runtime evidence

## Status

Accepted — 2026-08-23

## Context

Identity governance and policy analysis require database-enforced tenant
boundaries and maker-checker scope checks, not only pure policy contracts.

## Decision

Record the current live runtime result for
`tests/test_postgres_security_governance.py` and
`tests/test_postgres_policy_analysis_runtime.py` under PostgreSQL 16.14 and a
non-superuser/non-BYPASSRLS `reconforge_app` role. Preserve the distinction
between runtime control evidence and any legal, regulatory, compliance, or
certification claim.

## Limits

The run uses synthetic tenants on one local Docker host. External identity
providers, multi-host failure, HA/DR, independent review, compliance, and
production SLO evidence remain open.
