# ADR 0266: Consolidation certification attaches to posted runs

- **Status:** Accepted
- **Date:** 2026-08-03

## Decision

Expose local certification workflow for `consolidation_close_run` through the
consolidation-close API. Preparation is allowed only after a run is `Posted`
or `Reversed`; review uses a distinct permission and actor; every read first
replay-validates the run and then returns the immutable certification record.

## Boundary

The record is workflow metadata for internal control review. It is not a legal
signature, statutory certification, audit opinion, compliance assertion, or
source-ERP posting.

## Reversibility

The repository methods and routes are additive. Removing them leaves existing
close run transitions and historical certification APIs unchanged.
