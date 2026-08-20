# ADR 0411: Bind server policy re-evaluation to organization scope

- **Date**: 2026-08-07
- **Status**: Accepted

## Context

Server routes already selected a tenant and workspace, and some callers passed
a legal-entity scope. The central request-time policy helper did not include
the caller-selected organization, so a permission could be evaluated against a
workspace/entity context without proving the organization header was the same
scope that the authenticated principal was allowed to use.

## Decision

`enforce_server_scoped_permissions` accepts an optional `organization_id` and,
for workspace-scoped server requests, derives it from the validated
`X-ReconForge-Organization` header when callers do not pass it explicitly. An
explicit/header mismatch fails closed before policy evaluation. The
`PolicyEvaluationContext` now carries the organization and authorized
organization set, and reason-code mapping exposes `organization_scope_denied`.
The single-permission wrapper forwards the dimension while tenant-wide
administration remains compatible with a null workspace.

## Verification and boundary

Focused execution-scope tests cover an allowed organization and explicit
mismatch rejection. The full local regression and static/package gates pass.
This is central request-policy evidence; it does not prove that every route,
worker, export, UI, provider, federation, or PostgreSQL runtime has migrated,
nor does it prove production IAM or HA/DR.

## Reversibility

Remove the optional helper dimension, tests, and ADR. Existing callers that do
not provide organization scope retain their previous tenant/workspace contract.
