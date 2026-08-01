# Phase 3 Optional External Assurance Index

Status: deferred by owner decision E-251; not release-blocking

This index preserves the optional evidence paths and historical records. It does
not impose a requirement to recruit accountants, engineers, external operators,
customers, or an independent reviewer for owner/team publication.

## P3-EXT-001 — Optional controlled pilots

- Status: `deferred`
- Release requirement: `optional_assurance`
- Accepted external operator records: `0`
- Existing internal evidence:
  - [Public financial evidence protocol](../validation/public-financial-evidence.md)
  - [Retained owner/team live run](./PUBLIC_FINANCIAL_EVIDENCE_RUN_2026-08-01.json)
    (`passed`, 967/967 matched, not external)
  - [Pilot-001](./P3_EXT_001_PILOT_001.md)
  - [Pilot-002](./P3_EXT_001_PILOT_002.md)
  - [Pilot-003](./P3_EXT_001_PILOT_003.md)
- Optional future path:
  - [Operator attestation template](./P3_EXT_001_OPEN_SOURCE_OPERATOR_ATTESTATION_TEMPLATE.md)
  - Manual SHA-pinned workflow: `.github/workflows/public-financial-evidence.yml`
  - If resumed, three accepted independent records are required before making an
    external-pilot claim. Owner/team runs cannot be relabeled as external.

## P3-EXT-002 — Optional independent security review

- Status: `deferred`
- Release requirement: `optional_assurance`
- Independent reports: `0`
- Existing automated and team evidence remains technical input only.
- Optional future path:
  - [Review report](./P3_EXT_002_REVIEW_REPORT.md)
  - [Review template](./P3_EXT_002_INDEPENDENT_SECURITY_REVIEW_TEMPLATE.md)
  - [Private intake protocol](../security/open-source-independent-review-protocol.md)
  - If resumed, the exact reviewer, scope, findings, remediation, retest, and
    residual-risk evidence must exist before making an independent-review claim.

## Integrity rules

- Deferred does not mean verified.
- Internal/team evidence does not become external evidence by renaming it.
- Optional assurance artifacts must remain non-simulated if later claimed.
- Known Critical/High findings remain subject to the normal release policy even
  when no independent review is commissioned.
- Current owner/team publication readiness is governed by
  `PHASE_1_3_PUBLICATION_READINESS.md`, not by completion of this optional index.
