# ADR 0564: Verify deployment readiness evidence through the CLI

- Status: Accepted
- Date: 2026-08-23
- Decision owners: Deployment Governance / Platform Security

## Context

The mode-specific readiness matrix is schema-validated and path-bound, but a
reviewer still needed to open YAML manually. A raw YAML load in the CLI would
also bypass the repository's bounded structured-document policy and could
silently accept path traversal or contract expansion.

## Decision

Add `reconforge deployment readiness [--edition EDITION]`. It reads the matrix
through the centralized bounded safe-YAML ingress, validates its closed
identity/status/gate contract, verifies every evidence path remains inside the
repository and resolves to a regular file, computes a canonical digest, and
prints the selected edition(s). The command performs no network, secret,
database, IAM, or filesystem mutation.

Unknown editions, missing files, expanded fields, duplicate gates, unsupported
statuses, and escaping evidence paths fail closed.

## Consequences

- Reviewers receive a repeatable digest and a single command for evidence
  inspection.
- The command consumes evidence; it does not upgrade partial/open statuses or
  make a readiness claim.
- Future admission systems can bind to the digest without treating the local
  matrix as external runtime proof.
