# Supported Engine Parity Matrix

`engine-parity-matrix.v1.json` is the reviewed input contract for the dedicated
`engine-parity` GitHub Actions job. It covers four isolated cells:

Its canonical content digest is
`54777b4e1e92dfc675665ff55168507f2a9aa5b1415b2b4806f4fd99925a4aed`.

| Python | Profile | NumPy | Pandas | DuckDB |
| --- | --- | --- | --- | --- |
| 3.11 | lower-bounds | 1.26.4 | 2.2.0 | 1.0.0 |
| 3.12 | lower-bounds | 1.26.4 | 2.2.0 | 1.0.0 |
| 3.11 | current-compatible-2026-07-25 | 2.4.3 | 3.0.5 | 1.5.5 |
| 3.12 | current-compatible-2026-07-25 | 2.4.3 | 3.0.5 | 1.5.5 |

The lower profile is the first patch release satisfying the declared
`pandas>=2.2` and optional `duckdb>=1.0` bounds, plus NumPy 1.26.4 to avoid a
floating binary ABI. The current-compatible profile is a dated review of the
official PyPI release metadata on 2026-07-25. NumPy 2.4.3 is the newest reviewed
release supporting both declared Python versions; NumPy 2.5.1 requires Python
3.12 and therefore cannot define one shared 3.11/3.12 cell. Every selected
release publishes CPython 3.11 and 3.12 wheels. A future latest release does not
enter the matrix automatically.

Each cell requires binary distributions, verifies its resolved versions, then runs the signature, DuckDB
relation/partition, property, bounded-ambiguity, and golden-registry suites. The
job fails if any selected test is skipped, so a missing optional DuckDB install
cannot be reported as parity.

The manifest digest, schema, workflow, and tests prove that the matrix is configured
consistently. They are not evidence that GitHub executed the four cells. Record
the workflow run URL, commit, cell outcomes, durations, and artifacts in the
execution ledger before closing P0-009 or widening public wording.

This matrix is bounded correctness evidence. It does not support performance,
scale, true grouped matching, live-backend, process-recovery, or certification
claims.
