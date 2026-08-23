# ADR 0561: Expose worker permission manifest verification through the CLI

- Status: Accepted
- Date: 2026-08-23
- Decision owners: Platform Security / Deployment Governance

## Context

The hosted deployment profile gate requires evidence that reconciliation worker
discovery and execution permissions are separated. E-846 already provided a
pure, offline verifier, but operators could only reach it through Python APIs.
That made the evidence path harder to reproduce and left the normal CLI
surface without a safe inspection command.

## Decision

Add `reconforge deployment verify-worker-manifest MANIFEST.json`. The command
reads one operator-selected JSON file, invokes the strict closed-contract
verifier, and prints the canonical manifest plus SHA-256 digest. Parse and
validation failures return a safe CLI error and non-zero exit status. The
command is deliberately network-free and performs no IAM provisioning,
mutation, or hosted-runtime inspection.

The repository file-ingestion inventory records the direct `json.loads` call
and its bounded FI-041 surface so the AST allowlist remains exact.

## Consequences

- Local operators and CI can reproduce the same manifest digest used as
  deployment evidence.
- Invalid, ambiguous, or over-broad manifests fail closed before any deployment
  action is attempted.
- The command does not prove that a provider, identity system, or production
  worker actually enforces the manifest; that remains a separate runtime gate.

## Verification

- `tests/test_deployment_profiles.py` covers valid output and invalid closed
  contracts.
- `tests/test_worker_permission_manifest.py` covers the verifier invariants.
- `tests/test_file_ingestion_inventory.py` enforces the exact parser allowlist.
