# ADR 0050: Reviewed Supported Engine Parity Matrix

- Status: Accepted — configured gate, execution evidence pending
- Date: 2026-07-25
- Scope: Python/Pandas/DuckDB compatibility evidence for bounded local reconciliation

## Context

The general CI job runs on Python 3.11 and 3.12 but installs only the `dev`
extra. DuckDB is optional, so its parity tests can skip in both supported Python
cells. Local evidence uses Python 3.14.6, Pandas 3.0.3, and DuckDB 1.5.5 and
therefore cannot close P0-009.

The package declares open lower bounds (`pandas>=2.2`, `duckdb>=1.0`) rather
than a reproducible compatibility matrix. A floating "latest" job would change
without review, while testing only lower bounds would not cover the current
dependency generation users resolve today.

Official PyPI metadata reviewed on 2026-07-25 reports that the selected NumPy,
Pandas, and DuckDB releases publish CPython 3.11 and 3.12 wheels. NumPy 2.5.1 is
newer but requires Python 3.12; NumPy 2.4.3 is the newest reviewed release that
can keep the current profile identical across both declared Python versions.
These are dated snapshots, not permanently supported upper bounds.

## Decision

1. Add the closed, canonically digested `supported-engine-parity-v1` manifest and JSON Schema. It
   declares Python 3.11/3.12, a lower-bounds profile (NumPy 1.26.4, Pandas
   2.2.0, DuckDB 1.0.0), and a current-compatible-2026-07-25 profile (NumPy
   2.4.3, Pandas 3.0.5, DuckDB 1.5.5).
2. Record each release's official PyPI project URL, `Requires-Python`, first
   upload timestamp, and nonzero CPython 3.11/3.12 wheel counts. These fields
   document selection provenance; they do not replace dependency integrity
   hashes or a lockfile.
3. Add a dedicated GitHub Actions job with four explicit cells. Each isolated
   cell installs exact binary NumPy/Pandas/DuckDB pins alongside the project dev extra,
   verifies the resolved versions, and runs the signature, relation/partition,
   property, bounded-ambiguity, and golden-registry test files.
4. Fail the job if the selected pytest output reports any skip. An unavailable
   optional DuckDB installation must not become a passing parity cell.
5. Test manifest/schema validity, alignment with `pyproject.toml` Python
   classifiers and dependency floors, exact CI cross-product equality, pinned
   GitHub action SHAs, required test-file coverage, version verification, and
   the no-skip guard.
6. Do not mark P0-009 complete from configuration alone. Record the GitHub run
   URL, commit, all four cell results, durations, and artifacts before treating
   the matrix as executed evidence.

## Consequences

- Supported-Python engine parity can no longer silently pass through DuckDB
  skips in the dedicated job.
- Lower/current-compatible version selection is reviewable and reproducible at the direct
  dependency level.
- At adoption, the general project dependency graph remained lower-bounded and
  unlocked. ADR 0069 later added the universal application/server/tool lock;
  the three exact no-dependency engine overrides remain compatibility-test
  inputs rather than production resolution or artifact evidence.
- This is bounded correctness evidence only. It does not prove performance,
  volume, true grouped matching, live backend behavior, or crash durability.

## Rollback

Removing the dedicated job or no-skip guard reopens the supported-version parity
gap. A replacement must retain both supported Python versions, lower and dated
current profiles, exact resolved-version verification, every required parity
suite, and explicit skip rejection. Update current pins only with refreshed
official metadata, manifest/schema tests, ADR/ledger changes, and a complete
four-cell run; never relabel a configured matrix as executed evidence.
