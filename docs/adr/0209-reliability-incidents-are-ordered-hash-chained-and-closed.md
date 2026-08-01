# ADR 0209: Reliability incidents are ordered, hash-chained, and schema-closed

- Status: Accepted
- Date: 2026-07-30

## Context

Alert emission alone does not prove that an operator acknowledged a condition,
followed the bound runbook, verified recovery, or recorded residual risk. Free-form
incident text can also leak credentials, tenant identifiers, or financial rows.

## Decision

The bounded reliability profile records five monotonic states: `detected`,
`acknowledged`, `mitigating`, `recovered`, and `closed`. Transitions cannot be
skipped or reversed. Recovery requires a complete evaluation in which every
required reliability signal is present and `normal`.

Incident identity, operator references, action codes, policy/runbook bindings,
and correlation identifiers use a restrictive identifier alphabet. Evidence is
referenced only by SHA-256 digest. Each event commits to the prior event digest,
and the final manifest has a deterministic digest. The model accepts no arbitrary
commands, raw logs, reasons, financial values, credentials, or customer data.

The synthetic exercise uses separate operator references for mitigation and
recovery validation. This is maker-checker-like drill evidence, not proof of real
staff separation or an external pager acknowledgement.

## Consequences

- Missing or non-normal recovery signals fail closed.
- Retained incident manifests are tamper-evident but are not digital signatures,
  legal records, durable WORM storage, or external assurance.
- Real deployments still need an approved incident platform, retention policy,
  alert routing, on-call ownership, and exercises on independent infrastructure.

## Rollback

Remove the optional incident module and its drill artifacts. No database, API,
CLI, financial schema, or existing telemetry contract is changed.
