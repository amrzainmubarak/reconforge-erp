# ADR 0447: Pin the hosted PostgreSQL native-tool bootstrap contract

## Context

The PostgreSQL backup/restore adapter depends on native `pg_dump`,
`pg_restore`, `createdb`, `dropdb`, and `psql` binaries. A hosted runner may
have PostgreSQL libraries or wrapper commands without the complete versioned
client tool set, so dependency installation alone is insufficient evidence
for the server-boundary backup gate.

## Decision

The `server-boundaries` workflow installs the distribution
`postgresql-client` package before locked Python dependencies and live tests.
It resolves the PostgreSQL client bindir through `pg_config --bindir` and
fails closed unless all five required native tools are executable there. A
repository contract test protects the ordering, package install, and exact
tool checks from workflow drift.

## Evidence and boundary

`tests/test_phase4_execution_contract.py` proves the workflow contract
locally. A fresh hosted `server-boundaries` run is still required to prove
encrypted backup/isolated restore execution; this ADR does not claim hosted
tool availability, HA/DR, RPO/RTO, or production readiness by itself.
