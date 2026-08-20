# ADR 0515: Record the locked all-extras collection closure

## Context

Historical CI runs failed during collection because optional packages used by
observability, signing, upgrade, and WebAuthn tests were not installed in the
Python matrix.

## Decision

Keep the workflow contract on `uv sync --locked --all-extras --no-editable` and
record a local reproduction using the same locked profile on Python 3.11 and
3.12. Verify the previously failing optional imports and collect the seven
historical failure-surface test modules under both interpreters.

## Consequences

The local environment now proves dependency resolution and collection for the
known failure surfaces, with only the declared live-PostgreSQL WebAuthn skip.
This does not substitute for a fresh hosted matrix run, native backup/restore,
security attestation, or release approval.

## Rollback

Remove the E-704 evidence/ADR record only; do not weaken the locked all-extras
workflow requirement.
