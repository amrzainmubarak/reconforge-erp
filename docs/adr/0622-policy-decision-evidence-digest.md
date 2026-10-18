# ADR 0622: Bind central authorization decisions to redacted policy evidence

- Status: Accepted
- Date: 2026-08-25
- Decision owners: Identity Security, Financial Controls, Platform Architecture
- Scope: Central RBAC/ABAC/SoD decision logging and replay-oriented local evidence

## Context

ReconForge already evaluates permission contracts, resource scopes, amount
bounds, step-up requirements, ownership, and separation of duties through
`CentralPolicyEngine`. The structured authorization log retained a policy
version, actor digest, permission-contract digest, reason code, and request
correlation value, but it did not bind the record to the complete policy input
snapshot. A later reviewer could not distinguish two decisions with the same
reason code when their tenant, workspace, period, field, amount, delegated
authority, or prior-action context differed.

The missing binding must not put raw tenant identifiers, actor identities,
financial amounts, object IDs, or permission names into logs. It must also
avoid changing authorization semantics as a side effect of improving evidence.

## Decision

1. Every result produced by `CentralPolicyEngine.evaluate` and
   `evaluate_any` carries a deterministic `context_digest` and typed
   `scope_digest`. The context digest includes the permission snapshot, exact
   Decimal amount/bounds, step-up state, object/ownership context, delegation,
   requested fields, and normalized SoD history. The scope digest separates
   tenant, organization, workspace, entity, period, region, and data-class
   namespaces before hashing them.
2. `build_policy_decision_evidence` emits a closed schema-v1 artifact with
   actor, permission contract, granted permission, surface, request,
   context-binding, scope, decision status, reason code, policy version, and
   evaluator digests. Only digests and bounded classifications are emitted;
   raw identifiers, amounts, and permission names are not.
3. `verify_policy_decision_evidence` rejects unknown/missing fields, invalid
   digest shapes, unsupported schema/policy versions, and any digest mutation.
   The artifact is evidence input, not an authorization grant, signature, or
   durable tamper-proof audit store.
4. `audit_policy_decision` keeps the existing
   `permission_contract_digest` and redacted log fields for compatibility, and
   adds the closed decision evidence and its digest. Existing callers do not
   need to change their authorization behavior.
5. Actor presentation is normalized with the existing trim/case-fold policy
   before actor and ownership digests. Scope values are not silently
   case-folded for authorization; their typed namespaces are preserved in the
   digest so a future canonical scope policy cannot be implied by logging.

## Security and correctness consequences

- Identical policy inputs, policy version, and audit metadata reproduce the
  same decision evidence digest.
- Swapping the same textual ID between tenant and workspace namespaces changes
  the scope digest.
- Evidence verification detects post-write mutation without exposing the
  original sensitive values.
- This does not prove that every caller supplied an authenticated principal,
  that a provider/IAM system enforced the same grants, that the log sink is
  append-only, or that deployed operations retain the evidence durably.

## Compatibility and rollback

The change is additive to `PolicyDecision` and the structured logger. Existing
authorization reason codes, permission checks, route contracts, and public API
schemas remain unchanged. Roll back the policy evidence helpers, decision
fields, tests, and execution records together. Do not remove the existing
redacted fields before downstream log readers migrate to the additive schema.

## Verification

- `tests/test_policy_engine.py` verifies replay stability, closed-schema
  validation, mutation refusal, scope namespace separation, actor
  canonicalization, and raw-value redaction.
- Existing policy/cache suites remain green; Ruff and Mypy pass for the policy
  implementation.
