# ADR 0580: Current air-gapped recovery and upgrade rollback drill

## Status

Accepted — 2026-08-23

## Decision

Run `verify_airgap_install.py` without `--base-install-only`, including local
identity recovery and the exact tagged `0.7.0 -> 0.7.1` wheel cutover/rollback
inside the same `network=none`, read-only Docker boundary. Retain the closed
current report with encrypted-backup, wrong-key, audit-chain, no-network,
rollback-digest, and cleanup observations.

## Limits

This is one Linux runtime on one Docker host. It does not establish offline
signature trust, hardware-backed key custody, physical air-gap custody, OCI
verification, multi-node recovery, or production readiness.
