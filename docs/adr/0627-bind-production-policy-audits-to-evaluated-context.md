# ADR 0627: Bind production policy audit records to the evaluated context

- Status: Accepted
- Date: 2026-08-25
- Decision owners: Identity Security, Financial Controls, Platform Architecture
- Scope: Central-policy audit calls in production route, platform, workflow, worker, Studio, and export code

## Context

ReconForge already attached deterministic context and typed-scope digests to
`PolicyDecision`. `audit_policy_decision` could also verify those digests when
given the exact `PolicyEvaluationContext`, but production callers generally
passed only the decision. That produced a valid digest artifact while leaving
the audit boundary unable to prove that the caller supplied the same context it
had evaluated.

This distinction matters for tenant/workspace/entity isolation, amount-bounded
ABAC, maker-checker history, worker lanes, exports, and privileged Studio/API
actions. A central engine alone does not establish that its result was logged
against the exact input used at the caller boundary.

## Decision

1. Every production call to `audit_policy_decision` must pass the exact
   `PolicyEvaluationContext` object used for the corresponding policy
   evaluation.
2. API dependencies, local platform authorization, workflow transitions,
   durable-job claims, hosted worker guards, Studio checks, and PostgreSQL
   scoped exports now retain and pass that context to the audit builder.
3. A repository AST regression rejects any future production audit call that
   omits the `context=` keyword. Compatibility tests may still exercise the
   no-context historical builder path outside production code.
4. The existing authorization decisions, reason codes, log fields, and
   schema-v1 evidence shape remain unchanged; the improvement is provenance
   enforcement at the production call boundary.

## Security and correctness consequences

- Audit construction now fails closed if a caller tries to pair a decision with
  a different context, using the guard recorded in ADR 0625.
- Production audit records are bound to the exact identity, hierarchy,
  permissions, amount, step-up, ownership, and SoD inputs used by the policy
  check, subject to what each caller actually populated.
- The AST gate detects source-level omission but does not prove runtime
  authenticity of a principal, correctness of every context value, durable
  append-only storage, external IAM equivalence, or distributed invalidation.

## Compatibility and rollback

Authorization behavior and public schemas are unchanged. Roll back the caller
context plumbing, AST regression, tests, and this execution record together if
a supported compatibility surface cannot retain its evaluated context; that
surface must then be explicitly classified as legacy/unbound rather than
silently treated as fully bound evidence.

## Verification

- The production audit inventory contains no `audit_policy_decision` call
  without `context=` outside the defining module.
- The focused policy/API/worker/workflow/Studio collection passes `154` tests.
- The full Python 3.12 regression passes with `3,204` collected tests; Ruff,
  Mypy, and diff checks pass.
