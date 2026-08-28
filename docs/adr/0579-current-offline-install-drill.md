# ADR 0579: Current offline installation drill

## Status

Accepted — 2026-08-23

## Decision

Run `verify_airgap_install.py --base-install-only` with the digest-pinned
`python:3.14.1-slim` image. The run must build a wheel-only locked bundle,
install with `pip --no-index --no-deps --require-hashes` inside a `--network
none`, read-only container, run `reconforge doctor`, and clean the container.

## Limits

This current evidence covers base offline installation only. It does not prove
offline signature trust, local identity recovery, backup/restore, upgrade or
rollback, physical air-gap isolation, or production readiness.
