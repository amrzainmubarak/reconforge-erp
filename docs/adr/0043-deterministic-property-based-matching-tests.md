# ADR 0043: Deterministic Property-Based Matching Tests

- Status: Accepted
- Date: 2026-07-25
- Scope: Reconciliation permutation, duplicate, invalid-data, and tie-break regression testing

## Context

The deterministic matcher had many hand-written permutation regressions, but
each covered one fixed arrangement. P0-008 requires generated examples spanning
duplicates, invalid values, and stable tie-breaks. Home-grown pseudo-random
loops would not shrink failures and could drift between runs. Adding a runtime
testing dependency would unnecessarily expand the product attack and install
surface.

## Decision

1. Use Hypothesis as a development-only dependency, pinned exactly to `6.161.2`,
   the stable release published on official PyPI on 2026-07-24. The package
   declares Python >=3.10, covering the project's declared 3.11/3.12 matrix.
2. Configure each bounded property with `derandomize=True`, `max_examples=35`,
   and no wall-clock deadline. Derandomization makes generated examples
   reproducible from the test definition; removing deadlines avoids machine
   speed becoming a correctness result.
3. Generate two independent permutations from the same input multiset and
   assert invariant decision signatures/results across:
   - all four stock/GL strategies;
   - one-to-one, many-to-one, one-to-many, and many-to-many platform modes;
   - exact ties, equivalent duplicates, invalid amounts, missing dates, and
     bounded exact tolerance variants.
4. Generate invalid-record relocations and assert stable exception/record
   identity while the separately governed source position/row changes.
5. Keep example sizes at 1-7 records per side. These tests prove logical
   properties and shrinking behavior, not load, performance, or production
   scale.

## Consequences

- Three test properties cover 105 generated examples per ordinary run and
  shrink a future counterexample to a smaller reproducible case.
- The test suite has one new pinned dev dependency and its existing
  `sortedcontainers` transitive dependency. Runtime/community installs do not
  acquire Hypothesis.
- The exact pin improves this slice's repeatability but does not replace a full
  Python dependency lock or supported-version CI.
- P0-008 can close for the bounded deterministic matching contracts. Cross-
  engine/version parity and performance tiers remain separate gates.

## Rollback

If Hypothesis must be removed, retain the failing minimized examples as explicit
regressions and replace every property with an equivalently reproducible
generator before deleting the dependency. Do not silently return to unseeded
random loops or weaken duplicate/invalid/tie coverage.
