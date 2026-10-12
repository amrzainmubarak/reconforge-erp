# ADR 0678: Evidence record reads use fail-closed field projection

- **Status**: Accepted
- **Date**: 2026-08-26
- **Related execution slice**: E-1018
- **Scope**: Local and Server Profile evidence list/get/register responses

## Context

ADR 0677 protected evidence drill-down, but the adjacent list and single-record
read routes still serialized adapter records directly.  The Server Profile
registration response also returned the adapter record without the reviewed
response allowlist.  That left a sensitive response path outside the field
projection boundary.

## Decision

Reuse the E-1017 evidence record/link projection for local and Server Profile
list and get responses.  Ordinary reads use the non-sensitive projection and
retain the existing `***redacted***` token.  Server Profile list/get policy
checks request the same safe field set through the central scoped policy
boundary.  The Server Profile registration response uses the sensitive
allowlist after its existing `evidence.manage` authorization, so even that
response cannot expose an unreviewed future field.  Projection metadata is
returned additively with each record.

## Consequences and boundaries

The complete evidence record response family now has one reviewed field
projection boundary across local and Server Profile adapters.  This does not
grant access, expose artifact bytes, replace tenant/RLS authorization, or
prove universal field-level enforcement across other APIs, exports, workers,
or UI surfaces.  Live provider, external IAM, distributed revocation, and
production effectiveness remain unproven.

## Verification

- `python -m pytest -q tests/test_api_platform_routes.py tests/test_api_server_evidence.py tests/test_field_access.py`
- `python -m ruff check reconforge/api/routes/evidence.py tests/test_api_platform_routes.py tests/test_api_server_evidence.py`
- `python -m mypy reconforge/api/routes/evidence.py`
- Full Python regression, package build, and `git diff --check` are required
  before closing the slice.

## Rollback

Revert E-1018 route/test/ADR/manifest and execution-document changes.  The
rollback does not modify persisted evidence records or artifact bytes.
