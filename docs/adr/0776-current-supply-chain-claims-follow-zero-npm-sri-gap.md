# ADR 0776: Bind current supply-chain claims to the zero npm SRI-gap result

- Status: Accepted
- Date: 2026-08-29
- Owners: Supply Chain / Documentation / Release Engineering

## Context

The current `supply-chain-policy.v1.json` and validator report 211 npm registry
entries with zero missing integrity pairs. Several current-facing documents
still repeated the historical 155-entry gap from an earlier lock revision.
That contradiction weakens release truth and can cause operators to prioritize
a closed local control while overlooking the still-open hosted provenance and
external package-assurance boundaries.

## Decision

Update current gap, whitepaper, and documentation-drift surfaces to state the
verified local zero-gap result and preserve the distinction between local SRI
metadata, hosted audit enforcement, package provenance, reachability, license
suitability, and external assurance. Historical execution records remain
unchanged and are treated as dated evidence for their earlier revisions.

Add a regression contract that executes the current policy validator and
rejects the retired current-surface wording. Future lock changes must update
the machine-counted policy and current documentation together.

## Consequences and rollback

Current documentation becomes consistent with the checked-in lock and policy
validator without expanding the local evidence into a package-safety or
provenance claim. Rollback is a documentation/test/manifest/ADR revert; no
dependency or runtime behavior changes.
