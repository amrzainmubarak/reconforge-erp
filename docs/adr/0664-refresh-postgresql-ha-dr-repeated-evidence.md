# ADR 0664: Refresh bounded PostgreSQL HA/DR repeated evidence

- Status: Accepted
- Date: 2026-08-26
- Owners: Platform / SRE

## Context

The repository had older repeated PostgreSQL HA/DR reports. The current
environment provides Docker Engine and the existing drill is designed to run
three disposable primary/synchronous-standby cycles with encrypted isolated
restore, fencing, manual failover/failback, sentinel replay, and strict
labelled-resource cleanup.

## Decision

Run the existing verifier exactly three times through
`verify_postgres_ha_dr_repeated.py`, store the schema-valid current report,
package it in the source distribution manifest, and reference it in the
mode-specific readiness matrix as bounded failure-domain context. Do not
promote Team, Enterprise, or Regulated readiness from this artifact.

## Evidence and boundaries

The 2026-08-26 run completed 3/3 cycles with zero acknowledged transaction
loss, final sequence `4`, failover RTO max `11.721s`, failback RTO max
`1.316s`, and cleanup passed for every run. It used Docker Engine `29.7.2`,
PostgreSQL `17.10-alpine`, two nodes per run, one host/failure domain, a
manual controller, and synthetic data/key material. It does not prove
independent failure domains, quorum/witness, automatic failover, site loss,
production SLOs, customer-managed key custody, Enterprise readiness, or
Regulated readiness.

## Rollback

Remove the current report and its manifest/matrix/test/evidence references.
The verifier's temporary labelled containers, volumes, and networks were
already confirmed absent after the run; no production or customer data was
used.
