# ADR 0279: Read-only enterprise policy conflict analysis

## Status

Accepted for the current Phase 4 IAM slice.

## Decision

ReconForge adds `enterprise-policy-conflict-analysis-v1` as a pure,
versioned analysis artifact.  An approved policy snapshot contains tenant-bound
grants, principal type, role identity, permission sets, optional workspace and
resource dimensions, and a declared requirement for scoped privileged grants.
Grant order is canonicalized by stable grant ID.

The analyzer reports deterministic findings for:

- overlapping prepare/review/submit/approve permissions for one principal;
- human-governed permissions held by a service account;
- privileged permissions without a workspace or bounded resource scope when
  the snapshot requires scoped privilege; and
- duplicate active grants over overlapping scopes.

Each finding carries a stable digest, severity, grant IDs, permission names,
scope digests, and a bounded explanation.  The artifact is replay-verifiable
and maker/checker attributed through the request snapshot.  The CLI consumes
the shared bounded JSON reader and is strictly read-only.

## Explicit boundary

The analyzer never mutates authorization state and is not itself an
enforcement or approval path.  It does not replace CentralPolicyEngine,
PostgreSQL/RLS policy storage, OIDC/SAML/SCIM federation, emergency access,
distributed cache invalidation, route/job/export/UI migration, or independent
security assurance.  Wildcard dimensions are explicit policy inputs; no
unstated global-scope exception is inferred.

## Verification

- `tests/test_policy_analysis.py` covers SoD overlap, service-account misuse,
  privileged-scope findings, revoked/disjoint grants, permutation stability,
  maker-checker, tamper/schema validation, and the read-only CLI.
- `docs/schemas/enterprise_policy_conflict_analysis_v1.schema.json` is the
  closed result schema.
- `platform.core` exports the versioned analysis contract through the module
  registry and the threat/file-ingestion inventories bind the test evidence.
