# ADR 0625: Refuse policy evidence built from a mismatched context

- Status: Accepted
- Date: 2026-08-25
- Decision owners: Identity Security, Financial Controls, Platform Architecture
- Scope: Local policy-decision evidence construction when a caller supplies the evaluated context

## Context

`CentralPolicyEngine` returns a `PolicyDecision` carrying deterministic
`context_digest` and `scope_digest` values. The evidence builder also accepts a
`PolicyEvaluationContext` so a caller can bind the evidence to the input it
claims to have evaluated. Previously, the builder preferred a digest already
present on the decision whenever one existed. A caller could therefore pair a
decision from one context with a different supplied context and receive an
apparently valid evidence artifact whose digest described the first context.

This is an evidence-integrity failure even though it does not by itself grant
authorization. It weakens replay and review because the artifact can no longer
prove that the supplied context is the context represented by the decision.

## Decision

1. When `build_policy_decision_evidence` receives a context, it always derives
   the expected context and typed-scope digests from that context.
2. If the decision already carries either digest and it differs from the
   corresponding derived value, evidence construction raises a `ValueError`
   before an artifact is emitted.
3. If the decision digest fields are absent, the derived values are attached to
   the new evidence as before.
4. When no context is supplied, the existing compatibility behavior remains:
   a decision-bound digest is retained, and an unbound decision receives the
   explicit unbound sentinel digests. This keeps historical callers compatible
   while requiring context-aware callers to bind evidence correctly.

## Security and correctness consequences

- A decision cannot be rebound silently to a different tenant, workspace,
  entity, period, object, amount, or other policy input represented by the
  supplied context.
- The context and typed-scope namespaces are checked independently, so a
  decision with a matching full context digest but a mismatched scope digest
  is still refused.
- The check is local evidence construction only. It does not prove that the
  principal was authenticated, that every route supplied the right context,
  that the log sink is append-only, or that an external IAM provider enforced
  the same policy.

## Compatibility and rollback

The change affects only callers that pass a context inconsistent with a
decision's existing digest. Existing no-context evidence construction,
authorization outcomes, log fields, API schemas, and persisted artifact
versions remain unchanged. Roll back the guard, its regression tests, and this
execution record together if a legacy caller is found that intentionally
rebinds a decision; that caller must then be migrated to construct a fresh
decision from its actual context.

## Verification

- `tests/test_policy_engine.py` rejects mismatched full-context and
  scope-digest bindings while retaining the existing replay/tamper tests.
- Ruff, Mypy, the focused policy/cache suites, and the full local regression
  are required for the slice.
