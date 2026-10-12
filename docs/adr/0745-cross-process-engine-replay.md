# ADR 0745: Prove cross-process engine replay stability

- Status: Accepted
- Date: 2026-08-28
- Decision owners: matching and data-integrity maintainers

## Context

Same-process permutation tests can miss behavior that depends on interpreter
hash randomization, process initialization, or serialization boundaries. The
matching evidence package requires reproducible results, but its existing
engine parity tests did not make fresh-process replay an explicit contract for
the Pandas and partitioned DuckDB paths.

## Decision

Add a focused regression that generates a bounded 500-record synthetic input,
launches each supported local engine in fresh child processes, and executes
each engine under two distinct `PYTHONHASHSEED` values. Force the DuckDB child
through its partitioned path so the test covers the execution mode most likely
to expose partition ordering differences. Compare a closed JSON envelope that
includes result counts, summary rows, financial and matching policies, record
identity policy, reconciliation signature, and signature version. Require
both per-engine replay equality and cross-engine equality for the declared
profile.

## Consequences and boundaries

The test makes process-level determinism and cross-engine result equivalence
visible in the local regression suite. It does not replace the supported
Python/dependency matrix, hosted CI, live PostgreSQL/provider execution,
capacity or soak work, or independent production assurance. The profile is
synthetic and bounded; it is evidence for the exact paths and inputs exercised
by the test, not a universal performance or compatibility claim.

## Verification and rollback

`python -m pytest tests/test_engine_process_replay.py -q --tb=short` must pass
with DuckDB installed; the test is explicitly skipped when that optional
dependency is unavailable. Existing engine parity, matching-property, and
full regression gates remain required. Rollback is a source-level revert of
the test, execution records, manifest entry, and this ADR; no database
migration or persisted-data change is involved.
