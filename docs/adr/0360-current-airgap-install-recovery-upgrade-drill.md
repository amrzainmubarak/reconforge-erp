# ADR 0360: Retain the current no-network sovereign deployment drill

- **Status:** Accepted
- **Date:** 2026-08-05
- **Decision:** Retain a fresh Docker execution that assembles a locked
  dependency mirror, installs ReconForge 0.7.1 with network mode `none`,
  read-only root/bundle mounts and bounded tmpfs, restores two local users from
  an encrypted backup, rejects a wrong key atomically, excludes old sessions,
  and cuts over from the tagged 0.7.0 wheel to 0.7.1 before exact rollback.
- **Evidence:** The current report records 68 bundle entries, 100,386,256
  bytes, manifest digest
  `4be42566f0caba894140275186e9c679c6fbcc7c589c6c71cc8e33cafae94e99`,
  doctor success, identity recovery, zero network inputs, and exact rollback.
- **Boundary:** Bundle assembly was connected; this is one Linux/Python runtime
  and one run. It does not prove signature trust, physical air-gap custody,
  OCI offline verification, hardware-backed keys, multi-platform repetition,
  HA/DR, or production readiness.
- **Rollback:** Remove the dated report/schema/test pointer and retain the
  prior 2026-07-30 artifacts as historical evidence.
