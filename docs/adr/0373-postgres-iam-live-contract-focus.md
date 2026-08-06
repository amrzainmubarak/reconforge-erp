# ADR 0373: Retain the current PostgreSQL IAM contract focus

- **Date**: 2026-08-06
- **Status**: Accepted
- **Decision**: Promote the isolated current PostgreSQL runtime focus for
  access administration, identity administration, security governance,
  delegation, policy analysis, service accounts, and privileged sessions as
  bounded evidence, while retaining the broader federation/UI/distributed IAM
  limits.
- **Verification**: A fresh database migrated through `0065_pg_deferred_tax`
  and exercised with the non-privileged `reconforge_app` role passed 23/23
  selected live contracts in 19.1s. Tenant isolation, lifecycle transitions,
  policy scope, service identity, and privileged-session controls remained
  enforced.
- **Boundary**: One local PostgreSQL 17.10 host and synthetic identities only;
  no hosted attestation, provider federation interoperability, complete UI/job/
  export coverage, distributed invalidation, HA/DR, or production IAM claim.
- **Rollback**: Remove the evidence entry and this ADR; no runtime or data
  rollback is required.
