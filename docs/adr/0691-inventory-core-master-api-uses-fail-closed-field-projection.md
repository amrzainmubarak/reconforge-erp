# ADR 0691: Inventory Core master API uses fail-closed field projection

- **Status:** Accepted
- **Date:** 2026-08-26
- **Decision owners:** ReconForge execution slice

## Context

Inventory Core master-resource routes returned local SQLite and PostgreSQL
mappings for units of measure, items, warehouses, locations, and lots or
serials. Future storage or adapter fields could silently expand these
operational responses without a reviewed contract change.

## Decision

Apply one explicit central resource allowlist to every reviewed list and
mutation response for the five master-resource families. Movement, on-hand,
control-exception, summary, and snapshot responses remain separate surfaces
until their own contracts are reviewed.

## Consequences

- Future storage or adapter fields cannot silently expand the reviewed
  Inventory Core master-resource API response family.
- Local SQLite and PostgreSQL shapes share explicit resource contracts.
- Future fields require an allowlist update and regression test.
- This is a bounded disclosure control, not complete Inventory Core response
  coverage, universal field-level authorization, external IAM, distributed
  revocation, disclosure approval, source authenticity, or production
  authorization effectiveness.

## Verification and boundary

`tests/test_field_access.py` covers all five resource projections.
`tests/test_api_inventory_core.py` covers the PostgreSQL route with a
synthetic future adapter field. Focused tests and the full Python regression
pass at 100%; Ruff, Mypy (539 source files), Bandit, pip-audit, package build,
targeted YAML validation (9 files), and diff checks also pass. This ADR does
not cover movement, on-hand, control-exception, summary, or snapshot
responses.

## Rollback

Revert E-1031 code/tests/ADR 0691/manifest and execution metadata together.
Do not restore direct repository-row serialization.
