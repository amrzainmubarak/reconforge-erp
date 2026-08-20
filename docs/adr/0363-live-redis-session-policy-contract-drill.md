# ADR 0363: Retain the live Redis session and policy contract drill

- **Status:** Accepted
- **Date:** 2026-08-05
- **Decision:** Retain a fresh disposable Redis execution of the real
  tenant-scoped session/revocation store and shared policy-generation store.
  The drill proves tenant-key isolation, digest-only session persistence,
  cross-client generation visibility, and cleanup.
- **Verification:** Redis image digest
  `sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2`,
  endpoint `redis://127.0.0.1:16379`, four invariants true, and report digest
  `99fbd6b7aba969e0a41f4faa9e26d034e5e0f3b5a36e0e4e22bb2928ed9b44ca`.
- **Boundary:** One disposable single-node Redis process with synthetic keys
  and metadata. No replication, Sentinel/Cluster failover, cross-site
  durability, Redis HA, or production SLO is proven.
- **Rollback:** Remove the dated report, verifier, and focused report test;
  retain the existing provider-neutral Redis contracts and CI service test.
