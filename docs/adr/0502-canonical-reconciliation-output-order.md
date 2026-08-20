# ADR 0502: Canonical order for reconciliation result artifacts

- **Status**: Accepted
- **Date**: 2026-08-10
- **Decision**: Sort stock/GL reconciliation result frames by stable business
  identity (`match_id`, canonical record instance, or exception identity) before
  returning them. Source position and source row remain audit metadata only and
  are never used as output ordering keys.
- **Rationale**: Matching signatures already exclude mutable source location and
  remain permutation-stable, but unsorted unmatched and exception frames could
  still produce different CSV/JSON row order for the same inputs. Canonical
  output ordering makes the emitted artifact reproducible without discarding
  source-location evidence.
- **Verification**: E-665 adds a permutation regression over matched,
  unmatched, data-quality, and aggregate exception frames. The focused
  reconciliation suites pass.
- **Boundary**: This closes local result ordering for the stock/GL path only. It
  does not prove cross-engine hosted parity, distributed execution, live
  providers, posting, HA/DR, or production sizing.
- **Rollback**: Revert `_stable_output_order`, its regression test, and the
  E-665 documentation; retain the existing versioned signature contract.
