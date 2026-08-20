# ADR 0371: Retain the current live Redis contract drill

- **Date**: 2026-08-06
- **Status**: Accepted
- **Decision**: Commit the current disposable Redis runtime report beside the
  prior artifact and validate both reports against the closed schema and digest
  contract.
- **Verification**: `verify_redis_live.py` passed against the local
  `redis:7-alpine` image digest
  `sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99`.
  Tenant-key isolation, hashed-session-token storage, shared policy generation,
  and cleanup were all observed. Report digest:
  `f1c2d7ac3f08c8d49564e92461e13836c5e1d869e7fa877ad2cfa8ece1f59816`.
- **Boundary**: This is single-node synthetic adapter evidence only. It does
  not prove Redis replication, Sentinel/Cluster failover, cross-site durability,
  HA, production SLOs, or hosted release readiness.
- **Rollback**: Remove the dated report and its test assertion; no runtime or
  persistent-data rollback is required.
