# P3-EXT-001: Controlled Pilot Evidence Template (3–5 pilots)

Status: optional assurance template; deferred by owner decision E-251

## Purpose

Use this file format only if optional `P3-EXT-001` assurance is resumed.
Each record must be bounded to scoped, authorized access and synthetic/real business
evidence without exposing secrets, customer identifiers, or unrestricted raw records.

## Pilot Metadata

- Pilot ID:
- Organization (name or pseudonymized identifier):
- Environment (staging/prod-like/tenant boundary):
- Approval artifact reference (written authorization):
- Start date:
- End date:
- Operator/Contact:
- Platform version:
- Branch/commit hash:
- Evidence owner:

## Scope and Data

- Data class authorization checked (yes/no):
- Data source(s):
- Number of records:
- Dataset boundary (dates/entities/workflows):
- Integration surfaces used:

## Workflow Executed

- Scenario(s) executed:
- Manual steps (high-level):
- Failure handling steps:
- Recovery steps:

## Outcomes

- Successful outcomes (quantified):
- Failures/edge cases encountered:
- Mitigations applied:
- Residual risks:
- Business/user feedback summary:

## Quantified Financial/Control Evidence

- Reconciliation outcomes:
- Exceptions generated (count/type):
- Reproducibility command(s) or report(s) generated:
- Determinism evidence artifact path(s):
- Audit artifacts linked:

## Public-facing wording

- What can be published:
- What must remain internal:

## Reviewer and approval

- Reviewer name/title:
- Review date:
- Approval status:
- Any conditions:

## Completion check (before attaching to `P3_EXT-001`)

- This pilot includes a real environment and authorization trail.
- The outcome report references bounded internal artifacts in `docs/execution/`.
- No unsupported production/compliance/enterprise-grade claims are included.
