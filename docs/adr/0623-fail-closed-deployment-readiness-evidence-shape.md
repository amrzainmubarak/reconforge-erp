# ADR 0623: Require evidence and boundaries for deployment-readiness statuses

- Status: Accepted
- Date: 2026-08-25
- Decision owners: Platform Architecture, SRE, Security Governance
- Scope: Offline deployment-readiness matrix and runtime-evidence identity

## Context

The deployment-readiness matrix is intentionally descriptive and does not claim
production readiness. It still controls the wording operators see for four
editions and eight gates. Before this decision, the closed reader validated the
field names, edition/gate identities, status vocabulary, and evidence path
containment, but it could accept a `verified_scoped` gate with no evidence path
or an unresolved gate with an empty boundary explanation. It also retained the
operator's casing/whitespace for a runtime evidence edition even though the
profile lookup used a normalized edition.

Those shapes make a future evidence review ambiguous and can produce different
artifact identities for semantically equivalent profile selections.

## Decision

1. Every readiness gate must carry a non-empty boundary string, including
   `verified_scoped`, `partial`, and `open` gates.
2. A `verified_scoped` gate must list at least one repository-relative regular
   file. `partial` and `open` gates may have no evidence, but their boundary
   remains mandatory and explicit.
3. The reader continues to reject a readiness status of `verified`; no matrix
   file alone can close an edition or create a production/regulated claim.
4. Runtime evidence canonicalizes the selected edition through the immutable
   profile (`team`, not the caller's surrounding whitespace/casing) before
   constructing its digest-bound artifact. The profile digest must still match
   the selected canonical profile.

## Consequences and boundaries

- Missing evidence or missing claim boundaries fail before path resolution or
  operator output.
- Equivalent edition presentation cannot create two runtime artifact identities.
- The matrix remains an offline evidence contract; it does not probe services,
  provision IAM, verify KMS/HSM, establish RPO/RTO, or prove production
  effectiveness.
- Actual backup/restore, rollback, retention, identity, failure-domain, and
  provider drills remain required by E-1006 and are not inferred from this
  schema guard.

## Compatibility and rollback

The change is fail-closed validation only. Existing repository matrices already
contain boundaries and evidence for every `verified_scoped` gate, so their
canonical output remains valid. Roll back the reader, runtime canonicalization,
tests, ADR, and execution records together; do not relax the evidence contract
while retaining readiness wording.

## Verification

- `tests/test_deployment_readiness_matrix.py` covers empty evidence on a
  verified gate and empty boundary on unresolved gates.
- `tests/test_deployment_runtime_evidence.py` covers edition canonicalization.
- Deployment readiness, profile, runtime-evidence, and regulated-admission
  focused tests pass; Ruff and Mypy pass for the deployment package.
