# ADR 0791: Preserve typed retention errors and renew runtime evidence

Date: 2026-10-03. Status: accepted. Scope: production foundation verification.

## Context and decision

Running the previously filtered PostgreSQL CI selection exposed a real HTTP
error: APIError inherits ValueError, so a projection catch incorrectly turned
retention conflicts and missing evidence into a generic 503. Execute the service
before the projection-only catch. Preserve 409/404 domain responses and keep
malformed response projection sanitized as 503.

The full suite also exposed retained write-back reports bound to the earlier
dependency cutoff. Generate new dated reports through the actual pinned
PostgreSQL 16/17 drills. Do not edit historical report fingerprints. The identity
drill upgraded to head but asserted revision 0090; align it with 0093 and add a
test against Alembic's current head. Extend report schema target revisions
additively so historical 0090 evidence remains readable.

Keep existing approval-surface discovery strict: expose the SQLite AP creator
check at the public approval boundary, inside BEGIN IMMEDIATE. Verify a denied
approval releases its lock and emits no successful audit/outbox evidence.

## Verification and rollback

Focused AP tests: 78 passed, zero skipped. Actual broad PostgreSQL CI selection:
409 passed, zero failed, one explicit missing-native-client-tools skip. Preserve
the new 0093 retained-snapshot downgrade guard and assert data remains unchanged.
The identity API assertion follows the existing Reopened contract. Retention
tests cover stale version, missing evidence, retired policy and malformed output.
Fresh drill reports and full-suite outcomes are recorded separately in EVIDENCE.
These changes require no data rewrite. Rollback is a source revert, preserving
both historical and new evidence and the already-installed migration history.
