# ADR 0550: Bind the impairment route to amount-bounded ABAC

- **Status:** Accepted
- **Date:** 2026-08-23
- **Execution slice:** E-836

## Context

E-835 made bounded amount policies fail closed when a financial amount is
missing, but a central primitive is not sufficient if high-risk routes do not
pass their typed amount into the policy decision. The PostgreSQL consolidation
impairment prepare route receives canonical Money inputs and is a non-posting,
maker-checker financial control boundary.

## Decision

Before the impairment artifact is persisted, the route converts the request to
the typed domain request, sums all carrying amounts using `Decimal("0")` and
the typed Money amounts, and passes that total to the server-scoped central
policy re-evaluation. The GET/read route remains amount-free because it does
not authorize a financial mutation. Cross-currency or malformed values fail at
the existing domain conversion before policy or persistence.

## Rationale

Policy bounds must constrain the exact financial effect represented by the
route. Summing canonical carrying amounts gives the policy an auditable,
deterministic value without float conversion, while preserving the existing
non-posting and maker-checker boundary.

## Compatibility and rollback

The server-scoped permission helper gains an optional Decimal amount; existing
callers are unchanged. Local SQLite compatibility remains unchanged. Rollback
is a source-version rollback with no migration or data rewrite.

## Evidence and limits

Route tests assert the exact Decimal total passed to policy and retain the
authenticated actor. This proves one high-risk route binding, not universal
amount propagation across every financial route, policy-cache invalidation, or
production IAM effectiveness.
