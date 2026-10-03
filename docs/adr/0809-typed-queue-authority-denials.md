# ADR0809: Return typed denials for unauthorized queue projections

Date:2026-10-03

Status:Accepted for the bounded HTTP error contract

The governed durable-job queue reader correctly rejects ungranted workspace or
entity selections, but its `JobAuthorizationError` escaped the HTTP adapter.
GitHub's live server test exposed this failure; a later immutable-audit fixture
cleanup failure obscured the original exception. The old fixture had no durable
scope grants for the scopes it expected to read.

Map this authorization exception to HTTP403 with the fixed safe code
`durable_job_queue_scope_denied`. Keep the policy checks and audited denial;
do not grant a scope based on the requested query or expose the internal policy
exception. Existing permitted queue projections and cross-tenant401 behavior
remain covered.

The live synthetic fixture now provisions actual canonical scope records and
durable service-account grants, supplies its audit privileges explicitly, tests
ungranted workspace/entity requests, and removes only its own audit/grant rows
inside an administrative cleanup transaction. Trigger protection is restored
before cleanup commits. This is test-fixture administration, not a product
permission or deletion path.

On a fresh migration0093 database, the fixture-corrected red run is1failed/3passed
because the denied HTTP request raises the unhandled application exception.
After the adapter change,4tests pass with no skips in5.30s, including actual
authenticated service-account HTTP requests and PostgreSQL RLS. Provisioning,
verification and confirmed database removal take12.377s. Ruff, source Mypy and
whitespace checks pass. The prior failed remote run is retained.

Reverting the handler restores the erroneous HTTP failure; it does not grant
unauthorized data access. No schema migration, queue payload change, broad
operational-readiness claim, or production deployment is part of this repair.
