# ADR 0692: Inventory Core operational API uses fail-closed field projection

- **Date**: 2026-08-26
- **Status**: Accepted for E-1032

## Context

Inventory Core operational routes returned mappings produced by local SQLite
and tenant-scoped PostgreSQL adapters. Those mappings include backend-specific
columns (`tenant_id`, `row_version`, and similar) and can gain future columns.
The operational response family also contains nested movement lines, on-hand
balances, control exceptions, and bounded snapshots containing multiple master
collections. Returning repository mappings directly would allow storage growth
to become an accidental API disclosure change.

## Decision

Add central, explicit allowlists in `reconforge.auth.field_access` for:

- movement headers and movement lines;
- on-hand envelopes and exact balance records;
- control-exception envelopes and exception records;
- the Inventory Core summary; and
- the Inventory Core snapshot envelope, source, summary, and collections.

Apply the projectors to the local and PostgreSQL route branches for movement
list/create/read/post/void, on-hand, control exceptions, summary, and snapshot.
Reuse the E-1031 master-resource projectors inside the snapshot. Nested
collections must be lists of mappings; malformed values raise rather than
being silently discarded. Exact quantity fields and the existing response
envelopes are retained to avoid a breaking compatibility change. The existing
permission and step-up controls remain unchanged.

## Consequences

Known fields in the reviewed response contracts remain available, while
unknown adapter/storage fields are excluded before serialization. The same
projection contract applies to SQLite and PostgreSQL despite their physical
schema differences. This is a bounded disclosure control, not universal
field-level authorization, external IAM, distributed revocation, disclosure
approval, source authenticity, or production effectiveness.

The current focused field/API boundary passes 19 tests. The full Python,
security, package, YAML, and diff gates pass and are recorded in the execution
evidence for E-1032.

## Compatibility and rollback

No database schema, migration, route path, permission, or response envelope is
changed. The allowlists intentionally retain reviewed existing fields,
including raw exact quantity representations used by current clients. Rollback
is a code-and-metadata revert of E-1032, its tests, this ADR, the manifest entry,
and the execution documentation. Do not roll back by restoring unbounded
repository-row serialization in a later adapter change.
