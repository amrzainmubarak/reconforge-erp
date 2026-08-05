# ADR 0361: Retain the live S3-compatible object-storage contract drill

- **Status:** Accepted
- **Date:** 2026-08-05
- **Decision:** Retain a fresh disposable MinIO execution of the real
  boto3-backed object-store adapter. The drill creates normal and Object Lock
  buckets, proves tenant/workspace/entity key isolation, rejects immutable
  overwrite, detects checksum tampering, refuses deletion during retention,
  and cleans every synthetic object.
- **Verification:** MinIO image digest
  `sha256:13582eff79c6605a2d315bdd0e70164142ea7e98fc8411e9e10d089502a6d883`,
  endpoint `http://127.0.0.1:19000`, all five invariants true, report digest
  `5f4ef103abfe4b198bc64e348f554dc52e56d3ebb5d7f425faf1761ce6225c6a`.
- **Boundary:** One disposable single-node MinIO process, synthetic
  credentials/bytes, no replication, KMS, cross-site durability, provider
  interoperability, object-store HA/DR, malware scanning, or production SLO.
- **Rollback:** Remove the dated report and focused test, retaining the
  provider-neutral contract and the prior hosted evidence boundary.
