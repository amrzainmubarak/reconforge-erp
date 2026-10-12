# ADR 0774: Require strict Money serialization during PostgreSQL ownership-change hydration

- Status: Accepted
- Date: 2026-08-29
- Owners: Financial Integrity / Persistence / QA

## Context

The PostgreSQL ownership-change repository reconstructs an immutable request
from JSON persisted with the request digest. Its Money helper used the
compatibility restoration reader, which can normalize a policy-valid amount
or currency representation before the row-level digest comparison runs.
The row-level check already rejects a drifted JSON digest, but hydration
should fail at the typed financial boundary as well and must not create a
normalized request from a non-producer representation.

## Decision

Use `Money.from_strict_canonical_dict()` for the PostgreSQL ownership-change
request Money fields. This applies the same exact producer-serialization rule
used by the domain replay verifiers. API request models and other explicitly
compatible readers are unchanged.

## Consequences and rollback

Canonical persisted requests continue to hydrate identically. Non-canonical
amount text, currency text, or Money provenance now fails closed during
hydration before request replay can proceed. This is a read-boundary integrity
tightening with no schema or data mutation and no automatic migration. Rollback
is a reversible source, test, documentation, and manifest revert.
