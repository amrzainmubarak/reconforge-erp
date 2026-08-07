# ADR 0441: Targeted source mutation campaign for grouped matching

- Status: accepted
- Date: 2026-08-07
- Scope: `P4-MAT-001`, `grouped_matching.source_mutation`

## Decision

Add a small dependency-free source-mutation harness for the public grouped
matching domain module. It copies only the target module into a disposable
child package and runs a closed three-case contract against three explicit
mutants: disabling partial settlement, changing the date-window boundary, and
removing absolute-difference handling. The baseline contract must pass, and
each mutated child must fail; no production source is modified.

## Evidence boundary

The campaign reports a targeted 3/3 kill result for the declared mutation set.
It is not a domain-wide mutation score, does not replace Hypothesis/fault
testing, and does not establish PostgreSQL parity, distributed failures,
live-rate validity, or production performance.

## Rollback

Remove `reconforge/benchmark/grouped_matching_source_mutation.py`, its test,
this ADR, manifest entry, and the E-595 execution records. Existing matching
implementations and tests remain unchanged.
