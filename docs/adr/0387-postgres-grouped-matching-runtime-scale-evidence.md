# ADR 0387: PostgreSQL grouped-matching runtime and scale evidence

- **Date:** 2026-08-06
- **Status:** Accepted
- **Scope:** Evidence-only follow-up for P4-MAT-001

## Context

The grouped matching worker already had a PostgreSQL adapter, tenant-scoped
repository contract, checkpoint recovery path, and bounded scale profiles.
Most local runs skipped the live PostgreSQL cells when no DSN was configured.
That absence made the available worker path weaker evidence than the code
contract warranted.

## Decision

Run the existing live contracts against a local PostgreSQL service using a
non-superuser, non-BYPASSRLS application role. Record the results as a bounded
runtime/scale evidence slice without changing the matching algorithm, database
schema, public API, or published capacity claims. The evidence covers group
lineage, tenant isolation, crash/resume without duplicate partitions, the
declared 500-partition profile, and the declared 10,000-partition profile.

The scale result remains synthetic and single-host. Passing the profiles does
not establish production throughput, distributed capacity, cross-host failure
recovery, soak behavior, SLOs, or a complete P4-MAT-001 exit.

## Verification

The focused live runtime suite passed 2/2. The 500-partition and 10,000-
partition profile tests passed 1/1 each. All data was synthetic and confined to
the local PostgreSQL service; no external provider or customer data was used.

## Reversibility

This ADR adds no runtime behavior or migration. Removing the ADR and evidence
entry fully reverts the documentation-only slice.
