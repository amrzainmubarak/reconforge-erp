# ADR 0626: Align the deployment-readiness reader with its JSON Schema

- Status: Accepted
- Date: 2026-08-25
- Decision owners: Platform Architecture, DevSecOps, Financial Controls
- Scope: Offline deployment-readiness matrix v1 parser and schema

## Context

The deployment-readiness matrix has both a closed Python reader and a
Draft 2020-12 JSON Schema. The reader already enforced repository-relative
evidence paths, edition/gate identity, and fail-closed readiness statuses, but
several scalar constraints were not equivalent between the two contracts:

- Python treats `True` as equal to integer `1` unless booleans are excluded.
- The reader did not validate the ISO calendar date in `reviewed_on`.
- The reader did not enforce the schema's minimum `claim_boundary` length.
- Any profile command was accepted, even if it named another or no edition.
- The schema allowed short or all-whitespace gate boundaries that the reader
  did not accept.

This drift makes validation dependent on which entry point an operator uses
and weakens the claim that a matrix is one closed, reviewable artifact.

## Decision

1. The reader rejects boolean or non-integer schema versions, validates
   `reviewed_on` as a canonical `YYYY-MM-DD` calendar date, and requires a
   claim boundary of at least 80 characters.
2. Each edition must carry exactly
   `reconforge deployment profiles --edition <edition-id>` as its profile
   command.
3. Each gate boundary must contain at least 20 characters and at least one
   non-whitespace character.
4. The v1 JSON Schema expresses the same profile-command and non-whitespace
   boundary constraints. Existing matrix content remains valid.
5. Runtime path containment and existence checks remain intentionally stronger
   than the generic JSON Schema because evidence files are repository-bound
   runtime inputs, not merely shape fields.

## Security and correctness consequences

- YAML, JSON Schema, and CLI-backed local validation reject the same malformed
  scalar matrix cases instead of producing validator-dependent outcomes.
- A profile command cannot silently describe a different edition, and a
  readiness claim cannot be represented by a blank or underspecified boundary.
- This is offline contract integrity only. It does not prove that evidence is
  current, that deployment drills ran, or that external IAM, KMS/HSM,
  databases, queues, providers, or failure domains are available or enforced.

## Compatibility and rollback

The checked-in v1 matrix satisfies the tightened constraints; no valid current
artifact or public output version changes. Roll back the reader/schema/test
changes together if a supported external matrix intentionally relied on a
looser scalar shape; such a matrix must then receive a versioned migration
rather than silently bypassing the closed contract.

## Verification

- `tests/test_deployment_readiness_matrix.py` validates the checked-in matrix
  and proves schema/reader rejection parity for each tightened scalar case.
- The deployment readiness/runtime/profile/admission collection passes 36/36;
  Ruff and Mypy pass for the changed reader.
