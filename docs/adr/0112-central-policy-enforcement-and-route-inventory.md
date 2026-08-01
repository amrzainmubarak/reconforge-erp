# ADR 0112: Central policy enforcement and closed API route inventory

- Status: Accepted
- Date: 2026-07-27

## Context

The central RBAC/ABAC/SoD evaluator existed, but API dependencies, platform
services, Studio, and dynamic workflow transitions still performed independent
permission membership checks. That allowed policy drift and provided no closed
way to detect a newly registered route without an authorization contract.

## Decision

Route all API, platform-service, Studio, and workflow-transition enforcement
through `CentralPolicyEngine`. Support immutable single and any-of permission
contracts; reject malformed or empty contracts at application construction;
and continue to evaluate every supplied tenant/workspace/entity/period scope
and SoD context with deny-by-default behavior.

Derive a deterministic permission-to-route inventory from dependency metadata
when the API is created. Every operation must be classified as `all`, `any`,
`dynamic`, `identity`, or `public`; unclassified, duplicate, ambiguous, and
stale-allowlist entries fail application construction. Store the inventory and
its canonical SHA-256 digest on application state for inspection.

Emit a versioned structured record for each enforced policy decision. It
contains the allow/deny result, stable reason code, surface, request ID, and
SHA-256 digests of actor identity and the permission contract. Raw actor,
tenant, permission, or financial values are excluded.

## Consequences

The current 156 API operations form one reviewed, digest-addressed inventory:
150 permission-protected operations, three public operations, two identity-only
operations, and one explicitly dynamic workflow operation. Adding a route
without classification fails closed. Structured decision records support
operational review but are not an append-only tamper-evident authorization
ledger; durable central collection and retention remain an observability gate.
