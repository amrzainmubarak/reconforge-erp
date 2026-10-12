# ADR 0668: Current Community Compose head and backup/restore runtime evidence

- Status: Accepted
- Date: 2026-08-26
- Owners: Platform / DevSecOps / SRE

## Context

E-973 advanced the local SQLite migration head to 46, but the latest checked
runtime evidence for the Community Compose profile was historical schema 45/45.
The readiness matrix needed current-head proof that the hardened local service
still starts, survives restart, and can verify and restore its local database.
The host environment reserved the Compose profile's loopback port, so relying
on host-port reachability would have produced incomplete evidence.

## Decision

Build the current Community image and run a labelled disposable Compose service
without host-port publication. Verify the same health endpoint from inside the
container, observe the non-root/read-only/capability-dropped/internal-network
contract, register only synthetic evidence, verify a checksum manifest, and
restore to an independent SQLite target. Bind all observations to the current
image digest and a closed JSON schema/digest report.

## Verification and boundaries

E-974 passed after restart at SQLite schema `46/46`; API health was `ok`, UID
was `10001:10001`, and the runtime hardening attributes were observed. Backup
verification and independent restore passed at schema 46 with 113 tables, and
the restored database retained one synthetic evidence row with retention
version 1.

The evidence is one Docker Desktop host with synthetic data and local plaintext
backup files. It does not prove host-loss recovery, independent failure
domains, encrypted production-key custody, external identity/provider
interoperability, production SLOs, or compliance. Host-port reachability is an
environment limitation and is not counted.

## Rollback

Remove the E-974 report, schema, test, manifest/matrix references, and execution
entries. The disposable labelled container and volume are removed after the
report is captured. No application or production database is modified.
