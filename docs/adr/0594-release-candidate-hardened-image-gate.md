# ADR 0594: Gate release candidates on hardened image execution

## Status

Accepted — 2026-08-23

## Decision

The signed release-candidate workflow must execute the exact image that was
scanned, before registry publication, with a read-only root filesystem, all
Linux capabilities dropped, and `no-new-privileges`. The command runs
`reconforge doctor`; failures stop the candidate before login/push and before
any attestation is created.

## Boundary

This is a hosted Linux runner smoke for the candidate image. It does not prove
multi-architecture behavior, host isolation, seccomp completeness, registry
availability, or production orchestration.

## Rollback

Remove the release step and this ADR. No runtime, schema, or data migration is
involved.
