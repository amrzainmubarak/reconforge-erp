# ADR 0332: Expose signed package admission through a read-only CLI

## Status

Accepted — 2026-08-04

## Context

The signed connector package admission contract is available as a Python
boundary, but operators need a reproducible local verification path that does
not require a web service or package installation.

## Decision

Add `reconforge connectors verify-package` with an explicit package path,
publisher ID, key ID, and base64 raw Ed25519 public key. The command invokes
the existing trust-plus-conformance admission helper and emits only the
digest-bound admission record. Invalid keys, signatures, trust, or manifest
conformance return a non-zero exit code. The command never imports package
code, makes network calls, or mutates the package.

## Consequences

The owner/team can reproduce signed-package admission locally and retain the
JSON result as evidence. This is an operator verification surface, not a
marketplace installer, provider connector, or write-back authorization.

## Rollback

Disable the CLI command while retaining the library and package evidence; no
stored package or trust registry is deleted.
