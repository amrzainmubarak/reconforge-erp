# ReconForge Execution Evidence Log

This file records commands and observed results. It does not convert a dirty worktree into release evidence.

## Snapshot E-20260724-01

- Date/timezone: 2026-07-24, Africa/Cairo.
- Branch/commit: `feature/p0-atomic-audit-outbox` / `bdf63de48051a0ef5c694442208f5207f4dd5e1c`.
- Base: `origin/main` / `6a785c0b42f57aee80e3082c0226e6f99742f80b`.
- Worktree: 112 tracked files differ; 99 untracked files; not a release candidate.
- Host: Windows 11 Pro build 26200; Ryzen 7 7435HS; 16 logical CPUs; 21,144,231,936 bytes RAM.
- Runtime: Python 3.14.6; Node 26.3.0; Git 2.54.0.windows.1; Docker client 29.6.1.

## E-001: Git baseline

| Command | Result |
| --- | --- |
| `git fetch origin --prune` | Completed |
| `git branch -f main origin/main` | Local `main` moved to `6a785c0`; no checkout/merge/worktree change |
| `git rev-list --left-right --count origin/main...HEAD` | `0 11` |
| `git diff --shortstat` | 112 files changed, 11,897 insertions, 3,804 deletions |
| `git ls-files --others --exclude-standard` | 99 untracked files |

## E-002: Backend quality gates

| Command | Exit | Duration | Result |
| --- | ---: | ---: | --- |
| `python -m ruff check .` | 1 | 0.181s | 7 findings |
| `python -m mypy reconforge` | 1 | 21.406s | 2 errors in 205 source files |
| `python -m pytest --basetemp=.pytest-baseline-current -q` | 1 | ~150s | 637 collected: 626 passed, 10 skipped, 1 failed |
| `python -m bandit -q -r reconforge` | 0 | 4.367s | No findings; three notices for one justified `nosec B608` site |
| `python -m pip_audit` | 0 | 12.376s | No known vulnerabilities; local unpublished package skipped |
| `python -m build --no-isolation` | 0 | 14.404s | sdist and wheel built |
| `git diff --check` | 2 | 0.089s | Two trailing-whitespace lines and one extra EOF blank line |

Ruff findings:

- `reconforge/generator/synthetic.py`: module import placement/order.
- `reconforge/reconciliation/matching.py`: two unused money imports.
- `reconforge/reconciliation/stock_gl.py`: import order.
- `reconforge/reconciliation/workorders.py`: import order.
- `tests/test_matching_currency.py`: import order.

Mypy findings:

- `reconforge/reconciliation/matching.py:74`: `object` passed to `Money` constructor annotation.
- `reconforge/validators.py:171`: `object` passed to precision parser annotation.

## E-003: Determinism regression

Command, run twice with separate local temp directories:

```text
python -m pytest -q tests/test_generator_benchmark_engines.py::test_duckdb_partitioned_execution_is_row_order_invariant --basetemp=<local-temp>
```

Both replays failed in 3.536s and 3.566s with the same values:

- Original digest: `06a23b0c9c811d4524472ab7420975625edf9ff3a98ef72e87b6f0d714830d66`
- Shuffled digest: `6a8b26785d0d38f4a1d9fb1741595a4e323c61967be35645c86dd5e8250596ab`

Classification: reproducible P0 correctness failure, not flaky and not environmental.

## E-004: Web gates

PowerShell blocked `npm.ps1`, so equivalent commands used `npm.cmd`.

| Command | Exit | Duration | Result |
| --- | ---: | ---: | --- |
| `npm.cmd --prefix apps/web ci` | 0 | 23.866s | 158 packages installed; 0 vulnerabilities reported |
| `npm.cmd --prefix apps/web run typecheck` | 0 | 1.225s | Passed |
| `npm.cmd --prefix apps/web run test:run` | 0 | 7.288s | 17 tests passed |
| `npm.cmd --prefix apps/web run build` | 0 | 1.751s | Vite build passed |
| `npm.cmd --prefix apps/web run e2e` | 0 | 7.127s | 2 Playwright tests passed |

## E-005: Local product runtime

| Command | Exit | Duration | Result |
| --- | ---: | ---: | --- |
| `reconforge doctor` | 0 | 2.582s | Package/config/sample/output OK; 0 validation errors, 10 warnings |
| `reconforge validate examples/sample_data` | 0 | 2.360s | 0 errors, 10 visible warnings |
| `reconforge demo run --output output/baseline-demo-current` | 0 | 5.541s | 13 stock/GL exceptions, 16 work-order exceptions, 2 rules, 14 evidence cases |

The pre-existing `output/baseline-demo` directory was not overwritten.

## E-006: 1K smoke benchmark

Dataset directory digest: SHA-256 `a520b37ed7086c9f5a350f34de2333b945273331492dfa615465ae1bc19f3ac4` over sorted UTF-8 `filename:file_sha256` lines.

| Engine | Runtime metric | Wall | Stock / GL | Matched / exceptions | Decision digest proof |
| --- | ---: | ---: | ---: | ---: | --- |
| Pandas | 0.9930s | 3.356s | 1,000 / 1,144 | 996 / 369 | Not emitted by benchmark report |
| DuckDB | 1.1568s | 3.515s | 1,000 / 1,144 | 996 / 369 | Not emitted by benchmark report |

Memory was reported as `0.0 MB`, which is an instrumentation gap, not evidence of zero memory use. This measurement supports no claim above the exact 1K dataset/hardware/software boundary.

## E-007: Environment-unavailable gates

`docker info` exit 1:

```text
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine
The system cannot find the file specified.
```

Not run:

- `docker build -t reconforge:baseline .`
- `docker run --rm reconforge:baseline reconforge doctor`
- Live PostgreSQL, Redis, and object-storage integration tests because required service settings were absent.

Verification requirement: start a reviewed Docker/service environment, run the exact commands, record image/service digests and durations, and update this log. Do not infer success from workflow or Dockerfile presence.

## E-008: Baseline artifacts

- `docs/execution/BASELINE.md`
- `docs/execution/REPOSITORY_INVENTORY.md`
- `docs/execution/CLAIMS_EVIDENCE_MATRIX.md`
- `docs/execution/GAP_MATRIX.md`
- `docs/execution/QUALITY_BASELINE.md`
- `docs/execution/PERFORMANCE_BASELINE.md`
- `docs/execution/SECURITY_BASELINE.md`
- `docs/execution/DOCUMENTATION_DRIFT.md`
- `docs/execution/DEPENDENCY_RISK.md`
- `docs/execution/BACKLOG.yaml`

Baseline conclusion: documentation is now aligned to a failing, dirty snapshot. It is suitable for prioritization, not release approval.

## E-009: Documentation drift correction

Changed claim/link surfaces:

- README positioning no longer calls the product an ERP platform.
- Deleted root `DEMO.md` links now point to maintained showcase/scenario documents.
- Determinism is described as a release gate rather than an unqualified current property.
- The historical repository assessment points to `docs/roadmap.md` instead of deleted root `ROADMAP.md`.

Command:

```text
python -m pytest -q tests/test_website_launch_copy_docs.py tests/test_release_readiness_docs.py tests/test_pilot_readiness_docs.py --basetemp=.pytest-docs-current
```

Result: 15 passed, exit 0.

## E-010: Money/Currency critical-path slice

Implemented boundary:

- Stock/GL matching compares `Money` objects with explicit/defaulted currency and strict registry precision.
- Matched-row construction revalidates strict precision and emits currency-scaled Decimal amounts.
- Invalid, non-finite, scientific-notation, and over-precise values remain invalid/data-quality outcomes rather than zero or rounded matches.
- Legacy finite-float inputs remain accepted only at the parser ingress and are converted immediately via string-to-Decimal compatibility behavior.
- Mypy boundary annotations accept untrusted `object` values only where the parser performs runtime validation.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| `python -m ruff check .` | Pass | 0.116s |
| `python -m mypy reconforge` | Pass, 205 files | 1.282s |
| Money/validation/stock-GL/work-order targeted tests | 52 passed | 2.770s |
| `git diff --check` | Pass | 0.093s |

Focused suite files: `test_money_currency.py`, `test_matching_currency.py`, `test_reconciliation_hardening.py`, `test_validation.py`, `test_workorder_reconciliation.py`, and `test_stock_gl_reconciliation.py`.

## E-011: Decimal-scale stable identity remediation

Diagnostic evidence before the fix:

- Both inputs selected the same 499 `(move_id, entry_id)` business pairs.
- 32 matched rows differed only in scale-sensitive values/IDs, for example `2203.80` versus `2203.8`.
- 30 stock and 38 GL source rows had equal numeric values with different lexical Decimal scale after CSV rewrite.

Fix boundary:

- Stable row keys and decision signatures normalize equal finite Decimal values to the same plain canonical string.
- Strict `Money` output restores the registered currency scale for matched stock/GL amounts.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Full-scan Pandas/DuckDB parity + forced partition parity + partition permutation | 3 passed | 5.250s |
| `python -m ruff check .` | Pass | 0.126s |
| `python -m mypy reconforge` | Pass, 205 files | 0.988s |
| `git diff --check` | Pass | 0.082s |
| `python -m pytest --basetemp=.pytest-full-final -q` | 627 passed, 10 skipped, 0 failed | 132.040s |

Residual scope: duplicate-identical records, invalid-row `source_row` semantics, other strategies, live services, supported Python versions, and additional engine versions.

## E-012: Final local security, build, and runtime smoke

| Command | Exit | Duration | Result |
| --- | ---: | ---: | --- |
| `python -m bandit -q -r reconforge` | 0 | 4.335s | No findings; same three notices for one justified `nosec B608` line |
| `python -m pip_audit` | 0 | 13.113s | No known vulnerabilities in audited installed packages; local package skipped |
| `python -m build --no-isolation` | 0 | 13.927s | sdist and wheel built; setuptools warnings remain |
| `reconforge doctor` | 0 | 2.832s | Package/config/sample/output OK; validation 0 errors, 10 warnings |
| `reconforge validate examples/sample_data` | 0 | 2.606s | 0 errors, 10 visible warnings |
| `reconforge demo run --output output/baseline-demo-final` | 0 | combined run output not retained separately | 297 artifact files observed; summary generated at 2026-07-24T19:18:15Z |

The final demo summary reports 7 matched stock/GL transactions, 5 stock movements without GL, 2 GL entries without stock, 1 value difference, 16 work-order exceptions, 5 open WIP orders, and 1 critical risk.

## Current iteration verdict

Applicable local Python, security-scan, build, web, and CLI gates are green. This is still not release evidence because the worktree is broad and dirty, Docker is unavailable, live service tests are skipped, the Python runtime is outside the declared matrix, dependencies are not reproducibly locked, and signatures/provenance/rollback were not verified.

## E-013: Versioned fail-closed Currency Registry

Implemented boundary:

- Bundled registry schema version 1 contains 165 usable currency policies from
  SIX ISO 4217 Maintenance Agency List One published 2026-01-01. Entries with
  `N.A.` minor units are excluded because canonical Money requires explicit
  numeric precision.
- The registry exposes schema/version/source/digest provenance, bounded atomic
  local-file replacement, explicit process-local registration, reset, and
  deterministic snapshots. Runtime loading performs no network request.
- Unknown currency codes now fail closed. Stock/GL reconciliation emits
  `unknown_currency` data-quality exceptions rather than inventing two decimal
  places or matching the rows.
- `Money` captures minor units, `ROUND_HALF_UP`, policy digest, and registry
  provenance when created. Equal codes under different policies cannot be
  combined. Legacy `to_dict()` remains unchanged; canonical serialization
  carries the policy fields.
- Exact add/multiply helpers prevent the process Decimal context's default
  28-digit precision from silently altering tested 500-digit values.

Source inspected: `https://www.six-group.com/en/products-services/financial-information/market-reference-data/data-standards.html` and its linked List One XML. The source identifies SIX as the ISO 4217 Maintenance Agency; ReconForge's rounding mode is separately identified as product policy.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Currency/reconciliation/schema/CLI targeted suite | 73 passed | 8.480s |
| Full suite | 648 collected; 638 passed, 10 skipped, 0 failed | 99.235s |
| `python -m ruff check .` | Pass | 0.204s |
| `python -m mypy reconforge` | Pass, 206 files | 2.882s |
| `python -m bandit -q -r reconforge` | Pass, no findings | 4.829s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped | 12.185s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 12.824s |
| Archive inspection | `reconforge/data/currency_registry.v1.json` present in wheel and sdist | <1s |

Residual scope: registry selection is process-wide and not yet reconciled with
tenant master-data tables; source refresh governance/automation and historical
currency policies remain future work.

## E-014: Exact financial CLI policy boundaries

The accounts `--materiality`, journals `--high-value`, and intercompany
`--tolerance` options now enter the application layer as strings and are parsed
once by existing Decimal validation. Defaults and option names remain
compatible. Service-level finite-float inputs remain an explicit legacy reader
and convert immediately through `str(value)`; no binary-float arithmetic was
added.

Regression evidence includes values that binary float cannot distinguish:

- account materiality `0.10000000000000001` is stored exactly in the canonical
  Decimal column;
- journal amount `100000.00000000000` remains below the exact threshold
  `100000.00000000001` and does not produce `HIGH_VALUE`;
- intercompany imbalance `0.100000000000000003` remains within tolerance
  `0.100000000000000005` and does not produce a case;
- scientific notation is rejected before an account template mutation.

Focused accounts/journals/intercompany suite: 10 passed in 6.799s. At that
iteration boundary, variance thresholds and other classified candidates
remained; E-015 records the subsequent variance slice.

## E-015: Exact versioned variance threshold decisions

Implemented boundary:

- `--amount-threshold` and `--percent-threshold` preserve CLI text until strict
  finite, non-negative Decimal validation; scientific notation is rejected.
- Summary JSON uses lexical numeric readers and summary CSV uses text columns,
  so neither input path crosses Pandas/Python binary-float inference.
- Amount decisions use exact unrounded subtraction. Percentage decisions use
  exact cross multiplication, so division/display rounding cannot change a
  flag; equality remains inclusive and the legacy zero-amount-disable behavior
  remains explicit.
- Schema-v2 `variance_analysis.json` retains the legacy numeric `thresholds`
  keys and writes Decimal as exact JSON number lexemes. The canonical
  `threshold_policy` carries exact strings, comparison/display semantics, and a
  SHA-256 digest. `read_variance_thresholds()` reads legacy unversioned/v1 and
  v2 artifacts and detects policy tampering.
- Decimal JSON serialization and report display rounding are independent of
  the ambient Decimal context; non-finite output is rejected.

Regression evidence includes `0.100000000000000003` remaining below
`0.100000000000000005`, a separate exact percentage boundary, unquoted JSON
and CSV source lexemes, legacy numeric/string artifacts, legacy finite-float
service calls, schema validation, and invalid-input no-artifact behavior.

| Command | Result | Duration |
| --- | --- | ---: |
| Variance + workflow-schema focused suite | 21 passed | 4.822s |
| Reports/period/CLI broader suite | 49 passed | 10.513s |
| Full suite | 660 collected; 650 passed, 10 skipped, 0 failed | 122.276s |
| `python -m ruff check .` | Pass | 0.127s |
| `python -m mypy reconforge` | Pass, 206 files | 0.532s |
| `git diff --check` | Pass | 0.093s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 4.941s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped | 11.688s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 13.073s |

Environment: Windows, Python 3.14.6, pytest 9.1.1, Ruff 0.15.22, and Mypy
2.3.0. Python 3.14 remains outside the declared 3.11/3.12 support matrix.

P0-005 remains in progress: anonymizer monetary-noise behavior, report/Studio
amount filters, and other audited candidates still require classification or
remediation.

## E-016: Exact anonymizer noise and private-map boundary

Implemented boundary:

- CLI amount-noise input remains exact text until finite Decimal validation in
  the closed range 0–100. Scientific, negative, over-100, NaN, and infinite
  policies fail before output creation; finite-float library calls remain a
  strict legacy reader only.
- `exact-global-decimal-noise-v1` draws one seeded integer-step Decimal factor
  at four-decimal resolution for all files/amount columns. Multiplication uses
  a bounded local Decimal context and `ROUND_HALF_UP` at the input value's
  lexical scale, avoiding both float effects and a fabricated two-decimal
  currency assumption.
- One global factor preserves tested cross-file equalities and the stock/GL
  sample's matched/unmatched/value-difference outcome counts. Invalid amount
  text remains visible rather than becoming zero.
- Default shareable output no longer contains `anonymization_map.csv` with raw
  identifiers. A compatible `group,original,masked` CSV requires an explicit,
  non-existing private path outside both input and shareable output trees.
  Shareable targets must be new/empty, so legacy maps or stale files cannot be
  silently retained; ReconForge deletes neither.
- Schema-v1 `anonymization_manifest.json` carries exact/versioned policy,
  source filenames, a seed fingerprint, explicit reversible/known-field privacy
  limits, policy/manifest digests, and byte count/SHA-256 for each shareable CSV.
  The verifier rejects unsupported policy, metadata tampering, and modified
  output bytes. The checked-in anonymized example validates and its reversible
  sample map was removed (recoverable from Git history if explicitly needed).
- Generated CSV line endings are pinned to LF for cross-platform byte digest
  stability. The manifest intentionally does not include original identifiers,
  the raw seed, the private-map path, or the amount factor.

| Command | Result | Duration |
| --- | --- | ---: |
| Anonymizer/CLI/v0.3/schema focused suite | 56 passed | 7.395s |
| Full suite | 675 collected; 665 passed, 10 skipped, 0 failed | 123.362s |
| `python -m ruff check .` | Pass | 0.134s |
| `python -m mypy reconforge` | Pass, 206 files | 0.819s |
| `git diff --check` | Pass | 0.122s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 4.782s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped | 14.277s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 13.289s |
| Archive/example verification | Anonymizer v1 code present in wheel/sdist; checked-in example schema/digests/output hashes valid; sdist packages neither example map nor manifest | 2.6s |

Security boundary: deterministic aliases and amount noise remain reversible or
susceptible to known-value inference; free text, unclassified columns,
filenames, rare combinations, and metadata may remain identifying. This is a
risk-reduction tool, not a safe-publication, de-identification, or compliance
claim. R-017 remains High pending independent disclosure-risk methods and
qualified privacy review.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Ruff 0.15.22, and Mypy
2.3.0. Python 3.14 remains outside the declared 3.11/3.12 support matrix.

At the E-016 boundary, report/Studio amount filters still required remediation;
E-017 records that subsequent slice. Other audited candidates remain.

## E-017: Exact Studio filters and currency-scoped management reporting

Implemented boundary:

- FastAPI keeps `min_amount` as a string through bounded finite/non-negative
  Decimal validation. Scientific notation and overlong input receive a constant
  HTTP 400 response without reflection. The HTML field no longer forces a
  two-decimal step.
- Exception filtering compares exact Decimal values. The regression proves
  `0.100000000000000003` remains below
  `0.100000000000000005`; legacy finite-float service calls remain only a
  compatibility ingress.
- Matched stock/GL output now includes its resolved currency. Management-pack
  generation resolves one registry policy before creating output and rejects
  any explicit differing currency because this path has no FX conversion.
- Report sums derive a local Decimal precision from all terms and remain exact
  under a hostile four-digit ambient context. Display quantization uses captured
  currency minor units and `ROUND_HALF_UP`; the KWD regression preserves
  `12345678901234567890.003` rather than assuming two decimals.
- Schema-v1 `management_pack.json` publishes currency/minor-units/rounding,
  policy and registry digests/versions, the
  `single-currency-only-no-implicit-fx` rule, and the disclosed compatibility
  assumption for rows without currency. Cross-currency failure occurs before
  the report directory exists.
- Invalid/unavailable exception and WIP amounts are excluded from value totals
  with explicit unquantified counts rather than being represented as valid zero
  amounts. Grouped risk/theme views carry the same count.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Studio/review/report/reconciliation focused suite | 62 passed | 8.2s |
| Report/schema focused suite | 15 passed | 3.7s combined gate wall time |
| Full suite | 687 collected; 677 passed, 10 skipped, 0 failed | 105.426s |
| `python -m ruff check .` | Pass | 0.211s |
| `python -m mypy reconforge` | Pass, 206 files | 0.917s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.253s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 4.978s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped | 14.722s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 13.299s |

Schema evidence: `docs/schemas/management_pack.schema.json` passes Draft 2020-12
meta-schema validation and validates the generated sample management pack.

Compatibility/security boundary: existing route, query name, report sections,
and metric names remain. Report metadata/result columns are additive. Missing
currency retains the legacy configured-output-currency assumption but is now
explicit. No network call, telemetry, credential, raw-row logging, or FX
conversion was added.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Ruff 0.15.22, and Mypy
2.3.0. Python 3.14 remains outside the declared 3.11/3.12 support matrix.

P0-005 remains in progress: the broad audit contains 100 `float` token lines,
including non-financial ratios, synthetic scores, compatibility annotations,
and financial candidates still requiring classification.

## E-018: Exact, currency-aware synthetic finance fixtures

Implemented boundary:

- Generator rates are bounded, finite, plain-decimal values parsed without a
  binary-float round trip. Scientific notation, booleans, non-finite values,
  negative values, and values above one fail before the output directory is
  created; CLI failures use a constant non-reflecting message.
- Monetary randomness uses deterministic integer draws on a disclosed
  six-decimal grid. Multiplication and quantization run in derived local
  Decimal contexts, independently of the ambient context, and use the captured
  currency policy rather than a universal two-decimal assumption.
- Monetary CSVs now carry explicit currency. KWD preserves three minor-unit
  digits and JPY produces integral monetary values under the packaged registry
  policies.
- Additive schema-v1 `synthetic_manifest.json` records the generator algorithm,
  exact canonical rates, seed, row count, industry, currency policy and registry
  provenance, and the byte count/SHA-256 for each of the eight expected CSVs.
  Its verifier rejects unsupported metadata, path/name-set changes, policy
  tampering, duplicate entries, and modified output bytes.
- Same seed and policy produce byte-identical CSVs and manifests across output
  directories and under hostile versus normal ambient Decimal precision.
  Existing callers still receive the original eight-CSV path list.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Generator/CLI/schema focused suite | 43 passed | 13.643s |
| Full suite | 697 collected; 687 passed, 10 skipped, 0 failed | 105.190s |
| `python -m ruff check .` | Pass | 0.222s |
| `python -m mypy reconforge` | Pass, 206 files | 0.610s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.210s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 4.954s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped | 2.251s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 12.186s |

Schema evidence: `docs/schemas/synthetic_generator_manifest.schema.json`
passes Draft 2020-12 meta-schema validation and validates generated manifests;
the manifest verifier additionally checks policy and output identity against the
packaged registry and filesystem bytes.

Compatibility/security boundary: generation remains synthetic, local, and
network-free. The manifest is additive, contains no customer data, and the
existing return contract remains eight CSV paths. The `float` spelling retained
in `RateInput` is a legacy service-ingress compatibility reader; generated
financial values never depend on binary-float arithmetic. This is fixture and
benchmark-data provenance, not a production-volume, privacy, or performance
claim.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Ruff 0.15.22, and Mypy
2.3.0. Python 3.14 remains outside the declared 3.11/3.12 support matrix.

P0-005 remains in progress: the broad word-boundary audit contains 93 `float`
token lines. Most are non-financial ratios, timing/telemetry values, synthetic
presentation scores, or explicit compatibility annotations; control-decision
and persistence candidates still require classification or remediation.

## E-019: Exact evidence-risk and close-readiness decisions

Implemented boundary:

- Evidence binder risk selection now applies bounded policy
  `integer-0-to-100-v1` without Pandas numeric coercion, float conversion, or
  integer truncation. Exact integral lexical values remain valid; fractional,
  scientific, malformed, overlong, and out-of-range explicit scores are invalid.
- Invalid explicit scores remain visible as `Data Quality` evidence with
  `risk_score: null` and `risk_score_status: invalid`. Missing scores are
  distinct and are still collected when their declared risk level is
  High/Critical. Human-readable evidence renders unavailable status rather than
  a manufactured zero.
- `evidence_index.json` is now schema 2 with a declared score policy. Valid-case
  filenames and integer values remain; register/JSON/status fields are additive
  for valid cases.
- `EvidenceCase` itself enforces the same invariant with strict integer typing,
  a 0-through-100 range, and consistent valid/missing/invalid status; alternate
  callers cannot bypass the CSV boundary with a float, boolean, null-valid, or
  non-null-invalid value.
- One pure domain calculation derives a two-decimal readiness percentage from
  integer counts using a local Decimal context and `ROUND_HALF_UP`. Hostile
  ambient precision produces the same `33.33`, `66.67`, and `100.00` results.
- Local and PostgreSQL close services use the exact calculation. PostgreSQL
  approval/locking requires equality with `Decimal("100.00")`; the regression
  proves `99.999999999999999999` fails closed without float rounding.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Control/evidence focused suite | 25 passed | 4.901s |
| Evidence/close/API compatibility suite | 58 passed, 1 skipped | 10.442s |
| Control/schema/documentation suite | 33 passed | 4.840s |
| Full suite | 710 collected; 700 passed, 10 skipped, 0 failed | 126.856s |
| `python -m ruff check .` | Pass | 0.113s |
| `python -m mypy reconforge` | Pass, 207 files | 0.930s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.093s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.148s |
| `python -m pip_audit` before environment remediation | Exit 1: global unrequired `yt-dlp 2026.6.9`, `CVE-2026-55404`, fixed in `2026.7.4` | 12.076s |
| Environment-only `yt-dlp` upgrade | Installed `2026.7.4`; package is absent from project manifests and `Required-by` was empty | ~27s |
| `python -m pip_audit` after remediation (latest) | No known installed-package vulnerabilities; local package skipped | 2.163s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 13.203s |
| Archive inspection | `reconforge/domain/control_scores.py` present in wheel and sdist | <1s |

Compatibility/security boundary: valid score values, routes, filenames, close
statuses, and two-decimal readiness presentation remain. Malformed evidence
scores intentionally change from omission/zero/failure to visible null-valued
quality cases. The existing local SQLite `REAL` storage affinity is not changed
without a migration; current close decisions use exact count-derived values,
not a stored float. A ReconForge `Locked` state remains workflow metadata only
and does not lock source-ERP postings or imply a statutory close/certification.

Dependency incident boundary: the plain global-environment audit changed from
green at E-018 to a newly reported unrelated `yt-dlp` vulnerability at E-019.
The environment package was upgraded to the version named by the audit; no
project dependency file changed. This supports the existing conclusion that an
unlocked global environment is not reproducible project dependency evidence.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Ruff 0.15.22, and Mypy
2.3.0. Python 3.14 remains outside the declared 3.11/3.12 support matrix.

P0-005 remains in progress: the broad word-boundary audit now contains 90
`float` token lines. Remaining lines still include non-financial metrics,
timing/telemetry, synthetic presentation scores, JSON compatibility, and
persistence/general utility candidates requiring classification.

## E-020: Database-owned restore defaults

Implemented boundary:

- Local backup restore no longer reads a trusted SQLite default and attempts to
  interpret it as Python `int`, `float`, string, timestamp, or expression.
- Each restored row now gets an ordered parameterized insert column set.
  Supplied/compatibility-shim values are bound; missing defaulted or nullable
  columns are omitted so the freshly created trusted schema applies its own
  semantics. Missing `NOT NULL` columns without defaults still fail closed.
- Table/column identifiers still come from fixed restore allowlists and strict
  identifier validation/quoting. Backup content supplies parameter values only
  and cannot provide SQL/default expressions.
- The regression uses a long canonical fractional text default, proves its full
  lexical value survives, and inspects the executed insert to prove the default
  column was omitted rather than parsed/bound by the application.
- Audit finding: SQLite evaluates an unquoted fractional numeric default with
  REAL semantics even on a TEXT-affinity column. Exact decimal defaults must
  therefore be quoted canonical text or integer minor units; this slice does
  not claim to repair unsafe DDL semantics.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Backup/restore focused suite | 9 passed | 5.479s |
| Backup/export/import/enterprise DB compatibility suite | 20 passed | 7.892s |
| Schema/documentation suite | 13 passed | 1.700s |
| Full suite | 711 collected; 701 passed, 10 skipped, 0 failed | 126.310s |
| `python -m ruff check .` | Pass | 0.126s |
| `python -m mypy reconforge` | Pass, 207 files | 0.572s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.158s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.174s |
| `python -m pip_audit` | No known installed-package vulnerabilities after recorded E-019 environment remediation; local package skipped | 2.189s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 13.042s |

Compatibility/security boundary: backup schema versions, JSON/manifest format,
CLI commands, checksum/version checks, complete-row preferred inserts, explicit
legacy compatibility shims, overwrite protection, lifecycle replay, and
foreign-key verification remain. Row-dependent insert shapes are internal.
Defaults are trusted only because the target schema is created from installed
ReconForge migrations, never from backup data. This is tested local SQLite
backup/restore, not an enterprise DR, RPO/RTO, or clean-production recovery
claim.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Ruff 0.15.22, and Mypy
2.3.0. Python 3.14 remains outside the declared 3.11/3.12 support matrix.

P0-005 remains in progress: the broad word-boundary audit now contains 89
`float` token lines. Remaining lines still include non-financial metrics,
timing/telemetry, synthetic presentation scores, JSON compatibility, and
other general/financial candidates requiring classification.

## E-021: Canonical governed metric values

Implemented boundary:

- Close completion, evidence coverage, control effectiveness, and match rate
  use the shared exact integer-count percentage calculation. It establishes a
  local Decimal context, `ROUND_HALF_UP`, and two-decimal quantum for both
  populated and explicit empty-set policies.
- The first hostile-context regression exposed that empty evidence coverage
  still quantized `100.00` under ambient precision and failed. That branch was
  moved under its own derived local context; the repeated focused/full gates
  below are after the fix.
- `metric_snapshots.value_text` is now canonical: percentages/ages retain two
  places and counts use integer text. The existing `value REAL` receives the
  same text and remains a compatibility projection for API/Studio numeric
  readers; no schema migration or route/metric-key change was introduced.
- Period readiness is read as text, validated finite and within 0..100, then
  averaged/quantized with exact local-context Decimal arithmetic. A stored
  `NaN` regression fails before snapshot writes instead of becoming zero.
- Review/exception aging asks SQLite to cast its `AVG(julianday(...))` result to
  text before application validation/quantization. SQLite still performs the
  underlying time aggregate with its numeric semantics, so aging remains an
  explicitly approximate operational metric.
- Hostile ambient precision produces canonical `33.33` close completion and
  period readiness, `100.00` empty evidence coverage, and `0` count text; the
  legacy numeric projection remains `33.33` for compatible readers.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Metric/control/API/Studio/atomic focused suite (post-fix) | 22 passed | 5.374s |
| Schema/documentation suite | 13 passed | 1.706s |
| Full suite | 714 collected; 704 passed, 10 skipped, 0 failed | 126.120s |
| `python -m ruff check .` | Pass | 0.123s |
| `python -m mypy reconforge` | Pass, 207 files | 0.553s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.106s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.075s |
| `python -m pip_audit` | No known installed-package vulnerabilities after recorded E-019 environment remediation; local package skipped | 13.264s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 12.951s |

Compatibility/security boundary: existing metric table, numeric `value`, keys,
lineage, API routes, and Studio pages remain. Consumers requiring a stable
representation should use the pre-existing `value_text`, whose formatting is
now policy-driven. Metrics do not approve a match, lock a source system, close
a statutory period, or provide audit/executive assurance. Invalid readiness
errors are constant and do not reflect stored content.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Ruff 0.15.22, and Mypy
2.3.0. Python 3.14 remains outside the declared 3.11/3.12 support matrix.

P0-005 remains in progress: the broad word-boundary audit now contains 76
`float` token lines. Remaining lines are dominated by benchmark/timing values,
synthetic presentation scores, generic JSON/metadata compatibility, and strict
financial compatibility/rejection annotations; they still require an explicit
classification ledger and any justified residual remediation.

## E-022: Integer-exact DuckDB partition sizing and residual classification

Implemented boundary:

- DuckDB work-order partition sizing no longer converts integer record/work-order
  counts through binary float. It computes the existing ceiling as
  `(target * work_orders + records - 1) // records`, then applies the same one-to-
  work-order-count bounds and low-record fallback.
- Boundary regressions prove 3,000 records/six work orders selects one bucket and
  2,999 selects two. A reproduced `work_order_count = 10**18 + 3` case now returns
  exact eight buckets; the former float implementation returned seven.
- This is an execution/batching correction only. Matching rules, work-order
  keys, source rows, decision ordering, and signature format are unchanged; the
  large count is arithmetic evidence, not a supported-scale or performance claim.
- `docs/execution/FLOAT_BOUNDARY_CLASSIFICATION.md` classifies every remaining
  word-boundary hit: 21 timing/benchmark, 9 synthetic display, 6 suggestion/
  signature, 12 generic serialization/reporting, 6 explicit rejection guards,
  and 21 legacy financial compatibility-reader lines.
- The classification prevents a false closure: P0-005 remains open until the 21
  financial compatibility readers have a versioned strict/deprecation path and
  reconciliation signatures assert/version financial fields rather than merely
  accepting the generic float serializer.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Generator/benchmark/DuckDB focused suite | 28 passed | 9.587s |
| Corrected Backlog YAML structure assertion | Pass; P0-005 classification path present under `tasks` | <1s |
| Schema/documentation suite | 13 passed | 1.719s |
| Full suite | 715 collected; 705 passed, 10 skipped, 0 failed | 126.384s |
| `python -m ruff check .` | Pass | 0.119s |
| `python -m mypy reconforge` | Pass, 207 files | 0.538s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.114s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.206s |
| `python -m pip_audit` | No known installed-package vulnerabilities after recorded E-019 environment remediation; local package skipped | 12.887s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 13.259s |

Operator-evidence note: the first custom YAML assertion used a nonexistent root
key named `backlog`; `safe_load` and the 13 documentation tests still passed.
The command was corrected to the actual `tasks` key and then proved the P0-005
classification reference. This was a verification-command error, not a product
or YAML failure.

Compatibility/security boundary: only the internal partition bucket-size
heuristic changes at rounding boundaries. No query identifier, financial value,
rule, result, API, artifact schema, or network/security boundary changes. The
classification ledger explicitly distinguishes permitted non-financial floats,
rejection guards, and unresolved compatibility readers rather than using line
count as a quality claim.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Ruff 0.15.22, and Mypy
2.3.0. The full gate completed 2026-07-25 Africa/Cairo; Python 3.14 remains
outside the declared 3.11/3.12 support matrix.

P0-005 remains in progress with 75 classified `float` source lines. The next
slice must define a backward-compatible strict financial ingress/version policy
and a financial-field signature assertion; it must not delete timing or
rejection guards merely to reduce the lexical count.

## E-023: Versioned strict reconciliation signatures

Implemented boundary:

- `reconciliation-signature-v2` is now the Pandas/DuckDB writer and includes its
  policy identifier inside the hashed payload. `EngineResult` returns the same
  identifier beside the digest so downstream evidence can interpret it.
- V2 rejects binary floating-point values, including `NaN`, and booleans in
  `stock_amount`, `gl_amount`, and `value_difference` before Pandas missing-value
  handling. It accepts finite Decimal, integer, or exact plain-decimal text and
  hashes one normalized plain-decimal representation.
- Suggestion-only `confidence_score` and `reference_similarity` retain their
  existing non-financial representation and do not authorize a match.
- Explicit `reconciliation-signature-v1` preserves the pre-change serializer. A
  golden fixture reproduces digest
  `c323485405c9cb5ebc0627bbfd50f24dcacf6e3735d771859be571e2c686e745`.
- Exact amount scale/type variants and row permutations produce one v2 digest;
  both installed engines declare v2 and retain parity in the bounded fixtures.
- ADR 0039 defines the wider compatibility migration: introduce additive strict
  readers, migrate internal decision callers, retain explicitly named legacy v1
  readers until a documented breaking-release boundary, and never silently
  reinterpret historical values or digests.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Signature/generator/benchmark/DuckDB focused suite | 36 passed | 9.417s |
| Documentation/claim-boundary suite | 16 passed | 2.044s |
| Full suite with repository-local basetemp | 723 collected; 713 passed, 10 skipped, 0 failed; one known Starlette deprecation warning | 122.61s |
| `python -m ruff check .` | Pass | 0.185s |
| `python -m mypy reconforge` | Pass, 207 files | 0.571s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.193s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 4.870s |
| `python -m pip_audit` | No known installed-package vulnerabilities after recorded E-019 environment remediation; local package skipped | 3.522s |
| `python -m build --no-isolation` | Pass; wheel and sdist include the v2 signature module | 13.611s |

Environment incident: the first combined focused run could not read
`C:\Users\LOQ\AppData\Local\Temp\pytest-of-LOQ`; all `tmp_path` fixtures failed
during setup before product execution. The identical suite passed using
`output/pytest-e023-*`, as did the full suite. This is an environment-unavailable
attempt followed by an explicit local workaround, not a flaky-test retry.

Compatibility/security boundary: v2 digests intentionally differ from v1 and
cannot be compared without the policy identifier. V1 is an explicit historical
reader, not the current writer. No database, API route, rule, matching decision,
or network boundary changes. Error messages identify the field and policy class
without echoing its financial value.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Ruff 0.15.22, and Mypy
2.3.0. Python 3.14 remains outside the declared 3.11/3.12 support matrix.

P0-005 remains in progress. The signature closure condition is satisfied, but
21 classified legacy financial compatibility-reader lines still need additive
strict interfaces, internal migration, explicit deprecation evidence, and
supported-version/live-backend gates before the task can close.

## E-024: Versioned financial-input policy and first strict-reader migration

Implemented boundary:

- Canonical amount parsing defines `legacy-financial-input-v1` and current
  `strict-financial-input-v2`. Strict v2 rejects Python and NumPy floating
  scalars before text conversion; exact Decimal/integer/plain text still follows
  existing finite, scientific-notation, separator, and currency-precision rules.
- Legacy v1 preserves the historical shortest-text finite-value result and emits
  `LegacyFinancialInputWarning` only after successful validation. A lock-protected
  call-site registry emits once even when the host selects an `always` filter;
  errors never echo the financial value.
- `parse_exact_amount` and `parse_exact_amount_for_currency_precision` are the
  additive strict entry points. Existing parser defaults remain v1 until a
  documented breaking release; `CURRENT_FINANCIAL_INPUT_POLICY` is v2.
- Official dataset coercion now uses strict v2. Programmatic floating cells become
  visible invalid/raw values; CSV/XLSX readers already supply source text and
  retain their exact lexeme path.
- Reconciliation tolerance comparisons use strict v2 because configuration has
  already stored the value as Decimal. Signature-v2 text canonicalization also
  uses the strict entry point. PyYAML configuration explicitly names legacy v1
  and its accepted finite compatibility use warns.
- Hostile Decimal context, built-in/NumPy finite/non-finite values, unknown policy,
  no-value error disclosure, currency precision, exact types, warning deduplication,
  raw data-quality retention, v1 compatibility, and current-policy selection have
  direct regressions.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Financial policy/readers/signature/matching/config focused suite | 41 passed; one expected deduplicated config warning | 2.480s |
| Documentation/claim-boundary suite before final evidence append | 16 passed | 2.153s |
| Final full suite with repository-local basetemp | 734 collected; 724 passed, 10 skipped, 0 failed; 8 disclosed warnings | 123.01s |
| `python -m ruff check .` | Pass | 0.266s |
| `python -m mypy reconforge` | Pass, 207 files | 1.619s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.221s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.601s |
| `python -m pip_audit` | No known installed-package vulnerabilities after recorded E-019 environment remediation; local package skipped | 13.171s |
| `python -m build --no-isolation` | Pass; wheel and sdist include the input-policy implementation | 14.793s |
| Float-ledger assertion | Pass: 76 total; the added line is the strict policy detector; legacy classification remains 21 | <1s |

Regression history retained rather than hidden:

- The first complete run before warning deduplication passed 723 tests with 10
  skips but emitted 100 warnings. This was functionally green but rejected as
  noisy deprecation behavior.
- After call-site deduplication, the next complete run had two failed tests
  (`722 passed, 10 skipped`) because they expected repeated warnings from the
  already-seen configuration call site. The dedicated once-per-call-site test
  already covered the new contract; the two compatibility tests were corrected
  to assert their values without demanding a second warning.
- The final run passed once with 724 tests and 10 skips. No flaky retry or product
  exception was used.

Compatibility/security boundary: strict v2 is additive and is current for new
internal work; parser defaults remain v1. Official direct-coercion treatment of a
floating scalar intentionally changes from valid amount to visible data quality.
The warning registry stores source filename/line only in process memory, is
thread-safe, and never records input values. No DB, API route, matching strategy,
network, or authorization boundary changes.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Ruff 0.15.22, and Mypy
2.3.0. Python 3.14 remains outside the declared 3.11/3.12 support matrix.

P0-005 remains in progress. The parser policy and first internal group are
complete; stock/GL and platform matching public boundaries, Money/scalar helpers,
variance, anonymizer, generator, Studio, and per-run ingress-policy evidence still
require staged migration and supported-version/live-backend verification.

## E-025: Persisted reconciliation ingress policy and strict current writers

Implemented boundary:

- Stock/GL matching, its candidate predicates, risk amount reads, exception
  identity, and result contract now receive one validated
  `financial_input_policy`. Direct Python callers retain explicit legacy-v1
  compatibility; Pandas/DuckDB engines, stock/GL CLI workflows, Studio, and
  enterprise-demo writers select strict v2.
- Strict stock/GL binary amounts become source-visible data-quality exceptions;
  exact text/Decimal input retains deterministic match/exception output.
  `EngineResult` and `StockGLReconciliationResult` expose the applied policy,
  and DuckDB rejects inconsistent partition policies before merging.
- `MatchingService.run` and `match_records` expose the policy. Local run and
  rule JSON, completion audit metadata, and the transactional outbox payload
  persist it. Reusing an idempotency key with another policy fails closed.
- The local CLI and synthetic benchmark are strict writers. JSON numeric amounts
  become matching data-quality exceptions; CSV text amounts continue through
  the exact path.
- New PostgreSQL reconciliation submissions require strict v2 and canonicalize
  exact non-negative tolerance text. A JSON binary numeric tolerance or explicit
  legacy request is rejected before queueing. The worker reads the stored
  policy, while historical rules with no field retain legacy-v1 semantics.
- Stock/GL JSON/Excel evidence and management packs record policy. Management
  pack output advances to schema v2; the closed JSON Schema also validates
  historical schema v1 only when the policy field is absent.
- ADR 0041 and D-022 define compatibility and rollback. The classified lexical
  ledger now has 74 source hits: 21 timing, 9 synthetic presentation, 7
  suggestion/versioned-signature, 13 generic, 7 rejection guards, and 17
  legacy financial compatibility lines.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final policy/API/worker/report/engine focused suite | 11 passed | 5.654s |
| Documentation, schema, claim, and module-registry suite | 27 passed | 4.111s |
| Final full suite with repository-local basetemp | 740 collected; 730 passed, 10 skipped, 0 failed; 9 disclosed warnings | 123.90s (125.705s process wall time) |
| `python -m ruff check .` | Pass | 0.113s |
| `python -m mypy reconforge` | Pass, 207 files | 0.532s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.087s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 4.412s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 43.191s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 14.258s |
| Wheel/sdist policy-file assertion | Pass for Money, stock/GL, platform matching, PostgreSQL API, and worker modules | <1s |
| Backlog YAML and float-ledger assertions | Pass; P0-005 remains in progress and actual source count equals documented 74 | <1s |

Regression history retained rather than hidden:

- The first selected command named two nonexistent test files and stopped before
  collection; the corrected filenames were then used.
- The next focused attempt used the unreadable Windows global pytest directory
  and failed during `tmp_path` setup. All subsequent focused and full runs used
  explicit new paths under `output/`; this was an environment-unavailable
  attempt, not a product failure or flaky retry.
- The first new policy suite had one expectation error because the established
  exception contract uses `Left`/`Right`, not lowercase. The contract was
  preserved and the assertion corrected.
- The first artifact suite correctly rejected the new management-pack root field
  against closed schema v1. The writer was advanced to schema v2 and the schema
  gained an explicit v1 compatibility branch; the final report/schema tests pass.

Compatibility/security boundary: public Python defaults and historical rules
remain legacy v1 and warning-bearing; current product writers are strict v2.
Unsupported policies and exact-amount errors do not echo supplied financial
values. No schema migration was required because local and PostgreSQL matching
rules already persist versioned JSON. API routes and result fields are additive
except that new server submissions intentionally reject explicit legacy policy
and binary numeric tolerances. No network, authorization, or write-back scope was
expanded.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Ruff 0.15.22, and Mypy
2.3.0. Python 3.14 remains outside the declared 3.11/3.12 support matrix. Docker
and live PostgreSQL/Redis/object-storage gates remain unavailable and are not
claimed by the ten skips.

P0-005 remains in progress. Seventeen classified legacy compatibility lines,
supported Python versions, live backends, and the remaining public-default
migration/rollback boundaries still prevent closure.

## E-026: Canonical multiset duplicate identity and source-location semantics

Implemented boundary:

- Stock/GL inputs now receive a canonical record fingerprint plus an instance
  identifier. Equivalent copies are numbered as one deterministic multiset
  (`#occurrence:1`, `#occurrence:2`, ...), carry duplicate ordinal/count, and
  produce distinct match and data-quality exception identifiers. Reserved
  `_reconforge_*` fields are removed before public-ingress identity/location
  calculation.
- Source location is evidence rather than identity. Stock/GL and local CSV data
  use one-based data position and `tabular-header-offset-v1` physical row (first
  data row 2). Local JSON uses record position with no tabular row. Hosted or
  in-memory canonical records lacking trusted location retain null position/row
  under `source-location-unavailable-v1`; query order is not invented as source
  evidence.
- Exception IDs and deterministic decision digests exclude mutable source
  location. Relocating one invalid row preserves its exception and record
  instance IDs while reporting the new row. Identical copies cannot be mapped
  to one physical copy after permutation; ADR 0042 limits the claim to the
  stable multiset of occurrence identifiers.
- `reconciliation-signature-v3` is the Pandas/DuckDB writer. It retains v2's
  exact financial-field rules, includes record-instance/duplicate identity,
  and excludes source row. Explicit v1/v2 remain historical replay contracts.
  Engine results expose the record-identity policy, and DuckDB rejects mixed
  partition policies before merging.
- The deterministic platform matcher exposes and persists record identity in
  decision/data-quality lineage. Local rules, completion audit metadata, and
  transactional outbox payloads record the selected policy; idempotency replay
  across policies fails. Current CLI/benchmark/enterprise-demo writers select
  canonical v1. Historical missing-policy worker rules remain labeled
  `row-order-occurrence-legacy-v0`.
- New PostgreSQL API runs require canonical v1 and reject an explicit legacy
  policy before queueing. Stock/GL JSON and Excel output and the management pack
  record the policy. Management-pack output advances to closed schema v3, with
  explicit schema-v1/v2 compatibility branches that reject fields those
  historical versions did not contain.
- ADR 0042 and D-023 define identity limits, compatibility, and rollback.
  P0-007 is complete for this bounded matcher slice. P0-006 remains open for
  additional matching strategies and supported backend/version matrices.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final identity/signature/platform/API/worker/report focused suite | 128 passed, 1 live-PostgreSQL skip, 5 disclosed warnings | 24.34s |
| Documentation, schema, claim, and module-registry suite | 28 passed | 4.04s |
| Final full suite with repository-local basetemp | 746 collected; 736 passed, 10 skipped, 0 failed; 9 disclosed warnings | 128.54s (130.437s process wall time) |
| `python -m ruff check .` | Pass | 0.202s |
| `python -m mypy reconforge` | Pass, 207 files | 0.657s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.190s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.672s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 16.126s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 15.239s |
| Wheel/sdist signature-v3 and record-identity assertions | Pass | <1s |
| `reconforge doctor`; sample validate; local demo | Pass; 0 validation errors, 10 documented warnings, schema-v3 management pack produced | 10.8s combined |
| Backlog/schema parse and float-ledger source count | Pass; 74 source hits remain classified | <1s |

Regression history retained rather than hidden:

- The first broad focused command named test files not present in this
  repository and stopped before collection; the corrected real filenames were
  then used.
- The next attempt hit the unreadable Windows global pytest temp directory in
  fixture setup. Repository-local basetemp paths were used for every subsequent
  run; this was recorded as environment-unavailable rather than product
  success/failure.
- That attempt also exposed a real decision-signature drift: hosted record
  sequence was being presented as source location. The contract was corrected
  to explicit unavailable nulls when no trusted location exists, restoring full
  output permutation invariance without discarding known local-file rows.
- The first new platform duplicate test used an unmigrated in-memory database;
  its fixture was corrected to a migrated temporary DB.
- Mypy rejected a direct comparison between `Integral` and `int` in the NumPy
  source-position compatibility branch. Explicit integer conversion fixed the
  type boundary; final Mypy and all tests pass.

Compatibility/security boundary: single non-duplicate business outcomes retain
their established identifiers; duplicate IDs intentionally change under a
named policy. V1/v2 digests and schema-v1/v2 reports remain explicit readers.
Current server writers reject legacy identity policy, while historical missing
fields are not relabeled. Untrusted reserved lineage fields cannot choose
identity or location. No DB schema migration, network path, permission,
financial approval, or write-back scope was added.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Ruff 0.15.22, and Mypy
2.3.0. Python 3.14 remains outside the declared 3.11/3.12 support matrix.
Docker and live PostgreSQL/Redis/object-storage gates remain unavailable and
are not claimed by the ten skips.

## E-027: Derandomized property-based order invariance

Implemented boundary:

- Hypothesis `6.161.2` is pinned exactly in the development extra only. The
  selected version is the official stable PyPI release published 2026-07-24
  and requires Python 3.10 or newer. Runtime dependencies and public product
  APIs are unchanged; the exact pin and its deliberate-upgrade risk are
  recorded in `DEPENDENCY_RISK.md` and ADR 0043.
- Three deterministic property tests run 35 generated examples each with
  shrinking enabled, `derandomize=True`, no timing deadline, and bounded
  one-to-seven-record inputs. A normal suite run therefore exercises 105
  reproducible examples without claiming load, throughput, or scale evidence.
- Stock/GL signature properties cover all current `standard`, `strict`,
  `aggressive`, and `audit-safe` strategies. Platform properties cover
  one-to-one, many-to-one, one-to-many, and many-to-many grouping modes.
- Generated cases combine duplicate-identical records, malformed amounts,
  missing dates, exact ties, and exact Decimal tolerances. Permuting either
  side preserves canonical decisions, exceptions, record-instance identities,
  and the reconciliation digest for the bounded contracts.
- A separate relocation property proves the identity/location boundary:
  moving an invalid source row preserves its exception and record-instance
  identifiers while the trusted data position and physical row change.
- ADR 0043 and D-024 define reproduction, shrinking, compatibility, and
  rollback. P0-008 is complete for this bounded logical contract. P0-006 and
  P0-009 remain open for supported Python/Pandas/DuckDB version matrices,
  broader backend parity, and cross-engine digest evidence beyond current
  fixed examples.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final property suite | 3 passed; 105 derandomized generated examples across every current stock/GL strategy and platform grouping mode | 11.94s |
| Documentation, schema, claim, and module-registry suite | 27 passed | 5.449s wall time |
| Final full suite with repository-local basetemp | 749 collected; 739 passed, 10 skipped, 0 failed; 9 disclosed warnings | 139.04s (141.075s process wall time) |
| `python -m ruff check .` | Pass | 0.274s |
| `python -m mypy reconforge` | Pass, 207 files | 0.672s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.256s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.370s |
| `python -m pip_audit` | No known installed-package vulnerabilities, including Hypothesis 6.161.2; local package skipped because it is not on PyPI | 3.733s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 14.545s |
| Wheel/sdist development-extra assertion | Pass; exact `hypothesis==6.161.2` pin is present in both artifacts | <1s |
| Backlog YAML, float-ledger, and worktree assertions | Pass; 74 source hits; 154 tracked status entries and 124 untracked entries | <1s |

Regression history retained rather than hidden:

- The first property run passed all three functional properties but Ruff
  rejected the test module's import grouping. Imports were corrected and the
  final property, Ruff, Mypy, and full-suite gates pass.
- Strategy/mode coverage was then expanded from the first bounded cases to all
  four currently implemented stock/GL strategies and all four platform
  grouping modes before the final recorded run. No functional counterexample
  was suppressed or converted to `xfail`.

Compatibility/security boundary: Hypothesis is test-only and introduces no
network call, telemetry, production parser, authorization, approval, or
write-back behavior. Generated fixtures are synthetic and bounded. Exact
dependency pinning is not a complete lockfile or transitive reproducibility
claim. These properties do not prove performance, every supported dependency
version, live PostgreSQL behavior, or every future matching strategy.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, Pandas
3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 remains outside
the declared 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage gates remain unavailable and are not claimed by
the ten skips.

## E-028: Bounded CSV-level Pandas/DuckDB output parity

Implemented boundary:

- A new derandomized property writes bounded synthetic stock/GL CSVs and runs
  original plus permuted inputs through Pandas, DuckDB full scan, and forced
  DuckDB partition execution. Ten generated examples plus two explicit
  regressions cover equivalent duplicates, malformed amounts, missing dates,
  exact ties, and ordinary matches through the real file-reader boundary.
- The compared contract includes signature-v3 digest/version, strict financial
  input policy, canonical record-identity policy, input/match/exception counts,
  and ordered summary rows. Example sizes remain one to seven records per side;
  this is correctness evidence, not a volume or throughput measurement.
- The first generated run minimized a real difference to one exact pair:
  signatures, policies, and counts agreed, but partition aggregation sorted
  summary metrics alphabetically while Pandas/full scan used the established
  domain order. DuckDB partition merging now reindexes aggregates to the six
  existing domain metrics in that established order.
- Signature v3 and financial decisions did not change. The observable
  partitioned-summary row order intentionally changes to match the default
  engine contract. ADR 0044 and D-025 define compatibility and rollback.
- P0-009 is now in progress rather than planned. This slice proves the local
  Python 3.14.6/Pandas 3.0.3/DuckDB 1.5.5 combination only; declared Python
  3.11/3.12, reviewed dependency bounds, golden dense-ambiguity/multi-currency
  inputs, and broader backends remain exit work.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final property suite | 4 passed; existing 105 matcher examples plus 10 generated engine cases and 2 explicit engine regressions | 16.832s wall time |
| Engine/signature/property focused suite | 41 passed; 1 disclosed legacy-input warning | 26.359s wall time |
| Documentation, schema, claim, and module-registry suite | 27 passed | 4.536s |
| Final full suite with repository-local basetemp | 750 collected; 740 passed, 10 skipped, 0 failed; 9 disclosed warnings | 148.021s wall time |
| `python -m ruff check .` | Pass | 0.125s |
| `python -m mypy reconforge` | Pass, 207 files | 0.567s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.093s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.578s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 12.652s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 14.296s |
| Wheel/sdist E-028 assertions | Pass; wheel contains summary-order fix and exact dev pin; sdist also contains the generated property | <1s |
| Backlog YAML, float-ledger, collection, and worktree assertions | Pass; P0-009 in progress, 74 source hits, 750 collected, 154 tracked status entries and 125 untracked entries | <9s combined |

Regression history retained rather than hidden:

- The first 20-example engine property failed after 135.173s and shrank to
  `([0], [0], [0], [0])`. Inspection proved equal signature v3 and counts but
  different summary ordering. The product merger was corrected; the assertion
  was not weakened to unordered comparison.
- Ruff also rejected constant-name `getattr` calls in the first test helper.
  The helper now accepts typed `EngineResult` and uses direct attributes.
- After retaining two explicit boundary examples, the expensive file/connection
  property was bounded to ten generated examples. The three pure matcher
  properties remain at 35 examples each. This limit is documented and no
  minimized functional counterexample was suppressed.
- The first manual BACKLOG assertion used a nonexistent `items` key after YAML
  parsing succeeded. The command was corrected to the repository's `tasks`
  structure and P0-009 status verification passes.

Compatibility/security boundary: summary metric names/counts and signature v3
are unchanged. Only forced-partition summary row order changes from alphabetical
to the established domain order. Tests use synthetic local temporary files and
make no network call. No database schema, authorization, approval, financial
write, or external connector behavior changed. The local version proof is not a
support-matrix, scale, crash/recovery, or live PostgreSQL claim.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, Pandas
3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 remains outside
the declared 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage gates remain unavailable and are not claimed by
the ten skips.

## E-029: Versioned golden finance dataset registry

Implemented boundary:

- Closed schema v1 and `tests/golden/finance_registry.v1.json` now freeze two
  explicitly synthetic stock/GL cases: the existing workshop sample and a new
  exact/duplicate/malformed amount-and-date/JPY/cross-currency boundary case.
- Each case records semantic version, exact Decimal configuration, required
  engines, repository-relative file paths, byte counts and SHA-256 values,
  expected row/match/exception counts, the domain-ordered six-metric summary,
  signature v3, strict financial-input policy, and canonical multiset identity
  policy.
- Integrity is layered: input-file SHA-256, canonical expected-output digest,
  case digest, and registry digest. The verifier uses sorted compact ASCII JSON
  for canonical digest bytes, validates the JSON Schema, rejects paths escaping
  the repository, and verifies every referenced byte before engine execution.
- Both cases run through Pandas, DuckDB full scan, and forced DuckDB partition
  execution. The workshop case records signature
  `4812aded0f8bedb41b78623652ee0833f2431881c72d61208b0d550fa2f6a0ad`;
  the focused boundary case records
  `9c0890143ed07c249f2ff88d5206415e3dd524e58e9595879ed982a06c484841`.
- `docs/testing/golden-finance-datasets.md` prohibits customer data and silent
  expected-output rewrites, requires versioning and governing ADRs, separates
  input/output review, and disclaims performance/support-matrix inference.
- `MANIFEST.in` includes the registry, schema, policy, and all referenced CSVs
  in sdist. Direct archive inspection proves those artifacts are absent from the
  runtime wheel. ADR 0045 and D-026 govern updates and rollback.
- P0-010 meets its bounded exit evidence and is complete. P0-009 remains open
  for declared Python/Pandas/DuckDB version coverage, denser ambiguity, and
  crash/resume parity.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Initial golden registry/schema focused suite | 8 passed | 2.387s wall time |
| Final golden/schema/documentation suite | 32 passed | 5.351s wall time |
| Final full suite with repository-local basetemp | 755 collected; 745 passed, 10 skipped, 0 failed; 9 disclosed warnings | 146.268s wall time |
| `python -m ruff check .` | Pass | 0.115s |
| `python -m mypy reconforge` | Pass, 207 files | 0.519s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.111s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.242s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 3.527s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 14.105s |
| Direct archive inventory assertion | Pass; eight governed golden source artifacts present in sdist and absent from runtime wheel | <1s |
| Backlog, collection, float-ledger, inventory, and worktree assertions | Pass; P0-010 complete, 755 collected, 74 source hits, 207 source/96 test/32 schema/45 ADR files, 154 tracked status entries and 131 untracked entries | <8s combined |

Regression history retained rather than hidden:

- The first repository inventory measurement counted 44 ADR files before ADR
  0045 itself was added. A post-edit measurement returned 45 and the inventory
  was corrected before the final gates.
- The first E-029 evidence insertion matched a repeated environment-tail context
  and placed E-029 before E-028. The sections were reordered with a patch and
  heading-order/diff/documentation gates pass.
- No golden functional counterexample was suppressed, no expected output was
  rewritten after a failing engine run, and no skip/xfail was added. The only
  optional skip remains the pre-existing DuckDB dependency guard for
  environments that do not install that engine.

Compatibility/security boundary: runtime APIs, wheel contents, signature v3,
and matching decisions are unchanged. The existing synthetic sample is frozen
by reference rather than copied. The new bytes are small, synthetic, and contain
no credential, customer, or reversible private mapping. Checksums are integrity
aids, not signatures, accounting validation, certification, realism, volume, or
live-backend evidence.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, Pandas
3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 remains outside
the declared 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage gates remain unavailable and are not claimed by
the ten skips.

## E-030: Schema-validated normalized risk governance

Implemented boundary:

- `docs/risk-register.yaml` is now the normative schema-v1 source for every
  existing risk R-001 through R-017. The public Markdown table remains the
  readable narrative and must contain exactly the same unique IDs.
- Every normalized risk has a role-based owner, concrete trigger, likelihood,
  impact, calculated inherent rating, status, implemented mitigations,
  repository-contained evidence paths, residual rating/rationale, next actions,
  cadence, and next review date. Role labels do not assert named staffing.
- The fixed matrix multiplies likelihood 1-4 by impact 1-4 and maps 1-3 Low,
  4-7 Medium, 8-11 High, and 12-16 Critical. Tests recompute inherent ratings
  and forbid residual ratings above inherent ratings.
- The verifier enforces sequential R-001..R-017 IDs, unique titles, closed JSON
  Schema with ISO dates, next-review dates within the declared cadence, safe
  evidence paths that exist inside the repository, and Markdown/YAML ID parity.
- `MANIFEST.in` includes the normalized YAML, schema, and Markdown narrative in
  sdist. Direct archive inspection confirms they remain absent from the runtime
  wheel. ADR 0046 and D-027 govern replacement/rollback.
- P0-011 meets its exit evidence and is complete. This is repository risk
  governance, not proof of staffed ownership, completed review, effective
  controls, an independent assessment, a GRC product, or certification.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Initial risk/schema focused suite | 7 passed | 1.806s wall time |
| Final risk/schema/documentation suite | 31 passed | 4.871s wall time |
| Final full suite with repository-local basetemp | 759 collected; 749 passed, 10 skipped, 0 failed; 9 disclosed warnings | 146.274s wall time |
| `python -m ruff check .` | Pass | 0.117s |
| `python -m mypy reconforge` | Pass, 207 files | 0.478s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.104s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.357s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 10.799s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 14.560s |
| Direct risk-governance archive assertion | Pass; YAML/schema/Markdown present in sdist and absent from runtime wheel | <1s |
| Backlog, collection, float-ledger, inventory, and worktree assertions | Pass; P0-011 complete, 759 collected, 74 source hits, 207 source/97 test/33 schema/46 ADR files, 154 tracked status entries and 135 untracked entries | <8s combined |

Regression history retained rather than hidden:

- The first parallel post-documentation command had a JavaScript orchestration
  syntax error and executed no nested command. It changed no file and provided
  no gate result; the corrected invocation then passed all intended checks.
- The schema/rating/evidence tests passed on their first execution. No risk was
  deleted, accepted, downgraded after a failed test, or assigned to a named
  person. No skip/xfail was added.

Compatibility/security boundary: all 17 existing Markdown risk IDs and
narratives remain. Runtime code, APIs, database schemas, and wheel contents are
unchanged. The normalized source references repository evidence; it does not
embed secrets, customer data, vulnerability exploit details, or external
network calls. A passing schema does not mean a risk is mitigated or accepted.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, Pandas
3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 remains outside
the declared 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage gates remain unavailable and are not claimed by
the ten skips.

## E-031: Evidence-bounded maturity labels

Implemented boundary:

- `docs/execution/MATURITY_POLICY.yaml` is now the schema-v1 policy for public
  product wording and runtime module maturity ceilings. It links the product
  ceiling and every module ceiling to an exact row in the Claims Evidence
  Matrix rather than treating an implementation file as proof of maturity.
- All nine current runtime module IDs are covered exactly once and capped at
  Experimental. The three prior Beta descriptors (`platform.core`,
  `reconciliation.core`, and `mapping.profiles`) were downgraded because the
  repository has no approved evidence-backed Beta gate for them.
- Seven named publishing surfaces are checked for evidence-bounded language.
  The policy requires at least one explicit Alpha/early/evaluation/foundation,
  local-first, or pilot boundary and rejects unqualified release, scale,
  certification, compliance, and superiority phrases.
- Tests validate the closed JSON Schema, exact claim references, complete module
  coverage, maturity rank, a synthetic unsupported Beta promotion, and all seven
  publishing surfaces. The general claim-boundary guide remains separately
  tested and is intentionally not treated as publishable product copy.
- `MANIFEST.in` includes the maturity policy and schema in the source
  distribution. Direct archive inspection proves both are absent from the
  runtime wheel and that the wheel contains nine Experimental and zero Beta
  runtime descriptors. ADR 0047 and D-028 govern promotion and rollback.
- P0-012 meets its current exit evidence. This is a ceiling against unsupported
  wording, not proof that Alpha or Experimental software is release-ready,
  enterprise-ready, compliant, certified, or independently validated.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Initial maturity/schema/module focused suite | 21 passed | 4.596s wall time |
| Final maturity/documentation/governance suite | 33 passed | 5.272s wall time |
| Final full suite with repository-local basetemp | 763 collected; 753 passed, 10 skipped, 0 failed; 9 disclosed warnings | 148.189s wall time |
| `python -m ruff check .` | Pass | 0.135s |
| `python -m mypy reconforge` | Pass, 207 files | 0.549s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.110s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.082s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 2.213s |
| `python -m build --no-isolation` | Pass; wheel and sdist | 13.442s |
| Direct maturity-governance archive assertion | Pass; policy/schema present in sdist and absent from wheel; wheel has 9 Experimental and 0 Beta descriptors | <1s |
| Backlog, collection, inventory, and worktree assertions | Pass; P0-012 complete, 763 collected, 207 source/98 test/34 schema/47 ADR files, 155 tracked status entries and 139 untracked entries | <8s combined |

Regression history retained rather than hidden:

- Early read-only helper invocations contained a PowerShell quote error or a
  nonexistent guessed test filename and therefore produced no archive or test
  result. Corrected commands used an in-memory Python script and actual
  repository test names.
- One corrected focused run executed seven tests before Windows denied access to
  the global pytest temporary root during fixture setup. The same intended suite
  passed with a verified repository-local `--basetemp`; the final full suite had
  already passed with the same local-temp discipline. This was an environment
  setup incident, not converted into a product pass or failure.
- The post-gate parallel output was truncated by the orchestrator, so every gate
  was rerun with bounded output and recorded above. No skip, xfail, network call,
  or weakened assertion was introduced.

Compatibility/security boundary: module IDs, dependencies, permissions,
capabilities, local-first flags, and runtime behavior remain unchanged. The
descriptor type still accepts Beta/Stable for future evidence-backed promotions;
`reconforge modules list --maturity beta` now truthfully returns an empty set.
There is no database/API schema migration, external service call, customer data,
secret, or authorization change in this slice. Rollback restores the three
labels and removes the policy/schema/gate, but doing so would restore unsupported
public metadata.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, Pandas
3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 remains outside
the declared 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage gates remain unavailable and are not claimed by
the ten skips.

## E-032: Bounded unresolved equal-cost matching

Implemented boundary:

- `stable-tie-break-v1` remains the exact default assignment path. The opt-in
  `unresolved-equal-cost-v1` policy partitions each work-order candidate graph
  into connected components and refuses a component when another assignment has
  the same cardinality and aggregate integer cost.
- Non-uniqueness is proven by excluding each selected edge and resolving again.
  The proof is bounded at 64 candidates and 32 alternate-edge checks; larger
  components fail closed with `search_budget_exceeded`. No brute-force
  enumeration, timing-based cutoff, random seed, or approximate financial
  approval was introduced.
- Every unresolved source record remains counted exactly once in the existing
  stock/GL unmatched frames but is classified `ambiguous_match`. Evidence carries
  stable group ID, reason, candidate count, optimum cardinality/cost, ambiguity
  policy, multiset identity, source location, risk/workflow metadata, and a
  deterministic exception ID. A unique EUR pair still matches beside the dense
  3x3 USD and 2x2 JPY ambiguity components.
- `StockGLReconciliationResult`, `EngineResult`, CLI JSON/workbook metadata,
  management-pack configuration/audit evidence, and Management Pack schema v4
  record the selected policy. The closed schema continues to validate v1/v2/v3
  only under their historical field contracts and rejects a v4 policy field in
  v3.
- Golden registry 1.1.0 contains three ordered cases. Its dense case has signature
  `cdfb89883b491920dcbd52a27a19003275ffea6e87b9219d059b7d2b67a9d914`;
  the registry digest is
  `5b11613b34ff578c7b2754c361389690887518ac24ac85640babdb31ed0ea88e`.
  Original/permuted Pandas, DuckDB full scan, and forced partition outputs agree
  on signature, policies, counts, and ordered summary.
- Signature v3 remains a decision/exception digest, not a full rules digest. The
  expected/case/registry layers bind the policy externally. ADR 0048 and D-029
  define this limitation, compatibility boundary, and rollback.
- P0-009 remains in progress because Python 3.11/3.12/dependency matrices and
  durable crash/resume evidence are still open. This is bounded one-to-one
  evidence, not true grouped many-to-many, a live-backend result, or a scale
  claim.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Early unchanged-behavior matcher/engine suite | 54 passed | 29.638s wall time |
| Golden ambiguity focused suite | 35 passed | 18.955s wall time |
| Final ambiguity/golden/property/report/CLI suite | 64 passed | 25.579s wall time |
| Post-ledger ambiguity/schema/governance regression | 47 passed | 8.648s command wall time; pytest 6.58s |
| Final full suite with repository-local basetemp | 768 collected; 758 passed, 10 skipped, 0 failed; 9 disclosed warnings | 149.399s command wall time; pytest 147.39s |
| `python -m ruff check .` | Pass | 0.111s |
| `python -m mypy reconforge` | Pass, 207 files | 0.583s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.096s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.264s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 11.859s |
| `python -m build --no-isolation` after manifest remediation | Pass; wheel and sdist | 13.212s |
| Direct archive assertion | Pass; registry 1.1.0, dense CSVs, golden/management schemas in sdist only; ambiguity runtime in wheel | <1s |
| `reconforge doctor`; sample validate; local demo | Pass; 0 validation errors, 10 warnings, schema-v4 management pack with stable policy | 10.500s combined |
| Backlog, collection, inventory, and worktree assertions | Pass; P0-009 in progress, 768 collected, 207 source/99 test/34 schema/48 ADR files, 157 tracked status entries and 141 untracked entries | <8s combined |

Regression history retained rather than hidden:

- The first implementation split both policies into graph components. Registry
  regeneration exposed changed historical signatures despite equal counts. The
  compatibility policy was restored to the original whole-work-order assignment
  path, and the no-ambiguity result path avoids concatenating empty ambiguity
  frames. Both frozen signatures returned exactly to
  `4812aded0f8bedb41b78623652ee0833f2431881c72d61208b0d550fa2f6a0ad`
  and `9c0890143ed07c249f2ff88d5206415e3dd524e58e9595879ed982a06c484841`.
- Early Ruff found a local lambda/import-order issue and Mypy found an overly
  broad test-helper annotation; both were corrected without changing runtime
  behavior. No skip or weakened assertion was added.
- The first Management Pack compatibility fixture changed its version to v1 but
  accidentally retained the v4 ambiguity field. The closed schema rejected it;
  the fixture now removes later-version fields and separately proves v3 rejects
  the v4 field.
- Initial archive inspection showed Management Pack schema v4 absent from the
  sdist. `MANIFEST.in` now includes it explicitly; the rebuilt archive assertion
  passes. The runtime wheel remains free of docs and golden fixtures.

Compatibility/security boundary: default inputs, historical match selection,
signature v3, record identity, summary order, database/API schemas, and network
behavior are unchanged. Config/result policy fields are additive. Management
Pack current output advances from v3 to v4 with explicit v1/v2/v3 readers. The
new fixture and examples are synthetic and local; no customer data, secret,
telemetry, external call, autonomous approval, or unbounded combinatorial search
was introduced.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, Pandas
3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 remains outside
the declared 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage gates remain unavailable and are not claimed by
the ten skips.

## E-033: Bounded Lease-Based Crash/Resume Contract

Implemented boundary:

- The existing managed-failure regression remains: an ordinary matcher
  exception becomes `Failed`, explicit requeue returns it to `Queued`, and the
  retry skips its committed checkpoint. E-033 adds the distinct abrupt-control
  path without changing runtime code or database schemas.
- A test-only `BaseException` terminates execution immediately after the first
  partition transaction has returned. It bypasses the worker's intentional
  `Exception` failure handler, leaving the run `Running`, owned by worker A, at
  attempt one with exactly one result and one immutable checkpoint.
- The repository test double now models an active versus expired lease and
  asserts that the production claim SQL contains both the queued predicate and
  `execution_lease_until <= now()`. Worker B is rejected before expiry. After
  only the deterministic test clock advances, it claims attempt two, reads the
  checkpoint set, and yields only the remaining partition.
- The resumed and uninterrupted runs use the same four synthetic inputs and run
  identifier. Their input-manifest hash, result-set hash, and complete partition
  output-hash multiset match exactly. The resumed run has two unique result IDs,
  two unique checkpoint keys, one partition per attempt, and no duplicate
  business effect.
- ADR 0049 and D-030 distinguish this bounded control-flow verification from a
  process kill, connection-loss-at-commit case, live PostgreSQL durability test,
  supported-version matrix, RTO/RPO exercise, or deployment-supervisor proof.
  `P1-PLAT-004` remains planned for those broader gates; P0-009 remains open only
  on its declared Python/Pandas/DuckDB version matrix.
- The worker runtime remains in wheel and sdist. The crash regression is
  sdist-only and ADR 0049 is repository-only under the current manifest; none of
  those packaging facts are recovery evidence.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Targeted checkpoint/managed-retry/crash contract | 4 passed, 10 deselected | 3.590s command wall time; pytest 0.59s |
| Complete PostgreSQL reconciliation contract file | 13 passed, 1 live-service skip, 1 known warning | 2.401s command wall time; pytest 0.89s |
| Worker/repository/API/migration/benchmark/governance suite | 60 passed, 2 skipped, 3 known warnings | 14.417s command wall time; pytest 12.37s |
| Final full suite with repository-local basetemp | 769 collected; 759 passed, 10 skipped, 0 failed; 9 disclosed warnings | 157.48s pytest time |
| Post-ledger PostgreSQL/schema/maturity/risk/docs regression | 29 passed, 1 live-service skip, 1 known warning | 2.755s command wall time; pytest 1.03s |
| `python -m ruff check .` | Pass | 0.266s |
| `python -m mypy reconforge` | Pass, 207 files | 0.661s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.211s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.516s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 16.127s |
| `python -m build --no-isolation` | Pass; wheel and sdist with existing setuptools warnings | 15.814s |
| Corrected direct archive boundary assertion | Pass; worker in wheel+sdist, crash test sdist-only, ADR 0049 repository-only | <1s |
| Collection, inventory, and worktree assertions | Pass; 769 collected, 207 source/99 test/34 typed-schema/49 ADR files, 157 tracked status entries and 142 untracked entries | <8s combined |

Regression history retained rather than hidden:

- The first targeted crash contract passed before the SQL binding assertion was
  added. The test double was then tightened to require the actual queued and
  expired-lease predicates, and the complete file, focused suite, and full suite
  all passed afterward.
- The first archive assertion incorrectly assumed Python test files were absent
  from the sdist and therefore failed after a successful build. Direct archive
  inspection established the actual manifest boundary; the corrected assertion
  proves the crash test is sdist-only and ADR 0049 is repository-only. No build
  failure or runtime-package defect was relabeled.
- The pre-existing live PostgreSQL test remains one of the ten environment
  skips. No new skip, `xfail`, retry-until-pass loop, weakened digest assertion,
  or fake live-service result was introduced.

Compatibility/security boundary: production worker/repository code, SQL,
migrations, API and CLI contracts, runtime dependencies, network behavior, and
financial decisions are unchanged. The test uses synthetic values only and does
not spawn a process, mutate a live database, use credentials, or bypass tenant
authorization. A deterministic test clock is not evidence about real clock
skew, database time, process supervision, or crash consistency during commit.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, Pandas
3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 remains outside
the declared 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage gates remain unavailable and are not claimed by
the ten skips.

## E-034: Reviewed No-Skip Supported Engine Matrix

Implemented boundary:

- The general CI matrix already named Python 3.11 and 3.12, but installed only
  the `dev` extra. Optional DuckDB tests could therefore skip in both cells.
  The new dedicated `engine-parity` job has four explicit, non-allow-failure
  cells and installs the optional engine rather than inferring parity from a
  skip-capable full-suite job.
- `supported-engine-parity-v1` is a closed JSON-Schema contract over Python
  3.11/3.12 and two reviewed direct-dependency profiles: lower-bounds uses NumPy
  1.26.4, Pandas 2.2.0, and DuckDB 1.0.0; current-compatible-2026-07-25 uses
  NumPy 2.4.3, Pandas 3.0.5, and DuckDB 1.5.5. Its canonical digest is
  `54777b4e1e92dfc675665ff55168507f2a9aa5b1415b2b4806f4fd99925a4aed`.
- Official PyPI JSON reviewed on 2026-07-25 records release URLs,
  `Requires-Python`, upload timestamps, and nonzero CPython 3.11/3.12 wheel
  counts. NumPy 2.5.1 is newer but requires Python 3.12; 2.4.3 is the newest
  reviewed version supporting both declared Python cells. These dated pins are
  not automatic latest versions or permanent upper support bounds.
- Each CI cell requires binary distributions, verifies the resolved
  NumPy/Pandas/DuckDB versions, and runs the five named signature, relation and
  partition, property, bounded-ambiguity, and golden-registry test files. A
  captured pytest summary containing any skip makes the job fail. Checkout and
  setup actions remain full-SHA pinned.
- Repository tests validate the closed schema and canonical digest, exact Python
  classifiers and dependency floors, all four CI tuples, version verification,
  binary-only install, no-skip guard, required test files, action pins, and
  golden registry 1.1.0 digest.
- This machine has only Python 3.14.6. Pip resolver simulations found compatible
  Linux wheels for all four direct profiles, and the same five-file command
  passed locally without skips, but neither is execution evidence for Python
  3.11/3.12. No GitHub run URL or remote cell result exists in this ledger;
  P0-009 remains in progress.
- The matrix/schema/guide/test are source-distribution governance artifacts and
  are absent from the runtime wheel. The CI workflow and ADR 0050 are
  repository-only under the current manifest.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Official PyPI JSON metadata review | Selected NumPy/Pandas/DuckDB versions expose the recorded Python requirements, upload times, and CPython 3.11/3.12 wheels | 21.726s across three read-only queries |
| Matrix/schema/workflow contract, first and final focused runs | 6 passed on each run | 0.81s then 0.35s pytest time |
| Pip binary resolver simulation after platform-tag correction | Four direct profiles resolve: lower on manylinux2014; current-compatible on manylinux 2.28 | 14.307s investigative wall time |
| Exact five-file parity command on disclosed local non-support environment | 51 passed, 0 skipped, 1 known warning | 27.831s command wall time; pytest 26.35s |
| Final full suite with repository-local basetemp | 772 collected; 762 passed, 10 skipped, 0 failed; 9 disclosed warnings | 158.32s pytest time |
| Post-ledger matrix/schema/maturity/docs regression | 15 passed | 2.151s command wall time; pytest 0.38s |
| `python -m ruff check .` | Pass | 0.258s |
| `python -m mypy reconforge` | Pass, 207 files | 0.634s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | <1s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.538s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 12.810s |
| Final `python -m build --no-isolation` | Pass; wheel and sdist with existing setuptools warnings | 14.109s |
| Direct archive and canonical-digest assertion | Pass; matrix/schema/guide/test sdist-only; workflow/ADR repository-only | <1s |
| Collection, inventory, and worktree assertions | Pass; 772 collected, 207 source/100 test/35 typed-schema/50 ADR files, 157 tracked status entries and 145 untracked entries | 4.281s combined |

Regression history retained rather than hidden:

- Initial inspection found only Python 3.14 installed and no uv/tox/nox. The
  supported cells were not emulated by relabeling the local runtime or by
  downloading interpreters outside the repository workflow.
- The first resolver command proved both lower cells, then failed the current
  profile because the diagnostic requested the obsolete manylinux2014 tag.
  Official wheel filenames showed the modern releases use compatible
  manylinux-2.28 compound tags. Repeating current profiles with the correct tag
  passed; no dependency pin was weakened to hide the diagnostic error.
- The first manifest draft left NumPy floating. Review found latest NumPy 2.5.1
  drops Python 3.11, so lower/current-compatible profiles now pin 1.26.4/2.4.3
  and require binary distributions to avoid ABI/source-build drift.
- The first local parity invocation returned dots but no exit code or session ID
  from the tool. Process inspection found no running pytest; the complete command
  was rerun with measured output and passed 51 tests. The incomplete result is
  not counted as evidence.
- No remote workflow was triggered because these changes and their prerequisite
  matching slices are uncommitted inside the explicitly dirty multi-slice
  worktree. A configured workflow is not reported as an executed gate.

Compatibility/security boundary: runtime dependency declarations, application
code, financial outputs, APIs, database schemas, and default network behavior
are unchanged. The new network activity occurs only in CI dependency
installation from the configured package index. The repository metadata review
used public PyPI JSON and no credentials, customer data, secrets, telemetry, or
production system. Direct pins do not constitute hash-locked supply-chain
integrity, transitive reproducibility, platform-wide support, or a release claim.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage gates remain unavailable and are not claimed by
the ten skips. The four GitHub engine-parity cells remain unexecuted evidence.

## E-035: Strict Scalar Helper Compatibility Perimeter

Implemented boundary:

- Added `round_exact_money`, `exact_money_difference`, and
  `within_exact_tolerance`. Each enters through strict-financial-input-v2 and
  rejects Python/NumPy binary floating-point before conversion while retaining
  existing exact rounding semantics for text, integers, and `Decimal`.
- Kept `round_money`, `money_difference`, and `within_tolerance` unchanged as
  warning legacy-v1 public compatibility readers. This is a staged migration,
  not an undocumented breaking change or a claim that the residual public
  readers were removed.
- Platform amount buckets now use exact rounding directly. Rule and period
  boundaries isolate their still-compatible parsing and pass only `Decimal`
  values into exact scalar arithmetic. An AST inventory fails if any production
  module outside `utils/money.py` calls a legacy scalar helper name.
- ADR 0051 and D-032 define rollback and compatibility. The lexical audit
  remains exactly 74 classified lines, including 17 public legacy financial
  compatibility lines. P0-005 therefore remains in progress for `Money`
  construction/operators and the named ingress readers.
- Wheel and sdist contain the strict scalar runtime functions. The extended
  financial-input test is sdist-only; ADR 0051 is repository-only under the
  current manifest. These packaging facts prove distribution boundaries only.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Corrected targeted scalar/rule/period/platform suite with repository basetemp | 72 passed, 0 failed, 2 disclosed warnings | 17.224s command wall time |
| Post-documentation scalar/rule/period/platform/maturity/matrix suite | 79 passed, 0 failed, 1 disclosed warning | 17.575s command wall time |
| Final full suite with repository-local basetemp | 775 collected; 765 passed, 10 skipped, 0 failed; 9 disclosed warnings | 146.34s pytest time |
| `python -m ruff check .` | Pass | 0.136s |
| `python -m mypy reconforge` | Pass, 207 files | 2.299s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.115s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.105s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package not audited as a published dependency | 8.814s |
| `python -m build --no-isolation` | Pass; wheel and sdist with existing setuptools warnings | 14.601s |
| Direct archive assertion | Pass; exact helpers in wheel+sdist, extended test sdist-only, ADR 0051 repository-only | <1s |
| YAML, lexical, inventory, and worktree assertions | Pass; backlog has 50 tasks, float audit remains 74, and inventory is 207 source/100 test/35 schema/51 ADR files with 157 tracked and 146 untracked status entries | <2s combined |

Regression history retained rather than hidden:

- The first combined targeted run found no scalar logic failure: 15 tests not
  requiring a temp fixture executed, but subsequent fixtures hit `WinError 5`
  while scanning the already unreadable global pytest directory. The identical
  72-test command passed using a new repository-local basetemp.
- The first Ruff target found one import-order issue in the new test and fixed
  it mechanically before the passing targeted and full runs.
- The first backlog/count diagnostic parsed YAML successfully but then used the
  nonexistent key `items`; the actual schema key is `tasks`. The corrected
  assertion reports 50 tasks and the unchanged 74-line lexical audit. This was
  a diagnostic-script error, not a backlog or application failure.
- One parallel pip-audit invocation returned no process result after its
  30-second wrapper boundary. Process inspection found no surviving Python
  process, so a complete measured invocation was run and passed. The incomplete
  result is not evidence.
- The first post-ledger combined assertion invoked unavailable PowerShell
  `ConvertFrom-Yaml`. Its independent E-001 through E-035 sequence check was
  valid, but its zero backlog count was not. The corrected PyYAML assertion
  below is the only post-ledger backlog-count evidence.

Compatibility/security boundary: no API name was removed, no persisted schema,
digest, database record, or financial decision format changed, and the existing
legacy warning behavior remains. The AST guard covers repository production
Python calls, not arbitrary third-party dynamic invocation. Tests use synthetic
values only; no credentials, customer data, live services, network calls, or
production mutation were involved.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; the ten skips and the four
unexecuted GitHub engine-parity cells are not treated as passing runtime proof.

## E-036: Strict Money Construction and Scalar Operations

Implemented boundary:

- Added `Money.from_exact`, `Money.multiply_exact`, and `Money.divide_exact`.
  They select strict-financial-input-v2 and reject Python/NumPy floating scalars
  before construction, multiplication, or division. Exact text, integer, and
  `Decimal` behavior, currency rounding, and zero-division rejection remain.
- Preserved the public constructor default and scalar dunder operators as
  legacy-v1 compatibility contracts. Successful binary-float construction now
  emits the existing deduplicated deprecation warning instead of suppressing it;
  invalid and strict-rejected inputs do not emit a false acceptance warning.
- Extended the E-035 AST perimeter: all three production `Money(...)` calls
  outside the money module must include `input_policy=` explicitly. Current
  stock/GL and reconciliation callers already satisfy the rule, so writer policy
  remains versioned rather than inferred from a default.
- ADR 0052 and D-033 retain public-default removal for a breaking-release
  migration. The lexical inventory remains 74 classified source lines and 17
  public legacy compatibility lines, so P0-005 remains in progress.
- The strict factory/methods are in wheel and sdist. The extended existing test
  is sdist-only and ADR 0052 is repository-only; legacy constructor/operator
  compatibility remains part of the runtime package.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Targeted Money/input-policy/currency suite | 36 passed, 0 failed, 5 disclosed legacy warnings | 4.812s command wall time |
| Post-documentation Money/input-policy/currency/maturity suite | 40 passed, 0 failed, 5 disclosed legacy warnings | 5.014s command wall time |
| Final full suite with repository-local basetemp | 776 collected; 766 passed, 10 skipped, 0 failed; 12 disclosed warnings | 147.86s pytest time |
| `python -m ruff check .` | Pass | 0.134s |
| `python -m mypy reconforge` | Pass, 207 files | 0.551s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.112s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.187s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package not audited as a published dependency | 12.756s |
| `python -m build --no-isolation` | Pass; wheel and sdist with existing setuptools warnings | 14.927s |
| Direct archive assertion | Pass; strict Money factory/methods in wheel+sdist, extended test sdist-only, ADR 0052 repository-only | <1s |
| YAML, lexical, inventory, and worktree assertions | Pass after correction; 50 backlog tasks, 74 float lines, 207 source/100 test/35 schema/52 ADR files, 157 tracked and 147 untracked status entries | <2s combined |

Regression history retained rather than hidden:

- The first post-documentation backlog parse failed because the new YAML list
  item began with an unquoted Markdown backtick. The entry was changed to a
  quoted plain scalar; PyYAML then parsed all 50 tasks and the 74-line lexical
  assertion passed. No invalid backlog state is counted as evidence.
- The warning count intentionally rises from nine to twelve in the full suite.
  The three added locations are the reconciliation `Money` constructor and the
  stock/GL left/right Money constructors. Their finite-float compatibility was
  already present but previously suppressed its migration warning; no new float
  acceptance was introduced.
- No skip, xfail, retry-until-pass loop, output-digest change, or weakened
  financial assertion was added.

Compatibility/security boundary: existing Money constructor/operator values,
serialization schemas, currency policy/digests, reconciliation evidence, APIs,
database schemas, and network behavior are unchanged. This slice adds named
strict methods and warning visibility. The AST test covers static repository
constructor calls, not arbitrary third-party dynamic invocation. Tests use
synthetic values only and no credentials, customer data, or live services.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; the ten skips and the four
unexecuted GitHub engine-parity cells are not passing runtime proof.

## E-037: Versioned Studio Amount-Filter Ingress

Implemented boundary:

- Split exact current `AmountFilterInput` from explicit
  `LegacyAmountFilterInput`. The latter retains the single classified float
  annotation required by the direct Python compatibility window.
- Added a named financial-input policy to the minimum-amount parser and
  exception filter. Direct service calls retain warning legacy-v1 behavior;
  strict v2 rejects binary floats before threshold comparison.
- The Studio application now selects strict v2 explicitly. Its HTML form and
  OpenAPI query parameter remain bounded plain text, and existing invalid,
  negative, non-finite, scientific, and overlong input rejection remains.
- The AST compatibility perimeter now fails if a production
  `_filter_exceptions` call omits `financial_input_policy`. The only application
  call passes strict v2. This is read-only presentation state; it does not
  approve, persist, or affect reconciliation evidence/digests.
- ADR 0053 and D-034 preserve direct service compatibility until a breaking
  release. The source audit remains 74 classified lines and 17 legacy financial
  compatibility lines, so P0-005 stays in progress.
- Runtime Studio code and both aliases are in wheel and sdist. The extended
  Studio test is sdist-only and ADR 0053 is repository-only.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Targeted Studio/review/input-policy/CLI suite | 60 passed, 0 failed, 2 disclosed warnings | 10.150s command wall time |
| Post-documentation Studio/review/input-policy/CLI/maturity suite | 64 passed, 0 failed, 2 disclosed warnings | 10.336s command wall time |
| Final full suite with repository-local basetemp | 777 collected; 767 passed, 10 skipped, 0 failed; 12 disclosed warnings | 147.88s pytest time |
| `python -m ruff check .` | Pass | 0.124s |
| `python -m mypy reconforge` | Pass, 207 files | 0.549s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.107s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.339s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package not audited as a published dependency | 3.422s |
| `python -m build --no-isolation` | Pass; wheel and sdist with existing setuptools warnings | 15.075s |
| Direct archive assertion | Pass; strict application selection/legacy alias in wheel+sdist, Studio test sdist-only, ADR 0053 repository-only | <1s |
| YAML, lexical, inventory, and worktree assertions | Pass; 50 backlog tasks, 74 float lines, 207 source/100 test/35 schema/53 ADR files, 157 tracked and 148 untracked status entries | <2s combined |

Regression history retained rather than hidden:

- No product or documentation regression was found in this slice. The initial
  60-test suite, post-documentation 64-test suite, and final full suite passed
  without a retry or alternate implementation.
- The direct finite-float compatibility assertion captures its deprecation
  warning. The final warning count remains twelve because current Studio HTTP
  calls are strict and introduce no new uncaptured compatibility location.
- No skip, xfail, database write, filter-result persistence, digest change,
  retry-until-pass loop, or weakened invalid-input assertion was added.

Compatibility/security boundary: the HTTP/OpenAPI/form contract, direct legacy
service result, exception data, review state, routes, databases, audit, and
reconciliation artifacts are unchanged. Strict filtering only affects an
ephemeral page query. Invalid responses do not echo the rejected threshold.
Tests use synthetic data and no credentials, customer data, network calls, or
live services.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; the ten skips and four
unexecuted GitHub engine-parity cells are not passing runtime proof.

## E-038: Versioned Anonymizer Financial-Input Policy

Implemented boundary:

- Split exact current `AmountNoiseInput` from `LegacyAmountNoiseInput`, and
  threaded a named financial-input policy through percentage parsing,
  deterministic factor caching, frame/cell masking, and directory generation.
- Direct Python service defaults remain legacy-v1. A finite float warns and a
  schema-v2 manifest records legacy policy; strict v2 rejects the same value
  before creating an output directory. The CLI passes strict v2 explicitly and
  the AST perimeter rejects production calls that omit the policy.
- Advanced the current anonymization manifest writer from v1 to v2. V2 requires
  `financial_input_policy` and includes it in the policy/manifest digests. The
  verifier and closed JSON Schema retain v1 as an implicit-legacy historical
  reader; the checked-in v1 example and original digests remain unchanged.
- Amount algorithm version, seed/PRNG, factor scale, source-scale rounding,
  output hashes, private-map separation, and privacy boundary are unchanged.
  This is parser provenance, not a privacy or realism assurance.
- ADR 0054 and D-035 govern compatibility and rollback. The lexical inventory
  stays at 74 classified lines and 17 legacy financial compatibility lines, so
  P0-005 remains in progress.
- Runtime v1/v2 reader/current writer are in wheel and sdist. The schema and
  extended tests are sdist-only after an explicit manifest include; ADR 0054 is
  repository-only.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Corrected targeted anonymizer/input-policy/CLI suite | 50 passed, 0 failed, 1 disclosed unrelated config warning | 7.747s command wall time |
| Post-documentation anonymizer/input-policy/CLI/maturity suite | 54 passed, 0 failed, 1 disclosed unrelated config warning | 8.011s command wall time |
| Final full suite with repository-local basetemp | 778 collected; 768 passed, 10 skipped, 0 failed; 11 disclosed warnings | 149.18s pytest time |
| `python -m ruff check .` | Pass | 0.123s |
| `python -m mypy reconforge` | Pass, 207 files | 0.639s |
| `git diff --check` | Pass; existing `.gitignore` LF/CRLF warning only | 0.111s |
| `python -m bandit -q -r reconforge` | Pass, no findings; three existing justified B608 notices | 5.192s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package not audited as a published dependency | 22.333s |
| Final `python -m build --no-isolation` after manifest correction | Pass; wheel and sdist with existing setuptools warnings | 13.633s |
| Direct archive assertion | Pass; runtime v1/v2 code in wheel+sdist, schema/test sdist-only, ADR 0054 repository-only | <1s |
| YAML/schema/lexical/inventory/worktree assertions | Pass; 50 tasks, v1 schema compatibility, 74 float lines, 207 source/100 test/35 schema/54 ADR files, 157 tracked and 149 untracked entries | <2s combined |

Regression history retained rather than hidden:

- The first compound code patch did not apply because one manifest-call context
  differed; `apply_patch` made no partial changes. The implementation was then
  applied in bounded parser, masker, engine, schema, CLI, and test patches.
- The first targeted run found two import-order findings, one Mypy literal-
  narrowing error, and one warning assertion consumed by an earlier test at the
  same deduplicated parser call site. Imports were formatted, the variable was
  annotated as the policy union, and the earlier invalid-value test was changed
  from an unrelated float percentage to exact text. The dedicated service
  compatibility test then became the sole warning assertion and all 50 passed.
- The first documentation patch expected the newer ADR status format, while ADR
  0032 uses a heading/body format. It made no changes; ADR 0054 and the legacy
  ADR status were updated with their actual contexts.
- Initial archive inspection found the updated JSON Schema absent from both
  artifacts under the old manifest. `MANIFEST.in` now includes it in sdist; the
  final rebuild/assertion proves schema/test sdist-only and runtime code in both
  artifacts. The wheel intentionally excludes repository documentation schemas.
- No historical v1 manifest/digest was rewritten, and no skip, xfail, retry-
  until-pass loop, network call, or privacy claim was added.

Compatibility/security boundary: direct service outputs and exact algorithm are
unchanged; v2 digests intentionally add parser policy. V1 artifacts remain
verifiable and imply legacy; they are never relabeled. CLI remains exact text
and now records strict v2. Tests use synthetic files only; no secrets, customer
data, cloud upload, telemetry, or live service is involved.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; the ten skips and four
unexecuted GitHub engine-parity cells are not passing runtime proof.

## E-039: Versioned variance financial-input policy

Implemented boundary:

- Split exact `ThresholdInput` from explicit `LegacyThresholdInput`, and
  threaded `financial_input_policy` through threshold parsing,
  `variance_frame`, and `analyze_variance`. The direct Python default remains
  legacy-v1; finite binary-float input warns and preserves its documented
  shortest-text result. Strict-v2 rejects the same input before source loading
  or output-directory creation.
- The `analyze variance` CLI now selects strict-financial-input-v2 explicitly.
  The production AST perimeter rejects any `analyze_variance` call that omits
  the policy, preventing an internal call from silently inheriting the
  compatibility default.
- Advanced the current report writer from schema v2 to v3 and the nested
  threshold policy from v1 to v2. The canonical threshold-policy digest now
  binds `financial_input_policy` alongside exact thresholds, comparison rules,
  encoding, and display rounding. Changing only the policy fails digest
  verification; unknown policies fail closed without echoing source values.
- Preserved unversioned/v1 and schema-v2 readers. Unversioned/v1 thresholds and
  v2 threshold-policy-v1 artifacts imply legacy-financial-input-v1. A fixed
  historical v2 digest reproduces, while v2 rejects the v3-only policy field
  and v3 requires it. No historical artifact is rewritten or relabeled.
- Preserved exact JSON/CSV lexeme ingestion, unrounded amount comparison,
  division-free percentage comparison, inclusive boundaries, zero-threshold
  semantics, `ROUND_HALF_EVEN` display, result rows, legacy numeric threshold
  keys, and local-only execution. This slice changes provenance, not variance
  arithmetic.
- Added ADR 0055 and D-036; ADR 0031 now identifies only its current-writer
  statement as superseded. Current architecture, claims, drift, schema catalog,
  float ledger, inventory, backlog, quality, and state surfaces reflect v3.
- Added the variance schema to `MANIFEST.in`. Wheel and sdist contain the v3
  runtime writer plus unversioned/v1/v2/v3 reader. The schema and extended
  contract test are sdist-only; ADR 0055 is repository-only. Packaging proves
  distribution contents, not historical strictness or runtime execution.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final targeted variance + financial-input suite with repository-local basetemp | 35 passed, 0 failed | 5.944s command wall time |
| Final post-documentation variance/input-policy/maturity/release-copy suite | 50 passed, 0 failed | 6.180s command wall time |
| Final full suite with repository-local basetemp | 780 collected; 770 passed, 10 skipped, 0 failed; 10 disclosed warnings | approximately 106.97s command wall time |
| `python -m pytest --collect-only` | 780 tests collected | 2.30s pytest time |
| `python -m ruff check .` | Pass | 0.182s |
| `python -m mypy reconforge` | Pass, 207 files | 0.572s |
| `git diff --check` | Pass; existing `.gitignore` line-ending warning only | 0.141s final run |
| `python -m bandit -q -r reconforge` | Pass; no findings, three existing justified B608 `nosec` notices | 4.644s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 15.262s |
| `python -m build --no-isolation` | Pass; wheel and sdist, with existing setuptools metadata warnings | 14.380s |
| Archive membership/content assertion | Pass: runtime in both, schema/test sdist-only, ADR in neither | 1.98s |
| YAML/schema/evidence-sequence assertion | Pass: 50 tasks, variance versions 1/2/3, exact E-001..E-039 order | 0.731s |
| Inventory/worktree assertion | Pass: 207 source files, 100 test files, 35 schemas, 55 ADRs, 157 tracked and 150 untracked entries | <1s |

Observed regressions and environment handling:

- The first targeted run passed Ruff but found one Mypy `Literal` narrowing
  error; the v2 implied-legacy branch variable was explicitly annotated as the
  policy union. The same run produced 15 pytest setup errors because the global
  Windows pytest temp root denied access; no affected test body ran.
- The first repository-local basetemp attempt named a child beneath a missing
  `.test-tmp` parent, producing 15 `FileNotFoundError` setup errors. The parent
  was created explicitly and all affected tests were rerun on new basetemp
  paths; no result from either setup failure is counted as product evidence.
- The first executable strict-service regression expected the lower-level
  `InvalidAmountError`, while the established variance boundary intentionally
  wraps parser failures as safe `ValueError` with the field name. The assertion
  was corrected to the public contract; the strict rejection and no-artifact
  behavior were unchanged.
- The first post-documentation command named a nonexistent
  `tests/test_documentation_links.py`; pytest started no tests. The corrected
  command used the repository's actual maturity/release/copy test files and all
  50 passed. A final repeat after all ledger edits also passed all 50.
- The first evidence-sequence assertion used an over-escaped regex and found no
  IDs. The corrected assertion then exposed that two append attempts using a
  repeated environment footer had matched E-037 and placed E-039 before E-038.
  The block was moved intact using E-038-specific context; the final sequence
  assertion covers E-001..E-039.
- The cleanup command using `Remove-Item -Recurse` was blocked by execution
  policy after read-only absolute-path verification. PowerShell/.NET removed
  only the two verified repository-local basetemp directories; status returned
  to 157 tracked and 150 untracked entries.
- The final warning count falls from E-038's eleven to ten because the variance
  finite-float compatibility warning is now captured by its dedicated test;
  one Starlette deprecation and nine other legacy-input warnings remain visible.
- No skip, xfail, retry-until-pass loop, network call, database migration,
  customer data, or production mutation was added.

Compatibility/security boundary: existing service values, flags, rounding,
report rows, and legacy numeric keys are unchanged. V3 digests intentionally
add parser policy. Historical unversioned/v1/v2 artifacts remain readable and
implicit-legacy; they do not acquire strict provenance. The schema prohibits
cross-version policy relabeling. Inputs and tests are synthetic/local, and safe
errors disclose field/policy identifiers rather than financial values.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; ten skips and four
unexecuted GitHub engine-parity cells remain non-evidence.

## E-040: Versioned synthetic-generator financial-input policy

Implemented boundary:

- Split exact `RateInput` from explicit `LegacyRateInput`, and threaded
  `financial_input_policy` through rate parsing and dataset generation. Direct
  Python calls default to legacy-v1; finite floats warn and retain documented
  shortest-text results. Strict-v2 rejects them before target creation.
- The synthetic-generator CLI now selects strict-financial-input-v2 explicitly,
  and the production AST perimeter rejects calls that omit the selection.
  Internal generated-money and range parsing also use strict-v2 because those
  integer/text/Decimal values are exact by construction.
- Advanced the current manifest writer from schema v1 to v2. V2 requires
  `policy.financial_input_policy` and binds it into policy and manifest SHA-256
  digests. Unknown policies fail closed without echoing the rejected value.
- Preserved schema-v1 verification as implicit legacy-v1. A fixed historical
  v1 manifest with independently frozen policy/manifest/output hashes validates
  and verifies. V1 rejects the future field and v2 rejects its absence; no
  historical bytes or digests are relabeled.
- Proved the algorithm boundary by generating the same seed/rates under a
  legacy float and strict exact text: all eight CSV files are byte-identical.
  Only manifest policy/digests intentionally differ. `exact-decimal-v1`, six-
  decimal draws, scenario selection, currency quantization, LF output, output
  inventory, and the eight-path Python return contract remain unchanged.
- Added ADR 0056 and D-037; ADR 0034 now identifies only its current writer
  statement as superseded. Synthetic/benchmark/changelog/schema docs plus
  architecture, claims, float ledger, backlog, quality, inventory, and state
  surfaces reflect v2 without making realism or performance claims.
- Added the generator schema to `MANIFEST.in`. Wheel and sdist contain the v1/v2
  runtime reader/current writer. Schema and extended contract test are
  sdist-only; ADR 0056 is repository-only. Packaging is not runtime, realism,
  or benchmark evidence.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| First generator/CLI/input-policy/schema suite | 61 passed, 0 failed; one unrelated config compatibility warning | 16.332s command wall time |
| Corrected generator/CLI/input-policy/schema suite | 61 passed, 0 failed; one unrelated config compatibility warning | 16.005s command wall time |
| Final post-documentation generator/CLI/input-policy/schema/maturity suite | 76 passed, 0 failed; one unrelated config compatibility warning | 16.425s command wall time |
| Final full suite with repository-local basetemp | 782 collected; 772 passed, 10 skipped, 0 failed; 9 disclosed warnings | approximately 92.02s command wall time |
| `python -m pytest --collect-only` | 782 tests collected | 2.08s pytest time |
| `python -m ruff check .` | Pass | 0.161s final run |
| `python -m mypy reconforge` | Pass, 207 files | 0.513s final run |
| `git diff --check` | Pass; existing `.gitignore` line-ending warning only | 0.163s final run |
| `python -m bandit -q -r reconforge` | Pass; no findings, three existing justified B608 `nosec` notices | 4.632s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 16.696s |
| `python -m build --no-isolation` | Pass; wheel and sdist, with existing setuptools metadata warnings | approximately 2.01s cached command wall time |
| Archive membership/content assertion | Pass: runtime in both, schema/test sdist-only, ADR in neither | 1.4s |
| YAML/schema/evidence-sequence assertion | Pass: 50 tasks, generator versions 1/2, exact E-001..E-040 order | 0.752s |
| Lexical/inventory/worktree assertion | Pass: 74 float lines, 56 ADRs, 157 tracked and 151 untracked entries | <1s |

Observed regressions and environment handling:

- The first targeted suite passed all 61 tests and Ruff; Mypy alone rejected a
  v1 implied-legacy variable narrowed to one `Literal`. An explicit
  `FinancialInputPolicy` annotation fixed the type without changing runtime,
  and Mypy plus all 61 tests passed on the next run.
- The pre-existing broad generator-rate behavior test used float `0.2` and
  emitted an uncaptured warning. It now uses exact text because it tests outcome
  frequency, while a dedicated compatibility test owns the float warning,
  records legacy policy, proves byte parity against strict text, and proves
  strict-float no-output rejection.
- The final warning count falls from E-039's ten to nine because the generator
  compatibility warning is now captured explicitly. One Starlette deprecation
  and eight other uncaptured legacy-input warnings remain visible.
- Six repository-local basetemp directories were verified by absolute path and
  removed after the targeted, full, and final-documentation gates; status
  returned to 157 tracked and 151 untracked entries. No unrelated user artifact
  was removed.
- No skip, xfail, retry-until-pass loop, network call, customer data, database
  migration, generator distribution claim, or production mutation was added.

Compatibility/security boundary: equivalent canonical inputs preserve all CSV
bytes and service results; only v2 provenance/digests differ intentionally.
Schema-v1 remains readable and implicit-legacy, never strict. Validation occurs
before target creation, paths remain local, hashes use the standard library,
and errors disclose policy/field identifiers rather than submitted values.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; ten skips and four
unexecuted GitHub engine-parity cells remain non-evidence.

## E-041: Versioned configuration financial-input policy

Implemented boundary:

- Added a named `financial_input_policy` to `load_config`. Direct Python calls
  retain warning legacy-v1 by default; the six CLI config reads, benchmark
  runner, and server-rendered Studio select strict-financial-input-v2
  explicitly. The production AST perimeter rejects any new implicit
  `load_config` call.
- Added a private `yaml.SafeLoader` subclass for strict-v2. It intercepts the
  standard YAML floating-scalar tag and returns the original scalar lexeme as
  text before Pydantic/`parse_amount` validation. The regression value
  `0.100000000000000005` remains exact under strict-v2; explicit legacy-v1
  retains its historical `0.1` result and call-site-deduplicated warning.
- Passed the selected policy into the existing Decimal field validator through
  Pydantic validation context. Unknown policy fails before path access without
  echoing its submitted value. Non-finite YAML scalars fail validation, and an
  arbitrary Python object tag is rejected and wrapped as safe YAML error.
- Quoted `amount_tolerance` in the repository default and documented exact-text
  guidance. `write_default_config` already serializes the Decimal through JSON
  mode and now has an executable assertion that safe YAML reads its output as
  text. Historical unquoted `2.0` configs remain accepted by current strict
  callers without binary conversion.
- Added ADR 0057 and D-038; ADR 0040 now marks only its application-config item
  as superseded. Changelog, architecture, configuration guide, claims, float
  ledger, backlog, quality, inventory, and state surfaces describe the bounded
  migration without claiming a signed/digested config artifact.
- Reduced the lexical source audit from 74 to 73 lines and the classified
  compatibility category from 17 to 16. The single `config.py` occurrence is
  the standard YAML tag identifier used to preserve text, not amount
  arithmetic. Direct `ReconForgeConfig`/`load_config` defaults remain explicit
  compatibility work, so P0-005 stays in progress.
- Wheel and sdist contain the runtime config reader. The new contract test is
  sdist-only; ADR 0057 and the repository default config are in neither. This
  packaging boundary does not prove configuration signing, digest provenance,
  supported-Python execution, or removal of the direct legacy default.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final config/input-policy/CLI/benchmark/Studio/docs suite | 109 passed, 0 failed | 15.25s pytest time |
| Final full suite with repository-local basetemp | 791 collected; 781 passed, 10 skipped, 0 failed; 8 disclosed warnings | 148.88s pytest time |
| `python -m pytest --collect-only` | 791 tests collected | 2.28s pytest time |
| Final config/input-policy/maturity/release-doc suite | 34 passed, 0 failed | 1.17s pytest time |
| `python -m ruff check .` | Pass | 0.225s final run |
| `python -m mypy reconforge` | Pass, 207 files | 0.639s final run |
| `git diff --check` | Pass; existing `.gitignore` line-ending warning only | 0.208s final run |
| `python -m bandit -q -r reconforge` | Pass; no findings, three existing justified B608 `nosec` notices | 5.109s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 13.628s |
| `python -m build --no-isolation` | Pass; wheel and sdist, with existing setuptools metadata warnings | approximately 11s command wall time |
| Archive membership/content assertion | Pass: config runtime in both, dedicated test sdist-only, ADR/default repository config in neither | <1s |
| Lexical/inventory/worktree assertion | Pass: 73 float lines, 207 source files, 101 test files, 35 schemas, 57 ADRs, 158 tracked and 153 untracked entries | 1.1s including verified temp cleanup |

Observed regressions and environment handling:

- The first broad target used `.codex-test-tmp/e041-target` before its parent
  existed. Windows fixture setup therefore failed with `WinError 3`; this was
  an invocation/environment error, not a product result. The parent was then
  created explicitly and every subsequent distinct repository-local basetemp
  run completed.
- That first run also showed a flawed new assertion expecting every direct
  model construction to warn. The warning contract intentionally emits once
  per source call site, and all config validation reaches one validator line.
  The dedicated first legacy-loader regression now owns the warning assertion;
  later compatibility tests assert values rather than demanding duplicate
  warnings. A second run exposed the same mistaken expectation on the default
  loader test; it was corrected before the 99-test, 109-test, and full-suite
  passes.
- The final warning count falls from E-040's nine to eight because the new
  config compatibility regression captures that validator call-site warning.
  One Starlette deprecation and seven other uncaptured legacy-financial-input
  warnings remain visible.
- The repository-local `.codex-test-tmp` directory was absent before this
  slice, verified at its absolute path inside the workspace, and removed after
  all test runs. Status then measured 158 tracked and 153 untracked entries; no
  unrelated user artifact was removed.
- No skip, xfail, retry-until-pass loop, permissive YAML loader, network call,
  customer data, database migration, configuration signature claim, or
  production data mutation was introduced.

Compatibility/security boundary: current callers preserve exact YAML decimal
text while accepting historical unquoted values; direct Python defaults retain
legacy shortest-text results and warning behavior. The customized loader is a
`SafeLoader` subclass and rejects arbitrary Python tags. This slice does not
version, sign, or digest the config document itself; it changes no API route,
database schema, matching rule, currency policy, or durable output schema.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; ten skips and four
unexecuted GitHub engine-parity cells remain non-evidence.

## E-042: Exact declarative-rule ingress and versioned result provenance

Implemented boundary:

- Moved the ADR-0057 `yaml.SafeLoader`-derived exact-scalar reader into a
  shared utility and routed both config and control-pack loading through it.
  Strict v2 retains the original YAML decimal lexeme before validation;
  arbitrary Python tags remain rejected. ADR 0057 now records the shared
  location rather than claiming the tag handler remains in `config.py`.
- Added a named policy to rule loading, condition/rule evaluation, execution,
  explanation, and control-matrix derivation. Direct Python defaults remain
  warning legacy-v1. CLI validate/list/run/explain, demo, and control-matrix
  paths select strict-financial-input-v2 explicitly; the production AST gate
  rejects future implicit calls across all migrated functions.
- Numeric comparison literals plus tolerance/threshold fields are validated as
  finite Decimal-compatible inputs under the selected policy while preserving
  public `Condition.value` source shape. With a rule literal of
  `0.100000000000000005` and source amount `0.100000000000000004`, strict v2
  preserves the boundary and produces no result; legacy v1 retains historical
  `0.1`, warns, and produces one result. `.nan`, `.inf`, and `-.inf` fail.
- Preserved `run_rule_pack`'s list result and `write_rule_results`' unversioned
  `{"results": [...]}` v1 output. Added current `RulePackExecution` and v2
  writer/reader/verifier. The CLI and demo now write v2; historical v1 reads as
  `legacy-unverified` without manufactured policy or provenance.
- V2 records the selected policy, normalized executable `pack.yml`/`rules.yml`
  digest, sorted base-name/byte/SHA-256 records for all input CSVs, result count,
  deterministic decision digest, full artifact digest, and an explicit trust
  boundary. The decision digest excludes only `triggered_at`; the artifact
  digest covers timestamps. CSV rows repeat policy/pack/decision provenance.
- Hash input files before and after evaluation and fail before output if they
  change. Validate execution policy/digest before creating the output
  directory. The verifier detects decision/timestamp tampering and can rehash
  the local input directory plus reload the pack under the recorded policy.
- Added the closed v1/v2 `rule_results.schema.json`, included it and the new
  contract test in sdist, and documented the CLI artifact. These content
  digests are explicitly not signatures, pack approvals, audit opinions,
  compliance certifications, or proof of source-system authenticity.
- Added ADR 0058 and D-039. Changelog, README, architecture, rule-pack guide,
  schemas guide, claims, float ledger, backlog, quality, inventory, and state
  surfaces now describe the bounded migration. P0-005 remains in progress
  because direct/public defaults and 16 classified compatibility lines remain.
- Wheel and sdist contain the shared YAML helper plus rule runtime
  reader/writer/verifier. The schema and dedicated contract test are sdist-only;
  ADR 0058 is in neither. Packaging proves distribution boundaries, not signed
  provenance, supported-Python execution, or source authenticity.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final rule/input-policy/CLI/control-matrix/schema/docs suite | 80 passed, 0 failed | 7.11s pytest time |
| Final full suite with repository-local basetemp | 804 collected; 794 passed, 10 skipped, 0 failed; 7 disclosed warnings | 150.68s pytest time |
| `python -m pytest --collect-only` | 804 tests collected | 2.03s pytest time |
| `reconforge rules run` sample smoke | Pass; 3 triggered controls, v2 JSON/CSV written | 2.583s |
| Runtime v2 reader plus local pack/input re-verification | Pass: schema 2, `verified`, 3 results, strict-v2 | 1.2s command wall time |
| `python -m ruff check .` | Pass | 0.244s final run |
| `python -m mypy reconforge` | Pass, 208 files | 0.628s final run |
| `git diff --check` | Pass; existing `.gitignore` line-ending warning only | final assertion under 1s |
| `python -m bandit -q -r reconforge` | Pass; no findings, three existing justified B608 `nosec` notices | 4.832s final run |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 14.585s |
| `python -m build --no-isolation` | Pass; wheel and sdist, with existing setuptools metadata warnings | approximately 2s command wall time |
| Archive membership assertion | Pass: rule/YAML runtime in both, schema/test sdist-only, ADR in neither | <1s |
| Lexical/inventory/worktree assertion | Pass: 50 backlog tasks, 73 float lines, 208 source files, 102 test files, 36 schemas, 58 ADRs, 164 tracked and 157 untracked status entries | <1s plus verified temp cleanup |

Observed regressions and environment handling:

- The first existing control-matrix target exposed that operator validation now
  raises `ValueError` before Pydantic. The matrix wrapper only translated
  `ValidationError`, so one test failed with the raw unsupported-operator text.
  The wrapper now translates both validation exception types to its established
  concise error; the following 58-, 59-, 80-test, and full suites passed.
- One attempted documentation test bundle named nonexistent
  `tests/test_release_docs.py`. Pytest rejected that invocation before
  collection; it is not counted as a product result. The actual
  `test_release_readiness_docs.py`, pilot, website-copy, and maturity gates were
  then selected and passed in the 78-test documentation bundle and final
  80-test bundle.
- The full warning count falls from E-041's eight to seven because the broad
  amount-tolerance rule test now uses exact text; its binary-float behavior is
  owned by the dedicated legacy regression. One Starlette deprecation and six
  other uncaptured compatibility warnings remain visible.
- The repository-local `.codex-test-tmp` contained only this slice's pytest and
  CLI-smoke outputs. Its absolute target was verified as the exact child of the
  workspace, then recursively deleted with the .NET directory API; absence was
  verified before measuring 164 tracked and 157 untracked status entries.
- No skip, xfail, retry-until-pass loop, permissive YAML loader, network call,
  customer data, database migration, pack signature claim, source-authenticity
  claim, or production data mutation was introduced.

Compatibility/security boundary: current CLI/demo rule decisions preserve
exact YAML decimal text and write v2 provenance. Direct Python defaults and the
historical writer remain legacy-v1 compatibility surfaces. V1 is never
relabeled as strict or verifiable. V2 hashes executable pack metadata/rules and
all local CSV bytes, but does not cover other pack documents and provides no
identity/authenticity assurance without a future governed signing boundary.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; ten skips and four
unexecuted GitHub engine-parity cells remain non-evidence.

## E-043: Exact review/period ingress and versioned comparison provenance

Implemented boundary:

- Added a named financial-input policy to exception CSV collection,
  review-register construction/export, and multi-period comparison. Direct
  Python defaults remain warning legacy-v1; current review/compare CLI and demo
  calls select strict-financial-input-v2 explicitly. The production AST gate
  rejects implicit calls across all four migrated functions.
- Strict collection tells pandas to retain CSV fields as strings before Decimal
  validation. Exact `amount_impact` values therefore survive beyond IEEE-754
  precision and malformed values remain absent. The review workbook keeps
  `Review Register` first for compatibility and adds `Report Parameters`
  second with the selected policy.
- Strict fallback fingerprints distinguish `amount=invalid`, `amount=missing`,
  valid `0.00`, and exact values rounded under the explicitly recorded
  two-fractional-digit `ROUND_HALF_UP` compatibility rule. A high-magnitude pair
  on opposite sides of a cent boundary is distinct under strict v2 but collapses
  under the explicit legacy pandas-inference path; malformed versus valid zero
  is no longer recurring under strict v2.
- Advanced current period-comparison JSON to schema v2. It records the parser,
  comparison, rounding, invalid-value, and algorithm policies plus sorted byte/
  SHA-256 fingerprints for every recognized exception CSV and
  `review_state.json`. Inputs are hashed before and after reading and comparison
  fails before output creation if their bytes change.
- Added a path-independent decision digest over policy/configuration, input
  fingerprints, summaries/path-free trends, and sorted category keys. A
  separate artifact digest covers the complete JSON including display paths.
  Equivalent relocated inputs reproduce the decision digest while intentionally
  changing the artifact digest.
- Added a v1/v2 reader and v2 verifier. Historical unversioned JSON is labelled
  schema-v1 `legacy-unverified` without manufactured policy/provenance. V2
  verifies decision and artifact digests and can optionally rehash supplied
  period folders; decision, path, and source-byte tampering regressions fail.
- Added the closed `period_comparison.schema.json`, its package manifest entry,
  and ten dedicated contracts for exact review/period ingress, compatibility,
  workbook/HTML/Markdown policy surfaces, schema, digests, relocation, source
  recheck, CLI strictness, and fail-before-path policy validation.
- Added ADR 0059 and D-040. Changelog, architecture, period guide, schemas
  guide, claims, float ledger, backlog, quality, inventory, and state surfaces
  describe the bounded migration. P0-005 remains in progress because direct/
  public defaults and 16 classified compatibility lines remain.
- Wheel and sdist contain the period/review runtime readers, writer, and
  verifier. The schema and dedicated contract test are sdist-only; ADR 0059 is
  in neither. Packaging proves distribution boundaries, not signatures,
  source-system authenticity, currency-specific period identity, or supported-
  Python execution.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final period/review/input-policy/CLI/schema suite | 71 passed, 0 failed; one existing Starlette warning | 20.837s command wall time |
| Focused final period/review suite | 28 passed, 0 failed; one existing Starlette warning | 9.478s command wall time |
| Final full suite with repository-local basetemp | 814 collected; 804 passed, 10 skipped, 0 failed; 7 disclosed warnings | 157.247s command wall time |
| `python -m pytest --collect-only -q` | 814 tests collected | 4.006s command wall time |
| `python -m ruff check .` | Pass | 0.279s |
| `python -m mypy reconforge` | Pass, 208 files | 1.206s |
| `git diff --check` | Pass; existing `.gitignore` line-ending warning only | 0.319s |
| `python -m bandit -q -r reconforge` | Pass; no findings, three existing justified B608 `nosec` notices | 5.630s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 12.677s |
| `python -m build --no-isolation` | Pass; wheel and sdist, with existing setuptools metadata warnings | 16.447s |
| Archive membership assertion | Pass: period/review runtime in both, schema/test sdist-only, ADR in neither | <1s |
| Lexical/inventory/worktree assertion | Pass: 50 backlog tasks, 73 float lines, 208 source files, 103 test files, 37 schemas, 59 ADRs, 165 tracked and 160 untracked status entries | <1s plus verified temp cleanup |

Observed regressions and environment handling:

- The first workbook-metadata implementation placed `Report Parameters` before
  `Review Register`; two existing consumers that read the default first sheet
  failed. The final writer adds the policy sheet second, preserving the
  compatibility sheet order. The focused 28-test and full suites pass.
- The first new rounding regression used two low-magnitude lexemes that pandas
  3.0.3 did not collapse in this environment, so one assertion failed. The
  minimized replacement crosses the same cent-rounding boundary beyond exact
  IEEE-754 integer precision and proves the intended strict/legacy distinction.
- The first combined target named nonexistent `tests/test_review_state.py`, and
  a later documentation bundle named nonexistent `tests/test_docs_content.py`.
  Both invocations stopped before collection. The actual
  `test_review_workflow.py` and repository documentation/schema gates passed in
  the corrected target and full suite.
- One combined invocation used the inaccessible global Windows pytest temp
  root and produced setup-only `WinError 5` errors. The same selection passed
  with a distinct repository-local basetemp; no product result is inferred from
  the denied setup.
- An early test helper did not allow rewriting its synthetic source during the
  tamper case, and a combined numeric/malformed CSV caused pandas to infer text
  for the whole legacy column. The helper now permits deterministic overwrite,
  and separate recognized CSVs exercise real numeric inference plus malformed
  handling. These were test-fixture corrections, not suppressed product
  failures.
- The final warning count remains seven: one existing Starlette deprecation and
  six uncaptured call-site-deduplicated legacy-financial-input warnings. The
  dedicated period legacy regression captures its warning explicitly.
- The repository-local `.codex-test-tmp` contained only this slice's pytest
  outputs. Its absolute target was verified as the exact child of the workspace,
  then recursively deleted with the .NET directory API; absence was verified
  before measuring 165 tracked and 160 untracked status entries.
- No skip, xfail, retry-until-pass loop, network call, customer data, database
  migration, signature/source-authenticity claim, or production data mutation
  was introduced.

Compatibility/security boundary: current review/period callers preserve exact
CSV lexemes and v2 comparison provenance. Direct Python defaults and historical
unversioned JSON remain explicit legacy-v1 compatibility surfaces; v1 is never
relabeled as strict or verified. V2 hashes recognized local inputs and its own
content but provides no identity/authenticity assurance. The bounded period
fingerprint retains two fractional digits rather than claiming universal
currency precision.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; ten skips and four
unexecuted GitHub engine-parity cells remain non-evidence.

## E-044: Exact client-pack redaction and versioned manifest integrity

Implemented boundary:

- Added a named financial-input policy to amount bucketing and client-pack
  generation. Direct Python defaults retain warning legacy-v1 and the historical
  unversioned manifest. Current CLI/demo paths select strict-financial-input-v2;
  the production AST gate rejects implicit generation or bucket calls.
- Strict redacted JSON decodes decimal/non-standard numeric tokens as their
  source text before recursion. Amount-like values therefore cross no binary
  floating-point boundary before exact buckets; malformed, non-finite, and
  scientific values receive the full-redaction token. Other decimal scalars are
  emitted as strings only in the redacted copy; unredacted files remain byte
  copies and CSV redaction retains exact DictReader text.
- Fixed the existing JSON traversal to apply scalar redaction once. Previously
  it bucketed an amount and then parsed the bucket label a second time, replacing
  valid `0-99`/other buckets with `[AMOUNT_REDACTED]`.
- Advanced current strict `files_manifest.json` to schema v2. It records strict
  parser policy, `client-pack-redaction-v2`, exact bucket boundaries, invalid-
  value behavior, required output-checksum policy, and sorted SHA-256/byte
  fingerprints for every selected source and included output file. Source bytes
  are rechecked after copying before the manifest is written.
- Added a path-independent content digest over tool/policy/settings, relative
  source/output fingerprints, missing/excluded outcomes, and the explicit trust
  boundary. A separate artifact digest covers the complete manifest including
  `generated_at`. Equivalent relocated inputs reproduce the content digest.
- Omitted the operator's local input path from the current handoff summary and
  v2 manifest. Relative names and copied contents remain potentially sensitive;
  redaction is still best-effort and requires human review.
- Added a v1/v2 reader and v2 verifier. Historical unversioned output reads as
  `legacy-unverified` and retains optional hashes. V2 rejects policy/content/
  artifact/path tampering and can rehash the selected source set plus the
  complete output set, detecting missing, modified, unsafe, or unexpected files.
- Current schema-v2 always includes input/output hashes. The CLI
  `--include-manifest-checksums` option remains a compatibility request flag;
  explicit legacy direct calls retain the original optional-checksum effect.
- Added the closed `client_pack_manifest.schema.json`, its source-distribution
  manifest entry, and seven dedicated contracts for exact JSON boundaries,
  schema/policy/hash surfaces, v1 compatibility, manifest/source/output/path
  tampering, relocation-stable content, CLI strict selection, and validation
  before path/output access.
- Added ADR 0060 and D-041. Changelog, architecture, client-pack/redaction/
  integrity guides, case-study wording, schemas guide, claims, float ledger,
  backlog, quality, inventory, and state now describe the bounded migration.
  P0-005 remains in progress for direct/public compatibility and the next
  evidence-binder ingress boundary.
- Wheel and sdist contain client-pack redaction plus v1/v2 writer/reader/
  verifier runtime. The schema and dedicated test are sdist-only; ADR 0060 is in
  neither. Packaging is not proof of redaction completeness, permission to
  disclose, source authenticity, a signature, or supported-Python execution.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final client-pack/input-policy/schema/docs/maturity suite | 50 passed, 0 failed | 11.675s command wall time including Ruff/Mypy/diff |
| Focused client-pack/input-policy/schema suite | 31 passed, 0 failed | 10.146s command wall time including Ruff/Mypy |
| Final full suite with repository-local basetemp | 821 collected; 811 passed, 10 skipped, 0 failed; 7 disclosed warnings | 173.176s command wall time |
| `python -m pytest --collect-only -q` | 821 tests collected | 3.952s command wall time |
| `python -m ruff check .` | Pass | 0.318s |
| `python -m mypy reconforge` | Pass, 208 files | 0.696s |
| `git diff --check` | Pass; existing `.gitignore` line-ending warning only | 0.285s |
| `python -m bandit -q -r reconforge` | Pass; no findings, three existing justified B608 `nosec` notices | 6.005s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 21.218s |
| `python -m build --no-isolation` | Pass; wheel and sdist, with existing setuptools metadata warnings | 18.370s |
| Archive membership assertion | Pass: client-pack runtime in both, schema/test sdist-only, ADR in neither | 1.6s |
| Lexical/inventory/worktree assertion | Pass: 50 backlog tasks, 73 float lines, 208 source files, 104 test files, 38 schemas, 60 ADRs, 168 tracked and 163 untracked status entries | <1s plus verified temp cleanup |

Observed regressions and environment handling:

- The first static pass found one Mypy inference error in the heterogeneous
  manifest payload. Adding an explicit `dict[str, Any]` annotation first caused
  a `no-redef` error across the conditional branches; declaring the variable
  once before both assignments fixed the contract. Final whole-package Mypy
  passes all 208 files.
- The first pytest target ran immediately after E-043's verified temp cleanup;
  its nested basetemp parent did not exist, so six fixture setups returned
  `WinError 3` before product code ran. The exact workspace child parent was
  created, and the same 21-test selection then passed. The setup denial is not a
  product result.
- That retry chained Mypy and pytest without fail-fast, so pytest passed while
  the intermediate Mypy `no-redef` remained visible. The type error was fixed,
  then the 31-test, 50-test, and final full suites plus standalone Mypy all
  passed; the earlier mixed command is not claimed green.
- Test design exposed the existing double-redaction traversal before the exact
  bucket regression could be meaningful. The implementation now visits each
  JSON scalar once, and the strict `99.999999999999999999` case yields `0-99`
  while explicit legacy float decoding warns and yields `100-999`.
- The final warning count remains seven: one existing Starlette deprecation and
  six uncaptured call-site-deduplicated legacy-financial-input warnings. The
  dedicated client-pack legacy regression captures its warning explicitly.
- The repository-local `.codex-test-tmp` contained only E-044 pytest outputs.
  Its absolute target was verified as the exact workspace child, then recursively
  deleted through the .NET directory API; absence was verified before measuring
  168 tracked and 163 untracked status entries.
- No skip, xfail, retry-until-pass loop, network call, customer data, database
  migration, disclosure action, signature/source-authenticity claim, or
  production data mutation was introduced.

Compatibility/security boundary: current CLI/demo client packs use exact
redaction ingress and schema-v2 local byte verification. Direct Python defaults
and unversioned manifests remain legacy-v1; they are never relabeled strict or
verified. Required hashes detect local inconsistency but do not prove redaction
completeness, authorize sharing, authenticate source systems, or sign content.
Redacted JSON intentionally favors exact scalar text over type preservation;
unredacted copies remain byte-identical.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; ten skips and four
unexecuted GitHub engine-parity cells remain non-evidence.

## E-045: Exact evidence-binder ingress and versioned index integrity

Implemented boundary:

- Added a named financial-input policy to risk-score parsing, recognized CSV
  reads, case collection, and evidence-binder generation. Direct Python calls
  retain legacy-v1/schema-v2 compatibility. Current CLI/demo paths select
  strict-financial-input-v2; the production AST gate rejects implicit binder or
  collector policy selection.
- Strict CSV ingress reads fields as text before validation. A source
  `60.000000000000000001` risk score remains fractional, is retained as an
  invalid data-quality case, and preserves its exact source record. Explicit
  legacy pandas inference collapses it to valid `60` and excludes it, emitting
  the migration warning rather than silently claiming strict behavior.
- Preserved the exact schema-v2 top-level index shape for direct legacy
  generation and added a reader that labels it `legacy-unverified`. Current
  strict output advances to schema v3 while retaining `case_count` and `cases`.
- Schema v3 records artifact/tool identity, strict financial-input policy, the
  existing integer 0-100 risk policy, sorted SHA-256/byte fingerprints for all
  recognized exception/match/rule/review inputs, and an explicit integrity
  boundary. The complete recognized set is recomputed before index writing, so
  additions, removals, or byte changes during generation fail closed.
- Added a path-independent content digest over policies, selected input
  fingerprints, and case decisions with per-case generation times excluded. A
  full artifact digest covers the complete index including timestamps.
  Equivalent relocated inputs reproduce the content digest.
- Added a v3 verifier for exact top-level fields, safe unique/sorted paths,
  policies, case model/count consistency, content/artifact digests, and optional
  local source rehashing. The existing evidence manifest remains the generated-
  output checksum inventory; neither artifact supplies identity/authenticity.
- Added the closed `evidence_index.schema.json` v2/v3 contract, its source-
  distribution manifest entry, and seven dedicated regressions for the exact
  CSV boundary, current policy/schema/fingerprints, legacy compatibility,
  policy/timestamp/path/source tampering, relocated content, CLI strict
  selection, and validation before path/output access.
- Added ADR 0061 and D-042. Changelog, architecture, evidence-integrity guide,
  schema guide, claims, float ledger, backlog, quality, inventory, and state now
  describe the bounded migration. P0-005 remains in progress because 16 public/
  direct legacy reader lines require an approved breaking-release boundary.
- Wheel and sdist contain the evidence-binder v2/v3 writer/reader/verifier
  runtime. The schema and dedicated test are sdist-only; ADR 0061 is in neither.
  Packaging is not proof of stable source identity, upstream authenticity,
  evidence completeness, audit approval/opinion, signature, or supported-Python
  execution.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final evidence/input-policy/schema/docs/maturity suite | 103 passed, 0 failed; one existing Starlette plus one explicit legacy warning | 14.230s command wall |
| Initial corrected evidence/review/platform/input-policy suite | 77 passed, 0 failed; same two disclosed warnings | 14.210s command wall including Ruff/Mypy |
| Final full suite with repository-local basetemp | 828 collected; 818 passed, 10 skipped, 0 failed; 8 disclosed warnings | 163.499s command wall time |
| `python -m pytest --collect-only -q` | 828 tests collected by per-file totals | 3.998s command wall time |
| `python -m ruff check .` | Pass | 0.181s |
| `python -m mypy reconforge` | Pass, 208 files | 0.540s |
| `git diff --check` | Pass; existing `.gitignore` line-ending warning only | 0.130s |
| `python -m bandit -q -r reconforge` | Pass; no findings, three existing justified B608 `nosec` notices | 5.315s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local package skipped because it is not on PyPI | 15.617s |
| `python -m build --no-isolation` | Pass; wheel and sdist, with existing setuptools metadata warnings | 17.943s |
| Archive membership assertion | Pass: evidence-binder runtime in both, schema/test sdist-only, ADR in neither | <1s |
| Lexical/inventory/worktree assertion | Pass: 50 backlog tasks, 73 float lines, 208 source files, 105 test files, 39 schemas, 61 ADRs, 168 tracked and 166 untracked status entries | <1s plus verified temp cleanup |

Observed regressions and environment handling:

- The first combined static/pytest run found only an import-order Ruff issue;
  Mypy passed. Pytest then produced setup-only `WinError 3` errors because its
  nested repository basetemp parent did not exist after E-044 cleanup. The
  import was combined, the exact workspace temp parent was created, and the
  same 77-test selection passed. No product result is inferred from denied
  fixture setup.
- The first expanded documentation target named nonexistent
  `tests/test_documentation_links.py`. Pytest stopped before collection, while
  a later chained `git diff --check` made the shell's final code zero. That
  mixed command is not claimed green. The actual pilot/release/website
  documentation gates were selected, fail-fast chaining was added, and the
  corrected 103-test final target passed.
- The dedicated boundary deliberately exercises legacy pandas numeric
  inference, adding one uncaptured `LegacyFinancialInputWarning`. The full
  warning count is therefore eight: one existing Starlette deprecation and
  seven call-site-deduplicated legacy-financial warnings. The current CLI path
  is strict and produces no binder compatibility warning.
- The repository-local `.codex-test-tmp` contained exactly the four E-045
  pytest directories. Its absolute path was verified as the exact workspace
  child, then recursively deleted through the .NET directory API; absence was
  verified before measuring 168 tracked and 166 untracked status entries.
- No skip, xfail, retry-until-pass loop, network call, customer data, database
  migration, source-identity/signature/audit-opinion claim, or production data
  mutation was introduced.

Compatibility/security boundary: current CLI/demo evidence binders use exact
CSV ingress and schema-v3 local input/decision verification. Direct Python
defaults and schema-v2 indexes remain legacy; they are never relabeled strict or
verified. Required hashes detect local inconsistency but do not authenticate an
upstream export, stabilize report-local sequential case IDs, prove evidence
completeness, approve a control decision, sign content, or constitute an audit
opinion. The evidence manifest covers generated output bytes separately and is
also only a local checksum inventory.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; ten skips and four
unexecuted GitHub engine-parity cells remain non-evidence.

## E-046: Remote CI provenance audit and PR failure diagnosis

Read-only audit boundary:

- Resolved the authenticated GitHub context to
  `amrzainmubarak/reconforge-erp`, local branch
  `feature/p0-atomic-audit-outbox`, and open Draft PR #54. No workflow was
  dispatched, rerun, cancelled, edited, or approved.
- Queried the 20 latest CI runs and inspected jobs for the latest branch run and
  latest successful `main` run. Neither contains an `engine-parity` job. A diff
  against `origin/feature/p0-atomic-audit-outbox` confirms the four-cell job is
  an uncommitted local addition; therefore the older general Python 3.11/3.12
  jobs are not lower/current engine-matrix evidence.
- Latest Draft PR run
  `https://github.com/amrzainmubarak/reconforge-erp/actions/runs/30073610042`
  executed at head `45c6573c12dd456c17de41f5774255aea9694cf7` on
  2026-07-24. General Python 3.11 and 3.12, `docker-parity`, separate Docker
  build, Python security, and CodeQL checks passed. The overall CI run failed
  solely at `server-boundaries`.
- The specialist CI inspection script correctly identified the failing job but
  selected an unrelated successful Docker tail from the combined run log.
  Following its documented fallback, the job-specific failed log showed the
  exact cause: Pytest exited 4 before collection because
  `tests/test_postgres_foundation.py` did not exist in the remote head.
- Git history proves local HEAD
  `bdf63de48051a0ef5c694442208f5207f4dd5e1c` is exactly one commit ahead of
  the remote branch. That commit adds the nine PostgreSQL/Redis/Alembic/API test
  files referenced by the server job. This is a plausible missing-file fix, not
  a remote pass: it has not been pushed or executed by GitHub.
- The `gh-fix-ci` workflow requires explicit approval before implementing or
  publishing a CI fix. No push was performed. The much broader dirty worktree
  and uncommitted engine matrix must not be included in an incidental catch-all
  publication.

Evidence:

| Surface | Result |
| --- | --- |
| `gh auth status` / repo and PR resolution | Authenticated account `amrzainmubarak`; Draft PR #54, base `main`, remote head `45c6573` |
| Latest 20 CI runs | No `engine-parity` job/run found; latest branch run failed, latest `main` run `29951140420` succeeded without the new matrix |
| PR #54 checks | Python 3.11 1m54 pass; Python 3.12 2m19 pass; Docker parity 39s pass; Docker build 29s pass; security/CodeQL pass; server boundaries 59s fail |
| Job-specific failed log | `ERROR: file or directory not found: tests/test_postgres_foundation.py`; process exit 4 before test collection |
| Local/remote ancestry | `origin/feature/p0-atomic-audit-outbox...HEAD` = 0 behind, 1 ahead |
| Local fix commit inventory | `bdf63de` adds nine referenced test files, 3,735 lines; unpushed and unverified remotely |
| Local workflow diff vs remote branch | Adds the four-cell `engine-parity` job plus a separate migration-invocation change; not present in any audited run |

Interpretation limits:

- The successful remote Python jobs establish only their general CI commands at
  remote SHA `45c6573`; they do not execute the exact reviewed engine pins or
  no-skip parity contract and cannot close P0-009.
- The successful remote Docker jobs provide useful evidence for SHA `45c6573`
  on GitHub-hosted Ubuntu, not for the current dirty worktree or unavailable
  local Docker daemon.
- The missing test-file diagnosis is definitive for that run, but the unpushed
  commit may expose later test failures after collection. Only a new identified
  run can verify the fix.
- No remote write, local code change, commit, push, customer-data access,
  credential disclosure, or unsupported pass claim occurred in this audit.

## E-047: Evidence-bounded Security Architecture v2

Implemented boundary:

- Added `docs/security/security-architecture.v2.yaml` as the normative closed
  schema-v2 registry. It labels Community Local `implemented-bounded`, Team /
  Server `experimental-bounded`, and Regulated `planned-only`; the Regulated
  mode has no enforced controls.
- Registered six data classes and seven trust boundaries spanning file ingress,
  browser/API requests, local process/storage, the optional tenant PostgreSQL
  server profile, optional network dependencies, artifact disclosure, and
  build/release. References are closed and every boundary has an owner and
  existing evidence path.
- Registered ten role-owned controls with bounded or partial status, purpose,
  applicable boundaries/classes, concrete code/test evidence, and explicit
  limitations. No control is labelled as independently assessed, compliant,
  certified, or production-ready.
- Mapped ten security-relevant residual risks to the normalized risk-register
  source and enforced exact risk ID, owner, and rating parity. The selection
  covers security, identity, privacy, audit, and operations categories without
  duplicating risk scoring in the architecture registry.
- Added a closed Draft 2020-12 JSON Schema and four contract tests covering
  schema/format validity, closed references, existing code/test evidence,
  residual-risk parity, and the required unsupported/planned claim boundary.
- Replaced the readable security-architecture view from the registry and
  corrected API/data-handling prose that had drifted from the bounded server
  profile and optional operator-managed S3 adapter. No ReconForge-hosted cloud
  or public-service assurance was introduced.
- Added schema/source-distribution manifest and CI schema-test entries, ADR
  0062, D-043, DOC-012, and the claims/security/gap/inventory/state records.
  `P0-SEC-001` is complete; module threat-model indexing and official-standard
  mappings remain separate `P0-SEC-002` through `P0-SEC-004` work.
- The YAML registry, readable Markdown, schema, and dedicated test are in the
  sdist and absent from the wheel. ADR 0062 is in neither artifact. E-047 makes
  no runtime, API, database, identity, permission, deployment, or secret change.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Initial security/schema/risk contracts | 15 passed, 0 failed | 0.69s pytest time |
| Broader security/governance/documentation selection | 101 passed, 3 skipped, 0 failed; one existing Starlette warning | 8.97s pytest time |
| Final changed-document contract target | 33 passed, 0 failed | 2.695s command wall time |
| Final full suite with repository-local basetemp | 832 collected; 822 passed, 10 skipped, 0 failed; 8 disclosed warnings | 160.019s command wall time |
| `python -m pytest -o addopts='' --collect-only -q` | Exit 0; 832 tests corroborated by the full-suite collection | 4.442s |
| `python -m ruff check .` | Pass | 0.151s |
| `python -m mypy reconforge` | Pass, 208 files | 0.549s |
| `git diff --check` | Pass; existing `.gitignore` line-ending warning only | 0.128s |
| `python -m bandit -q -r reconforge` | Pass; no findings, three existing justified B608 `nosec` notices | 5.490s |
| `python -m pip_audit` | No known installed-package vulnerabilities | 3.349s |
| `python -m build --no-isolation` | Pass; wheel and sdist, with existing setuptools metadata warnings | 14.964s |
| Archive membership assertion | Pass: architecture YAML/Markdown/schema/test sdist-only; ADR absent from both; none in wheel | <1s |
| Inventory/worktree assertion | Pass: 50 backlog tasks, 73 float lines, 208 source files, 106 test files, 40 schemas, 62 ADRs, 170 tracked and 170 untracked status entries | <1s after verified temp cleanup |

Observed regressions and environment handling:

- The first security-document inventory attempt named nonexistent historical
  `architecture.md`, `data-security.md`, and `deployment-security.md` paths.
  The repository was re-inventoried with `rg --files`; only actual security
  paths were used in the registry. No missing path is presented as evidence.
- Existing prose described cloud storage as wholly unsupported despite the
  optional operator-configured S3-compatible adapter, and the API guide omitted
  the bounded PostgreSQL server profile. Both descriptions were corrected while
  retaining the stronger limitation that no hosted ReconForge cloud or complete
  public deployment is proven.
- The first E-047 cleanup assertion expected four temp children, but pytest had
  already removed two and left only `e047-full` and `e047-target`. The assertion
  stopped before deletion. A second check resolved the absolute target inside
  the workspace, rejected every non-E-047 child name, deleted only that temp
  root through the .NET directory API, and verified absence plus the final
  170/170 worktree counts.
- Ten skipped optional/live-service tests remain non-evidence. The eight full-
  suite warnings are one existing Starlette deprecation plus seven legacy-
  financial-input migration warnings; E-047 adds no runtime warning.
- No skip removal, xfail, retry-until-pass loop, network call, customer data,
  production mutation, credential use, remote write, certification statement,
  or control-effectiveness claim occurred.

Security/claim boundary: this registry makes repository intent and evidence
links mechanically reviewable. It does not verify deployment configuration,
continuous control operation, public-internet hardening, incident response,
backup recovery, tenant isolation under live services, independent assessment,
or alignment with a current official standard. `planned-only`, `partial`, and
`implemented-bounded` are evidence ceilings, not synonyms for secure,
compliant, certified, bank-grade, enterprise-ready, or production-ready.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; ten skips and four
unexecuted GitHub engine-parity cells remain non-evidence.

## E-048: Closed threat-model index for every active module

Implemented boundary:

- Added `docs/security/threat-model-index.v1.yaml` as the normative closed
  module threat source. It is explicitly joined to the runtime module registry,
  Security Architecture v2, and normalized risk register rather than creating
  parallel module/control/risk truth.
- Exact registry contracts cover all nine active modules and require matching
  maturity, capability status, interfaces, data classifications, and at least
  the registry's declared module-test evidence. All remain Experimental and
  every threat model remains `evidence-bounded`.
- Defined eight scoped actors: workspace operator, authenticated user,
  untrusted input provider/API caller/contributor/dependency endpoint, external
  recipient, and browser viewer. Trust statements explicitly limit operator
  and authenticated-user assumptions.
- Defined eight shared threats covering path/parser abuse, financial decision
  manipulation, authentication/authorization/SoD bypass, tenant/dependency
  escape, partial mutation/audit/replay, artifact tamper/disclosure,
  extension/build/egress supply chain, and UI/synthetic confusion.
- Mapped 20 module-specific classified assets and 32 distinct threat cases.
  Every case names an attack surface, one or more architecture controls,
  existing test evidence, exact normalized risk IDs where an appropriate entry
  exists, and limitations. Empty risk links are documented as no exact registry
  entry, never as zero risk.
- Limited case status to `bounded`, `partial`, `deployment-dependent`, or
  `planned` and required every module to retain a non-bounded case, assumptions,
  and out-of-scope capabilities. No case is called fully mitigated.
- Added a closed Draft 2020-12 schema and five contracts for schema/format,
  unique/closed references, existing evidence paths, exact runtime-registry
  parity, residual claim visibility, and readable-view parity.
- Replaced the readable threat-model overview, added ADR 0063 and D-044, and
  updated claims, security/gap/drift/architecture/inventory/backlog/state and
  schema/package surfaces. `P0-SEC-002` closes; current official ASVS/SSDF
  mappings remain independent `P0-SEC-003`/`P0-SEC-004` work.
- The index, readable Markdown, schema, and dedicated test are sdist-only and
  absent from the wheel; ADR 0063 is in neither. E-048 changes no runtime, API,
  persistence, identity, permission, deployment, network, or secret behavior.

Evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final dedicated architecture/threat/maturity target | 13 passed, 0 failed | approximately 2.5s command wall |
| Final broader security/governance/documentation target | 38 passed, 0 failed | 3.141s command wall |
| Final full suite with explicitly created repository-local basetemp parent | 837 collected; 827 passed, 10 skipped, 0 failed; 8 disclosed warnings | 162.205s command wall |
| `python -m pytest -o addopts='' --collect-only -q` | 837 tests collected | 2.60s pytest time |
| `python -m ruff check .` | Pass | 0.129s |
| `python -m mypy reconforge` | Pass, 208 files | 0.540s |
| `git diff --check` | Pass; existing `.gitignore` line-ending warning only | 0.111s |
| `python -m bandit -q -r reconforge` | Pass; no findings, three existing justified B608 `nosec` notices | 5.865s |
| `python -m pip_audit` | No known installed-package vulnerabilities | 14.542s |
| `python -m build --no-isolation` | Pass; wheel and sdist, with existing setuptools metadata warnings | 16.181s |
| Archive membership assertion | Pass: threat index/Markdown/schema/test sdist-only; ADR absent from both; none in wheel | <1s |
| Registry/inventory/worktree assertion | Pass: 8 actors, 8 threats, 9 modules, 20 assets, 32 cases, 50 backlog tasks, 73 float lines, 208 source files, 107 test files, 41 schemas, 63 ADRs, 170 tracked and 174 untracked status entries | <1s after verified temp cleanup |

Observed regressions and environment handling:

- The first static gate found only Ruff import-block formatting in the new
  test. Ruff's single-file formatter removed the excess separation; Mypy was
  already green. The test command had stopped before pytest and was not counted
  as a test pass.
- The next dedicated run correctly failed readable-view parity because the old
  prose threat model did not name `platform.core`. The readable view was
  replaced with all nine module boundaries, then the complete 13-test target
  passed. The failing contract was not weakened.
- The first full-suite timing wrapper returned exit 1 after 37.690s but hid
  pytest details. A new fail-fast run exposed a setup-only `WinError 3`: pytest
  could not create the nested basetemp because its parent had been removed.
  The exact workspace temp parent was created explicitly and the entire suite,
  not merely the remaining tests, then passed in a fresh child.
- After verifying the sole remaining temp child was `e048-full-final` under the
  exact workspace root, the .NET directory API deleted only that temp root and
  verified absence. A combined post-cleanup command then lacked the optional
  PowerShell `ConvertFrom-Yaml` cmdlet, so its zero structural counts were
  discarded; cleanup/status results had already succeeded, and Python/PyYAML
  separately verified the 8/8/9/20/32 structure and final 170/174 counts.
- Ten skipped optional/live-service tests remain non-evidence. The eight full-
  suite warnings are one existing Starlette deprecation plus seven legacy-
  financial-input migration warnings; E-048 adds no runtime warning.
- No skip removal, xfail, retry-until-pass loop, official-standard lookup,
  customer data, production mutation, credential use, network/remote write,
  compliance statement, penetration-test assertion, or threat-mitigation claim
  occurred.

Security/claim boundary: exact module coverage proves that repository threat
intent and linked tests cannot silently omit an active registered module. It
does not prove that controls are configured or operate in a deployment, that
all threats or abuse cases are enumerated, that tests simulate a capable
adversary, that live tenant/dependency isolation works, or that an independent
review occurred. `bounded`, `partial`, `deployment-dependent`, and `planned`
are evidence ceilings, not secure/compliant/certified/bank-grade/enterprise-
ready/production-ready labels.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; ten skips and four
unexecuted GitHub engine-parity cells remain non-evidence.

## E-049: Scoped official OWASP ASVS 5.0.0 evidence mapping

Implemented boundary:

- Verified on 2026-07-25 from official OWASP sources that ASVS 5.0.0, released
  2025-05-30, is the latest stable release. The mutable `master` publication is
  explicitly labelled Bleeding Edge and is excluded from the normative source.
- Pinned release tag `v5.0.0_release`, commit
  `5cf9b032440be53ce345ab3c130fda46ba1ce7a2`, official project/release/CSV
  URLs, CC BY-SA 4.0 attribution, CSV size 105,100 bytes, and SHA-256
  `98c8fe911b9edb403af8ee05d3ce8201ecac2659e313b053890a62847cdcf680`.
  The source contains 345 requirements in 17 chapters and recommends
  version-qualified requirement references.
- Added `docs/security/asvs-5.0.0-mapping.v1.yaml` as a closed, normative,
  schema-v1 mapping. It names every official chapter and requirement count but
  assesses only 55 selected high-relevance requirements: four implemented, 32
  partial, 11 planned, and eight not applicable. The other 290 requirements are
  explicitly unassessed, which means no conclusion rather than a failed or
  satisfied requirement.
- Each selected requirement records its version-qualified ID, reviewed official
  level, status, scope, owner, assessment, gap/limitation, next action, and
  evidence where the status permits it. Implemented and partial entries require
  existing code plus test paths. Planned and not-applicable entries require no
  positive evidence; each conditional not-applicable entry has a reassessment
  trigger.
- The four implemented labels are deliberately narrow: FastAPI `nosniff`,
  opaque backend session verification, logout/session invalidation, and FastAPI
  `no-store`. Partial/planned gaps remain visible for CSV formula injection,
  file type/magic and malware handling, password/recovery policy, ABAC,
  transport security, secret management, dependency locking/provenance, and
  authorization-failure logging.
- Added a closed Draft 2020-12 schema, five dedicated contracts, and a readable
  mapping. Tests freeze the stable source identity, all chapter names/counts,
  the 55 selected IDs and official levels, exact status totals, closed owner and
  evidence paths, and the explicit scope/claim boundary.
- Added ADR 0064, decision D-045, backlog completion for `P0-SEC-003`, schema
  inventory/workflow coverage, source-distribution manifest entries, and
  security/claims/gap/drift/architecture/state records. No runtime, API,
  persistence, identity, cryptography, deployment, or release behavior changed.
- The ASVS YAML, readable Markdown, schema, and dedicated test are in the sdist
  and absent from the wheel. ADR 0064 is in neither artifact.

Official source evidence:

| Source | Verified result |
| --- | --- |
| `https://owasp.org/www-project-application-security-verification-standard/` | Official project page identifies ASVS 5.0.0 as the stable release |
| `https://github.com/OWASP/ASVS/releases/tag/v5.0.0_release` | Official release dated 2025-05-30 and tagged `v5.0.0_release` |
| `https://github.com/OWASP/ASVS` | Official repository; current master publication labels itself Bleeding Edge and points to 5.0.0 as stable |
| Official tagged English CSV | 105,100 bytes; SHA-256 `98c8fe911b9edb403af8ee05d3ce8201ecac2659e313b053890a62847cdcf680`; 345 requirements in 17 chapters |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final ASVS/architecture/threat-model contract target | 14 passed, 0 failed | recorded before documentation integration |
| Broader security/governance/documentation selection | 43 passed, 0 failed | 3.310s command wall time |
| Final full suite with repository-local basetemp | 842 collected; 832 passed, 10 skipped, 0 failed; 8 disclosed warnings | 160.082s command wall time |
| `python -m pytest -o addopts='' --collect-only -q` | Exit 0; 842 tests | 4.665s command wall time; 2.56s pytest collection |
| `python -m ruff check .` | Pass | 0.120s |
| `python -m mypy reconforge` | Pass, 208 files | 0.491s |
| `git diff --check` | Pass; existing `.gitignore` line-ending warning only | 0.110s |
| `python -m bandit -q -r reconforge` | Pass; no findings, three existing justified B608 `nosec` notices | 5.733s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local project itself is not on PyPI | 13.446s |
| `python -m build --no-isolation` | Pass; wheel and sdist, with existing setuptools metadata warnings | 16.228s |
| Archive membership assertion | Pass: ASVS YAML/Markdown/schema/test sdist-only; ADR absent from both; none in wheel | <1s |
| Inventory/worktree assertion | Pass: 50 backlog tasks, 208 source files, 108 test files, 42 schemas, 64 ADRs, 170 tracked and 179 untracked status entries | <1s after verified temp cleanup |

Observed regressions and environment handling:

- The first Ruff check rejected import grouping in the new contract test. Ruff's
  focused safe fix normalized only that import block, and the full Ruff gate
  then passed.
- The first mapping contract run rejected an imprecise claim-boundary phrase
  and the absent readable view. The mapping wording was made explicit and the
  readable view was added; the contract was not weakened.
- The repository-local test root contained only `e049-full-final` at cleanup.
  Its resolved absolute path was verified inside the workspace, every child was
  required to match `e049-*`, and only that temporary root was deleted via the
  .NET directory API. Absence and final 170/179 worktree counts were verified.
- Ten skipped optional/live-service tests remain non-evidence. The eight full-
  suite warnings are one existing Starlette deprecation plus seven legacy-
  financial-input migration warnings; E-049 adds no runtime warning.
- Official-source retrieval was read-only and limited to OWASP project/release/
  repository content. No upstream artifact was copied into the repository, and
  upstream requirement prose was not reproduced in the mapping.
- No skip removal, xfail, retry-until-pass loop, customer data, production
  mutation, credential use, remote repository write, penetration test,
  certification statement, compliance statement, or control-effectiveness
  claim occurred.

Security/claim boundary: this mapping provides reproducible source identity,
selected requirement evidence, and visible gaps. It is not a complete ASVS
assessment; it establishes no ASVS verification level, deployed configuration,
continuous operating effectiveness, penetration-test result, independent
validation, compliance, certification, secure-product assurance, or production
readiness. `implemented` is bounded to the exact cited code/tests, `partial`
does not satisfy a requirement, `planned` is not implementation evidence,
`not_applicable` is conditional and reviewable, and `unassessed` expresses no
conclusion.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; ten skips and four
unexecuted GitHub engine-parity cells remain non-evidence.

## E-050: All-task final NIST SSDF 1.1 repository mapping

Implemented boundary:

- Verified on 2026-07-25 from official NIST CSRC sources that SP 800-218 / SSDF
  1.1 remains the current final core publication. NIST lists SP 800-218 Rev. 1 /
  SSDF 1.2, published 2025-12-17, as an Initial Public Draft; it is monitored
  but excluded from the normative mapping.
- Read the official final PDF and Excel table in memory. Pinned the PDF at
  739,891 bytes with SHA-256
  `617746e553a9e2da49bfbd4eef0dfc3094758a39b869314e4173ac36605cde22`
  and the official table at 50,039 bytes with SHA-256
  `f5729c4c6c792cbf6cfbea74eee7cc84c579b2109006fe3cbfa8934eb460bd55`.
  The table establishes four groups, 19 practices, and 42 tasks.
- Recorded final SP 800-218A (2024-07-26) as a supplemental AI community
  profile requiring a separate assessment before any model-backed AI
  capability is promoted. It is not silently treated as covered or not
  applicable by the core mapping.
- Added `docs/security/nist-ssdf-1.1-mapping.v1.yaml` as a closed normative
  schema-v1 all-task mapping. Every task appears exactly once with a Security
  Architecture owner, status, assessment, gap, and next action. Positive
  partial statuses require existing repository and test paths.
- The first review assigns no task `implemented-bounded` or `not_applicable`:
  28 are partial and 14 planned. This preserves visible gaps for requirements,
  training/management commitment, toolchain locks/reproducibility, environment
  and endpoint hardening, code access, release verification/archive/provenance,
  secure build/testing, and vulnerability response/root-cause operation.
- Added a 90-day review cadence, 2026-10-23 due date, and source/SDLC/AI/
  vulnerability event triggers. Review metadata is governance intent, not
  evidence that an organizational review process has operated historically.
- Added a closed Draft 2020-12 schema, five dedicated contracts, readable view,
  ADR 0065, D-046, DOC-015, backlog completion for `P0-SEC-004`, schema and
  source-distribution manifest coverage, and claims/security/gap/architecture/
  inventory/state records. No runtime, API, source-control, CI execution,
  personnel, release, identity, cryptography, or vulnerability-response
  behavior changed.
- The SSDF YAML, readable Markdown, schema, and dedicated test are in the sdist
  and absent from the wheel. ADR 0065 is in neither artifact.

Official source evidence:

| Source | Verified result |
| --- | --- |
| `https://csrc.nist.gov/pubs/sp/800/218/final` | Official final SP 800-218 / SSDF 1.1 publication, dated 2022-02-03 |
| `https://doi.org/10.6028/NIST.SP.800-218` | Official DOI for the final core publication |
| Official final PDF and Excel table | Digests and byte counts above; 4 groups, 19 practices, 42 tasks |
| `https://csrc.nist.gov/pubs/sp/800/218/r1/ipd` | SSDF 1.2 is an Initial Public Draft dated 2025-12-17, not the normative final source |
| `https://csrc.nist.gov/pubs/sp/800/218/a/final` | SP 800-218A is a final supplemental AI community profile dated 2024-07-26 |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final SSDF/ASVS/architecture/threat-model contract target | 19 passed, 0 failed | approximately 3s command wall |
| Final broader security/governance/documentation selection | 48 passed, 0 failed | 3.607s command wall time |
| Final full suite with repository-local basetemp | 847 collected; 837 passed, 10 skipped, 0 failed; 8 disclosed warnings | 161.775s command wall time |
| `python -m pytest -o addopts='' --collect-only -q` | Exit 0; 847 tests | 4.624s command wall time; 2.53s pytest collection |
| `python -m ruff check .` | Pass | 0.126s |
| `python -m mypy reconforge` | Pass, 208 files | 0.552s |
| `git diff --check` | Pass; existing `.gitignore` line-ending warning only | 0.120s |
| `python -m bandit -q -r reconforge` | Pass; no findings, three existing justified B608 `nosec` notices | 5.764s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local project itself is not on PyPI | 15.450s |
| `python -m build --no-isolation` | Pass; wheel and sdist, with existing setuptools metadata warnings | 16.507s |
| Archive membership assertion | Pass: SSDF YAML/Markdown/schema/test sdist-only; ADR absent from both; none in wheel | <1s |
| Inventory/worktree assertion | Pass: 50 backlog tasks, 208 source files, 109 test files, 43 schemas, 65 ADRs, 170 tracked and 184 untracked status entries | <1s after verified temp cleanup |

Observed regressions and environment handling:

- The first five-test SSDF run passed the schema, source, exact coverage/status,
  and evidence/review contracts but failed readable-view claim text because a
  Markdown line break split the required “not an SSDF conformance” phrase. The
  readable sentence was made contiguous; the contract was not weakened, and
  the complete 19-test nested target then passed.
- An exploratory document read requested nonexistent
  `docs/security/questionnaire.md`; `rg --files` showed the actual questionnaire
  is `docs/security/security-questionnaire.md`. The missing path was discarded
  and not used as evidence.
- The repository-local test root contained only `e050-full-final` at the first
  cleanup. Its resolved absolute path was verified inside the workspace, every
  child was required to match `e050-*`, and only that temporary root was
  deleted through the .NET directory API. Absence and final 170/184 worktree
  counts were verified.
- Ten skipped optional/live-service tests remain non-evidence. The eight full-
  suite warnings are one existing Starlette deprecation plus seven legacy-
  financial-input migration warnings; E-050 adds no runtime warning.
- Official-source retrieval was read-only and limited to NIST CSRC/NVL
  publication content. Neither official file nor full task prose was copied
  into the repository.
- No skip removal, xfail, retry-until-pass loop, customer data, production
  mutation, credential use, remote repository write, personnel assessment,
  management attestation, penetration test, conformance/compliance/certification
  statement, or control-effectiveness claim occurred.

Security/claim boundary: complete task-ID coverage proves only that the mapping
does not silently omit a final SSDF 1.1 task. It does not prove organizational
conformance, personnel proficiency, source-control enforcement, secure build or
release operation, signed provenance, vulnerability response, continuous
improvement, deployment hardening, SP 800-218A coverage, independent assurance,
compliance, certification, secure-product status, or production readiness.
`partial` is not task satisfaction and `planned` is not implementation evidence.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; ten skips and four
unexecuted GitHub engine-parity cells remain non-evidence.

## E-051: Versioned SLSA 1.2 provenance plan before pipeline implementation

Implemented boundary:

- Verified from official SLSA sources that version 1.2 is the current Approved
  specification, announced 2025-11-24, and that it defines separate Build and
  Source tracks. Pinned official tag `v1.2` to peeled commit
  `19e4e2f005f871270c4f555fc47afecfb37f3efe`; the observed release-branch head
  is recorded separately and is not treated as the immutable source identity.
- Added `docs/security/slsa-provenance-plan.v1.yaml` as a closed normative plan.
  It keeps both tracks `UNEVALUATED`; no SLSA level or verified property is
  assigned to ReconForge.
- Defined exact release identities for the Python wheel, Python sdist, OCI
  image, and CycloneDX SBOM, including digest/media/subject expectations and
  publication coupling rather than filename-only identity.
- Defined seven explicit trust boundaries: source control, tenant-owned build
  definition, hosted control plane, build environment, attestation signing,
  distribution, and consumer verification.
- Versioned an in-toto Statement v1 plus SLSA Provenance v1 attestation
  contract, signing expectations, independent fail-closed verification, 12
  safe failure codes, and evidence-preserving rollback/revocation behavior.
- Defined 12 owned and testable implementation gates. Immutable source/build-
  definition intent is partial; ten gates remain planned. A 90-day cadence
  sets the next review to 2026-10-23.
- Added a closed Draft 2020-12 schema, five dedicated contracts, readable view,
  ADR 0066, D-047, DOC-016, backlog completion for `P0-SEC-005`, schema and
  source-distribution manifest coverage, and claims/security/gap/architecture/
  inventory/state records. No release workflow, runtime, signing key,
  attestation, publication, source-control protection, or verifier changed.
- The plan YAML, readable Markdown, schema, and dedicated test are in the sdist
  and absent from the wheel. ADR 0066 is in neither artifact.

Official source evidence:

| Source | Verified result |
| --- | --- |
| `https://slsa.dev/spec/v1.2/` | Official Approved SLSA 1.2 specification index with Build and Source tracks |
| `https://slsa.dev/blog/2025/11/announce-slsa-v1.2` | Official 2025-11-24 version 1.2 announcement |
| `https://github.com/slsa-framework/slsa` | Official source repository; read-only tag resolution pinned `v1.2` to commit `19e4e2f005f871270c4f555fc47afecfb37f3efe` |
| `https://slsa.dev/spec/v1.2/build-provenance` | Official SLSA Provenance v1 predicate contract |
| `https://in-toto.io/Statement/v1` | Versioned in-toto Statement envelope identity used by the plan |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final nested SLSA/security-governance target | 15 passed, 0 failed | approximately 3s command wall |
| Final broader security/governance/documentation selection | 53 passed, 0 failed | approximately 4s command wall |
| Final full suite with repository-local basetemp | 852 collected; 842 passed, 10 skipped, 0 failed; 8 disclosed warnings | 161.632s command wall time |
| `python -m pytest -o addopts='' --collect-only -q` | Exit 0; 852 tests | 4.708s command wall time; 2.64s pytest collection |
| Final six-file SLSA/SSDF/ASVS/architecture/threat/schema target | 27 passed, 0 failed | 3.147s command wall time |
| `python -m ruff check .` | Pass | 0.127s |
| `python -m mypy reconforge` | Pass, 208 files | 0.541s |
| `git diff --check` | Pass; existing `.gitignore` line-ending warning only | 0.116s |
| `python -m bandit -q -r reconforge` | Pass; no findings, three existing justified B608 `nosec` notices | 5.793s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local project itself is not on PyPI | 3.423s |
| `python -m build --no-isolation` | Pass; wheel and sdist, with existing setuptools metadata warnings | 15.352s |
| Archive membership assertion | Pass: SLSA plan YAML/Markdown/schema/test sdist-only; ADR absent from both; none in wheel | <1s |
| Inventory/worktree assertion | Pass: 50 backlog tasks, 208 source files, 110 test files, 44 schemas, 66 ADRs, 170 tracked and 199 untracked status entries | <1s after verified temp cleanup |

Observed regressions and environment handling:

- The first five-test run failed only the exact readable-view claim-boundary
  assertion because its sentence did not say that no ReconForge artifact has a
  SLSA level. The prose was strengthened; the assertion was not weakened, and
  the complete nested and broader targets then passed.
- `git ls-remote` and official-source retrieval were read-only. No repository,
  tag, branch, release, artifact, attestation, or external system was changed.
- The repository-local test root contained only `e051-full-final` at cleanup.
  Its resolved absolute path was verified inside
  `F:\\reconforge-erp\\.codex-test-tmp`, and only that directory was deleted
  through the .NET directory API. Absence and final 170/199 worktree counts
  were verified.
- Ten skipped optional/live-service tests remain non-evidence. The eight full-
  suite warnings are one existing Starlette deprecation plus seven legacy-
  financial-input migration warnings; E-051 adds no runtime warning.
- No signing key, OIDC token, release credential, customer data, production
  mutation, workflow execution, remote write, signature, attestation,
  publication, verifier result, protected-branch assessment, SLSA level,
  compliance/certification, or control-effectiveness claim occurred.

Security/claim boundary: schema validity and complete plan gates prove only
that intended identities, boundaries, verification failures, and rollback are
explicit and drift-tested. They do not prove a trusted builder or source-control
system, isolated build, signed provenance, artifact publication coupling,
independent verification, revocation readiness, SLSA level/property, release
integrity, compliance, certification, secure-product status, or production
readiness. `partial` is not a verified property and `planned` is not execution.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; ten skips and four
unexecuted GitHub engine-parity cells remain non-evidence.

## E-052: Tag-only signed release-candidate definition and bounded package reproducibility

Implemented boundary:

- Added `.github/workflows/release.yml` as a tag-only, non-publishing candidate
  workflow. Workflow permissions default to none; its single GitHub-hosted job
  grants only `contents: read`, `id-token: write`, `attestations: write`, and
  `packages: write`, behind the `release-candidate` environment.
- The workflow accepts only exact `vMAJOR.MINOR.PATCH` refs matching
  `pyproject.toml`, the checked-out full commit, and `origin/main` ancestry. It
  rejects a dirty checkout and requires an annotated tag whose GitHub API
  verification is `verified=true` with reason `valid` and whose target is the
  exact workflow commit.
- Pinned every action to a full reviewed commit: checkout v7
  `3d3c42e5aac5ba805825da76410c181273ba90b1`, setup-python v7
  `5fda3b95a4ea91299a34e894583c3862153e4b97`, login-action v4
  `abd2ef45e78c5afb21d64d4ca52ee8550d9572c7`, setup-buildx-action v4
  `bb05f3f5519dd87d3ba754cc423b652a5edd6d2c`, build-push-action v7
  `53b7df96c91f9c12dcc8a07bcb9ccacbed38856a`, attest v4
  `f7c74d28b9d84cb8768d0b8ca14a4bac6ef463e6`, and upload-artifact v7
  `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`.
- Added an exact hash-locked release build set from official PyPI wheels:
  `build 1.5.0`, Windows-conditional `colorama 0.4.6`, `packaging 26.2`,
  `pyproject-hooks 1.2.0`, `setuptools 83.0.0`, and `wheel 0.47.0`. A real
  `--require-hashes --only-binary=:all:` Windows installation completed for all
  six applicable packages after the conditional dependency was made explicit.
- The workflow derives `SOURCE_DATE_EPOCH` from the release commit and records
  it in the closed schema-v1 release manifest. The manifest helper validates
  exact tag/version/revision/image-repository/digest identity, a closed artifact
  set, archive-root safety, package metadata, and deterministic SHA-256 output;
  it writes the manifest and checksum list atomically.
- Added a no-extraction sdist normalizer. It rejects absolute/traversing or
  out-of-root paths, links, special member types, duplicate member names,
  missing/duplicate root `PKG-INFO`, unsafe filenames, symlink inputs, and gzip
  epoch overflow before replacing the input. Accepted members are sorted and
  receive fixed gzip/tar time, zero numeric ownership, empty owner names, and
  no atime/ctime/mtime PAX headers.
- Two consecutive Python builds on this Windows/Python 3.14.6 machine with
  epoch `1784876463` produced identical wheel bytes at
  `0bb308b4899d7dcd6721e72cca6b982ef43921b9436a30dfd4678aaefb47706b`.
  After normalization, both sdists matched at
  `b27e7e55f7befe46dba00c60e2fc1642c44dabf5be8a47c96e1693957cef5f45`;
  normalization took 0.383s and 0.307s. Two `git archive` snapshots of `HEAD`
  matched at
  `dc0404f9ecf7b60f31b4aa459791a69883f2a0a5fe512895b5d3dada5a3eae5f`.
  The package builds used the dirty worktree while the source snapshots used
  `HEAD`; this proves only repeated local bytes, not one coherent release set.
- The candidate image is pushed only when the workflow is externally exercised,
  under a commit-specific discovery tag and identified by OCI manifest digest.
  Separate `actions/attest@v4` steps request SLSA provenance for files and the
  image. The same job preserves bundles and uses `gh attestation verify` with
  independent repository, workflow, workflow/source revision, tag ref, and
  GitHub-hosted-runner expectations before a 14-day Actions artifact upload.
- GitHub Release and PyPI publication are absent. The runbook makes immutable
  GitHub Release creation and any PyPI Trusted Publisher design separate human
  gates. No long-lived signing or package credential was added.
- Added the closed release-manifest schema, 14 collected manifest/normalizer/
  workflow/tool/runbook contracts, maintainer runbook, ADR 0067, D-048,
  DOC-017, and claims/security/dependency/gap/architecture/backlog/state records.
  Seven SLSA plan gates are now partial and five planned, but both Build and
  Source tracks remain UNEVALUATED.
- The release schema, runbook, and dedicated test are in sdist only. The
  workflow, locked requirements, helper/normalizer scripts, and ADR 0067 are
  repository-only; none is in the runtime wheel.

Official source and immutable-input evidence:

| Source | Verified result |
| --- | --- |
| `https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds` | Official permission and provenance workflow guidance |
| `https://github.com/actions/attest` | Official current combined attestation action; v4 peeled to the full commit recorded above |
| `https://cli.github.com/manual/gh_attestation_verify` | Official verifier options include signer workflow/digest, source ref/digest, bundle, and denial of self-hosted runners |
| `https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases#immutable-releases` | Official immutable-release boundary used by the human publication runbook |
| Official Git repositories for the seven actions | Read-only `git ls-remote` resolved the version tags to the seven full commits recorded above on 2026-07-25 |
| `https://pypi.org/pypi/build/1.5.0/json` and equivalent official JSON endpoints for the other five tools | Exact official wheel SHA-256 values recorded in `.github/release-build-requirements.txt` |
| `https://github.com/rhysd/actionlint/releases/tag/v1.7.12` | Official Windows AMD64 archive verified against published SHA-256 `6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9` before local workflow linting |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final release/SLSA/readiness/workflow/claim-surface contract target after documentation updates | 41 passed, 0 failed | 5.215s command wall time |
| Official-checksum-verified actionlint v1.7.12 on `.github/workflows/release.yml` | Pass | 0.065s final run |
| Two fixed-epoch build/digest comparison | Source archive, wheel, and normalized sdist each byte-identical across both copies; exact digests above | Build duration not separately retained; normalizers 0.383s/0.307s |
| Real manifest helper against built source/wheel/normalized-sdist plus a synthetic valid image digest | Pass; closed schema validates and records epoch `1784876463` | Not separately retained |
| First full suite with repository-local basetemp | 866 collected; 854 passed, 10 skipped, 2 failed only because two tracked root files disappeared during the slice | 290.971s command wall time |
| Affected Alembic/SSDF target after exact file restoration | 6 passed, 1 skipped, 0 failed | 2.930s command wall time |
| Final full suite with a fresh repository-local basetemp | 866 collected; 856 passed, 10 skipped, 0 failed; 8 disclosed warnings | 320.780s command wall time |
| Final collection count | Exit 0; 866 tests across 111 collected test modules | 4.589s |
| `python -m ruff check .` | Pass | 0.346s |
| `python -m mypy reconforge` | Pass, 208 files | 22.443s |
| `git diff --check` | Pass; existing `.gitignore` line-ending warning only | 0.129s final check |
| `python -m bandit -q -r reconforge` | Pass; no findings, three existing justified B608 `nosec` notices | 5.902s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local project itself is not on PyPI | 15.635s |
| Final `python -m build --no-isolation` | Pass; wheel and sdist, with existing setuptools metadata warnings | 20.161s |
| Archive membership assertion | Pass: schema/runbook/test sdist-only; workflow/requirements/scripts/ADR repository-only; none in wheel | Included in final build command |
| Inventory/worktree assertion | Pass: 50 backlog tasks, 208 source files, 111 collected test files, 45 JSON schemas, 67 ADRs, 7 workflows, 171 tracked and 207 untracked status entries | <2s after verified temp cleanup |

Observed regressions and environment handling:

- The first hash-locked Windows install failed because `colorama`, a conditional
  dependency of the selected build frontend, was not listed. Its exact official
  wheel/version/hash were added rather than disabling hash checking; the same
  six-package install then passed.
- Initial repeated builds showed wheel equality but sdist inequality. Inspection
  found gzip headers plus 53 root/directory/`PKG-INFO` member mtimes differed.
  The fail-closed normalizer and positive/negative no-overwrite tests fixed that
  bounded cause; no general reproducible-build claim was substituted.
- Two exploratory PowerShell wrappers passed an equals-prefixed `git archive`
  output path, which Git rejected. The already-successful package builds were
  retained and the source archive was rerun with a separate `--output PATH`
  argument. These command-construction failures are not artifact passes.
- `MANIFEST.in` unexpectedly disappeared mid-slice. It was recovered through
  `apply_patch` from the last built sdist plus the three E-052 sdist includes;
  the final build and direct membership assertion validated the recovered
  boundary.
- During the first final full suite, tracked root files `alembic.ini` and
  `CONTRIBUTING.md` disappeared. Git identified both as deletions. They were
  restored through `apply_patch` from exact `HEAD` content, after which Git
  reported no status entry for either. The affected target and a new full-suite
  run passed. The original two failures remain recorded above; this was not a
  retry-until-pass assertion.
- Eighteen verified `.codex-test-tmp/e052-*` directories were listed by resolved
  absolute path, required to remain under
  `F:\\reconforge-erp\\.codex-test-tmp`, and deleted through the .NET directory
  API. No non-E052 child existed or was removed. The root is empty and final
  worktree counts are 171 tracked/207 untracked entries.
- Ten optional/live-service skips remain non-evidence. The eight warnings are
  one existing Starlette deprecation plus seven legacy-financial-input migration
  warnings. E-052 adds no runtime warning.
- No skip/xfail weakening, customer data, secret, OIDC token, package credential,
  signed tag, registry push, GitHub workflow run, remote repository write,
  GitHub Release, PyPI publication, signature, attestation, independent verifier
  record, or production mutation occurred.

Security/claim boundary: workflow definitions, exact pins, local contract tests,
and same-machine package byte parity do not prove that GitHub controls operated,
that a tag is signed, that a builder is isolated/trusted, that an OCI image is
reproducible, that provenance is authentic/retained, that consumer verification
passed, or that an immutable release exists. They establish no SLSA Build/Source
level or verified property, release integrity, compliance, certification,
secure-product assurance, or production readiness. `P0-SEC-006` remains in
progress until a reviewed clean hosted tag run and independent retained
verification exist.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Python 3.14 is
outside the declared Python 3.11/3.12 support matrix. Docker and live
PostgreSQL/Redis/object-storage remain unavailable; OCI build/reproducibility,
ten skips, and four unexecuted GitHub engine-parity cells remain non-evidence.

## E-053: Exact-subject CycloneDX 1.7 candidate SBOM definition and bounded local output

Implemented boundary:

- Replaced the separate `.github/workflows/sbom.yml`, which installed a
  floating `cyclonedx-bom` and described the runner environment, with
  per-subject generation inside the existing tag-only non-publishing candidate
  job. No manual trigger, GitHub Release, PyPI upload, or new permission was
  added.
- Added `.github/scripts/build_release_sboms.py`. It accepts only a regular
  schema-v1 release manifest inside the project, recomputes source/wheel/sdist
  SHA-256 values, requires the exact digest-addressed GHCR image identity, and
  rejects release/source epoch drift before building any SBOM output.
- The helper reads archives without filesystem extraction. It validates safe
  tar/ZIP paths and bounded metadata, exact source `pyproject.toml` identity,
  exact wheel `METADATA` and sdist `PKG-INFO` identity, and set-equal canonical
  `Requires-Dist` values including project extras. Direct-URL requirements,
  duplicate declarations, missing metadata, and source/package drift fail
  closed.
- Source SBOM generation additionally requires `apps/web/package.json` and
  `package-lock.json` together, validates lockfile v3 and exact root
  name/version/dependency-group parity, rejects unsafe locations, links, and
  non-HTTPS resolutions, and converts valid SHA-256/384/512 npm integrity values
  only when their decoded lengths are exact. The clean-HEAD source document
  inventories 209 non-root npm lock entries plus 26 Python declarations; 155 npm
  entries lack integrity in the source lock and remain visibly unhashed.
- Python components represent declared constraints with
  `resolution=unresolved`; wheel/sdist documents therefore do not claim an
  installed transitive environment. All documents and the closed
  `sbom-manifest.v1.json` record `completeness=unknown`.
- The image path downloads Syft 1.49.0 from its official release, checks Linux
  AMD64 archive SHA-256
  `7aa2f03ee92739cf643279ba3990548b9925d4e22cae13f46831ee62821147fe`,
  and checks version, platform, and commit
  `29fd7d0dec81cf03e0a1194a1985c7c893bb2396`. It scans the exact
  `registry:repo@sha256:digest`, not the mutable discovery tag.
- The Syft normalizer accepts only CycloneDX 1.7 from that tool version,
  preserves component inventory, replaces volatile timestamp/serial/root
  identity deterministically, canonicalizes order-insensitive lists, and rejects
  empty inventories, duplicate/unknown references, signatures it would
  invalidate, pre-injected ReconForge policy properties, and configured runner
  or workspace path disclosures.
- Added a closed SBOM manifest schema binding one document to each exact
  source/wheel/sdist/image subject, the release-manifest digest, generator
  identities, component counts, canonical inventory hashes, SBOM hashes,
  generation modes, verification requirements, and the claim boundary.
  `SBOM_SHA256SUMS` covers all four documents plus the manifest. Every output
  uses `O_EXCL` temporary creation and atomic replacement; a pre-existing
  sentinel collision is rejected and preserved.
- The release workflow now issues six pinned `actions/attest@v4` calls: file and
  image SLSA provenance plus four distinct CycloneDX predicates. It preserves
  all bundles and verifies each subject with repository, workflow,
  workflow/source revision, tag ref, GitHub-hosted runner, bundle, and explicit
  `https://cyclonedx.org/bom` predicate expectations before candidate upload.
  `create-storage-record` is false for every call; the existing least-privilege
  job permissions remain unchanged.
- Added five dedicated contracts, ADR 0068, D-049, DOC-018, SBOM claim/runbook/
  dependency/security records, and updated the SLSA plan to five identities and
  eight partial/four planned gates. Build and Source remain UNEVALUATED.

Official source and tool research:

| Source/input | Verified result |
| --- | --- |
| `https://cyclonedx.org/specification/overview/` | CycloneDX 1.7 is the selected versioned JSON contract; no floating latest-schema lookup occurs in the release job |
| `https://cyclonedx.org/schema/bom-1.7.schema.json` | Official downloaded schema SHA-256 `71152f97948eeeca2fd4a1434a9d29aab35d377be11828b504d029dfeeb1925a`; all four generated fixture documents validate |
| `https://cyclonedx.org/bom` | CycloneDX attestation predicate type used explicitly by generation and `gh attestation verify` |
| `https://github.com/anchore/syft/releases/tag/v1.49.0` | Tag peels to commit `29fd7d0dec81cf03e0a1194a1985c7c893bb2396`; official Windows AMD64 archive matched published SHA-256 `6edff6c6e06ddd43ae3b779099653f499a856009786b5375a7cf23aed6b67b1a`; binary reported Syft 1.49.0/schema 16.1.10 |
| `https://github.com/actions/attest` at pinned v4 commit | Official action inputs support CycloneDX/SPDX `sbom-path` with file or digest/name subjects and preserved bundles |
| `https://cli.github.com/manual/gh_attestation_verify` | SBOM verification requires explicit non-default `--predicate-type`; repository/workflow/source/bundle/runner expectations remain available |
| `https://github.com/rhysd/actionlint/releases/tag/v1.7.12` | Official-checksum-verified Windows AMD64 actionlint validated the integrated workflow |

Local artifact and determinism evidence:

- Research with the official Syft binary showed raw scans were not byte
  deterministic: repeated wheel outputs differed at least in timestamp and
  serial; repeated sdists also carried a random package identifier and temporary
  extraction path. The wheel scan found no components and the sdist scan found
  only the project package, so these outputs were not substituted for Python
  declaration parity.
- The first real local set intentionally combined `git archive HEAD` with
  dirty-worktree package builds. E-053 rejected it because wheel metadata
  contained the uncommitted `hypothesis==6.161.2` extra while the source archive
  did not. This is retained fail-closed drift evidence; E-052 had checked
  package identity but not dependency-set parity.
- A fresh source snapshot extracted from clean revision
  `bdf63de48051a0ef5c694442208f5207f4dd5e1c`, epoch `1784876463`, was built
  separately without changing the dirty worktree. The coherent artifact set
  passed release-manifest and SBOM generation:

| Subject/output | SHA-256 / count |
| --- | --- |
| Source archive | `dc0404f9ecf7b60f31b4aa459791a69883f2a0a5fe512895b5d3dada5a3eae5f` |
| Clean-HEAD wheel | `35873639b6d244baf55e6245a58b928bad6f6d9a8bde60a55ec4b14e639ab955` |
| Normalized clean-HEAD sdist | `f6737e27f55af5fc5e706aabe1741a27f8b297d018f6010e01f39384ad2e1073` |
| Source CycloneDX | `b1cf140d0bb9fa30cf47e1a5b3d22c6b5f08a1e70159a382b6e8df0f0de0aebc`; 235 components |
| Wheel CycloneDX | `67d783c00dae30d141f813bd8d663d271881ebf9134866a2dadd4de3e3f5b18d`; 26 components |
| Sdist CycloneDX | `632b82a08549f49a8f220040de28ad71c8463d0f1b61b05028a6949defd6b65d`; 26 components |
| Synthetic image CycloneDX | `01b4bc7d762c21f0aae147f95fc6cc29e22b7ddb1a97faf7a116242ad43e6e59`; 2 fixture components, not image evidence |
| SBOM manifest | `e960438103c7a8ffca3d3cff3ac168077958c1b798a25e1465613d21d88f4d85` |

- Re-running all four documents against identical inputs reproduced every byte
  and checksum. Each document validated against the official CycloneDX 1.7
  schema and the manifest validated against the repository Draft 2020-12
  schema. The image subject digest and two inventory components were synthetic
  because Docker is unavailable; they establish normalizer behavior only.

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Final post-hardening full Python suite with repository-local basetemp | 871 collected; 861 passed, 10 skipped, 0 failed; 8 disclosed warnings | 347.39s |
| Final security/SBOM/SLSA/schema/readiness/maturity/claims focused target | 64 passed, 0 failed | 10.236s command wall time |
| Final E-053 release/SBOM/SLSA target after npm-root negative coverage | 24 passed, 0 failed | 7.592s command wall time |
| Official CycloneDX 1.7 plus repository manifest validation | Four documents and one manifest valid | <1s on the initial fixture; 4.232s including real clean-HEAD generation/validation |
| Identical-input SBOM rerun | Byte-identical `SBOM_SHA256SUMS` | 3.627s |
| Official-checksum-verified actionlint 1.7.12 on `release.yml` | Pass | Duration not separately retained |
| `python -m ruff check .` after final-suite basetemp cleanup | Pass | <1s |
| `python -m mypy reconforge` | Pass, 208 files (cache warm) | 0.554s |
| `python -m bandit -q -r reconforge` | Pass; no findings, three existing justified B608 notices | 7.215s |
| `python -m pip_audit` | No known installed-package vulnerabilities; local project skipped because it is not on PyPI | 15.574s |
| `python -m build --no-isolation` | Pass; wheel/sdist with existing setuptools metadata warnings | 26.000s |
| Archive membership assertion | Pass: SBOM schema/runbook/test sdist-only; workflow/script/ADR repository-only; all absent from runtime wheel | <1s |
| `git diff --check` after final-suite basetemp cleanup | Pass; existing `.gitignore` line-ending warning only | <1s |
| Final inventory/worktree assertion | 50 backlog tasks, 208 source files, 112 test files, 871 collected tests, 46 JSON schemas, 68 ADRs, 6 workflows, 179 tracked and 211 untracked status entries | <2s |

Observed failures and environment handling:

- One exploratory local set failed exact dependency parity because it mixed an
  immutable `HEAD` source archive with dirty-worktree package artifacts. A
  coherent clean-HEAD build then passed; the dirty worktree was not altered or
  called release evidence.
- The first post-suite Ruff command inspected the deliberately extracted
  clean-HEAD research tree under `.codex-test-tmp` and found two import-order
  issues in that historical snapshot. Six verified E-053 temporary directories
  and three verified E-053 temporary files were shown to resolve inside
  `F:\reconforge-erp\.codex-test-tmp` and removed. Ruff then passed the actual
  worktree; no extracted or repository source was reformatted to force success.
- An initial combined focused command named a nonexistent
  `tests/test_nist_ssdf_mapping.py`; the correct existing
  `tests/test_ssdf_mapping.py` target then passed with the other 50 contracts.
  The command-construction error is not a test pass.
- Ten optional/live-service skips and the same eight existing warnings remain
  non-evidence. Python 3.14.6 remains outside the declared 3.11/3.12 support
  matrix. Docker, hosted GitHub execution, live PostgreSQL/Redis/object storage,
  and all remote signatures remain unavailable or unexecuted.
- The final post-hardening suite used only
  `.codex-test-tmp/e053-final-full`; the resolved directory was verified as an
  ordinary directory inside the repository before it was removed, and both
  Ruff and `git diff --check` passed after cleanup.
- No customer data, secret, OIDC token, registry push, signed tag, GitHub
  workflow execution, remote write, Release/PyPI publication, signature,
  attestation, immutable storage record, or production mutation occurred.

Security/claim boundary: E-053 proves deterministic, schema-valid local
source/package SBOM construction, fail-closed drift/tamper checks, and a pinned
non-publishing image-scan/attestation/verification definition. It does not prove
that the image was built or scanned, that inventories are complete, that a
dependency is safe/reachable/licensed, that GitHub controls operated, that an
attestation is authentic/retained, or that consumer verification passed. It
establishes no signed release, release integrity, SLSA Build/Source level or
verified property, compliance, certification, secure-product assurance, or
production readiness. `P0-SEC-007` remains in progress pending a reviewed clean
hosted run and independent retained verification.

Environment: Windows, Python 3.14.6, pytest 9.1.1, Hypothesis 6.161.2, NumPy
2.5.1, Pandas 3.0.3, DuckDB 1.5.5, Ruff 0.15.22, and Mypy 2.3.0. Docker and
live PostgreSQL/Redis/object-storage remain unavailable. The next safe local
slice is `P0-SEC-008`; any signed-tag exercise or remote publication remains an
explicitly authorized external action.

## E-054: Locked application resolution and fail-closed dependency/secret gates

Implemented boundary:

- Added universal `uv.lock` format v1/revision 3 for Python `>=3.11`, generated
  by exact uv 0.11.32 with absolute `exclude-newer` cutoff
  `2026-07-26T00:00:00Z`. The final graph contains 103 non-root packages across
  runtime, server, build/developer, docs, and DuckDB extras. Registry artifacts
  use official PyPI/files HTTPS locations and carry SHA-256, size, and upload
  time metadata.
- Kept public lower bounds for downstream package compatibility. Added the
  declared setuptools/wheel backend to the developer extra after the first
  locked `build --no-isolation` exposed that it was absent; the final locked
  environment builds both artifacts without an undeclared backend download.
- Normal Python/server CI now performs locked non-editable synchronization, and
  Docker performs a locked runtime-only non-editable sync. Engine-parity cells
  start from the lock before their three exact, deliberate no-dependency
  compatibility overrides.
- Docker keeps its digest-pinned Python base and obtains uv 0.11.32 from the
  official Linux archive through Dockerfile `ADD --checksum`; no curl/pipe
  execution or floating installer is used. The local daemon remains unavailable,
  so this is an unexecuted definition rather than image evidence.
- Security and tag-only candidate workflows pin `setup-uv` and `setup-node` by
  full commit, check the lock/policy, hash-export every Python extra for
  `pip-audit`, audit the npm lock, and run checksum/version-pinned Gitleaks on all
  Git history and the checked tree. Candidate gates occur before registry login.
- Added weekly Dependabot definitions for pip, npm, Docker, and GitHub Actions.
  Bot output remains an update proposal requiring lock regeneration, audit,
  tests, and review.
- Preserved the existing npm v3 exact-version tree. It has 209 non-root lock
  records; 54 contain both `resolved` and `integrity`, while 155 contain neither.
  The policy machine-counts that gap. An exploratory fresh lock was not adopted
  because it also changed versions and platform-optional layout; no complete npm
  artifact-hash claim is allowed.
- Added closed schema-v1 supply-chain policy and exception registries, with zero
  active exceptions. The validator rejects unknown fields, manifest/lock/source
  drift, unapproved sources, missing Python hashes/sizes, npm root/version/SRI
  count drift, workflow pin/order drift, scanner operational/report mismatch,
  unknown advisories, expired/revoked/non-exact/overlong/self-approved
  exceptions, and any attempted critical npm exception.
- Added `.gitleaks.toml` extending default rules. It excludes only VCS,
  repository tool/cache/build/output directories and contains no commit,
  regex, stopword, finding-baseline, or disabled-rule allowlist. Findings remain
  redacted in automation.
- Added 13 dedicated contracts, two schemas, ADR 0069, D-050, DOC-019, and
  evidence-bounded security/architecture/operator/claim updates. Supply-chain
  schemas, readable/normative policy, zero-exception registry, and test are
  sdist-only; lock, validator, workflows, Gitleaks/Dependabot/Docker definitions,
  and ADR are repository-only. None is in the runtime wheel.

Official source and immutable-tool research:

| Source/input | Verified or selected result |
| --- | --- |
| `https://github.com/astral-sh/uv/releases/tag/0.11.32` | Latest stable observed 2026-07-26; commit `3010295ae7ff572de459987ad70db315a62ecd61`, Windows x86_64 archive SHA-256 `acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984`, Linux x86_64 archive SHA-256 `aab924fd522efd06f1c5f3b93a243864fc453132c94b2dc49f1371b528a4b967` |
| `https://github.com/astral-sh/setup-uv/releases/tag/v9.0.0` | Full action commit `c771a70e6277c0a99b617c7a806ffedaca235ff9` |
| `https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1` | Commit `83d9cd684c87d95d656c1458ef04895a7f1cbd8e`; Windows x64 archive SHA-256 `d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e`, Linux x64 archive SHA-256 `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb` |
| `https://github.com/actions/setup-node` | Full selected v7 action commit `820762786026740c76f36085b0efc47a31fe5020` |
| `https://github.com/rhysd/actionlint/releases/tag/v1.7.12` | Official Windows archive SHA-256 `6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9`; checksum-verified local binary used |
| Official uv lock/settings, npm package-lock, pip-audit, Gitleaks, Dependabot, and Docker `ADD --checksum` documentation | Selected fail-closed lock, audit, scan, update, and remote-archive verification semantics; no source claims that a clean scan proves package safety |

Final policy inputs before execution-ledger finalization:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `uv.lock` | 434,146 | `ae5857bbe7eeebe41c2f1a2a688ab89da30130fa3715a1d33635cbc458a0f373` |
| `apps/web/package-lock.json` | 73,395 | `c18dc8b38c62de19a97180d5d57e4948c9df21bea87598a6e9ff70a47573ff88` |
| `.gitleaks.toml` | 588 | `1338e473edda8e52772e10ec6363457999dd7137da8ba482feec6630e54ea724` |
| `supply-chain-policy.v1.json` | 3,420 | `36aca67c2767d48fa019f3cd8234286d591f3185083c658152c55ad6f81bc32e` |
| `supply-chain-exceptions.v1.json` | 134 | `53e685d48482adf468a2e2ad1a6f867a838c3157813b6cf7b8a804c5474a2649` |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| `uv lock --check` and closed policy validation | Pass; 103 Python packages, 209 npm packages, 155 npm integrity-gap entries, zero active exceptions | <1s final policy invocation |
| Locked Python 3.11 all-extra sync | Pass; exact graph installed non-editably | Initial graph sync required one recorded identical DNS retry; final two-package backend update sync 14.519s |
| Hash-exported `pip-audit 2.10.1 --require-hashes --disable-pip` plus policy enforcement | No known vulnerabilities; zero policy findings | 9.825s audit; <1s policy enforcement |
| `npm audit --package-lock-only --audit-level=high` plus policy enforcement | Zero known vulnerabilities/high findings | Duration not separately retained |
| Focused supply-chain plus security/SBOM/SLSA/schema/readiness governance target | 68 passed, 0 failed | 9.80s final rerun |
| Locked Python 3.11 full implementation suite | 884 collected; 874 passed, 10 skipped, 0 failed; 8 disclosed warnings | 219.10s |
| Final locked Python 3.11 suite after E-054 documentation/build-backend integration | 884 collected; 874 passed, 10 skipped, 0 failed; 8 disclosed warnings | 393.69s |
| Locked `ruff check .` | Pass | 2.427s |
| Locked `mypy reconforge` | Pass, 208 files | 1.488s |
| Locked `bandit -q -r reconforge` | Pass; no findings, three existing justified B608 notices | 8.954s |
| Locked `python -m build --no-isolation` | Pass; wheel and sdist with existing setuptools metadata warnings | 20.685s final build |
| Archive membership assertion | Six required E-054 members present in sdist; repository/governance members absent from the 215-entry runtime wheel | <1s |
| Final Gitleaks history scan | Pass; 69 commits, about 4.73 MB, no leaks | 576ms scanner time |
| Final post-documentation Gitleaks checked-tree scan | Pass; about 15.07 MB, no leaks | 552ms scanner time |
| Checksum-verified actionlint 1.7.12 | Pass on all six workflows | <1s final explicit-path run |
| `npm ci` / typecheck / unit / production build / Playwright E2E | Pass; 158 installed packages and zero vulnerabilities; 17/17 unit and 2/2 E2E tests | 35s / 1.658s / 6.96s test / 2.237s / 7.2s E2E |
| Final post-cleanup `python -m ruff check .` and `git diff --check` | Pass; whitespace check emits only the existing `.gitignore` LF-to-CRLF warning | <1s combined wall time |
| Final inventory/worktree assertion | 50 backlog tasks, 208 source files, 113 test files, 884 collected tests, 48 JSON schemas, 69 ADRs, 6 workflows, 186 tracked and 221 untracked status entries | <1s after verified temp cleanup |

Observed failures and environment handling:

- The first exact locked sync retried and failed after a transient DNS lookup on
  a NumPy wheel. The identical lock/input retry then succeeded. The failed
  network attempt is retained and is not counted as an install pass.
- The first locked `build --no-isolation` failed because
  `setuptools.build_meta` was absent from the all-extra environment. Setuptools
  83.0.0 and wheel 0.47.0 were added to the developer extra, `uv.lock` was
  regenerated/audited, the environment resynchronized, and the same build
  passed. The failure was not relabeled environmental.
- The first checked-tree secret scan identified the high-entropy test fixture
  `idempotent-key-12345`. The behavior-equivalent fixture became
  `repeat-repeat-repeat`; no allowlist or default rule was weakened. Final
  history and tree scans both pass.
- The first 68-test governance target had one failure because the signed-release
  action-set assertion did not include the newly pinned setup-uv/setup-node
  actions. The exact action contract was updated and all 68 tests passed.
- Two PowerShell actionlint wrappers failed before reading workflows: one passed
  an unexpanded wildcard and one used an invalid color argument. The final run
  passed six explicit files with the documented `-no-color` flag; wrapper errors
  are not workflow results.
- An exploratory fresh npm lock embedded integrity for all 209 records but also
  changed dependency versions and cross-platform optional layout. It remained
  temporary and was not substituted for the reviewed exact tree. The 155-entry
  integrity gap stays visible.
- Ten optional/live-service skips and eight existing warnings remain
  non-evidence. Docker, hosted GitHub execution, Python 3.12, live
  PostgreSQL/Redis/object storage, branch controls, signed candidates, and
  consumer verification remain unavailable or unexecuted.
- Thirteen resolved ordinary `.codex-test-tmp/e054-*` directories were shown to
  remain inside `F:\reconforge-erp\.codex-test-tmp`, with no reparse point and
  no non-E054 child, before recursive deletion through the .NET directory API.
  All 13 were removed, the root remained, and its final child list is empty.
- No customer data, production secret, OIDC token, registry login/push, signed
  tag, GitHub run, remote write, publication, exception approval, signature,
  attestation, or production mutation occurred.

Security/claim boundary: E-054 proves a bounded local exact Python/server/build
resolution, fail-closed policy contracts, current advisory responses, and
current history/tree scan results. It does not prove package code is safe,
reachable, correctly licensed, malware-free, or provenance-authentic; that no
secret ever existed; that hosted controls operate; that the container contains
only intended files; or that npm artifacts have complete embedded integrity.
It establishes no signed release, supply-chain assurance level, compliance,
certification, secure-product assurance, or production readiness.
`P0-SEC-008` remains in progress pending supported-version hosted execution,
container evidence, branch/release enforcement, and closure or formally bounded
resolution of the npm SRI gap.

Environment: Windows, Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff 0.16.0,
Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, Hypothesis 6.161.2, NumPy 2.4.6,
Pandas 3.0.5, DuckDB 1.5.5, Node 26.3.0, npm 11.16.0, Gitleaks 8.30.1, and
actionlint 1.7.12. Docker and live server dependencies remain unavailable. The
next safe local slice is `P0-SEC-009`; any hosted execution, signed tag, or
publication remains an explicitly authorized external action.

## E-055: Bounded tabular file ingress and closed parser-surface inventory

Implemented boundary:

- Added runtime `reconforge/io/ingress.py` with versioned
  `tabular-file-ingress-v1`. The immutable default policy caps one file at
  67,108,864 bytes, data rows at 1,000,000, columns at 2,048, cells at
  20,000,000, a CSV field at 128,000 characters, XLSX members at 4,096, one
  uncompressed member at 134,217,728 bytes, total uncompressed content at
  268,435,456 bytes, and compression ratio at 1,000:1.
- Rejects unsupported, missing, non-regular, symlinked, empty, unreadable,
  over-limit, and extension/content-mismatched CSV/XLS/XLSX before a normal
  dataframe or SQL parser. Rejections expose only `Input file rejected
  (<stable-code>).`; local paths and source values are absent.
- CSV preflight uses strict streaming UTF-8 parsing and enforces header,
  rectangular shape, row/column/cell/field ceilings. XLSX preflight rejects
  unsafe traversal/control/drive/backslash paths, symlinks, exact or casefolded
  duplicates, encryption, unsupported compression, oversized/over-ratio
  members, VBA/ActiveX/embeddings/external links, DTD/entities, external
  relationships, formulas, malformed cell references, sparse over-limit column
  references, and aggregate over-limit worksheet rows. XML iteration uses
  `defusedxml` with DTD/entity/external access forbidden and element clearing.
- The first review found that XLSX `max_columns` was enforced only after pandas
  and `max_rows` was per worksheet. The implementation now derives sparse cell
  reference indices and aggregates data rows across sheets before parsing; two
  regression cases prove both corrections.
- `read_table()` preflights before pandas, caps parser rows, rechecks dataframe
  shape, and converts parser-specific failures to stable safe codes. Both direct
  DuckDB CSV paths preflight before path handoff. Mapping header inspection and
  `GenericCSVConnector` now route through the canonical reader.
- Declared stable `defusedxml>=0.7.1` as a direct runtime dependency after
  Bandit correctly rejected standard-library XML parsing. Exact uv 0.11.32
  regenerated/checks the universal lock; the graph remains 103 non-root
  packages because defusedxml 0.7.1 was already present transitively. Official
  PyPI metadata observed 0.7.1 as the stable release and 0.8.0rc2 as a
  prerelease; no prerelease was selected.
- Added closed
  `docs/security/file-ingestion-inventory.v1.yaml` with 13 sequential surfaces,
  module/trust/format/entrypoint/parser/control/test/risk/limitation/action
  records and ten exact file/parser allowlist records representing 12 direct
  pandas/stdlib delimited-parser calls. Its contract checks the closed schema,
  active module/risk/evidence references, real Python symbols, runtime-policy
  equality, and exact AST call counts; a new direct parser now fails until it is
  routed or explicitly governed as partial.
- Added R-018 for unbounded/hostile local parsing and linked it to Security
  Architecture TB-001/SEC-C-001/002/009, reconciliation/mapping/plugin threat
  cases, and the file inventory. Updated OWASP ASVS V5.1.1/V5.2.1 evidence and
  advanced only V5.2.2 from planned to partial, changing selected totals to
  four implemented, 33 partial, ten planned, and eight not applicable. Updated
  NIST SSDF PW.5.1 evidence without changing its partial status or any SSDF
  total.
- Added schema/readable boundary, ADR 0070, D-051, DOC-020, claims, risk,
  architecture, threat, module, ASVS/SSDF, package-manifest, and execution
  ledger integration. The task remains in progress because legacy XLS internals,
  JSON/YAML and generated-artifact resource limits, malware scanning/quarantine,
  HTTP uploads, source authenticity, and future connector controls are absent.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| `uv.lock` | `92a28d97f3758b7994c9f80b113719d422a2d4b18c6fca4459bb8fb32d115af9` |
| `reconforge/io/ingress.py` | `f4b9be95d7c9568f51439a3fee4591191ba954d2b49a1e22223100eae82f70bb` |
| `docs/security/file-ingestion-inventory.v1.yaml` | `8c0c35b6a6fd32de40263ed8399de796531ce8aa1f70914b8a67c5fef9b8448c` |
| `docs/schemas/file_ingestion_inventory.schema.json` | `62a868d4d11efa5cc0d893d4f3a17e66f2954c802e1da8289c3b80da0f69c527` |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Exact uv 0.11.32 `lock --check` plus supply-chain policy | Pass; 103 Python packages, 209 npm packages, 155 npm SRI-gap entries, zero active exceptions | 4.0s combined invocation |
| Locked Python 3.11.15 all-extra non-editable sync | Pass; 102 installed distributions plus the local package, including direct defusedxml 0.7.1 | 18.31s prepare/install plus build |
| Focused ingress, readers, mapping, plugin, and DuckDB regression target | 64 passed, 0 failed | 17.20s final pre-governance run |
| Final ingress/inventory target after sparse-column and aggregate-sheet correction | 19 passed, 0 failed | Included in 5.3s test/lint/type invocation |
| File/risk/module/threat/architecture/ASVS/schema governance target | 48 passed, 0 failed | 8.4s |
| Locked supported Python 3.11.15 full suite | 903 collected; 893 passed, 10 skipped, 0 failed; 8 disclosed warnings | 204.46s |
| Additional local Python 3.14.6 compatibility suite | 903 collected; 893 passed, 10 skipped, 0 failed; same 8 warnings | 224.73s |
| Locked Ruff / Mypy / Bandit | Pass; 209 source files type-checked, no Bandit findings, three existing B608 nosec notices | Combined gate duration not separately retained |
| Hash-exported pip-audit 2.10.1 plus policy enforcement | No known vulnerabilities; zero findings; policy valid | Combined gate duration not separately retained |
| Locked `build --no-isolation` to isolated E-055 output | Pass; wheel and sdist with existing setuptools metadata warnings | Combined gate duration not separately retained |
| Package membership assertion | Six required runtime/governance/test files present in 434-entry sdist; ingress runtime present and governance/tests absent from 216-entry wheel; wheel metadata declares `defusedxml>=0.7.1` | <1s |
| Schema/AST/runtime-policy contracts | Exact 13 surfaces, ten file/parser records, 12 parser calls, runtime budgets, active modules/risks/evidence/symbols all pass | Included in focused/full suites |
| Final documentation/governance target | 72 passed, 0 failed after all readable/normative ledger updates | Included in final build invocation |
| Final package rebuild and membership assertion | Pass; final 434-entry sdist and 216-entry wheel preserve the declared boundary | Build duration not separately retained; assertion <1s |
| Final post-cleanup Ruff and `git diff --check` | Pass; whitespace emits only the existing `.gitignore` LF-to-CRLF warning | <1s combined |
| Final inventory/worktree assertion | 50 backlog tasks, 209 source files, 115 test files, 903 collected tests, 49 JSON schemas, 70 ADRs, 6 workflows, 188 tracked and 228 untracked status entries | <1s after verified temp cleanup |

Observed failures and environment handling:

- The first focused command referenced nonexistent
  `tests/test_mapping_inspection.py` and therefore collected zero tests. The
  correct mapping test filenames were selected and the 64-test target passed;
  the command error is not test evidence.
- The first Bandit run failed B405/B314 on `xml.etree.ElementTree`. No suppression
  was added. XML iteration moved to direct stable `defusedxml`, the lock was
  regenerated, and Bandit plus hostile XML tests passed.
- The first post-column-bound Mypy run found that `_reject()` returned `None`
  for control-flow analysis, leaving a possible `Match | None`. `_reject()` was
  correctly annotated `NoReturn`; the unchanged behavior then passed all 209
  source files.
- The preserved downloaded uv archive initially had an extensionless extracted
  file that PowerShell would not execute. The already checksum-verified official
  ZIP was expanded into its named `uv.exe`; exact version/commit output was
  checked before lock/sync use. The failed invocation did not change the lock
  or count as a tool pass.
- Two attempted PowerShell `Remove-Item` E-055 cleanup commands were rejected by
  the execution safety layer before running. A read-only listing then verified
  13 explicit E-055 directories and two explicit files as non-reparse targets
  under `F:\reconforge-erp\.codex-test-tmp`; the same explicit paths were removed
  through the .NET directory/file APIs. The temp root and every non-E-055 child
  remained, and a final listing returned zero E-055 items.
- The first complete E-055 suite used the ambient Python 3.14.6 interpreter.
  Its result is retained as additional compatibility only. A fresh temporary
  Python 3.11.15 environment was then created and synchronized exactly from the
  lock, and the full supported-version suite and all gates passed there.
- Ten optional/live-service skips and eight existing warnings remain
  non-evidence. Docker, Python 3.12 hosted execution, live PostgreSQL/Redis/object
  storage, malware scanning, quarantine, and remote workflow execution remain
  unavailable or unexecuted.
- No customer data, production secret, HTTP upload, malware sample, external
  connector, registry login/push, signed tag, GitHub run, remote write,
  publication, exception approval, or production mutation occurred.

Security/claim boundary: E-055 proves a bounded local pre-parser policy for the
named canonical CSV/XLS/XLSX, mapping, DuckDB, and built-in adapter paths; exact
repository-visible direct tabular-parser inventory; stable safe errors; and the
listed hostile fixture outcomes on locked Python 3.11.15 plus additional local
Python 3.14.6. It does not prove malware absence, file/source authenticity,
polyglot resistance, safe legacy XLS internals, bounded JSON/YAML/generated
artifacts, safe HTTP upload or redistribution, connector sandboxing, operating
system containment, hosted enforcement, continuous control operation, or
independent assessment. It establishes no secure-product, ASVS level,
compliance, certification, enterprise readiness, bank-grade quality, or
production readiness. `P0-SEC-009` and R-018 remain in progress.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, defusedxml 0.7.1, NumPy
2.4.6, Pandas 3.0.5, DuckDB 1.5.5, and additional Python 3.14.6 compatibility.
Docker and live server dependencies remain unavailable. The next safe local
slice is bounded structured JSON/YAML/generated-artifact ingestion; any HTTP
upload, malware-scanner integration, connector expansion, remote execution, or
publication requires its own reviewed authorization and evidence boundary.

## E-056: Bounded structured-document ingress for configuration and controls

Implemented boundary:

- Added runtime `reconforge/io/structured.py` with versioned
  `structured-document-ingress-v1`. The immutable default policy caps one
  UTF-8 JSON/YAML document at 8,388,608 bytes, 200,000 parsed/constructed
  nodes, depth 64, 100,000 items in one collection, 1,000,000 characters in
  one scalar, and 64 YAML aliases. Policy values must be positive integers and
  the policy ID must match exactly.
- File reads reject unsupported suffixes, non-regular/missing/symlinked paths,
  invalid UTF-8, oversized files, and size changes with only `Input document
  rejected (<stable-code>).`. The read itself is capped at policy bytes plus
  one, so a file-growth race cannot turn the post-`stat` read into an
  unbounded allocation. Paths and source values are absent from boundary
  messages.
- JSON uses duplicate-key and non-finite hooks, wraps malformed/deep/huge
  numeric conversion safely, and validates the resulting object graph for
  depth/node/collection/scalar/type/cycle/finite-number constraints.
- YAML first scans SafeLoader events to bound nodes, depth, scalars, aliases,
  and document count and to reject implicit/explicit merge keys. Construction
  uses a SafeLoader-derived duplicate-key-rejecting mapping implementation,
  preserves strict financial float lexemes as exact text, then rejects cyclic
  graphs, non-finite legacy values, unsupported/binary/set-like values, unsafe
  tags, and over-budget collections. Quoted `"<<"` remains ordinary data.
- The adversarial review found that implicit merge events have no resolved
  merge tag, that `read_bytes()` could allocate past a stale size check, that
  huge integer conversion can raise a raw `ValueError`, and that SafeLoader
  can construct binary scalars. Explicit detection, bounded reads, safe
  wrapping, binary rejection, and regressions close each observed edge.
- Routed FI-010 `load_config`, mapping inspection/validation, control-pack
  loading, and `ReconciliationAsCodeSpec.from_yaml` through the boundary.
  Valid legacy/strict financial policies and existing packs remain compatible;
  duplicate keys now fail instead of silently taking the last value, and
  configuration validation no longer returns a local path or input-bearing
  Pydantic detail.
- Extended the closed 13-surface file inventory with exact structured-policy
  parity and three direct-PyYAML allowlist records/calls. Only central
  `yaml.parse`, central legacy `yaml.safe_load`, and the still-partial
  close-workflow `yaml.safe_load` remain. FI-010 advances from partial/none to
  bounded/complete; FI-011 and generated/restore/Studio/report surfaces remain
  explicitly partial.
- Added 27 dedicated structured-ingress cases and two new inventory contracts;
  linked them to reconciliation/mapping module manifests, Security Architecture
  TB-001/SEC-C-002, module threat cases, R-018, selected ASVS V5.1.1/V5.2.1,
  and SSDF PW.5.1. No ASVS/SSDF status total changes. Readable security views
  were corrected where they still described YAML as unbounded or Python as
  unlocked.
- Added ADR 0071, D-052, DOC-021, changelog, claim boundary, package manifest,
  and execution ledgers. `P0-SEC-009` and R-018 remain in progress because
  generated/restore/Studio/report JSON/CSV, close-workflow YAML, legacy XLS
  internals, malware scanning/quarantine, uploads, authenticity, and future
  connector controls remain incomplete.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| `uv.lock` | `92a28d97f3758b7994c9f80b113719d422a2d4b18c6fca4459bb8fb32d115af9` |
| `reconforge/io/structured.py` | `bfc91c8da601e6ef1e5e90afb7eb0c0086f1b6a94af999f3a0964248ffe2862e` |
| `reconforge/utils/yaml.py` | `cf8657ff99db9df9dd32bfcd7d0f4cadbd9a33d318690e55c105c29e57a81f6f` |
| `docs/security/file-ingestion-inventory.v1.yaml` | `4dcb983059491757075c07908ee2641401b10cac9456ed338c075c9b10110f35` |
| `docs/schemas/file_ingestion_inventory.schema.json` | `11175bcf456bafb5e9c069606a6d3a7fbdf439fd3ae204df07c36d9bb857cf67` |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Exact policy-recorded uv archive hash and `uv --version` | Pass; Windows archive SHA-256 `acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984`, uv 0.11.32 commit `3010295ae` | Download/extraction duration not separately retained |
| Locked Python 3.11.15 all-extra non-editable sync | Pass; 102 distributions plus local package installed from 104-package resolution | 13.97s install after interpreter preparation |
| Direct structured-ingress/inventory target on Python 3.11.15 | 32 passed, 0 failed/skipped | 5.61s |
| Same direct target on ambient Python 3.14.6 | 32 passed, 0 failed/skipped | 6.82s |
| Final security/module/risk/ASVS/SSDF/documentation governance target | 74 passed, 0 failed | 19.36s |
| Locked supported Python 3.11.15 full suite with retained session/JUnit | 932 collected; 922 passed, 10 skipped, 0 failed/errors; 8 disclosed warnings | 353.63s wrapper; 351.281s JUnit |
| Locked Ruff 0.16.0 | Pass | 2.49s |
| Locked Mypy 2.3.0 | Pass; no issues in 210 source files | 12.97s |
| Locked Bandit 1.9.4 | Pass; no findings, three existing B608 nosec notices at the same allowlisted identifier-quoted SQL line | 7.68s |
| Exact uv 0.11.32 `lock --check`, hash-exported pip-audit 2.10.1, and policy validation | Pass; 103 Python packages, 0 known findings, 209 npm packages, 155 npm SRI gaps, 0 active exceptions | 22.36s export/audit/policy invocation |
| Final locked Python 3.11 `build --no-isolation` | Pass with existing setuptools metadata warnings | 25.12s |
| Final package membership assertion | Pass; six required runtime/governance/test members in 436-entry sdist; structured/YAML runtime in 217-entry wheel; docs/tests absent from wheel and ADR absent from both | <1s |
| Final sdist | 835,023 bytes; SHA-256 `bbec121cfe62e674a13b155405e7046eeec1b576515dc7b3504062adaa3bc1c6` | Included above |
| Final wheel | 622,152 bytes; SHA-256 `ddb227dd278b5da9d9e46e22715cf5aeb82a892e59367b39b106057b34e95763` | Included above |
| Post-cleanup selected governance target | 43 passed, 0 failed | 14.22s |
| Post-cleanup Ruff, whitespace, evidence-sequence, and temp assertions | Pass; 56 sequential evidence headings, zero `e056*` items, and only the existing `.gitignore` LF-to-CRLF warning | <1s after the test target |

Observed failures and environment handling:

- Inspection after the prior context interruption showed that the intended
  five-call-site integration patch had not applied; no success was inferred.
  The actual call sites were read, patched, and then covered by integration
  tests.
- The first targeted lint found one import-order issue in the new
  Reconciliation-as-Code imports. Ruff's non-writing diff identified the exact
  layout, `apply_patch` corrected it, and all later Ruff runs passed.
- The first supported full-suite shell wrapper discarded the returned process
  session ID after partial output. The test process later exited, but neither
  its exit code nor summary was recoverable, so it is not counted. A new
  basetemp run retained session `39384`, exit code 0, and JUnit SHA-256
  `f9b58379a7fe0c903d81cac781f903fe06ef06de16fbe16b33786f938b0c4a13`.
- The first uv archive comparison used a 65-character transcription from the
  earlier summary rather than the authoritative 64-character policy value;
  extraction stopped. A second attempt referenced the wrong JSON property and
  also stopped. The already-downloaded bytes were then compared to the actual
  closed policy, matched exactly, and only then extracted/executed. Neither
  stopped attempt counts as tool verification.
- One large multi-file documentation patch stopped before mutation when a
  context line differed. Smaller exact-context patches applied and the final
  74-test governance target passed.
- The first post-cleanup gate command stopped during PowerShell parsing because
  a loop variable was immediately followed by a colon inside an interpolated
  error string. No command in that wrapper ran and no result was inferred. The
  variable was delimited explicitly; the fresh 43-test governance, Ruff,
  whitespace, evidence-sequence, and temp assertions then passed.
- The dependency export printed its full hash set despite an output-file
  option, causing tool-output truncation. The audit JSON, exit code, package
  count, finding count, and separate policy result were still captured and
  passed; truncation is not treated as additional dependency evidence.
- Ten optional/live-service skips and eight existing warnings remain
  non-evidence. Docker, Python 3.12 hosted execution, live PostgreSQL/Redis/
  object storage, malware scanning, quarantine, and remote workflow execution
  remain unavailable or unexecuted.
- No customer data, production secret, HTTP upload, malware sample, external
  connector, registry login/push, signed tag, GitHub write/run, publication,
  exception approval, or production mutation occurred.

Final cleanup and inventory: a read-only check resolved 11 explicit `e056*`
temporary targets beneath `F:\reconforge-erp\.codex-test-tmp`, confirmed that
none was a reparse point, and only then removed those targets. The temp root
and every non-E-056 child remain; zero `e056*` items remain. The verified
post-cleanup repository inventory is 210 Python source files, 116 test files,
932 collected tests, 49 JSON schemas, 71 ADRs, 6 workflows, 50 backlog tasks,
189 tracked status entries, and 231 untracked status entries.

Security/claim boundary: E-056 proves fixed local JSON/YAML resource limits,
duplicate/ambiguity/unsafe-structure rejection, exact FI-010 YAML routing,
stable non-sensitive errors, exact repository-visible direct PyYAML inventory,
and the listed hostile fixtures on locked Python 3.11.15 plus a bounded Python
3.14.6 target. It does not prove semantic correctness of an accepted mapping
or rule, author/source authenticity, malware absence, every JSON/YAML/CSV
caller, safe legacy XLS internals, HTTP upload/redistribution, connector
sandboxing, operating-system containment, hosted enforcement, continuous
control operation, or independent assessment. It establishes no secure-product,
ASVS level, compliance, certification, enterprise readiness, bank-grade
quality, or production readiness. `P0-SEC-009` and R-018 remain in progress.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, PyYAML 6.0.3,
defusedxml 0.7.1, NumPy 2.4.6, Pandas 3.0.5, DuckDB 1.5.5, and ambient Python
3.14.6 for the 32-case compatibility target only. Docker and live server
dependencies remain unavailable. The next safe slice is FI-011 bounded close
workflow JSON/YAML; HTTP upload, malware-scanner integration, connector
expansion, remote execution, or publication requires its own reviewed
authorization and evidence boundary.

## E-057: Bounded FI-011 close-workflow JSON/YAML ingress

Implemented boundary:

- Routed local close checklist JSON and JSON/YAML templates through the existing
  `structured-document-ingress-v1` file readers. Direct `json.loads` and
  `yaml.safe_load` no longer parse FI-011 files.
- Preserved valid JSON/YAML task normalization, status semantics, generated
  checklist structure, the legacy `title` alias, report/update callers, and the
  existing public `Close checklist ... could not be parsed.` messages. The
  underlying structured rejection remains chained for diagnosis without
  exposing a selected path or input value in the CLI message.
- Added ten dedicated cases for a valid JSON template, duplicate/non-finite/deep
  JSON, the default 8,388,608-byte ceiling, and duplicate/deep/alias-heavy/
  unsafe-tag/multiple-document YAML. The pre-existing seven close-workflow cases
  remain unchanged and pass.
- Advanced FI-011 from partial/none to bounded/complete in the closed 13-surface
  inventory. Its direct PyYAML entry was removed only after the AST contract
  proved that the two central calls—`yaml.parse` in the structured preflight and
  the legacy `yaml.safe_load` compatibility constructor—are the only production
  direct PyYAML parser calls.
- Linked the dedicated test to `finance.controls`, added its hostile-file threat
  case, and updated Security Architecture SEC-C-002, R-018, selected ASVS
  V5.1.1/V5.2.1, and SSDF PW.5.1. R-018 remains High and partially mitigated;
  no ASVS or SSDF status total changed.
- Added ADR 0072, D-053, DOC-022, backlog/changelog/claim updates, and an explicit
  next slice. FI-012 and generated/report/restore/Studio JSON/CSV, legacy XLS
  internals, authenticated provenance, malware scanning/quarantine, upload, and
  connector controls remain open, so `P0-SEC-009` stays in progress.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| `uv.lock` | `92a28d97f3758b7994c9f80b113719d422a2d4b18c6fca4459bb8fb32d115af9` |
| `reconforge/io/structured.py` | `bfc91c8da601e6ef1e5e90afb7eb0c0086f1b6a94af999f3a0964248ffe2862e` |
| `reconforge/close_workflow.py` | `ff61160adc5bf093da51570ddcb92bfdcf7d8a3ba6d2a27307c92486822fea9b` |
| `tests/test_close_workflow_structured_ingress.py` | `8f835cfa31179208cbda481ec013fc5d36505a7f836aad6367cc8ca315ac2d22` |
| `docs/security/file-ingestion-inventory.v1.yaml` | `5439d8c0e89c5fa1929d2c2a11ef992ae66ba966715d148cfef947c4a29261a3` |
| `docs/security/security-architecture.v2.yaml` | `471aaae75c56fb9887aef1e61ccd4b1152a80b9a7935013ff2e96ce9ed47af00` |
| `docs/security/threat-model-index.v1.yaml` | `eab79c382bf87fb12c4240d08d3a65ac008f1f02ac5e93cb1a9619a08e3d5fd8` |
| `docs/adr/0072-bound-close-workflow-structured-ingress.md` | `caeaa18b4e62343196b1c7ecc56362350eecebe271c7bd08822a27352eb5d39e` |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Exact policy-recorded uv archive hash and version | Pass; Windows archive SHA-256 `acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984`, uv 0.11.32 commit `3010295ae` | Initial download/setup duration not recoverable; idempotent locked resync 0.97s |
| Locked Python 3.11.15 all-extra non-editable resync | Pass; 104-package resolution and 102 installed packages checked | 0.97s |
| FI-011 focused close/inventory/module target on locked Python 3.11.15 | 31 passed, 0 failed/errors/skipped; JUnit SHA-256 `7515b1adc6a97d0428b5760b305d0e98cf611b732ee2fbd832209684917af83c` | 12.15s wrapper; 10.174s JUnit |
| Same focused target on ambient Python 3.14.6 | 31 passed, 0 failed | 13.55s |
| Combined structured/FI-011/inventory boundary target on Python 3.11.15 | 42 passed, 0 failed; JUnit SHA-256 `7a36e52a247ce57ce34bc341d7dc5dd6df79e7888bce1611a5a1e1f52c6a3714` | 10.21s |
| Final security/module/risk/ASVS/SSDF/documentation governance target | 43 passed, 0 failed | 13.86s |
| Locked supported Python 3.11.15 full suite with retained session/JUnit | 942 collected; 932 passed, 10 skipped, 0 failed/errors; 8 disclosed warnings; JUnit SHA-256 `b62ffe331806063cc5b0895486aad9c6173a7778cc8ccc82956c5004417878b0` | 363.79s wrapper; 361.795s JUnit |
| Locked Ruff 0.16.0 | Pass | 3.30s |
| Locked Mypy 2.3.0 | Pass; no issues in 210 source files | 24.24s |
| Locked Bandit 1.9.4 | Pass; no findings and the same three B608 nosec notices at the allowlisted identifier-quoted SQL line | 7.55s |
| Exact uv `lock --check`, hash-exported pip-audit 2.10.1, and policy validation | Pass; 103 policy Python packages, 101 environment-applicable audit dependencies, 0 known findings, 209 npm packages, 155 npm SRI gaps, 0 active exceptions | 27.01s export/audit/policy invocation |
| Final locked Python 3.11 `build --no-isolation` | Pass with existing setuptools metadata warnings | 27.14s |
| Final package membership assertion | Pass; bounded close/structured runtime in 437-entry sdist and 217-entry wheel; updated governance and new test sdist-only; tests/docs absent from wheel and ADR absent from both | <1s |
| Final sdist | 836,107 bytes; SHA-256 `ddc6bcb19c9db3b2ba01d1071307b5924830ecf9c91067b25309998687f23de3` | Included above |
| Final wheel | 622,145 bytes; SHA-256 `9241cedbfb60bdec142f66a64cb2374fbd430091a06ce49a999298d4c5dc25b4` | Included above |
| Post-cleanup selected governance target | 43 passed, 0 failed | 18.83s |
| Post-cleanup Ruff, whitespace, evidence-sequence, and temp assertions | Pass; 57 sequential evidence headings, zero `e057*` items, and only the existing `.gitignore` LF-to-CRLF warning | <1s after the test target |

Observed failures and environment handling:

- The first policy lookup used a nonexistent `python_lock.uv` property and
  returned no data; no mutation or tool identity was inferred. The actual
  `python_resolution` record was then read before any download.
- The first setup wrapper yielded without its session output while the same
  PowerShell process was still writing the uv archive. The partial file was not
  read, deleted, or replaced. Read-only process/size checks showed progress;
  the process completed, the archive then matched the closed policy, and exact
  uv/Python versions plus an idempotent locked resync were verified. The lost
  initial setup duration is not evidence.
- The first supported focused wrapper returned only a progress character and no
  summary. A fresh run with a longer wrapper and JUnit produced the retained
  31-case result; the partial output is not counted.
- An initial PowerShell XML read collided with the `name` attribute and returned
  no suite counts. XPath selection of `/testsuites/testsuite` then produced the
  recorded counts; the mistaken read changed nothing.
- The combined static wrapper retained Ruff and Mypy results but not Bandit's
  summary. A separate complete Bandit run returned exit 0 and the disclosed
  notices; no Bandit pass is inferred from the incomplete wrapper.
- The first package-membership wrapper used a PowerShell option unavailable in
  5.1, so archive variables were empty and `tar` refused the missing argument
  before inspection. The fresh assertion required exactly one wheel and sdist,
  opened them read-only, and passed all presence/absence checks.
- Build logs exceeded the display budget, but the build exit/duration and
  independently reopened artifact counts, bytes, hashes, and membership were
  retained. Truncation is not treated as additional build evidence.
- Ten optional/live-service skips and eight existing warnings remain
  non-evidence. Docker, Python 3.12 hosted execution, live PostgreSQL/Redis/
  object storage, malware scanning, quarantine, and remote workflow execution
  remain unavailable or unexecuted.
- No customer data, production secret, HTTP upload, malware sample, external
  connector, registry login/push, signed tag, GitHub write/run, publication,
  exception approval, or production mutation occurred.

Final cleanup and inventory: a read-only check resolved nine explicit `e057*`
temporary targets beneath `F:\reconforge-erp\.codex-test-tmp`, confirmed that
none was a reparse point, and only then removed those targets. The temp root
and every non-E-057 child remain; zero `e057*` items remain. The verified
post-cleanup repository inventory is 210 Python source files, 117 test files,
942 collected tests, 49 JSON schemas, 72 ADRs, 6 workflows, 50 backlog tasks,
57 sequential evidence records, 190 tracked status entries, and 233 untracked
status entries.

Security/claim boundary: E-057 proves that the documented local FI-011 close
checklist JSON and JSON/YAML template readers inherit fixed structural budgets,
ambiguous/unsafe structure rejection, stable generic CLI errors, and the listed
valid/hostile fixtures on locked Python 3.11.15 plus an additional focused
Python 3.14.6 run. It does not authenticate a template or task author, prove
task/business correctness, create approval/sign-off/audit opinion, scan malware,
cover generated/report/restore/Studio readers or legacy XLS internals, secure an
upload/connector/deployment, or establish independent assessment. It establishes
no secure-product, ASVS level, compliance, certification, enterprise readiness,
bank-grade quality, statutory close, or production readiness. `P0-SEC-009` and
R-018 remain in progress.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, PyYAML 6.0.3,
defusedxml 0.7.1, NumPy 2.4.6, Pandas 3.0.5, and DuckDB 1.5.5. Ambient Python
3.14.6 ran the 31-case compatibility target only. Docker and live server
dependencies remain unavailable. The next safe slice is bounded FI-012 generated
client-pack/evidence JSON manifest readers; CSV redaction, malware/authenticity,
HTTP upload, connector expansion, remote execution, and publication require
their own reviewed evidence boundaries.

## E-058: Bounded FI-012 generated-manifest JSON readers

Implemented boundary:

- Routed `read_client_pack_manifest` and `read_evidence_index` through
  `structured-document-ingress-v1`, replacing direct filesystem `read_text`
  plus `json.loads` at those two FI-012 entrypoints.
- Preserved client-pack current schema v2 and legacy unversioned v1 behavior,
  evidence-index current schema v3 and legacy v2 behavior, policy/fingerprint/
  digest verification, verification-status labels, and the public generic
  `... JSON is invalid` errors. A structured code-only rejection is chained
  internally without exposing a local filename or input value.
- Added ten dedicated cases covering duplicate-key, non-finite, deep, malformed,
  and default-ceiling oversized JSON for both readers; every public message and
  structured cause is asserted. Existing 14 current/legacy/schema/digest/tamper
  contracts also pass.
- Kept FI-012 status `partial` and advanced only `policy_coverage` from none to
  partial. `_redact_json_file` deliberately retains its exact-lexeme strict
  `parse_float` behavior; `_redact_csv_file` and text copying also remain outside
  one uniform bounded redistribution policy. No complete-FI-012 claim is made.
- Linked the dedicated test to `reconciliation.core`, Security Architecture
  SEC-C-002/006, its hostile-file and disclosure threat cases, R-018, selected
  ASVS V5.1.1/V5.2.1, and SSDF PW.5.1. R-018 remains High/partially mitigated;
  R-014/R-017 remain High and no mapping status total changed.
- Added ADR 0073, D-054, DOC-023, backlog/changelog/claim updates, and an E-059
  next action. Generated JSON/CSV/text redaction/copying, report/restore/Studio
  readers, legacy XLS internals, authenticated provenance/disclosure, malware
  scanning/quarantine, upload, and connector controls remain open, so
  `P0-SEC-009` stays in progress.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| `uv.lock` | `92a28d97f3758b7994c9f80b113719d422a2d4b18c6fca4459bb8fb32d115af9` |
| `reconforge/io/structured.py` | `bfc91c8da601e6ef1e5e90afb7eb0c0086f1b6a94af999f3a0964248ffe2862e` |
| `reconforge/reports/client_pack.py` | `658681d5c6154cea0ff5501e0f8f4b893320f275c7eb60dd44a1aadc3e34fe3b` |
| `reconforge/evidence/binder.py` | `26b7dc10937962f530aec95dd81ec5d4e2dbbb4d81d1c33fea9a16b17d607c47` |
| `tests/test_generated_manifest_structured_ingress.py` | `5723d18867cbf6335d0a78a28d130f533fd4da90dfee2a351283f03a285c6114` |
| `docs/security/file-ingestion-inventory.v1.yaml` | `ba117b130571c89b2d9049f5b6c2bada06738da851b39675dba6323dfc8d5dd7` |
| `docs/security/security-architecture.v2.yaml` | `061c9642b2f46ab13e563f5c6c0c0fa68380b95814584d969a9b87e336a24325` |
| `docs/security/threat-model-index.v1.yaml` | `ba572d1e1e7bf081e8eb0743c42858d051401f79e4325c24004b2ebf8c7d76b6` |
| `docs/adr/0073-bound-generated-manifest-json-readers.md` | `533f01adffb8a93f2c1c03038b304ff05813ecba6ed269c8689098b9a84e52b0` |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Exact policy-recorded uv archive and version | Pass; Windows archive SHA-256 `acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984`, uv 0.11.32 commit `3010295ae` | Initial setup duration not retained; locked resync 1.07s |
| Locked Python 3.11.15 all-extra non-editable resync | Pass; 104-package resolution and 102 installed packages checked | 1.07s |
| FI-012 focused manifest/compatibility/inventory/module target on Python 3.11.15 | 38 passed, 0 failed/errors/skipped; one existing legacy-financial warning; JUnit SHA-256 `46eafef8a2a318c7c69a6bdce9791bec311e17c3c8863a8ec5d5bb8e02377d9a` | 14.14s wrapper; 11.620s JUnit |
| Same focused target on ambient Python 3.14.6 | 38 passed, 0 failed; same existing warning | 15.00s |
| Combined structured/close/generated-manifest/inventory boundary target | 52 passed, 0 failed/errors/skipped; JUnit SHA-256 `867d7752eaeca161d8282df6db9fe5c7b84be05eb44396f56b77fceb4ad9e132` | 7.71s wrapper; 5.599s JUnit |
| Final security/module/risk/ASVS/SSDF/documentation governance target | 43 passed, 0 failed | 19.05s |
| Locked supported Python 3.11.15 full suite with retained session/JUnit | 952 collected; 942 passed, 10 skipped, 0 failed/errors; 8 disclosed warnings; JUnit SHA-256 `c3e1beadbd24f05c57d15293ceb335f1b62163b0c6733349be42eedce84dfb9c` | 395.36s wrapper; 393.023s JUnit |
| Locked Ruff 0.16.0 | Pass | 7.02s |
| Locked Mypy 2.3.0 | Pass; no issues in 210 source files on the final cached run | 0.61s |
| Locked Bandit 1.9.4 | Pass; no findings and the same three B608 nosec notices | 8.06s |
| Exact uv `lock --check`, hash-exported pip-audit 2.10.1, and policy validation | Pass; 103 policy Python packages, 101 environment-applicable audit dependencies, 0 known findings, 209 npm packages, 155 npm SRI gaps, 0 active exceptions | 27.20s |
| Final locked Python 3.11 `build --no-isolation` | Pass with existing setuptools metadata warnings | 19.49s |
| Final package membership assertion | Pass; manifest/structured runtime in 438-entry sdist and 217-entry wheel; updated governance/new test sdist-only; tests/docs absent from wheel and ADR absent from both | <1s |
| Final sdist | 837,229 bytes; SHA-256 `89187d41ad2e8ef042e8d5a42b03dbd2bd488f885991dd116db646f71e50b2e1` | Included above |
| Final wheel | 622,195 bytes; SHA-256 `f6da43ee9f32f114dde3d64f803dad1748eb93a40d8e7fa998aff39883afdcab` | Included above |
| Post-cleanup selected governance target | 43 passed, 0 failed | 11.39s |
| Post-cleanup Ruff, whitespace, evidence-sequence, and temp assertions | Pass; 58 sequential evidence headings, zero `e058*` items, and only the existing `.gitignore` LF-to-CRLF warning | <1s after the test target |

Observed failures and environment handling:

- The initial curl/setup wrapper reached its output deadline after the verified
  archive, Python 3.11 environment, and sync had started, but did not return its
  summary. A read-only process check showed the setup still active and then
  completed; exact tool/interpreter/import checks and a separate locked resync
  passed. The lost setup duration is not evidence.
- The first supported focused wrapper hit its 30-second envelope after writing
  a complete 38-test JUnit but before returning the shell exit/timing lines. A
  fresh longer-envelope run returned exit 0 and the retained final JUnit; the
  first run is compatibility corroboration only, not the recorded tool pass.
- The first final static wrapper retained only Ruff's result before its output
  envelope ended. No Mypy or Bandit result was inferred. A fresh command then
  returned Mypy success and Bandit exit 0 with the disclosed notices.
- The first package build produced both archives but its verbose output hid the
  final exit/duration. It is not the final build evidence. A fresh isolated
  output directory captured the complete log in memory, returned exit 0 and
  duration, and its archives alone supplied the recorded hashes/membership.
- Build output from the non-evidence first attempt was truncated; no additional
  build claim is derived from it.
- Ten optional/live-service skips and eight existing warnings remain
  non-evidence. Docker, Python 3.12 hosted execution, live PostgreSQL/Redis/
  object storage, malware scanning, quarantine, and remote workflow execution
  remain unavailable or unexecuted.
- No customer data, production secret, HTTP upload, malware sample, external
  connector, registry login/push, signed tag, GitHub write/run, publication,
  disclosure approval, exception approval, or production mutation occurred.

Final cleanup and inventory: a read-only check resolved 11 explicit `e058*`
temporary targets beneath `F:\reconforge-erp\.codex-test-tmp`, confirmed that
none was a reparse point, and only then removed those targets. The temp root
and every non-E-058 child remain; zero `e058*` items remain. The verified
post-cleanup repository inventory is 210 Python source files, 118 test files,
952 collected tests, 49 JSON schemas, 73 ADRs, 6 workflows, 50 backlog tasks,
58 sequential evidence records, 190 tracked status entries, and 235 untracked
status entries.

Security/claim boundary: E-058 proves fixed structured-document budgets and
ambiguity rejection before semantic/digest verification for exactly the local
client-pack manifest and evidence-index JSON readers, while preserving the
listed current/legacy contracts and safe public errors on locked Python 3.11.15
plus an additional focused Python 3.14.6 run. It does not prove FI-012 complete,
bound JSON/CSV/text redaction or copying, authenticate sources, approve
disclosure, prove redaction completeness or malware absence, secure remaining
report/restore/Studio/legacy-XLS/upload/connector/deployment paths, or establish
independent assessment. It establishes no secure-product, ASVS level,
compliance, certification, enterprise readiness, bank-grade quality, audit
opinion, or production readiness. `P0-SEC-009`, FI-012, R-014, R-017, and R-018
remain open/partial as recorded.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, PyYAML 6.0.3,
defusedxml 0.7.1, NumPy 2.4.6, Pandas 3.0.5, and DuckDB 1.5.5. Ambient Python
3.14.6 ran the 38-case compatibility target only. Docker and live server
dependencies remain unavailable. The next safe slice is a bounded exact-lexeme
JSON redaction reader for FI-012; CSV/text copying, malware/authenticity,
disclosure authorization, HTTP upload, connector expansion, remote execution,
and publication require their own reviewed evidence boundaries.

## E-059: Bounded exact-lexeme FI-012 JSON redaction

Implemented boundary:

- Extended `structured-document-ingress-v1` JSON APIs with an explicit
  `preserve_float_lexemes` representation mode. Valid fractional and exponent
  tokens return as their exact source strings, integers remain integers, and
  the existing byte/node/depth/collection/scalar, duplicate-key, non-finite,
  strict-UTF-8, regular-file, and read-race rejections remain unchanged.
- Migrated FI-012 `_redact_json_file` to the shared reader. Strict financial
  mode selects exact float lexemes and preserves the existing boundary fixture
  (`99.999999999999999999` remains in `0-99`); legacy mode retains its finite
  binary-float behavior and the same fixture remains in `100-999`.
- Removed malformed-JSON fallback to unrestricted replacement-decoded text.
  Duplicate, non-finite, malformed, over-depth, invalid-UTF-8, and default
  ceiling oversized JSON now raises the generic
  `Client pack JSON redaction input is invalid` message with a code-only
  `StructuredDocumentError` cause and no filename or financial value.
- Preflighted every selected JSON redaction input before fingerprint hashing or
  destination preparation, then read it again through the same boundary during
  copying. The oversized regression replaces `_sha256` with a failing sentinel,
  proving the 8 MiB rejection occurs before unbounded fingerprint I/O; all six
  hostile integration cases prove the requested output does not yet exist.
- Kept FI-012 `partial`. A concurrent source mutation after preflight can still
  fail after destination preparation, and CSV/text redaction/copying,
  non-redacted artifact copying, complete output transactionality, authenticated
  provenance, disclosure authorization, malware scanning/quarantine, uploads,
  and connectors remain open under R-018.
- Added ADR 0074, D-055, DOC-024, module/package inventory evidence, and updated
  Security Architecture, threat model, ASVS V5.1.1/V5.2.1, SSDF PW.5.1, risk,
  backlog, claims, quality, inventory, changelog, and execution state. FI-012
  remains partial, R-018 remains High/partially mitigated, and no ASVS/SSDF
  status total changes.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| `uv.lock` | `92a28d97f3758b7994c9f80b113719d422a2d4b18c6fca4459bb8fb32d115af9` |
| `reconforge/io/structured.py` | `0a44b8cee51ea7e48f32339dc8b3c94edafe54bb0332b23373be9ce9777cff63` |
| `reconforge/reports/client_pack.py` | `405a45ae17756328aae1aad793d63fdd0a99f1fb94213a47f5e9a8129a19a942` |
| `tests/test_client_pack_redaction_ingress.py` | `f65e8d85f14843738cdb343eb9b0a52db434a8d878867eb452147e497c37cccb` |
| `docs/security/file-ingestion-inventory.v1.yaml` | `8911c60405971b1e3d12a9011cd94f8065282f2c9b9ecaccd95cfe649da71921` |
| `docs/security/security-architecture.v2.yaml` | `b7ebd6c9a512125855219b69405d7f25d90e3ffa19cd96841df3880891f61818` |
| `docs/security/threat-model-index.v1.yaml` | `d3097f0710cb543e12981b681cd94ffe5d96010d54eb39ea2fc1e9847738a7c5` |
| `docs/adr/0074-bound-client-pack-json-redaction.md` | `e287ddd66a7995ba6c1ac75ffd4e3d361cb4858d32d3661c313b8641107f5736` |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Exact policy-recorded uv archive, Python, and locked all-extra sync | Pass; Windows uv archive SHA-256 `acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984`; uv 0.11.32 commit `3010295ae`; Python 3.11.15; 104-package resolution and 102 installed packages | 335.68s including downloads/build/install |
| E-059 focused reader/redaction/financial/inventory/module target on Python 3.11.15 | 55 passed, 0 failed/errors/skipped; JUnit SHA-256 `7a0c26e683e42e3d01d34e2925eb111060feeb61347beafa6359a284a205f1a3` | 13.11s wrapper; 10.989s JUnit |
| Same focused target on ambient Python 3.14.6 | 55 passed, 0 failed | 14.36s |
| Combined structured/close/generated-manifest/redaction/inventory boundary target | 59 passed, 0 failed/errors/skipped; JUnit SHA-256 `68be2d7d8e06f3f633a35e3794d66fad99588cd054497599fbee0b281191652d` | 6.56s wrapper; 4.723s JUnit |
| Final security/module/risk/ASVS/SSDF/documentation governance target before cleanup | 49 passed, 0 failed | 14.83s |
| Locked supported Python 3.11.15 full suite with retained session/JUnit | 959 collected; 949 passed, 10 skipped, 0 failed/errors; 8 disclosed existing warnings; JUnit SHA-256 `2d7ac587878b7881db39b94f1f8446d49811e019c1bd0782bda812aa4f1be13e` | 395.94s wrapper; 393.620s JUnit |
| Locked Ruff 0.16.0 | Pass | 2.21s |
| Locked Mypy 2.3.0 | Pass; no issues in 210 source files | 2.14s |
| Locked Bandit 1.9.4 | Pass; no findings and the same three B608 nosec notices | 9.70s |
| Exact uv `lock --check`, hash-exported pip-audit 2.10.1, npm lock audit, and closed policy validation | Pass; 103 policy Python packages, 0 findings; 209 npm packages, 0 high findings, 155 disclosed SRI gaps; 0 active exceptions | 23.99s |
| Final locked Python 3.11 `build --no-isolation` | Pass with existing setuptools metadata warnings | 19.11s |
| Final package membership assertion | Pass; exact-lexeme structured/client-pack runtime in 439-entry sdist and 217-entry wheel; updated security/risk governance and new test sdist-only; tests/docs absent wheel and ADR 0074 absent both | <1s |
| Final sdist | 838,880 bytes; SHA-256 `6c76c65dcb8386e812bc5d4eb6404e48be728643b0457e31fd5670549f79b76f` | Included above |
| Final wheel | 622,415 bytes; SHA-256 `3ebe5adeee95e15f1c454736146b239d51e5c6e8e412b67b1c94fada1fd1a7e9` | Included above |
| Post-cleanup selected governance target on ambient Python 3.14.6 | 49 passed, 0 failed | 15.53s |

Observed failures and environment handling:

- A first successful package build was intentionally superseded because the
  readable normalized risk record changed afterward. Its artifacts supplied no
  final hash or membership claim and were deleted; the fresh `e059-dist-final`
  build alone supplied the recorded package evidence.
- The safety wrapper rejected the first PowerShell `Remove-Item` cleanup command
  before execution, so it deleted nothing. A subsequent verified .NET pass
  removed eight ordinary E-059 targets and stopped at a read-only file inside
  `e059-python`. The remaining ten top-level targets were re-inventoried inside
  the exact temp root, zero top-level or nested reparse points were found,
  read-only attributes were normalized only beneath those targets, and the ten
  were deleted. The post-cleanup governance run then created one fresh
  `e059-post-base`; its exact location and zero nested reparse points were
  checked before deletion. Zero `e059*` targets remain and the temp root plus
  all unrelated children remain.
- Ten optional/live-service skips and eight existing warnings remain
  non-evidence. Docker, Python 3.12 hosted execution, live PostgreSQL/Redis/
  object storage, malware scanning, quarantine, and remote workflow execution
  remain unavailable or unexecuted.
- No customer data, production secret, HTTP upload, malware sample, external
  connector, registry login/push, signed tag, GitHub write/run, publication,
  disclosure approval, exception approval, or production mutation occurred.

Final cleanup and inventory: 18 explicit top-level `e059*` temporary targets,
plus the one later post-cleanup governance basetemp, were resolved under
`F:\reconforge-erp\.codex-test-tmp` before deletion; the read-only interruption
and bounded recovery are disclosed above. Zero E-059 targets remain. The
post-cleanup repository inventory is 210 Python source
files, 119 test files, 959 collected tests, 49 JSON schemas, 74 ADRs, 6
workflows, 50 backlog tasks, 59 sequential evidence records, 190 tracked status
entries, and 237 untracked status entries.

Security/claim boundary: E-059 proves fixed structured-document resource and
ambiguity controls for exactly FI-012 JSON redaction while preserving the
documented strict/legacy financial buckets and rejecting predictable hostile
JSON before fingerprint hashing or destination preparation. It does not prove
FI-012 complete, bound CSV/text or non-redacted copying, complete output
atomicity under concurrent mutation, redaction completeness, authenticated
source/provenance, disclosure approval, malware absence, remaining
report/restore/Studio/legacy-XLS/upload/connector/deployment safety, or
independent assessment. It establishes no secure-product, ASVS level,
compliance, certification, enterprise readiness, bank-grade quality, audit
opinion, or production readiness. `P0-SEC-009`, FI-012, R-014, R-017, and R-018
remain open/partial as recorded.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, PyYAML 6.0.3,
defusedxml 0.7.1, NumPy 2.4.6, Pandas 3.0.5, and DuckDB 1.5.5. Ambient Python
3.14.6 ran the 55-case compatibility target only. Docker and live server
dependencies remain unavailable. The next safe slice is bounded streaming
FI-012 CSV redaction; text/non-redacted copying, complete client-pack output
atomicity, malware/authenticity/disclosure authorization, HTTP upload,
connector expansion, remote execution, and publication require their own
reviewed evidence boundaries.

## E-060: Bounded streaming FI-012 CSV redaction

Implemented boundary:

- Added a CSV-specific FI-012 preflight that delegates file/type/size/row/
  column/cell/field checks to `tabular-file-ingress-v1`, decodes strict UTF-8,
  parses with strict `csv.DictReader`, and rejects duplicate headers through a
  generic public error with a code-only `FileIngressError` cause.
- Runs that preflight before source fingerprint hashing or output preparation,
  and repeats it immediately before the redaction read. Oversized sparse input
  therefore fails before `_sha256` and before an existing requested output is
  cleared.
- Streams exact CSV strings one row at a time through the existing strict or
  legacy amount-bucketing policy. Quoted commas, multiline fields, and exact
  decimal lexemes remain strings rather than binary floats.
- Writes each redacted CSV to a hidden same-directory temporary file, closes it,
  and replaces the target only after the complete strict read/write succeeds.
  Header/shape drift or a mid-stream failure removes the temporary file and
  leaves an existing target unchanged.
- Added ten hostile/compatibility/streaming/rollback cases, updated the closed
  direct-parser AST inventory to record both `DictReader` passes, registered the
  test in module/source-distribution contracts, and added ADR 0075, D-056, and
  DOC-025. Security Architecture, threat model, ASVS, SSDF, risk, backlog,
  claims, quality, inventory, changelog, and execution state retain conservative
  partial status.
- FI-012 remains partial. Generated text and non-redacted copies remain
  unbounded, publication is not a complete pack-level transaction, a concurrent
  source mutation can still fail after output preparation, and source
  authenticity, disclosure authorization, redaction completeness, malware
  scanning/quarantine, uploads, and connectors remain open under R-018.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| `uv.lock` | `92a28d97f3758b7994c9f80b113719d422a2d4b18c6fca4459bb8fb32d115af9` |
| `reconforge/reports/client_pack.py` | `75ece002cc51970ab0ab0047a2f7275adcfce1dacea5e87f23181c7dc54dfe9f` |
| `tests/test_client_pack_csv_redaction_ingress.py` | `62539628d658d22bcbf023d62c6d45737a28a29b4cccf0545371a3b92f8ac7cd` |
| `docs/security/file-ingestion-inventory.v1.yaml` | `02dbe04fcc478ac85ad0ad4f87b30e87d5314f51b5b7a3e9b58b7abc75ce3301` |
| `docs/security/security-architecture.v2.yaml` | `28dfc9c1cdaa2a71f25d29f97070d43abb2c93f3da399f7b92c8bc552d18ad75` |
| `docs/security/threat-model-index.v1.yaml` | `338a57aa40e9ab061967d8348ac4752fad0cbdb94f0082d544d6330a32e1044d` |
| `docs/adr/0075-bound-streaming-client-pack-csv-redaction.md` | `a5cee3a2a40bca1c518aef82ed5c12884d3cdc071e41a36b3b658cee07fed1f9` |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Exact policy-recorded uv archive, Python, and locked all-extra sync | Pass; Windows uv archive SHA-256 `acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984`; uv 0.11.32 commit `3010295ae`; Python 3.11.15; 104-package resolution and 102 installed packages | 263.76s including setup/sync |
| E-060 focused ingress/CSV-redaction/financial/inventory/module target on Python 3.11.15 | 53 passed, 0 failed/errors/skipped; JUnit SHA-256 `56fa646f0a59627b2e2e19fde14eca8445d72513d2ea6bf9428f467c9d2a9c34` | 13.99s wrapper; 11.653s JUnit |
| Same focused target on ambient Python 3.14.6 | 53 passed, 0 failed | 13.55s |
| Combined structured/close/manifest/JSON-redaction/CSV-redaction/inventory boundary target | 85 passed, 0 failed/errors/skipped; JUnit SHA-256 `45515643c2749e1ec7d48aabe64c9ff0fd4708b599cb7a02bdddae3a21ffacf5` | 8.17s wrapper; 6.263s JUnit |
| Final security/module/risk/ASVS/SSDF/documentation governance target before cleanup | 53 passed, 0 failed | 15.01s |
| Locked supported Python 3.11.15 full suite with retained session/JUnit | 969 collected; 959 passed, 10 skipped, 0 failed/errors; 8 disclosed existing warnings; JUnit SHA-256 `2a67e994fe79617d924f5f4307c44d746bdb99f0a86daf6e51b301a20b91f88d` | 387.42s wrapper; 385.117s JUnit |
| Locked Ruff 0.16.0 | Pass | 2.24s |
| Locked Mypy 2.3.0 | Pass; no issues in 210 source files | 1.90s |
| Locked Bandit 1.9.4 | Pass; no findings and the same three B608 nosec notices | 8.85s |
| Exact uv `lock --check`, hash-exported pip-audit 2.10.1, npm lock audit, and closed policy validation | Pass; 103 policy Python packages, 0 findings; 209 npm packages, 0 high findings, 155 disclosed SRI gaps; 0 active exceptions | 5.16s |
| Final locked Python 3.11 `build --no-isolation` | Pass with existing setuptools metadata warnings | 22.44s |
| Final package membership assertion | Pass; client-pack runtime in 440-entry sdist and 217-entry wheel; updated security/risk governance and new CSV-redaction test sdist-only; tests/docs absent wheel and ADR 0075 absent both | <1s |
| Final sdist | 841,036 bytes; SHA-256 `e5cd79f13b10441525262ab13810ddd029599ac916315f0fabe5c2a18f5b4b09` | Included above |
| Final wheel | 622,880 bytes; SHA-256 `ef4630de1f1e4d1856c66796276d3154d2056e272b235b75b675e01870f4d522` | Included above |
| Post-cleanup selected governance target on ambient Python 3.14.6 | 53 passed, 0 failed | 15.49s |

Observed failures and environment handling:

- The first parametrized focused run passed five cases but produced two fixture
  setup errors because pytest embedded a 128,001-character parameter value in
  a Windows temporary path. Neither affected product case ran. Short stable
  parameter IDs removed the path artifact, and the complete 22-case immediate
  target then passed.
- The first 61-case expanded target had 60 passes and one real governance
  failure: exact AST inventory correctly rejected a newly unregistered
  `csv.reader` site. Duplicate-header preflight was expressed with the already
  inventoried strict `csv.DictReader`; its exact call count/rationale were
  updated, and the full 61-case rerun passed.
- The first audit wrapper returned after lock and pip-audit success but before
  npm/policy completion, so it supplies no aggregate audit claim. A fresh
  retained run completed all four checks in 5.16s and supplies the recorded
  result.
- Ten optional/live-service skips and eight existing warnings remain
  non-evidence. Docker, Python 3.12 hosted execution, live PostgreSQL/Redis/
  object storage, malware scanning, quarantine, and remote workflow execution
  remain unavailable or unexecuted.
- No customer data, production secret, HTTP upload, malware sample, external
  connector, registry login/push, signed tag, GitHub write/run, publication,
  disclosure approval, exception approval, or production mutation occurred.

Final cleanup and inventory: 17 explicit top-level `e060*` temporary targets
were resolved beneath `F:\reconforge-erp\.codex-test-tmp`; zero top-level or
nested reparse points were found, attributes were normalized only within those
targets, and .NET deleted them while preserving the temp root and unrelated
children. The post-cleanup governance run created one later
`e060-post-base`; its exact location and zero nested reparse points were checked
before deletion. Zero E-060 targets remain. The verified post-cleanup inventory
is 210 Python source files, 120 test files, 969 collected tests, 49 JSON schemas,
75 ADRs, 6 workflows, 50 backlog tasks, 60 sequential evidence records, 190
tracked status entries, and 239 untracked status entries.

Security/claim boundary: E-060 proves bounded tabular preflight and streaming,
exact-string, per-file atomic replacement for exactly FI-012 CSV redaction on
the documented local paths. It does not prove FI-012 complete, bound text or
non-redacted copying, full pack-level transactionality, redaction completeness,
authenticated source/provenance, disclosure approval, malware absence,
remaining report/restore/Studio/legacy-XLS/upload/connector/deployment safety,
or independent assessment. It establishes no secure-product, ASVS level,
compliance, certification, enterprise readiness, bank-grade quality, audit
opinion, or production readiness. `P0-SEC-009`, FI-012, R-014, R-017, and R-018
remain open/partial as recorded.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, PyYAML 6.0.3,
defusedxml 0.7.1, NumPy 2.4.6, Pandas 3.0.5, and DuckDB 1.5.5. Ambient Python
3.14.6 ran the 53-case compatibility target only. Docker and live server
dependencies remain unavailable. The next safe slice is to bound generated
text and non-redacted client-pack copies and define compatibility-safe complete
pack staging/publication; malware/authenticity/disclosure authorization, HTTP
upload, connector expansion, remote execution, and publication require their
own reviewed evidence boundaries.

## E-061: Bounded client-pack copying and staged publication

Implemented boundary:

- Replaced unbounded replacement-decoded generic text reads and `copy2` with a
  frozen FI-012 candidate/selected-set policy: at most 20,000 traversed entries,
  10,000 selected regular non-symlink files, 64 MiB per file, and 512 MiB
  aggregate. Output manifest rechecks use the same bounded traversal/fingerprint
  family with a small generated-file allowance.
- Generic redacted text now requires strict UTF-8 and streams one line at a
  time with a 1 MiB line ceiling. Non-redacted bytes stream in 1 MiB chunks to a
  same-directory temporary file while comparing lstat/open/final sizes and the
  final whole-set fingerprint. The AST contract rejects reintroduction of
  whole-file `read_text`/`read_bytes` and common unbounded shutil copy helpers in
  the client-pack module.
- Froze all initially discovered candidates separately from the selected,
  fingerprinted copy set. Files created after selection are not copied or
  manifested, while initially present raw/unsupported files remain visible in
  `excluded_files` without having their content copied or fingerprinted.
- Builds copies, redactions, summaries, final source recheck, and manifest in a
  unique sibling staging directory. Fresh publication uses one rename. Existing
  output moves to a unique rollback sibling, the staged pack moves into place,
  and handled publish or old-pack cleanup failure restores the prior output.
  Successful publication removes stale—including hidden—content and returned
  artifact paths are rebased to the published directory.
- Preserved the historical demo-compatible `source/client_pack` path because
  top-level non-evidence directories are outside the frozen candidate set;
  source-equal/source-containing, evidence-nested, symlink, and non-directory
  output targets fail before mutation.
- Added 17 resource/encoding/symlink/race/enumeration/publication/rollback/
  nested-output/compatibility/AST tests, ADR 0076, D-057, DOC-026, module and
  sdist registration, and updated security architecture, threat, ASVS, SSDF,
  risk, backlog, claims, operator docs, inventory, changelog, and state.
- FI-012 and R-018 remain partial/High. Existing non-empty directory replacement
  on Windows requires two renames and is not observer-atomic or crash-atomic; a
  process/host loss in that window can leave a rollback sibling requiring an
  explicit recovery protocol. Malware scanning/quarantine, authenticated
  provenance, disclosure authorization, redaction completeness, remaining
  report/restore/Studio/legacy-XLS paths, uploads, and connectors remain open.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| `uv.lock` | `92a28d97f3758b7994c9f80b113719d422a2d4b18c6fca4459bb8fb32d115af9` |
| `reconforge/reports/client_pack.py` | `74f6ed3a7864e2afe91d7e562e797ae2e24c5a875f9c1b4fbd5ac43a1a5cae76` |
| `tests/test_client_pack_copy_publication.py` | `fe78d139cd8352bfab0612247ef86c8769e9efbe5d37623499b891dcf3c6563a` |
| `docs/security/file-ingestion-inventory.v1.yaml` | `76be9a52ee7bc4900b3d0b8d53312e28a30faeec1e9ec7b517b08cdf45077847` |
| `docs/security/security-architecture.v2.yaml` | `d145f6581f6e3156209bd87d57f2fedadf167704d300300317dded3b9951ac8d` |
| `docs/security/threat-model-index.v1.yaml` | `e6dd853a7cd58bf99fc7ea880a30bd6bd57664c0ac1030258775ab664f40d368` |
| `docs/adr/0076-bound-client-pack-copy-and-staged-publication.md` | `9d2efaea2bcf17524ac69334d43ae3a0786a777a6af1242e5995e2dfc1458684` |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Exact policy-recorded uv archive, version, Python, and locked all-extra sync | Pass; Windows archive SHA-256 `acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984`; uv 0.11.32 commit `3010295ae`; Python 3.11.15; 104-package resolution, 101 prepared/installed packages | Wrapper duration not retained; uv reported 3m19s preparation and 2.03s installation |
| Final E-061 focused client-pack/manifest/ingress/inventory/module target on Python 3.11.15 | 80 passed, 0 failed/errors/skipped; JUnit SHA-256 `15635f48eae8cdeafaa0a839c6fb4cc9dca441c9d810564e19393edad9ab1786` | 14.18s |
| Same focused target on ambient Python 3.14.6 | 80 passed, 0 failed | 14.53s |
| Final combined tabular/structured/close/manifest/JSON/CSV/text-copy/inventory boundary target | 102 passed, 0 failed/errors/skipped; JUnit SHA-256 `dd949cba4d1b0958bd4cac22d212cccf250282b4ee2ace4e18be75dfd64ec2db` | 7.98s |
| Final security/module/risk/ASVS/SSDF/documentation governance target before cleanup | 60 passed, 0 failed | 18.30s |
| Final locked supported Python 3.11.15 full suite with retained session/JUnit | 986 collected; 976 passed, 10 skipped, 0 failed/errors; 8 disclosed existing warnings; JUnit SHA-256 `ff2f76f8b8c72f50eaa921fb939f06019830419cd2d60d25889f9839363ee10d` | 373.85s wrapper; 371.577s JUnit |
| Locked Ruff 0.16.0 | Pass | 2.27s |
| Locked Mypy 2.3.0 | Pass; no issues in 210 source files | 3.17s |
| Locked Bandit 1.9.4 | Pass; no findings and the same three B608 nosec notices | 11.10s |
| Exact uv `lock --check`/hash export, pip-audit 2.10.1, npm lock audit, and closed policy validation | Pass after the disclosed network retry; 103 policy Python packages, 0 findings; 209 npm packages, 0 high findings, 155 disclosed SRI gaps; 0 active exceptions | 16.33s final pip-audit plus 2.19s npm/policy validation |
| Final locked Python 3.11 `build --no-isolation` | Pass with existing setuptools metadata warnings | 28.92s |
| Final package membership assertion | Pass; bounded client-pack runtime in 441-entry sdist and 217-entry wheel; updated security/risk governance and new copy/publication test sdist-only; tests/docs absent wheel and ADR 0076 absent both | <1s |
| Final sdist | 846,175 bytes; SHA-256 `362f4393f170c926bf8d26b3113bc561c749d8ad6566cc8983e5983920232839` | Included above |
| Final wheel | 624,758 bytes; SHA-256 `75e73d246bcbd39df84c556a504006acbdfd018626b9c13cbb50f8e05534f551` | Included above |
| Post-cleanup selected governance target on ambient Python 3.14.6 | 60 passed, 0 failed | 20.80s |

Observed failures and environment handling:

- The first final governance target had 57 passes and one real failure: the
  runtime module registry linked the new test but `reconciliation.core`'s exact
  threat-model `module_test_evidence` did not. The normative threat record and
  its disclosure threat case were updated; the fresh 58-case target passed,
  followed by the final expanded 60-case target after two additional rollback/
  compatibility tests were added.
- The first locked full run collected 984 tests and ended with 972 passes, two
  real failures, ten skips, and eight warnings. The demo's compatible nested
  `source/client_pack` output was rejected, and the frozen selected-only list
  no longer reported an excluded raw record. Separating frozen candidates from
  selected/fingerprinted copies and permitting only top-level non-evidence
  nested output fixed both; the affected target passed. A later cleanup-failure
  rollback test raised the total to 986, and the retained full rerun passed.
- The first aggregate audit wrapper returned no complete result and produced no
  pip report. A separate pip-audit then failed operationally on a 15-second TLS
  handshake timeout to `pypi.org`; it is not a vulnerability result. The same
  hash-required audit with a 60-second socket timeout completed in 16.33s with
  zero findings, and fresh npm plus both closed-policy validations passed.
- Ten optional/live-service skips and eight existing warnings remain
  non-evidence. Docker, Python 3.12 hosted execution, live PostgreSQL/Redis/
  object storage, malware scanning, quarantine, and remote workflow execution
  remain unavailable or unexecuted.
- No customer data, production secret, HTTP upload, malware sample, external
  connector, registry login/push, signed tag, GitHub write/run, publication,
  disclosure approval, exception approval, or production mutation occurred.

Final cleanup and inventory: 33 explicit top-level `e061*` temporary targets
were resolved beneath `F:\reconforge-erp\.codex-test-tmp`; zero top-level or
nested reparse points were found, attributes were normalized only within those
targets, and .NET deleted them while preserving the temp root and unrelated
children. The post-cleanup governance run created one later `e061-post-base`;
its exact name and zero nested reparse points were checked before deletion.
Zero E-061 targets remain. The verified post-cleanup inventory is 210 Python
source files, 121 test files, 986 collected tests, 49 JSON schemas, 76 ADRs, 6
workflows, 50 backlog tasks, 61 sequential evidence records, 194 tracked status
entries, and 241 untracked status entries.

Security/claim boundary: E-061 proves fixed resource limits, frozen selection,
strict streamed text, bounded non-redacted copying/output recheck, complete-pack
staging, and prior-output rollback for handled FI-012 generation/publication
failures on the documented local paths. It does not prove crash-atomic or
observer-atomic existing-directory replacement, recovery after process/host
loss, redaction completeness, authenticated source/provenance, disclosure
approval, malware absence, remaining report/restore/Studio/legacy-XLS/upload/
connector/deployment safety, or independent assessment. It establishes no
secure-product, ASVS level, compliance, certification, enterprise readiness,
bank-grade quality, audit opinion, or production readiness. `P0-SEC-009`,
FI-012, R-014, R-017, and R-018 remain open/partial as recorded.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, PyYAML 6.0.3,
defusedxml 0.7.1, NumPy 2.4.6, Pandas 3.0.5, and DuckDB 1.5.5. Ambient Python
3.14.6 ran the 80-case compatibility target only. Docker and live server
dependencies remain unavailable. The next safe slice is an integrity-checked,
explicitly unauthenticated local publication marker and recovery path for the existing-directory
two-rename window; malware/authenticity/disclosure authorization, HTTP upload,
connector expansion, remote execution, and publication require their own
reviewed evidence boundaries.

## E-062: Integrity-checked client-pack publication recovery

Implemented boundary:

- Existing-output publication writes a schema-v1 JSON marker before its first
  rename. The path-minimized document contains a random 128-bit transaction ID,
  exact output/staging/rollback basenames, phase, bounded previous/staged tree
  SHA-256 digests, a canonical marker digest, and an explicit integrity
  boundary; it contains no absolute path or financial row. Atomic temporary
  replacement, flush, and file `fsync` are used, without claiming portable
  parent-directory or power-loss durability.
- `reconforge report client-pack-recover --output PATH` is explicit rather than
  automatic. It accepts exactly four output/staging/rollback states, including
  phase-lag states possible between a rename and marker update. It restores the
  verified previous pack before publication, or finalizes/confirms a verified
  staged pack after publication.
- Recovery requires exactly one closed, canonically self-validating marker,
  exact bound siblings, bounded hidden-plus-visible tree fingerprints, regular
  directories, and no reparse point. Missing/multiple/tampered markers, changed
  bytes, unknown/temporary siblings, and all ambiguous states fail before
  mutation. Fresh publication also refuses an unexpected matching sibling.
- Handled exceptions retain ADR 0076 rollback. Unhandled `BaseException`
  simulation bypasses that handler; generator cleanup preserves staging only
  when an exact valid marker binds it. This closed a review-discovered gap where
  `KeyboardInterrupt`/`SystemExit` unwinding could otherwise delete recoverable
  staging.
- Added 13 direct/generator interruption, four-state, marker/tree tamper,
  multiple/unknown sibling, reparse, fresh-output refusal, CLI, minimized-data,
  and successful-cleanup cases; ADR 0077, D-058, DOC-027, operator guidance,
  module/risk/security/threat/ASVS/SSDF links, and FI-012 inventory evidence.
- The marker is deliberately described as integrity/self-consistency, not
  authenticated. An actor who can rewrite marker and directories can recompute
  unkeyed hashes. Existing-output replacement remains non-observer-atomic and
  non-crash-atomic; real process kill, host/power loss, journal replay, remote
  filesystem, malware, provenance, disclosure authorization, and remaining
  report/restore/Studio/legacy-XLS paths remain open under R-018.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| `uv.lock` | `92a28d97f3758b7994c9f80b113719d422a2d4b18c6fca4459bb8fb32d115af9` |
| `reconforge/reports/client_pack.py` | `6d757778fdb4732c98c7956e2b202dd23aaf14ddf8d09235f85a583ba2464d8a` |
| `reconforge/cli.py` | `b870ee1f6c64fdd7c9d78347e497117a735a6a2f6b1838caf62b209e498be2d2` |
| `tests/test_client_pack_publication_recovery.py` | `0435739c812a2d2a47bd78481b422818530c351af8ee2c4d571d97330a3a73f5` |
| `docs/security/file-ingestion-inventory.v1.yaml` | `0224ab84e2ff4408e0f22b5b4124e29f7e879e9d6091cba44599bc6e46848e65` |
| `docs/security/security-architecture.v2.yaml` | `e964d453d57c085de2a439762111f4af8d1501ad623b60d887cda7f36b0ee54f` |
| `docs/security/threat-model-index.v1.yaml` | `5dd609e6a2421410844f49f58862ec38b68edb6a269ea1286749c9b5cfb09b10` |
| `docs/risk-register.yaml` | `30bd42faf69a3e31dee5e167507b1ce882ab3a6afffbe04c17ee685ccdbea31e` |
| `docs/adr/0077-integrity-checked-client-pack-publication-recovery.md` | `b665569ef47272b5beea49da75ff43e7222ffd726869d0b127e22f5df2b54b2f` |
| `docs/client-handoff-pack.md` | `5c0b15e27f11d40b13a00c9360425f36c46cb251138ee5efc2a6a0ad8d48fec3` |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Official uv 0.11.32 Windows archive verification and locked all-extra Python 3.11.15 sync | Pass; archive SHA-256 `acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984`; uv commit `3010295ae`; 104-package resolution | setup duration not retained |
| Final locked focused client-pack/recovery/manifest/inventory/module/demo target | 83 passed, 0 failed/errors/skipped; JUnit SHA-256 `9735ce8b94ee1ba25482dc09a57ce8b13a2869cec0a2307a6d71b490d9a1829a` | 23.124s JUnit |
| Final fixed-snapshot locked Python 3.11.15 full suite | 999 collected; 989 passed, 10 skipped, 0 failed/errors; eight existing warnings; JUnit SHA-256 `d733b8329d4f6192012b5605d5567aecf1f0ce3a027d5194e201a73c05afcf17` | 364.98s wrapper; 362.142s JUnit |
| Locked Ruff 0.16.0 | Pass | duration not retained |
| Locked Mypy 2.3.0 | Pass; no issues in 210 source files | duration not retained |
| Locked Bandit 1.9.4 | Pass; no findings and the same three B608 `nosec` notices | duration not retained |
| Exact uv `lock --check`/hash export, pip-audit 2.10.1, and closed policy validation | Pass; 103 policy Python packages, 101 environment-applicable dependencies, 0 findings, 0 active exceptions | duration not retained |
| npm lock audit and closed policy validation | Pass; 209 packages, 0 high findings, 155 disclosed SRI gaps, 0 active exceptions | 2.5s final invocation |
| Locked Python 3.11 `build --no-isolation` | Pass with existing setuptools metadata warnings | 26.48s |
| Package membership assertion | Pass; recovery runtime/CLI in 442-entry sdist and 217-entry wheel; updated governance and recovery test sdist-only; tests/docs absent wheel and ADR 0077 absent both | <1s |
| Final sdist | 851,151 bytes; SHA-256 `77ee6523b3de691329ee4b88d83f1a8f1b371d9341e1c45ea7923bdce5be9d69` | included above |
| Final wheel | 627,531 bytes; SHA-256 `e7487484dfbc811e9319dff9c7bdaa9e3d0cc6a1b80f9424c17afae4c237b261` | included above |
| Post-cleanup recovery/security/module/risk/ASVS/SSDF governance target on ambient Python 3.14.6 | 56 passed, 0 failed; Ruff pass; `git diff --check` pass with the existing `.gitignore` LF-to-CRLF warning | duration not retained |

Observed failures and environment handling:

- Two early test-harness cases failed: the marker-removal crash monkeypatch was
  still active during recovery, and Windows denied an unprivileged real symlink
  fixture. Restoring the real helper before recovery and simulating the reparse
  predicate made the tests portable without weakening production checks.
- Review then found that generator `finally` could remove staging after an
  unhandled interruption. The in-progress full run against the superseded code
  was explicitly stopped and is not evidence. Valid-marker-bound staging
  preservation plus an end-to-end generator regression was added; the final
  focused and full runs above use the fixed snapshot.
- The first npm invocation selected execution-policy-blocked `npm.ps1`; the
  next BOM-bearing PowerShell JSON write was rejected by the validator. Neither
  is an audit result. Direct `npm.cmd` plus BOM-free UTF-8 produced the retained
  clean audit/policy result.
- Docker, Python 3.12 hosted execution, live PostgreSQL/Redis/object storage,
  real process/host/power/filesystem loss, malware scanning, and quarantine
  remain unavailable or unexecuted. No customer data, production secret,
  external connector, registry login/push, signed tag, GitHub write/run,
  publication, or production mutation occurred.

Final cleanup and inventory: 12 explicit top-level `e062*` temporary targets
were resolved beneath `F:\reconforge-erp\.codex-test-tmp`; zero nested reparse
points were found. Two policy-blocked `Remove-Item` attempts made no mutation;
the same preverified absolute targets were then deleted with explicit .NET
directory/file calls, preserving the temp root and unrelated children. Zero
E-062 targets remain. The verified post-cleanup inventory is 210 Python source
files, 122 `test_*.py` modules, 999 collected tests, 49 JSON schemas, 77 ADRs,
six workflows, 50 backlog tasks, 62 sequential evidence records, 194 tracked
status entries, and 230 untracked status entries.

Security/claim boundary: E-062 proves deterministic explicit recovery for the
four simulated local filesystem states using closed marker/name/tree checks on
the documented client-pack path. It does not prove marker or source
authentication, non-repudiation, parent-directory durability, observer/crash
atomicity, real process/host/filesystem recovery, malware absence, disclosure
approval, redaction completeness, remaining parser/upload/connector safety, or
independent assessment. It establishes no ASVS level, compliance,
certification, enterprise readiness, bank-grade quality, audit opinion, or
production readiness. `P0-SEC-009`, FI-012, R-014, R-017, and R-018 remain
open/partial as recorded.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, PyYAML 6.0.3,
defusedxml 0.7.1, NumPy 2.4.6, Pandas 3.0.5, and DuckDB 1.5.5. Ambient Python
3.14.6 ran only pre-final focused/governance checks and is not retained as
E-062 exit evidence. Docker and live server dependencies remain unavailable.
The next safe slice is E-063 bounded backup/restore archive and manifest
ingress; real host-loss recovery, malware, authenticated provenance, and
disclosure authorization require separate reviewed evidence boundaries.

## E-063: Bounded database backup restore JSON ingress

Implemented boundary:

- Auditing the shipped database format corrected the planned scope: restore
  accepts adjacent `backup.json` and `manifest.json` files and has no ZIP/TAR
  archive parser. E-063 hardens that real compatibility surface and does not
  invent decompression or traversal behavior for a nonexistent format.
- Both files use the named `database-backup-json-ingress-v1` policy: 64 MiB per
  file, one million nodes, depth 64, 250,000 items per collection, and 8 MiB per
  scalar. Strict UTF-8, duplicate JSON keys, non-finite numbers, non-regular or
  reparse files, and before/after size/digest instability fail closed.
- The manifest is a closed document with one exact `backup.json` artifact,
  strict non-boolean version/byte integers, lowercase SHA-256, and matching
  schema/created-at/privacy metadata. Backup documents allow only registered
  table names, object rows with string keys, the exact excluded-table contract,
  and supported schema/format versions. Missing known tables remain compatible
  with historical additive backups.
- Bounded bytes and unkeyed SHA-256 are checked before target preparation. The
  hash proves local integrity/self-consistency only: it does not authenticate a
  publisher or prevent an actor from replacing both adjacent files.
- Added current-writer backup and manifest JSON Schemas plus 19 hostile,
  compatibility, TOCTOU, destination-non-mutation, schema, and AST contracts.
  Nine existing backup/restore cases remain green. FI-009 stays partial because
  `reconforge/db/importers.py::_read_json` is a separate unbounded reader.
- ADR 0078, D-059, DOC-028, the claims matrix, operator guidance, module/risk/
  security/threat/ASVS registries, package manifest, and persistent backlog/state
  now state the exact implemented boundary and its limitations.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| `uv.lock` | `92a28d97f3758b7994c9f80b113719d422a2d4b18c6fca4459bb8fb32d115af9` |
| `reconforge/db/backup.py` | `98d69916b6def931c5da30c93606336e424a01cedd56644d8f6c63cdb0332906` |
| `tests/test_db_backup_structured_ingress.py` | `3c7e58ec30f70e91291f01c07db7342cedb782761ab7a6916d8ef8224b23ca63` |
| `docs/schemas/database_backup.schema.json` | `2724eae7a15d1c238f7c4de6d2acb047d740d0250c086f5a8c42c96448b9a276` |
| `docs/schemas/database_backup_manifest.schema.json` | `2e8dd1cbc16182e8fbeb081a93cdced9ef9a024717cdf85fee13e037b28223c4` |
| `docs/security/file-ingestion-inventory.v1.yaml` | `f4fbbeb9b1dc171198e4a1c9c4bd405c5e1cbaf980ffafb5c8afb7852e5c35db` |
| `docs/security/security-architecture.v2.yaml` | `53226ac028273b36d301ddba756cf9f9fe722251fbf51fe788b859493128f31b` |
| `docs/security/threat-model-index.v1.yaml` | `a13944e4a31b81b814f49ff8d29edd8c2da9306b66b88a0e1bb69250109354b6` |
| `docs/risk-register.yaml` | `3ace40dbb7bfe55ebcd7715d34e7b3add73b2604acc680c0cf573ccf0daeb062` |
| `docs/adr/0078-bound-database-backup-restore-json.md` | `6174aa5222150e73677e6d5e39f44da7aabb2bce45266d3fe8ff2b80eefa223e` |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Official uv 0.11.32 Windows archive verification and locked all-extra Python 3.11.15 sync | Pass; archive SHA-256 `acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984`; uv commit `3010295ae`; 104-package resolution and 102 installed packages | 9.0s sync; download duration not retained |
| Final locked focused backup-ingress/restore target | 28 passed, 0 failed/errors/skipped; JUnit SHA-256 `d67b46989dbaa7c16c6bac4f98939be39d032a08c95f4a02f1f50c9706bedddae` | 16.096s JUnit |
| Final fixed-snapshot locked Python 3.11.15 full suite | 1,018 collected; 1,008 passed, 10 skipped, 0 failed/errors; eight existing warnings; JUnit SHA-256 `613751c4e1af3bbd923ac564b0f7bcc64e04be81f063fe436b0b1f07a3bf7755` | 363.317s JUnit |
| Locked Ruff 0.16.0 | Pass | duration not retained |
| Locked Mypy 2.3.0 | Pass; no issues in 210 source files | duration not retained |
| Locked Bandit 1.9.4 | Pass; no findings and the same three B608 `nosec` notices | 6.7s parallel wrapper with lock export |
| Exact uv `lock --check`/hash export, pip-audit 2.10.1, and closed policy validation | Pass; 103 policy Python packages, 0 known findings, 0 active exceptions | 16.53s final audit/policy invocation |
| npm lock audit and closed policy validation | Pass; 209 packages, 0 high findings, 155 disclosed SRI gaps, 0 active exceptions | 3.9s final invocation |
| Locked Python 3.11 `build --no-isolation` | Pass with existing setuptools metadata warnings | 20.07s |
| Package membership assertion | Pass; backup runtime in 445-entry sdist and 217-entry wheel; two schemas, governance, and dedicated test sdist-only; tests/docs absent wheel and ADR 0078 absent both | <1s |
| Final sdist | 856,321 bytes; SHA-256 `05b2b8db4cb0325d76bdf4ed15b0f2e4986994fb09bb8c686fd6a98687a2150c` | included above |
| Final wheel | 628,901 bytes; SHA-256 `f28f1055eba866a2bc5d9b4c6f9e569a700be92829407fa19dc03612757981eb` | included above |

Observed failures and environment handling:

- The first focused governance run exposed one real YAML error: an unquoted
  colon in the new FI-009 limitation parsed as a mapping rather than a scalar.
  Quoting the limitation restored the closed registry contract; the final
  seven-module governance target passed 38 cases.
- The first npm command used incorrect nested `cmd.exe` quoting, returned exit
  1, and left an invalid/empty report; the policy validator rejected it. This
  is an operational command failure, not an audit result. Direct `npm.cmd`
  capture plus explicit BOM-free UTF-8 produced the retained clean result.
- Docker, Python 3.12 hosted execution, live PostgreSQL/Redis/object storage,
  real process/host/power/filesystem loss, centralized restore authorization,
  backup encryption, malware scanning, and quarantine remain unavailable or
  unexecuted. No customer data, production secret, external connector, registry
  login/push, signed tag, GitHub write/run, publication, or production mutation
  occurred.

Final cleanup and inventory: seven explicit top-level `e063*` temporary targets
were resolved beneath `F:\reconforge-erp\.codex-test-tmp`; zero top-level or
nested reparse points were found, and the preverified targets were deleted with
explicit .NET directory/file calls while preserving the temp root and unrelated
children. Zero E-063 targets remain. The post-cleanup ambient-Python governance
target passed 70 cases; Ruff and `git diff --check` passed with only the existing
`.gitignore` LF-to-CRLF warning. The verified inventory is 210 Python source
files, 123 `test_*.py` modules, 1,018 collected tests, 51 JSON schemas, 78 ADRs,
six workflows, 50 backlog tasks, 63 sequential evidence records, 194 tracked
status entries, and 234 untracked status entries.

Security/claim boundary: E-063 proves bounded, duplicate-safe, closed local JSON
validation and pre-target mutation refusal for the documented two-file SQLite
restore path. It does not prove authenticated provenance, confidentiality,
centralized authorization, archive safety, malware absence, importer coverage,
real host/filesystem recovery, cross-edition DR, or independent assessment. It
establishes no ASVS level, compliance, certification, enterprise readiness,
bank-grade quality, audit opinion, or production readiness. `P0-SEC-009`,
FI-009, R-014, R-017, and R-018 remain open/partial as recorded.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, PyYAML 6.0.3,
defusedxml 0.7.1, NumPy 2.4.6, Pandas 3.0.5, and DuckDB 1.5.5. Ambient Python
3.14.6 ran only pre-final focused/governance checks and is not retained as
E-063 exit evidence. Docker and live server dependencies remain unavailable.
The next safe slice is E-064 bounded `reconforge/db/importers.py::_read_json`;
archive support, real host loss, malware, authenticated provenance, and restore
authorization require separate reviewed evidence boundaries.

## E-064: Bounded legacy database import JSON ingress

Implemented boundary:

- The remaining FI-009 reader for account_reconciliations.json and
  control_tests.json now uses the shared duplicate-safe JSON engine under
  database-legacy-import-json-ingress-v1: 16 MiB per file, 500,000 nodes,
  depth 32, 50,000 items per collection, and 1 MiB per scalar.
- A bounded raw-byte checksum/size pass before and after parsing requires a
  regular non-reparse file and refuses file instability. Invalid UTF-8,
  duplicate keys, non-finite constants, and every resource excess retain the
  existing path/value-free Input JSON parse error.
- Direct record lists, exactly one source-specific list envelope, empty
  objects, and identifier-keyed object maps remain compatible. Multiple
  recognized aliases, non-list envelope values, non-object records, and
  arbitrary objects that previously became zero-row imports now fail visibly
  before database status inspection, connection, audit, outbox, or workflow
  mutation.
- The SHA-256 and byte count bracket the bytes actually parsed and flow with the
  named profile into sanitized legacy summaries, audit metadata, and outbox
  metadata. Later file mutation cannot cause evidence to be recalculated from
  bytes different from the parsed object.
- Two published schemas describe the account/control compatibility shapes and
  reject alias ambiguity. Individual record fields remain deliberately open;
  this bridge is not a full account-reconciliation or control-testing semantic
  importer.
- Added 25 dedicated hostile, resource, ambiguity, TOCTOU, reparse,
  pre-mutation, schema, provenance, compatibility, and AST cases. Four existing
  DB export/import cases remain green. FI-009's two inventoried parser
  entrypoints are now bounded, while unkeyed provenance, centralized
  authorization, encryption, malware scanning, full record semantics, and real
  recovery/DR remain open.
- ADR 0079, D-060, DOC-029, the claims matrix, migration/operator/schema docs,
  module/risk/security/threat/ASVS/SSDF registries, package manifest, backlog,
  and state record the implemented boundary without an archive or assurance
  claim.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| uv.lock | 92a28d97f3758b7994c9f80b113719d422a2d4b18c6fca4459bb8fb32d115af9 |
| reconforge/db/importers.py | 8eb29f41ed000c298269adb0cd97a907cb146422105fb08d589fc2e8bad15ce4 |
| tests/test_db_import_structured_ingress.py | 90f1eb242844caed59d652544974a9506ab5a3ec5967cc74532933d1697f6baa |
| docs/schemas/database_account_reconciliations_import.schema.json | 279ab8f4420528678870002d9c012f5d5661fc9b6bb73d08d670a36b22b52224 |
| docs/schemas/database_control_tests_import.schema.json | 370d4fab18f9b69c563f06882a8fe95164d51c5d37ef556f1adc6370aa5a2361 |
| docs/security/file-ingestion-inventory.v1.yaml | 5482cb1933adc641d64fd0172b39b227db124ea1a1ea6691532815b2da39e45e |
| docs/security/security-architecture.v2.yaml | aaa67d3aa04de5a479099d8b7e21b6330d54ee4437c64ddf45ebd1a40b006ebf |
| docs/security/threat-model-index.v1.yaml | 84e65c39fc86d176db56a1fa39ce39ec6dae55e131352aa4a772b510028151c0 |
| docs/risk-register.yaml | 09a509425311f388f77dfb934f27c6ae1c89b36e0ef8e12f36e0f8935917cc8c |
| docs/adr/0079-bound-legacy-database-import-json.md | 22016cc9243adeec61e84c68923d8fc0bec250bd696a6a4fdd1435a078fdd3f8 |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Official uv 0.11.32 Windows archive verification and locked all-extra Python 3.11.15 sync | Pass; archive SHA-256 acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984; uv commit 3010295ae; 104-package resolution and 102 installed packages | 6.21s sync; download 42.95s wrapper |
| Final locked importer/governance target | 76 passed, 0 failed/errors/skipped; JUnit SHA-256 52b94da2234f96d64e5afcaa4dba23a27ab4621e570f433673b6ec3030142777 | 14.973s JUnit |
| Final fixed-snapshot locked Python 3.11.15 full suite | 1,043 collected; 1,033 passed, 10 skipped, 0 failed/errors; eight existing warnings; JUnit SHA-256 5efa4166dc4a329a658a1aa24299e5651f01c4c1b8946a1b883f2d112ec49f5a | 192.422s JUnit |
| Locked Ruff 0.16.0 | Pass | duration not retained |
| Locked Mypy 2.3.0 | Pass; no issues in 210 source files | duration not retained |
| Locked Bandit 1.9.4 | Pass; no findings and the same three B608 nosec notices | 6.6s parallel wrapper with lock export |
| Exact uv lock check/hash export, pip-audit 2.10.1, and closed policy validation | Pass; 103 policy Python packages, 0 known findings, 0 active exceptions | 16.97s final audit/policy invocation |
| npm lock audit and closed policy validation | Pass; 209 packages, 0 high findings, 155 disclosed SRI gaps, 0 active exceptions | 2.6s final invocation |
| Locked Python 3.11 build --no-isolation | Pass with existing setuptools metadata warnings | 20.42s |
| Package membership assertion | Pass; importer runtime in 448-entry sdist and 217-entry wheel; two schemas, governance, and dedicated test sdist-only; tests/docs absent wheel and ADR 0079 absent both | <1s |
| Final sdist | 860,303 bytes; SHA-256 1a55bf538a8d034ee54b11115a1fef5520bce2c628511f6057c45468d60a8e51 | included above |
| Final wheel | 629,839 bytes; SHA-256 854e3a48b0d54486243ad961e8ce4e5c9bc8de7347139bf8efe8e22e0eecf40d | included above |

Observed failures and environment handling:

- The first dedicated test run had one test-expectation failure: a non-object
  record correctly produced the existing safe shape error rather than the
  generic parser error expected by the new harness. The case was moved to the
  shape-error group; production behavior did not change to satisfy the test.
- The first focused Mypy check found that adding integer source_size_bytes to a
  summary inferred as string-only was inconsistent. The private summary return
  annotation was widened to dict[str, Any], matching the existing downstream
  JSON contract; the final full Mypy gate passed.
- Two documentation patch invocations failed before mutation because of
  JavaScript template quoting and an over-narrow context line. The patches were
  split and applied through the required patch mechanism; neither failure is a
  code/test result.
- Docker, Python 3.12 hosted execution, live PostgreSQL/Redis/object storage,
  real process/host/power/filesystem loss, centralized import/restore
  authorization, encryption, malware scanning, and quarantine remain
  unavailable or unexecuted. No customer data, production secret, external
  connector, registry login/push, signed tag, GitHub write/run, publication, or
  production mutation occurred.

Final cleanup and inventory: seven explicit top-level e064* temporary targets
were resolved beneath F:\reconforge-erp\.codex-test-tmp; zero top-level or
nested reparse points were found, and the preverified targets were deleted with
explicit .NET directory/file calls while preserving the temp root and unrelated
children. Zero E-064 targets remain. The post-cleanup ambient-Python
importer/governance target passed 76 cases; Ruff and git diff --check passed
with only the existing .gitignore LF-to-CRLF warning. The verified inventory is
210 Python source files, 124 test_*.py modules, 1,043 collected tests, 53 JSON
schemas, 79 ADRs, six workflows, 50 backlog tasks, 64 sequential evidence
records, 194 tracked status entries, and 238 untracked status entries.

Security/claim boundary: E-064 proves bounded, duplicate-safe, stable local JSON
parsing; explicit compatibility-shape decisions; parsed-byte consistency
metadata; and pre-database rejection for the documented legacy account/control
bridge. It does not prove record semantic completeness, source authenticity,
actor authorization, confidentiality, malware absence, cross-edition recovery,
real host/filesystem DR, or independent assessment. It establishes no ASVS
level, compliance, certification, enterprise readiness, bank-grade quality,
audit opinion, or production readiness. P0-SEC-009, R-014, R-017, and R-018
remain open/partial as recorded.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, PyYAML 6.0.3,
defusedxml 0.7.1, NumPy 2.4.6, Pandas 3.0.5, and DuckDB 1.5.5. Ambient Python
3.14.6 ran only pre-final focused/governance checks and is not retained as
E-064 exit evidence. Docker and live server dependencies remain unavailable.
The next safe slice is E-065 bounded FI-008 business-record import ingress;
malware, authenticated provenance, centralized authorization, and real recovery
require separate reviewed evidence boundaries.

## E-065: Bounded exact business-record CSV/JSON ingress

Implemented boundary:

- `business-record-ingress-v1` centralizes every inventoried FI-008 CSV/JSON
  entrypoint with 64 MiB/file, 250,000 records, 512 fields/record, 10,000,000
  cells, 128,000-character field/scalar, and JSON 2,000,000-node/depth-32
  ceilings. Regular non-reparse pre/post fingerprints bind SHA-256, byte count,
  and policy profile to the bytes parsed.
- JSON uses strict UTF-8 duplicate/non-finite rejection and keeps fractional or
  exponent lexemes as text. Direct lists, one recognized envelope, and the
  generic historical single object remain compatible; ambiguity and every
  non-object record fail visibly rather than being selected or dropped.
- CSV receives tabular preflight before strict `DictReader`, rejects blank or
  duplicate headers, preserves field text, and rejects row-count/source change.
- Account, control, intercompany, journal, and matching services plus ledger,
  inventory, and receivables CLI readers use the document. The public
  `read_local_records` tuple remains a shim. Import audit/outbox metadata now
  reuses the parsed-byte digest/size/profile instead of rehashing a mutable path.
- One prior strict-matching test intentionally changed: exact JSON numeric
  `10.5` now matches under strict policy because it is no longer constructed as
  binary float. ADR 0080 records this correctness change and rollback risk.
- Added 21 dedicated hostile, resource, exactness, TOCTOU, reparse,
  compatibility, policy, and AST cases. The final focused target contains 89
  tests, and FI-008 inventory/security/risk/threat/ASVS/SSDF governance passes.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| uv 0.11.32 Windows archive | acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984 |
| reconforge/io/records.py | ae4dd865e9f11ccadf575910dc0324856265745d3c579bb492b21b2eed96c6ea |
| reconforge/platform/common.py | cb116b507d4a366e3dadc310cf7f1f47319e4dea66d2c200c2f8fc11dd1295a1 |
| reconforge/cli.py | 13577bc80f5450d3270f3ff45679c43f1d31c16ded87ad5db684ce9c48eac3b3 |
| tests/test_business_record_ingress.py | b8ac0fad9dbdf1e9692c861a49f3264bda864070dffd3282cc0d53c470b66e2c |
| tests/test_reconciliation_input_policy.py | 1996b1087faf9f2cf6b22a06cb8b34eb2de3feb22fe4671529626391148f31e8 |
| docs/security/file-ingestion-inventory.v1.yaml | 03f40e3e1db710f325ccbddf11ed8fcd14b95fcbe55188ff20b3ad1d12100fab |
| docs/adr/0080-bound-business-record-ingress.md | cd3fa521fbf1c224d5174301c3754cac381f0fd42de2fb280ae0465f7a35b757 |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Official uv archive hash check, Python 3.11.15 environment, locked all-extra sync | Pass; uv 0.11.32 commit 3010295ae; 3.11.15 environment resolved from `uv.lock` | duration not retained |
| Final focused Python 3.11.15 target | 89 passed, 0 failed/errors/skipped; JUnit SHA-256 8d5e70c953eaa0173d50336fcd7980203486d6656687b0e9d0b1ac7361692b4b | 27.236s JUnit |
| Final Python 3.11.15 full suite | 1,064 collected; 1,054 passed, 10 skipped, 0 failed/errors; eight existing warnings; JUnit SHA-256 c5662c9d0487b51a2d37b83d371c28e18236415a155be73681623a2374c4eab2 | 189.662s JUnit |
| Locked Ruff 0.16.0 | Pass | duration not retained |
| Locked Mypy 2.3.0 | Pass; no issues in 211 source files | duration not retained |
| Locked Bandit 1.9.4 | Pass; no findings and the same three B608 nosec notices | duration not retained |
| Locked pip-audit 2.10.1 | Pass; no known vulnerabilities | duration not retained |
| Python 3.11 build --no-isolation | Pass with existing setuptools metadata warnings | duration not retained |
| Package membership | Pass; runtime reader in 450-entry sdist and 218-entry wheel; dedicated test sdist-only; ADR 0080 absent both | <1s |
| Built sdist | 865,018 bytes; SHA-256 ab7e111a6013d9b1fddfbfd5ab4576cd09fe74b954097481871eb0720b69ac28 | included above |
| Built wheel | 632,681 bytes; SHA-256 868d231c9adceb9036d2b7d9324a77d34bc12c7affbd36fd576afa7940ca3516 | included above |

Observed failure and correction: the first ambient full run produced 1 failure,
1,053 passes, and 10 skips because the historical test expected strict matching
to reject JSON `10.5` after stdlib float construction. The shared reader now
preserves `10.5` exactly, so the regression was renamed and changed to require
one deterministic match. The final locked focused and full suites pass; no
production behavior was weakened to satisfy the test.

Security and claim boundary: E-065 proves bounded stable local parsing, strict
structural rejection, exact fractional lexemes, parsed-byte consistency
metadata, and current compatibility routing for FI-008. It does not prove
business-semantic completeness, source authenticity, actor authorization,
field classification, confidentiality, malware absence, supported throughput,
hosted enforcement, compliance, certification, bank-grade quality, enterprise
readiness, or production readiness. P0-SEC-009 and R-018 remain open/partial.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, and pip-audit 2.10.1. Docker and live
PostgreSQL/Redis/object storage were not exercised. No customer data, secret,
external connector, remote write/run, publication, or production mutation
occurred. The next safe slice is E-066 bounded FI-007 Studio/report generated-
artifact reads; authenticated provenance, malware quarantine, and centralized
authorization require separate reviewed boundaries.

Final cleanup and inventory: all explicit e065 temporary targets were resolved
beneath `F:\reconforge-erp\.codex-test-tmp`. The first cleanup invocation was
rejected before execution by command policy. The verified retry removed the uv
directory, then stopped on uv's expected Python-version junction; that junction
target was verified inside the E-065 Python directory and removed without
traversal before deleting the remaining explicit directories/files. Zero
`e065*` targets remain. The verified inventory is 211 Python source files, 125
test modules, 1,064 collected tests, 53 JSON schemas, 80 ADRs, six workflows,
194 tracked status entries, and 241 untracked status entries. The three added
untracked repository files relative to E-064 are the reader, dedicated test,
and ADR; no unrelated dirty changes were deleted.
The post-cleanup ambient Python governance/ingress target passed 49 cases;
targeted Ruff, full Mypy (211 files), and `git diff --check` passed with only
the pre-existing `.gitignore` LF-to-CRLF warning.

## E-066: Bounded Studio generated-artifact ingress

Implemented boundary:

- `generated-artifact-ingress-v1` centralizes all FI-007 Studio CSV/JSON reads:
  64 MiB/file, 250,000 CSV rows, 512 columns, 10,000,000 cells, 128,000
  characters/CSV field, and JSON 1,000,000 nodes, depth 64, 250,000 items per
  collection, and 1,000,000 characters/scalar.
- Bounded SHA-256 and byte counts before/after parsing reject non-regular,
  reparse, empty, changed, malformed, invalid-encoding, duplicate-header/key,
  non-finite, and over-budget artifacts without exposing paths or values.
- CSV retains pandas `keep_default_na=False` display typing after strict tabular
  and header preflight. JSON fractional/exponent lexemes remain exact strings.
- Health, rule-results, variance, control-matrix, control-pack, and evidence-
  coverage reads now use the helper. Missing/rejected input keeps the current
  empty-state response instead of a route parser traceback.
- When companion JSON exists, its named collection must be an object-record
  list with the same row count and columns available in CSV. CSV-only legacy
  output remains compatible. This does not cryptographically bind the files.
- Added 24 dedicated hostile/resource/TOCTOU/reparse/companion/display/route/
  policy/AST cases. Thirty-six existing Studio tests and all inventory/security/
  risk/threat/ASVS/SSDF contracts remain green under ADR 0081.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| uv 0.11.32 Windows archive | acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984 |
| reconforge/io/generated.py | c9e1e1c2d2de73a96acbbb6f441ebd171a0bba98eb423f6d033a379ff6bbd890 |
| reconforge/studio/data.py | 89bc6f200dc8debc594a36bbf8726219709f01c538e8f2d100ff4753fd390654 |
| reconforge/studio/app.py | 7547c154286958b5c7ea33588d400e6bfecdb8e8fc0c4d1dc12952866562122b |
| tests/test_studio_artifact_ingress.py | 20b8984e78085c5ad042960d92eb8892b2ba4ad8ef1a8db82313b1c9952c4fd5 |
| docs/security/file-ingestion-inventory.v1.yaml | beb51da055d088e514a378e87ddd733c7bff7cd6c15f94e1ff09e2a1032dc96d |
| docs/adr/0081-bound-studio-generated-artifact-ingress.md | e3ad314ece7994db6e455fc85a54522248c4073ea4580ed64742beb382b4f679 |

Verification evidence:

| Command | Result | Duration |
| --- | --- | ---: |
| Official uv archive hash check, Python 3.11.15 environment, locked all-extra sync | Pass; uv 0.11.32 commit 3010295ae; 104-package resolution and 101 installed packages | 195s prepare plus install; wrapper duration not retained |
| Final focused Python 3.11.15 target | 88 passed, 0 failed/errors/skipped; JUnit SHA-256 db8aea733ea777ac4dad54be98031f08ce0d1e0d62bdbe71fa4337299b5cdeb0 | 15.489s JUnit |
| Final Python 3.11.15 full suite | 1,088 collected; 1,078 passed, 10 skipped, 0 failed/errors; eight existing warnings; JUnit SHA-256 98221b57f5d29561efa064ad274990b914678a2dc43a54efd1d42ab3822d8ee2 | 194.128s JUnit |
| Locked Ruff 0.16.0 | Pass | duration not retained |
| Locked Mypy 2.3.0 | Pass; no issues in 212 source files | duration not retained |
| Locked Bandit 1.9.4 | Pass; no findings and the same three B608 nosec notices | duration not retained |
| Locked pip-audit 2.10.1 | Pass; no known vulnerabilities | duration not retained |
| Python 3.11 build --no-isolation | Pass with existing setuptools metadata warnings | duration not retained |
| Package membership | Pass; runtime helper in 452-entry sdist and 219-entry wheel; dedicated test sdist-only; ADR 0081 absent both | <1s |
| Built sdist | 868,835 bytes; SHA-256 a558aa86d74777616a84f6c7dff017f2047be4bda7cec0138f86207503676804 | included above |
| Built wheel | 635,186 bytes; SHA-256 cc4db67f3aa270bd68f51346def978c724f309f3360efdfe2d9138470172f011 | included above |

Observed failure and correction: the first dedicated run had one expectation
failure because the shared tabular preflight intentionally maps invalid UTF-8
CSV to the existing `csv_structure_invalid` code rather than a new encoding
code. The test was corrected to the established safe contract; production code
was not changed to satisfy it. The first inventory run then exposed the new
central `csv.reader` header call missing from the exact AST allowlist. That call
was registered under FI-007; the final inventory and full suites pass.

Cleanup and inventory: the exact E-066 uv/Python/cache/venv/dist/JUnit targets
were resolved below `F:\reconforge-erp\.codex-test-tmp`. The sole uv-managed
Python-version junction targeted its sibling version directory inside the same
E-066 root; it was removed without traversal before deleting the verified
directories. Zero `e066*` targets remain. Inventory is 212 Python source files,
126 test modules, 1,088 collected tests, 53 JSON schemas, 81 ADRs, six
workflows, 194 tracked status entries, and 244 untracked status entries. The
three added untracked files relative to E-065 are the helper, dedicated test,
and ADR; no unrelated dirty changes were removed.

Security and claim boundary: E-066 proves stable bounded local parsing, strict
structural rejection, exact JSON fractional lexemes, preserved Studio display
typing, safe empty views, and optional companion shape/count consistency for
FI-007. It does not prove cryptographic CSV/JSON binding, source authenticity,
actor or disclosure authorization, field classification, confidentiality,
malware absence, supported throughput, hosted enforcement, compliance,
certification, enterprise readiness, bank-grade quality, or production
readiness. P0-SEC-009 and R-018 remain open/partial.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, Pandas 3.0.5, and PyYAML
6.0.3. Docker and live PostgreSQL/Redis/object storage were not exercised. No
customer data, secret, external connector, remote write/run, publication, or
production mutation occurred. The next safe slice is E-067 FI-006 generated
report readers.
The post-cleanup ambient ingress/governance target passed 52 cases; targeted
Ruff, full Mypy (212 files), direct-Studio-parser zero scan, and
`git diff --check` passed with only the pre-existing `.gitignore` LF-to-CRLF
warning.

## E-067: Bounded generated report ingress

Implemented boundary:

- Extended `generated-artifact-ingress-v1` with explicit, recorded `display`
  and `exact-text` CSV representation modes. Unknown modes fail before file
  access; Studio keeps its historical display inference.
- Routed FI-006 variance CSV through exact-text mode and its JSON through the
  exact fractional/exponent-lexeme reader, so policy inputs reach strict Decimal
  validation without pandas or stdlib binary-float construction.
- Routed management-pack period-comparison/evidence-index JSON through the same
  bounded reader. Rejected optional artifacts retain the prior empty/not-
  available behavior without exposing paths, values, parser details, or
  tracebacks.
- The shared 64 MiB/file, 250,000-row, 512-column, 10,000,000-cell,
  128,000-character CSV field and 1,000,000-node/depth-64/250,000-item/
  1,000,000-character JSON ceilings now apply to every FI-006 parser entrypoint,
  together with duplicate/header/non-finite rejection, reparse refusal, and
  stable pre/post-parse fingerprints.
- Added 14 dedicated exact-text/display/mode/hostile/resource/management/AST
  cases and removed the final direct FI-006 parser from the exact AST allowlist
  under ADR 0082.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| uv 0.11.32 Windows archive | acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984 |
| reconforge/io/generated.py | af10fc4e97958079e965967469d395746ee9ff6753c3817da6685d828eab60aa |
| reconforge/variance.py | d525dddb2cc46024f31f7c37f49a149f4074f932fb687f6b3d92777532530625 |
| reconforge/reports/management_pack.py | 8794a65aff81b6d7fa29822a07debbccc4367de8728d76f2cd1621848f1cc6bd |
| tests/test_generated_report_ingress.py | a28f67378e014b3c3eed146c26a3b8a2ebd15489ac4904f674fc6ae96ff9f32f |
| docs/security/file-ingestion-inventory.v1.yaml | c90dbf6b97335d5cf29d99345bfb79f7055f357ecb8cde1e51d3e0898ddccd81 |
| docs/adr/0082-bound-generated-report-ingress.md | 73da380f184659f523a56e9cb166399a3363a0b0c7a724e1a3d5f8b62a495259 |

Verification evidence:

| Command | Result |
| --- | --- |
| Official uv archive hash check, isolated Python 3.11.15 install, locked all-extra sync | Pass; uv 0.11.32 commit 3010295ae; 104-package resolution and 102 installed packages |
| Focused Python 3.11.15 target | 98 passed, 0 failed/errors/skipped; 12.67s; JUnit SHA-256 4da6dad351860f359b0f9164d6e66dbd0650636cffea4f090136e274e6b3f035 |
| Full Python 3.11.15 suite | 1,102 collected; 1,092 passed, 10 skipped, 0 failed/errors; eight existing warnings; 196.81s; JUnit SHA-256 a8d79fff39ebb9a7deb3a9b405652fbe7ab5e3761b6f9329a920711130e961e1 |
| Locked Ruff 0.16.0 | Pass |
| Locked Mypy 2.3.0 | Pass; no issues in 212 source files |
| Locked Bandit 1.9.4 | Pass; no findings and the same three B608 nosec notices |
| Locked pip-audit 2.10.1 | Pass; no known vulnerabilities; local project is not a PyPI dependency |
| Python 3.11 build --no-isolation | Pass with existing setuptools metadata warnings |
| Package membership | Pass; three migrated runtime files in 453-entry sdist and 219-entry wheel; dedicated test sdist-only; ADR 0082 absent both |
| Built sdist | 870,393 bytes; SHA-256 33f7048119261c98ea914954608f90f30891b91f71ac7e5515841e7435f13ec2 |
| Built wheel | 635,095 bytes; SHA-256 56f1b6a3265146f25538642b1d9cb8df4149f5dc37e51dd00514a17f5c8c873c |
| `doctor`, sample-data `validate`, and local demo | Pass; validation retained 0 errors/10 synthetic warnings and demo produced the expected local artifacts |

Observed failures and correction: the first focused inventory run correctly
failed because the obsolete direct `variance.py` pandas call remained declared;
the allowlist was contracted after migration. The first risk-governance run
rejected an over-500-character R-018 rationale; it was shortened without
weakening its listed residual risks. Two package-inspection command attempts
failed from PowerShell argument/quoting mistakes; no product code or package was
changed, and the final .NET/tar membership assertions passed.

Inventory before cleanup: 212 Python source files, 127 test modules, 1,102
collected tests, 53 JSON schemas, 82 ADRs, six workflows, 194 tracked status
entries, and 247 untracked status entries. No unrelated dirty changes were
removed.

Cleanup: the E-067 root resolved exactly to
`F:\reconforge-erp\.codex-test-tmp\e067`. Its sole Python-version junction
targeted the sibling version directory inside that verified root; the junction
was removed without traversal, then the root was recursively deleted. Zero
`e067*` targets remain. The first two `Remove-Item` command forms were rejected
by the execution safety policy before running; explicit .NET directory deletion
was used only after the absolute target and junction target were printed and
verified inside the workspace.

Security and claim boundary: E-067 proves bounded stable local parsing,
structural ambiguity rejection, and exact variance representation for FI-006.
Unkeyed SHA-256 is byte consistency, not producer/schema authentication. This
slice does not prove actor or disclosure authorization, classification,
confidentiality, malware absence, FI-005 safety, supported throughput, hosted
enforcement, compliance, certification, enterprise readiness, bank-grade
quality, or production readiness. P0-SEC-009 and R-018 remain open/partial.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, Pandas 3.0.5, and PyYAML
6.0.3. Docker and live PostgreSQL/Redis/object storage were not exercised. No
customer data, secret, external connector, remote write/run, publication, or
production mutation occurred. The next safe slice is E-068 FI-005 generated
evidence/review CSV compatibility ingress.

## E-068: Bounded evidence/review CSV ingress and parsed-byte provenance

Implemented boundary:

- Routed both FI-005 direct pandas readers through
  `generated-artifact-ingress-v1`: 64 MiB/file, 250,000 rows, 512 columns,
  10,000,000 cells, and 128,000 characters/field, with strict encoding/shape/
  header checks, regular non-reparse paths, and stable pre/post-parse SHA-256.
- Strict financial operations explicitly select exact-text CSV; the named
  legacy compatibility policy retains display inference and its existing
  warning/rounding behavior.
- Missing optional CSV remains empty. A hostile present artifact now fails
  closed; evidence-binder, review-list, and review-export CLI surfaces emit one
  generic path-free message without a traceback or output workbook.
- Evidence generation caches every selected exception/match/rule CSV document
  once instead of parsing match/rule files per case. A three-file/three-case
  regression proves one parse per selected path.
- Evidence-index v3 CSV fingerprints now use the exact checksum/size returned
  by the parsed document. The selected path list is frozen and every cached CSV
  is verified against current bytes before index publication, closing the prior
  parse-then-independent-hash race.
- Added 17 dedicated mode/hostile/resource/cache/provenance/change/CLI/missing/
  AST cases and removed both final FI-005 pandas calls from the exact parser
  allowlist under ADR 0083.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| uv 0.11.32 Windows archive | acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984 |
| reconforge/io/generated.py | d7fe105f4e5346ef2f690b67960a7f56975f5d355e9573b02bdb1867c4122e44 |
| reconforge/evidence/binder.py | 120d4ea20618d1ff89145aa100923d91d6de1abff04c392d39f730282c10375a |
| reconforge/review/state.py | a497f6d270a691d62b4ab7348f84561bcb7799d3909e5c4512a9ebe7b2de58c6 |
| reconforge/cli.py | 6b19e6a95dd2acbb30f2f7f9950f6e0c246a0b91069755506c8f1f183198a91e |
| tests/test_evidence_review_csv_ingress.py | 890ee322480bdc4e923efb1c22c50f7570a03be73b85845f996a865e77d5d809 |
| docs/security/file-ingestion-inventory.v1.yaml | 648c624a9946891f3fe24967f4b03f4cde941a693aa9f5684cff34b7754054ed |
| docs/adr/0083-bound-evidence-review-csv-ingress.md | 554c49cf5286ecc3556ac5375f743fa155ede4b87c2d5478d2d68d2b7233b3d4 |

Verification evidence:

| Command | Result |
| --- | --- |
| Official uv archive hash check, isolated Python 3.11.15 install, locked all-extra sync | Pass; uv 0.11.32 commit 3010295ae; 104-package resolution and 102 installed packages |
| Focused Python 3.11.15 target | 115 passed, 0 failed/errors/skipped; 23.36s; JUnit SHA-256 1933b5f4c4102deedece420a02fd2db9e0d7c9bfb85e419dd3fa457084f398f3 |
| Full Python 3.11.15 suite | 1,119 collected; 1,109 passed, 10 skipped, 0 failed/errors; eight existing warnings; 197.37s; JUnit SHA-256 25a48c2f6ee4a3cf1413876836b85364898bc421869cc8ec54e1b0b07ff2c73c |
| Locked Ruff 0.16.0 | Pass |
| Locked Mypy 2.3.0 | Pass; no issues in 212 source files |
| Locked Bandit 1.9.4 | Pass; no findings and the same three B608 nosec notices |
| Locked pip-audit 2.10.1 | Pass; no known vulnerabilities; local project is not a PyPI dependency |
| Python 3.11 build --no-isolation | Pass with existing setuptools metadata warnings |
| Package membership | Pass; four affected runtime files in 454-entry sdist and 219-entry wheel; dedicated test sdist-only; ADR 0083 absent both |
| Built sdist | 873,413 bytes; SHA-256 c54135dfea5a9622b1657fc48a9b5d4ef64668f9b00879e28d15c09b7a7b3203 |
| Built wheel | 635,716 bytes; SHA-256 41cdef39d83811d428b59b25e9fa7a4cebf3ef908c4051581bfce2f01ae5384c |
| `doctor`, sample-data `validate`, and local demo | Pass; validation retained 0 errors/10 synthetic warnings and demo produced evidence/review/client-pack artifacts through the migrated paths |

Observed failures and correction: the first inventory run correctly failed on
the two obsolete direct-parser allowlist records, which were removed after
migration. The first resource test expected `csv_row_limit`; the established
tabular policy emitted its existing `table_row_limit` code and the test was
corrected without changing production behavior. The new mode-selection test
initially consumed the once-per-location legacy warning before an older warning
contract; its fixture was narrowed to representation-only fields so test order
no longer affects the established compatibility assertion. One initial CLI
patch context did not match and made no change; it was reapplied at the inspected
import/command locations.

Inventory before cleanup: 212 Python source files, 128 test modules, 1,119
collected tests, 53 JSON schemas, 83 ADRs, six workflows, 194 tracked status
entries, and 249 untracked status entries. No unrelated dirty changes were
removed.

Cleanup: the E-068 root resolved exactly to
`F:\reconforge-erp\.codex-test-tmp\e068`. Its sole Python-version junction
targeted the sibling version directory inside that verified root; the junction
was removed without traversal, then the root was recursively deleted. Zero
`e068*` targets remain.

Security and claim boundary: E-068 proves bounded stable local CSV parsing,
explicit financial representation, one-parse binder reuse, and parsed-byte
fingerprints for FI-005 current evidence-index v3. Unkeyed SHA-256 is byte
consistency, not producer/schema authentication. This slice does not bound the
adjacent review-state JSON reader or prove actor/disclosure authorization,
classification, confidentiality, malware absence, supported throughput, hosted
enforcement, compliance, certification, enterprise readiness, bank-grade
quality, or production readiness. P0-SEC-009 and R-018 remain open/partial.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, Pandas 3.0.5, and PyYAML
6.0.3. Docker and live PostgreSQL/Redis/object storage were not exercised. No
customer data, secret, external connector, remote write/run, publication, or
production mutation occurred. The next safe slice is E-069 bounded review-state
JSON compatibility ingress.

## E-069: Bounded review-state JSON compatibility ingress

Implemented boundary:

- Added FI-014 and `review-state-json-ingress-v1`: 16 MiB/file, 500,000 graph
  nodes, depth 32, 100,000 items/collection, and 1,000,000 characters/scalar.
- Extended the stable generated JSON helper to accept a narrower caller policy
  and named profile while leaving its dynamic default behavior unchanged. The
  review reader now rejects non-regular/reparse, duplicate, non-finite,
  invalid-encoding, malformed, non-object, changed, and over-budget present
  files under stable pre/post-parse SHA-256 and byte counts.
- Preserved missing-file-as-empty, valid direct-map and versioned `entries`
  envelopes, ignored non-object entries, and established status/certification
  fallback coercion. Malformed present JSON is no longer silently converted to
  “no review state”.
- Review list/set-status, Studio, evidence/report/period consumers, and legacy DB
  import share the reader. CLI/Studio expose generic path-free failures; a
  rejected update leaves the original bytes unchanged; DB import rejects before
  database creation or mutation.
- Added 15 dedicated profile/legacy/hostile/resource/change/CLI/Studio/DB/
  evidence/AST cases under ADR 0084. The closed inventory, architecture, threat,
  ASVS, SSDF, risk, claims, drift, backlog, and dependency records now distinguish
  bounded FI-014 structure from unauthenticated semantics.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| uv 0.11.32 Windows archive | acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984 |
| reconforge/io/generated.py | 9e0fb85a9d5d5c045539fdcb2ffc1e189c1e584633c0ada1eb2079f4778b5985 |
| reconforge/review/state.py | de4a46b3b40b4acb4cda7fe596a0dc21327bab3ae55aad8ddd9b47455f62a2cd |
| reconforge/cli.py | 40fed560494afc2664e844bc56fc26038a8238288e445777363b3fe9be2c5323 |
| reconforge/db/importers.py | ca6cefd60597fc6353517fc54edbe63fc864ab8c7e36e7a88f613524bf25df1f |
| reconforge/studio/app.py | abbf2a360229929bf05f80aa2785676ce53db8de8a80bd2d658df768dfacd554 |
| tests/test_review_state_json_ingress.py | 049ebc75c135b234fc0a7566704d754ba3aeaafcceccdc5d2c866e66a79173f5 |
| docs/security/file-ingestion-inventory.v1.yaml | 9d6576f843f392afe8f0ccc2661c37cfbd264b5ab2aae0a5886b7b10509201ff |
| docs/adr/0084-bound-review-state-json-ingress.md | ceba599e9be18a7c8282581069db48587eb3ce68c69313f821ddfa5008b4e4c1 |

Verification evidence:

| Command | Result |
| --- | --- |
| Official uv archive hash check, isolated Python 3.11.15 install, locked all-extra sync | Pass; uv 0.11.32 commit 3010295ae; 104-package resolution and 102 installed packages |
| Focused Python 3.11.15 target | 110 passed, 0 failed/errors/skipped; 22.078s JUnit (27.50s wrapper); JUnit SHA-256 2b6fc858a94815de207e6ae174814c42ba68c04c51139e33fbc551a8fb9b6c1e |
| Full Python 3.11.15 suite | 1,134 collected; 1,124 passed, 10 skipped, 0 failed/errors; eight existing warnings; 200.197s JUnit (202.03s wrapper); JUnit SHA-256 79d5d501bc37f6d5a416092e936ca779d4a7c31570bfbe55859f5de8b88c7cd1 |
| Locked Ruff 0.16.0 | Pass; 1.63s |
| Locked Mypy 2.3.0 | Pass; no issues in 212 source files; 3.97s |
| Locked Bandit 1.9.4 | Pass; no findings and the same three B608 nosec notices; 5.50s |
| Locked pip-audit 2.10.1 | Pass; no known vulnerabilities; local project is not a PyPI dependency; 12.79s |
| Python 3.11 build --no-isolation | Pass with existing setuptools metadata warnings; 19.46s |
| Package membership | Pass; five affected runtime files in 455-entry sdist and 219-entry wheel; FI-014 inventory and dedicated test sdist-only; ADR 0084 absent both |
| Built sdist | 875,849 bytes; SHA-256 999850bf72961f1433fbf5ab06ecec84893261e0fec0af25e15461d2d0f44b2e |
| Built wheel | 636,220 bytes; SHA-256 e8dbf7b5b2d08cbf995eaab290dd091b3d2fdaa9d2eeb3811af9601da05f9667 |
| `doctor`, sample-data `validate`, and local demo | Pass; validation retained 0 errors/10 synthetic warnings and demo produced one bounded review-state entry plus evidence/review/client-pack artifacts |
| Governance schemas/contracts and `git diff --check` | Pass; inventory/architecture/threat/ASVS/SSDF/risk registries remain schema-valid and repository-linked |

Observed failures and correction: the first combined patch context did not match
the actual review-state import block and changed nothing; smaller inspected
patches were applied. The first Ruff run caught a mistakenly removed `json`
writer import and two import-order issues, while the first ambient focused run
therefore showed 14 dependent failures; the import was restored, Ruff organized
the blocks, and the new CLI fixture was changed from invalid positional syntax to
the command's documented options. The corrected 65-case ambient target and all
locked targets pass. `uv` was absent from PATH, so the official archive was
downloaded and hash-verified. A post-install `uv python find --install-dir`
option was unsupported but did not affect the successful installation; the exact
managed interpreter path was selected directly. The first JUnit attribute query
targeted the wrapper element and returned blanks; counts were then read from its
single `testsuite` child without changing test evidence.

Inventory before cleanup: 212 Python source files, 129 test modules, 1,134
collected tests, 53 JSON schemas, 84 ADRs, six workflows, 194 tracked status
entries, and 251 untracked status entries. No unrelated dirty changes were
removed.

Cleanup: the E-069 root resolved exactly to
`F:\reconforge-erp\.codex-test-tmp\e069`. Its sole Python-version junction was
verified to target the sibling version directory inside that root and removed
without target traversal. The remaining tree contained zero reparse points; the
verified root was then recursively deleted. The path no longer exists. A final
post-cleanup target of 65 tests plus Ruff, Mypy, governance-schema contracts,
direct-review-parser AST search, and `git diff --check` passed; the worktree
retained 194 tracked and 250 untracked status entries.

Security and claim boundary: E-069 proves bounded duplicate-safe stable local
JSON parsing and retained normalization compatibility for FI-014. Unkeyed
SHA-256 is byte consistency, not producer/schema or actor authentication. This
slice does not prove workflow authorization, disclosure approval, classification,
confidentiality, malware absence, supported throughput, hosted enforcement,
compliance, certification, enterprise readiness, bank-grade quality, or
production readiness. P0-SEC-009 and R-018 remain open/partial.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, Pandas 3.0.5, and PyYAML
6.0.3. Docker and live PostgreSQL/Redis/object storage were not exercised. No
customer data, secret, external connector, remote write/run, publication, or
production mutation occurred. The next safe slice is E-070 direct filesystem
JSON parser inventory reconciliation and AST gating.

## E-070: Close the direct filesystem JSON parser inventory

Implemented boundary:

- Audited all 20 production `json.load`/`json.loads` calls by AST. Six opened
  filesystem JSON; 12 decode persisted DB/Redis/event values, one is the central
  bounded parser, and one parses already-loaded packaged currency-registry text.
- Added a generated JSON value-document reader and explicit `display` and
  `exact-text` modes. The stable-byte, regular non-reparse, strict UTF-8,
  duplicate/non-finite, graph-budget, pre/post size/SHA-256 controls are shared;
  exact-text remains the default.
- Migrated exception explanation, dashboard, synthetic enterprise demo, period
  comparison, rule results, and Studio demo JSON readers through FI-015/FI-016
  named bounded profiles. Missing/legacy/envelope/root compatibility and existing
  public safe-error wording remain tested.
- Added an exact schema-backed direct parser allowlist for the 14 non-filesystem
  calls. An AST regression proves none of the six migrated entry points can
  return to direct `json` or `Path.read_text` parsing and no production direct
  stdlib JSON reader opens a filesystem path.
- Added 26 dedicated value-root, numeric-mode, valid compatibility, duplicate,
  non-finite/resource, changed-during-parse, path-free CLI, and AST cases under
  ADR 0085. Security architecture, threat, ASVS, SSDF, risk, claim, drift,
  backlog, dependency, and repository inventories distinguish bounded structure
  from unauthenticated semantics.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| uv 0.11.32 Windows archive | acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984 |
| reconforge/io/generated.py | 160b8c876db0aafce4d518136d777fa49b14917d24dde4998470678228421f86 |
| reconforge/ai/summaries.py | eedacc1029d53e565e52ae35344d3feac0f190c3610f9c053738cca80a9c3723 |
| reconforge/dashboard/app.py | 54cb63a6f86a1d9e6b3f54a9364404dbceab9206f29be904e50e32f212576593 |
| reconforge/enterprise_demo.py | fabbe1f04235b4948ca4895543fa40d90a0dfd4bd5fd9347285b78ab0292bd2c |
| reconforge/periods.py | 84eaf19a6b0db6cc34459475d56a9ded05e09961595c36d61ab74d107ee52347 |
| reconforge/rules/engine.py | 33a5fdfa58933481ce0f433948ba66bd7fd5ebf290d9c4ad01deb8a149173949 |
| reconforge/studio/demo_bridge.py | b41f306d297ef3f3965e9ce237694aad5366a7a9ad6e7e22e4b85a487b78463d |
| tests/test_direct_json_ingress_inventory.py | 6fe917696aa8288505890ada5a45b622aaec5bcd2c8c5349c863a2ba2d93526d |
| docs/security/file-ingestion-inventory.v1.yaml | e875b5adf61053eb8f9c1a933f73567f24d7d7692b2c144732c6126db8bc1218 |
| docs/adr/0085-close-direct-filesystem-json-parser-inventory.md | ca5fa9891e2993248227a4ce19205bba507232d875d4d6168f9c7d52007d77ae |

Verification evidence:

| Command | Result |
| --- | --- |
| Official uv archive hash check, isolated Python 3.11.15 install, locked all-extra sync | Pass; uv 0.11.32 commit 3010295ae; 104-package resolution and 102 installed packages |
| Focused Python 3.11.15 target | 164 passed, 0 failed/errors/skipped; 20.942s JUnit (26.45s wrapper); JUnit SHA-256 92ed493e6d20ce5c87d32cd1d3e8a66d21a37fb26b838fc42fe1f2a4c40e236e |
| Full Python 3.11.15 suite | 1,152 collected; 1,142 passed, 10 skipped, 0 failed/errors; 196.279s JUnit; JUnit SHA-256 b04f4421ad7ebdd59ca869961876e7d6986eaa97262ff65b5bdc0de059521895 |
| Locked Ruff 0.16.0 | Pass |
| Locked Mypy 2.3.0 | Pass; no issues in 212 source files |
| Locked Bandit 1.9.4 | Pass; no findings and the same three B608 nosec notices |
| Locked pip-audit 2.10.1 | Pass; no known vulnerabilities; local project is not a PyPI dependency |
| Python 3.11 build --no-isolation | Pass with existing setuptools metadata warnings |
| Package membership | Pass; seven affected runtime files in 456-entry sdist and 219-entry wheel; dedicated test and inventory sdist-only; ADR 0085 absent both |
| Built sdist | 880,115 bytes; SHA-256 d5ff5a0614cd53c1b426b3e36e661ffd95f6587531958bd6b001351eb417397b |
| Built wheel | 636,976 bytes; SHA-256 79b84936d190cd199d464df164c338ec23fd8499583d906eed5f4d6459d63956 |
| `doctor`, sample-data `validate`, local demo, and synthetic enterprise showcase | Pass; validation retained 0 errors/10 synthetic warnings, demo artifacts were produced, and showcase loaded 96 generated records with four strict Studio contracts and no external calls |
| Governance schemas/contracts and `git diff --check` | Pass; exact direct-JSON AST inventory and all linked security/risk registries remain valid |

Observed failures and correction: the first ambient compatibility run exposed 18
real regressions because exact-text parsing changed historical period/rule
digests and Studio numeric values. The shared reader gained explicit modes;
these compatibility readers now select `display`, while exact-text remains the
default for financial ingestion. Existing Studio size/non-finite wording was
retained. A resource assertion was aligned with that intentional wording, and
Ruff fixed three import-order issues. The corrected 112-case ambient target, 164
locked focused cases, and full locked suite pass. The focused test wrapper had a
post-test PowerShell spacing error after pytest succeeded; JUnit was read with a
separate correct command. The completed full-test process expired from the PTY
registry before polling, but its complete zero-failure JUnit file was present,
parsed, and hashed.

Inventory before cleanup: 212 Python source files, 130 test modules, 1,152
collected tests, 53 JSON schemas, 85 ADRs, six workflows, 197 tracked status
entries, and 253 untracked status entries. No unrelated dirty changes were
removed.

Cleanup: the E-070 root resolved exactly to
`F:\reconforge-erp\.codex-test-tmp\e070`. Its sole Python-version junction was
verified to target the sibling version directory inside that root and removed
without target traversal. The remaining tree contained zero reparse points; the
verified root was then recursively deleted. Zero `e070*` targets remain. A
post-cleanup target of 113 tests plus Ruff, Mypy, exact JSON/inventory and linked
governance contracts, and `git diff --check` passed; the worktree retained 197
tracked and 252 untracked status entries.

Security and claim boundary: E-070 proves complete AST accounting of direct
stdlib JSON calls and bounded duplicate-safe stable local parsing for FI-015 and
FI-016. Unkeyed SHA-256 is byte consistency, not producer/schema authentication.
This slice does not bound the 12 persisted-value decoders or prove actor/
disclosure authorization, classification, confidentiality, malware absence,
supported throughput, hosted enforcement, compliance, certification, enterprise
readiness, bank-grade quality, or production readiness. P0-SEC-009 and R-018
remain open/partial.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, Pandas 3.0.5, and PyYAML
6.0.3. Docker and live PostgreSQL/Redis/object storage were not exercised. No
customer data, secret, external connector, remote write/run, publication, or
production mutation occurred. The next safe slice is E-071 persisted JSON
producer/consumer contract inventory and one bounded homogeneous group.

## E-071: Bounded AP/AR financial idempotency JSON

Implemented boundary:

- Audited all 12 FI-013 direct persisted-value decoders and selected the
  homogeneous AP/AR idempotency group because replay controls whether a
  financial business effect is repeated. Ten audit/outbox/reconciliation/Redis/
  matching/worker direct calls remain explicitly inventoried.
- Added `financial-idempotency-json-v1`: 4,194,304 UTF-8 bytes, 100,000 nodes,
  depth 32, 25,000 items/collection, and 262,144 characters/scalar. Object root,
  unique string keys, finite values, integer-only JSON number tokens, and a
  recursive structural schema are mandatory.
- Both producers preflight the in-memory graph, reject binary floats/cycles/
  excess resources, emit sorted compact ASCII JSON, and parse it through the
  same consumer policy before insertion. Both consumers reject duplicate,
  fractional/exponent, non-finite, non-object, malformed, and over-budget state.
- Existing public `PlatformError` replay wording remains. Valid historical
  string/integer object responses remain readable; historical JSON fractional
  tokens fail visibly rather than entering binary-float financial state.
- Producer rejection occurs inside the existing SQLite transaction and rolls
  back business, idempotency, audit, and outbox changes. Corrupt replay rejects
  before a new business/audit/outbox effect. Two direct JSON calls leave the
  exact AST allowlist under ADR 0086.

Final policy/artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| uv 0.11.32 Windows archive | acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984 |
| reconforge/io/structured.py | 97e92e8e0960bcdbd0db37639a80748c95815940de891040f5dd1e10ee12c598 |
| reconforge/io/persisted.py | 626f9838db75debe52db47923533807d0e6b52d47b32fa94a655f9ea373395c1 |
| reconforge/platform/payables.py | cccfd2309bff8e985bff62d2ff87259794e0a24910236c9e4566f2717fc9c8a0 |
| reconforge/platform/receivables.py | 0a79abdf9f3e73244287ea0f40125a5dec87584877a663b4fed5735aa9b3848e |
| tests/test_financial_idempotency_json.py | c5ee7b4d2048d0664664eebb65532c6981ffef55b83c26222663853bc28afbec |
| tests/test_file_ingestion_inventory.py | a50e515a1dc8a22ec687f27c575c311f241b24d40b9828ef95caac45765e6c2f |
| docs/schemas/financial_idempotency_response.schema.json | 4bb49c4d5f059f38d6866e53e85aad020b2925b7820e3fc60dc568f94d9c0ba0 |
| docs/schemas/file_ingestion_inventory.schema.json | 4affe8a3a30b4ed70290d6526ec6729792394d03648e75e1a358fb38817f7d14 |
| docs/security/file-ingestion-inventory.v1.yaml | 65c688d5419f68d12d998edf4735b5b91576446069853bc37bacdfb6ddfe5ae4 |
| docs/adr/0086-bound-financial-idempotency-json.md | dade16252b69a57612baa3f53535d0914e5c9af32361210da69301e5a266fbfd |
| MANIFEST.in | c20ed9eb4f0c73826330142babf988e018f257b04122f425e72651a5ad879254 |

Verification evidence:

| Command | Result |
| --- | --- |
| Official uv archive hash check, isolated Python 3.11.15 install, locked all-extra sync | Pass; uv 0.11.32 commit 3010295ae; 104-package resolution and 102 installed packages |
| Focused Python 3.11.15 target | 174 passed, 0 failed/errors/skipped; 22.512s JUnit (25.50s wrapper); JUnit SHA-256 242c61f655838abb3ca74ec141ff7216b752082db585175f61da6f47563cbe74 |
| Full Python 3.11.15 suite | 1,167 collected; 1,157 passed, 10 skipped, 0 failed/errors; eight warnings; 199.620s JUnit (201.45s wrapper); JUnit SHA-256 23334f2c827f83c360e4f9726206f1b089a1e343ee94e62bdaf32582a6b3bf3b |
| Locked Ruff 0.16.0 | Pass |
| Locked Mypy 2.3.0 | Pass; no issues in 213 source files |
| Locked Bandit 1.9.4 | Pass; no findings and the same three B608 nosec notices |
| Locked pip-audit 2.10.1 | Pass; no known vulnerabilities; local project is not a PyPI dependency |
| Python 3.11 build --no-isolation | Pass after explicit schema/test manifest membership; existing setuptools metadata warnings remain |
| Package membership | Pass; four affected runtime files in 459-entry sdist and 220-entry wheel; response/inventory schemas, inventory, and two tests sdist-only; ADR 0086 absent both |
| Built sdist | 884,623 bytes; SHA-256 a7e8b65f3400daa7d60c1a9c670169468600b2a6dd6fa58dc98c046a3ccd5dc8 |
| Built wheel | 639,064 bytes; SHA-256 a7c0e8b4d1fdf5569119630b939f993b7bf4d0d13f55c6e8a38e69b01422a7f1 |
| `doctor`, sample-data `validate`, and local demo | Pass; validation retained 0 errors/10 synthetic warnings and demo produced the established evidence/review/client-pack artifacts |
| Exact direct JSON AST inventory | Pass; 12 total calls remain, of which ten are FI-013 direct persisted decoders, one central bounded parser, and one packaged registry parser |
| Governance schemas/contracts and `git diff --check` | Pass; FI-013, architecture, threat, ASVS, SSDF, risk, claims, drift, backlog, and package boundaries remain linked |

Observed failures and correction: removing the two AP/AR direct calls correctly
failed the old exact allowlist until its obsolete entries were removed. An
unquoted colon made one new YAML limitation a mapping; it was quoted. The first
risk rationale exceeded its closed 500-character ceiling and was tightened
without weakening the residual gaps. Two broad ambient commands named
nonexistent test filenames and stopped before collection; the inspected real
backup/platform filenames were then used and 151 cases passed. The first build
showed the new recursive schema absent from sdist because schemas are explicitly
listed; `MANIFEST.in` now names both schema and dedicated test, and the rebuilt
459-entry sdist contains them. No production regression was hidden by these
tooling/governance failures.

Inventory before cleanup: 213 Python source files, 131 test modules, 1,167
collected tests, 54 JSON schemas, 86 ADRs, six workflows, 197 tracked status
entries, and 257 untracked status entries. No unrelated dirty changes were
removed.

Cleanup: the E-071 root resolved exactly to
`F:\reconforge-erp\.codex-test-tmp\e071`. Its sole Python-version junction was
verified to target the sibling version directory inside that root and removed
without target traversal. The remaining tree contained zero reparse points; the
verified root was recursively deleted and zero `e071*` targets remain. A
post-cleanup target of 82 tests plus Ruff, Mypy, exact inventory/governance
contracts, and `git diff --check` passed; the worktree retained 197 tracked and
256 untracked status entries.

Security and claim boundary: E-071 proves resource/ambiguity/numeric controls
and transaction/replay failure behavior for only the AP/AR FI-013 idempotency
pair. It does not authenticate stored-row producers, validate business semantics
beyond the recursive structural schema, establish supported throughput, cover
the ten remaining direct FI-013 decoders, or prove malware absence, hosted
enforcement, compliance, certification, enterprise readiness, bank-grade
quality, or production readiness. P0-SEC-009 and R-018 remain open/partial.

Environment: Windows, locked Python 3.11.15, uv 0.11.32, pytest 9.1.1, Ruff
0.16.0, Mypy 2.3.0, Bandit 1.9.4, pip-audit 2.10.1, Pandas 3.0.5, and PyYAML
6.0.3. Docker and live PostgreSQL/Redis/object storage were not exercised. No
customer data, secret, external connector, remote write/run, publication, or
production mutation occurred. The next safe slice is E-072 bounded canonical
SQLite/PostgreSQL audit metadata producer/consumer parity.

## E-072: Bounded SQLite/PostgreSQL audit metadata JSON

Implemented boundary:

- Added `audit-metadata-json-v1` and `audit-metadata-object-v1`: canonical
  finite object JSON, unique keys, 4,194,304 UTF-8 bytes, 100,000 nodes, depth
  32, 25,000 items/collection, and 262,144 characters/scalar. Finite JSON
  numbers remain accepted only for historical non-financial metadata
  compatibility; financial values retain exact-text/minor-unit requirements.
- SQLite and PostgreSQL writers share the bounded producer. SQLite verifier
  hashes exact stored text and separately validates metadata. PostgreSQL
  verifier decodes JSONB-rendered text and reconstructs the established compact
  canonical producer bytes, preserving valid historical hashes despite JSONB
  display whitespace.
- SQLite/PostgreSQL list readers fail closed instead of inventing
  `invalid_metadata_json` or `metadata_value` sentinel objects. Invalid metadata
  is an independent verification issue even when a hash is recomputed over the
  corrupt text. SQLite public export refuses corrupt audit metadata before any
  JSON output file or new export audit event.
- Three audit-specific direct `json.loads` calls left the exact AST allowlist.
  Nine total direct calls remain: seven FI-013 generic export/outbox/
  reconciliation/Redis/matching/worker decoders, one central bounded parser,
  and one packaged currency-registry parser. FI-013 remains partial under ADR
  0087 and R-018.

Final artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| uv 0.11.32 Windows archive | acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984 |
| reconforge/io/persisted.py | acac5508ba29b9f5a09c207619c1ff46192ee837ac56668a28deb7fc8400fa09 |
| reconforge/audit/events.py | e8971a4261b8de154138eb3460bcff5672d7184365d57d7d6eda5a9ae2a2edde |
| reconforge/infrastructure/postgres_ledger.py | 0a8020fd10eb7a3b302a3aac524ccb03f87ef98ed2dbbc55f03c6682b6a1b4c0 |
| reconforge/db/exporter.py | 1c80af369ab4e264681045da73c3d3368dcaecc80c41a85f892ef3164f5329ee |
| tests/test_audit_metadata_json.py | f4eaf79b286e8d1d435ae0eed720117eac66441757bf4cadf6a34c3b5c1e6e51 |
| tests/test_audit_events.py | f5c2e31f75426702dfe783f9d1f4680926a697d9472c1839f675c3fa211631f4 |
| tests/test_postgres_ledger.py | 555495f2b1311bd9260b6add0deadf6a4ebfe1e31d51ab1d451b64f5de237002 |
| tests/test_db_export_import.py | 607408f4881aa8e2f18b8c6eb4c7f39594625f9c5a9a8096e5ae2ceb7a9bad33 |
| docs/schemas/audit_metadata.schema.json | 0480c7de053d19623bb0fdef6d016b578a3dab57586031afd960c7b461391b13 |
| docs/security/file-ingestion-inventory.v1.yaml | bd1853b40af42eb54df36e61cb8307886d4da7355a2713593dda5635bb7ffeb5 |
| docs/adr/0087-bound-audit-metadata-json.md | 33a23cd8ce07009ec95d2a0c303eaf888a7d14deed12187c9327fb04774fc90c |
| MANIFEST.in | 3503343ef237e88cab13c5f1e6331de11239fb713a387592d0859595385757f7 |

Verification evidence:

| Command | Result |
| --- | --- |
| Checksum-verified uv, isolated Python 3.11.15, locked all-extra sync | Pass; uv 0.11.32 commit 3010295ae; 104-package resolution and 102 installed packages |
| Focused audit/governance target | 56 passed, one live-PostgreSQL skip; Ruff and targeted Mypy passed |
| Full locked Python 3.11.15 suite | 1,179 collected; 1,169 passed, 10 skipped, 0 failed/errors; eight warnings; 210.46s; JUnit SHA-256 `4c7449e5d1a4af5733ebaf8da86103d2821e45a7f962a4f5f3ccf6110f2f1fa5` |
| Locked Ruff 0.16.0 / Mypy 2.3.0 | Pass; Mypy found no issues in 213 source files |
| Locked Bandit 1.9.4 / pip-audit 2.10.1 | Pass; no Bandit findings, same three B608 nosec notices; no known dependency vulnerabilities and local project not found on PyPI |
| Python 3.11 build --no-isolation | Pass with existing setuptools metadata warnings |
| Package membership | Pass; four affected runtime files in 461-entry sdist and 220-entry wheel; audit schema and dedicated test sdist-only; ADR 0087 repository-only |
| Built sdist | 886,817 bytes; SHA-256 `43de4b6c12ca914cf1ecd865871ed2756c8ba22897ce0abb5ada95bd79ecf3a6` |
| Built wheel | 639,416 bytes; SHA-256 `c3baf9cf78c3768c2de6fbf303d7060939bcc5f30de0e5838273355152a835fd` |
| doctor / sample validate / local demo | Pass; validation retained 0 errors/10 synthetic warnings and demo wrote established artifacts |
| Governance schemas, exact AST inventory, and git diff --check | Pass; nine direct JSON calls remain and linked FI-013/risk/architecture/threat/ASVS/SSDF records validate |

Observed failure and correction: the first focused run exposed a missing `json`
import after moving metadata decoding out of `audit/events.py`; the hash encoder
still requires that module and the import was restored. Review then identified
that PostgreSQL `metadata::text` renders JSONB with whitespace, unlike the
compact canonical text hashed by existing producers. Verification now decodes
the valid JSONB value and re-encodes it canonically before hashing. One broad
governance command named a nonexistent test file and collected nothing; the
real `test_ssdf_mapping.py` target was then run with 65 other contracts. No
failed command is counted as passing evidence.

Inventory before cleanup: 213 Python source files, 132 test modules, 55 JSON
schemas, 87 ADRs, six workflows, 201 tracked status entries, and 260 untracked
status entries including the E-072 root. No unrelated dirty changes were
removed.

Cleanup: the E-072 root resolved exactly to
`F:\reconforge-erp\.codex-test-tmp\e072`. Its Python installation and venv are
inside that verified root; reparse-point targets are checked before recursive
removal. After cleanup, zero `e072*` roots remain and the worktree retains 201
tracked and 259 untracked status entries. The 65-pass/one-skip ambient
post-cleanup governance target plus Ruff, Mypy, and `git diff --check` passed.

Security and claim boundary: E-072 proves only local contract behavior and
hash-byte compatibility for the SQLite implementation plus simulated
PostgreSQL records. The live PostgreSQL test was skipped. It does not prove
stored-row authenticity, centralized actor/disclosure authorization, business
semantic correctness, supported throughput, the seven remaining FI-013
decoders, malware absence, hosted enforcement, compliance, certification,
enterprise readiness, bank-grade quality, or production readiness. P0-SEC-009
and R-018 remain open/partial. No customer data, secret, remote write/run,
publication, or production mutation occurred. The next safe slice is E-073
bounded PostgreSQL outbox metadata producer/consumer parity.

## E-073: Bounded PostgreSQL outbox payload JSON

Scope correction retained: E-072 correctly bounded SQLite audit metadata and
the PostgreSQL ledger audit path, but its summary overstated PostgreSQL producer
coverage. The master-data, evidence, and reconciliation audit writers still
used local unbounded encoders. E-073 found and migrated those three call sites;
ADR 0088, D-069, DOC-038, the audit-writer AST assertion, and this evidence
entry preserve the correction.

Implemented boundary:

- Added `postgres-outbox-payload-json-v1` and
  `postgres-outbox-payload-object-v1`: canonical finite object JSON, unique
  keys, 4,194,304 UTF-8 bytes, 100,000 nodes, depth 32, 25,000
  items/collection, and 262,144 characters/scalar. Finite display numbers are
  accepted only for historical non-financial payload compatibility; financial
  values retain exact-text/minor-unit requirements.
- All six outbox insert call sites across ledger, master data, close, evidence,
  and reconciliation now share the producer contract. List and claim readers
  reconstruct canonical objects instead of wrapping invalid roots or publishing
  sentinel values.
- Claim decoding remains inside the claim transaction. A corrupt stored payload
  raises the stable outbox integrity error, rolls back the lease/attempt
  mutation, and never invokes the publisher. Valid event IDs, JSONB storage,
  lease/retry counters, and dead-letter behavior remain unchanged.
- Exact AST governance asserts all six outbox inserts use the bounded helper and
  all six PostgreSQL audit insert functions use the bounded audit helper. The
  direct `json.loads` inventory falls from nine to eight total calls: six open
  FI-013 consumers, one central bounded parser, and one packaged currency
  registry parser.

Final artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| uv 0.11.32 Windows archive | acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984 |
| reconforge/io/persisted.py | 2313da0d1194623c10c1cfea26ff8b4f2dd665680723a5f1c117d3aa45c52765 |
| reconforge/infrastructure/postgres_outbox.py | 26b032265b43a2edcc3473bc51f52b6435c5882bee0eec636656ed1806f6f59b |
| reconforge/infrastructure/postgres_ledger.py | 6bff416025b7edc1a4be41b5ac544b48d844e5075e27bc631d211f2c783332f8 |
| reconforge/infrastructure/postgres_master_data.py | d0198da8e2d1b2c3e7a7a50a4ce531d8bdef12727976d128fb0ece8b03872a00 |
| reconforge/infrastructure/postgres_close.py | 879f704ba5848d3932760c2fcd2743255caac4655055f7ca0b11cc342e5e2be9 |
| reconforge/infrastructure/postgres_evidence.py | 6e82d6c07d638549c422a6e16cd4e6ed00ed842ae1de2c8efa8864ba3cf4d729 |
| reconforge/infrastructure/postgres_reconciliation.py | 9cbadf72082df2001fe1d396e114963ad6313700753d3ad14f0e189d861cd24b |
| tests/test_postgres_outbox_payload_json.py | 02bdbf3d686a4061ca4745c7607cdde1aa547962dde4cc3e724c501739b1a4e2 |
| docs/schemas/postgres_outbox_payload.schema.json | 0c3ba01831f9a4ff0455f40d57bb9a598d97c24c7813e0f056b7c9e8fcfed660 |
| docs/security/file-ingestion-inventory.v1.yaml | 7e21d4f9d8d2a06d5b9dbf38bb46302d23f4faddfc81b402ebfe370d626803fb |
| docs/adr/0088-bound-postgresql-outbox-payload-json.md | 0f68a4852b23c4dd62dbabbf8a8da9f6f3bc9e9e5506b99dc0fdfc42a596d10a |
| MANIFEST.in | a75ffe7c1b089c95f1f6c2a63c301138d35f160522d2e9285f5a5470f1b0da16 |

Verification evidence:

| Command | Result |
| --- | --- |
| Checksum-verified uv, isolated Python 3.11.15, locked all-extra sync | Pass; uv 0.11.32; 104-package resolution and 102 installed packages |
| Focused PostgreSQL outbox/audit/governance target | 103 collected; 99 passed, four service skips, zero failures/errors; 10.493s; JUnit SHA-256 `06e009755b51dc9227391e6ce61434e90d50172fedecd09f7a32756a63e91dce` |
| Full locked Python 3.11.15 suite | 1,192 collected; 1,182 passed, 10 skipped, zero failures/errors; eight warnings; 332.375s; JUnit SHA-256 `3cb0cb25e0e8c37d9740eafaa7e5d91d3f66c81f5b1ce0a5908aec33942021e1` |
| Locked Ruff 0.16.0 / Mypy 2.3.0 | Pass; Mypy found no issues in 213 source files |
| Locked Bandit 1.9.4 / pip-audit 2.10.1 | Pass; no Bandit findings, same three B608 nosec notices; no known dependency vulnerabilities and local project not found on PyPI |
| Python 3.11 build --no-isolation | Pass with existing setuptools metadata warnings |
| Package membership | Pass; affected runtime modules are in wheel/sdist; outbox schema and dedicated test are in sdist; ADR 0088 is repository-only |
| Built sdist | 889,637 bytes; SHA-256 `db4d42b4c91d56721508c16b118ac968de59ed81996c39d150c2215a71f51c18` |
| Built wheel | 639,729 bytes; SHA-256 `7a4ea2720a78e7ee530178188096a9287ac1f9bba76b03e713d9f384bdbdeb51` |
| doctor / sample validate / local demo | Pass; validation retained zero errors/ten synthetic warnings and demo wrote the established artifacts |
| Governance schemas and exact AST inventory | Pass; eight direct JSON calls remain and linked FI-013/risk/architecture/threat/ASVS/SSDF records validate |

Observed failures and corrections: the first focused run expected the close
wrapper to expose the ledger validation exception as a module attribute; the
test now asserts the actual public exception class. The first audit AST check
used a suffix match that accidentally counted `_outbox_json_text` as
`_json_text`; it now enumerates the exact audit helper names. More importantly,
review exposed the E-072 PostgreSQL audit-writer omission described above. All
three are retained as failed/review findings and none is counted as passing
evidence.

Inventory before cleanup: 213 Python source files, 133 test modules, 56 JSON
schemas, 88 ADRs, six workflows, 205 tracked status entries, and 263 untracked
status entries including the E-073 root. No unrelated dirty changes were
removed.

Security and claim boundary: E-073 proves local contract and simulated
transaction behavior only. Live PostgreSQL and an external publisher were not
exercised. It does not prove stored-row authenticity, centralized
actor/disclosure authorization, business semantic correctness, supported
throughput, the six remaining FI-013 decoders, malware absence, hosted
enforcement, compliance, certification, enterprise readiness, bank-grade
quality, or production readiness. P0-SEC-009 and R-018 remain open/partial. No
customer data, secret, remote write/run, publication, or production mutation
occurred. The next safe slice is E-074 bounded PostgreSQL reconciliation stored
rule/attributes/lineage/evidence producer-consumer contracts.

Cleanup: the E-073 root resolved exactly to
`F:\reconforge-erp\.codex-test-tmp\e073`. Its sole Python-version junction was
verified to target a sibling version directory inside that root and was removed
without traversing the target. The remaining tree contained zero reparse
points; the verified root was recursively deleted and zero `e073*` targets
remain. A 51-test ambient post-cleanup governance target plus Ruff, Mypy, and
`git diff --check` passed. The worktree retains 205 tracked and 262 untracked
status entries; no unrelated dirty changes were removed.

## E-074: Bounded PostgreSQL reconciliation JSONB objects

Implemented boundary:

- Added `postgres-reconciliation-object-v1` with four named profiles for
  stored rule, input attributes, decision lineage, and exception evidence.
  Rule/lineage/evidence allow 4,194,304 UTF-8 bytes and 262,144 characters per
  scalar. Attributes preserve their prior 100,000-byte producer ceiling and
  allow 100,000 characters/scalar. All four allow at most 100,000 nodes, depth
  32, and 25,000 items per collection; require unique-key finite object JSON;
  and retain finite display numbers only for historical non-financial
  compatibility.
- `create_run`, `register_input`, `append_result`, and `append_exception` use
  the corresponding canonical producer before persistence SQL. Partition
  lineage/evidence are preflighted before output hashing or acquiring the run
  lock, preventing resource rejection from occurring after those operations.
- Repository rows validate and return all four JSONB fields as objects. The
  local matcher adapter and execution worker use the same decoders; a corrupt
  stored rule fails while reading the run before claim update or matcher use.
- JSONB-rendered rule text is re-encoded to the established compact sorted
  producer bytes before idempotency fingerprinting. No run/result/checkpoint
  identity or matching digest formula changes.
- Three reconciliation `json.loads` calls leave the exact AST allowlist. Five
  total direct calls remain: three FI-013 consumers, one central bounded
  parser, and one packaged currency-registry parser.

Final artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| uv 0.11.32 Windows archive | acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984 |
| reconforge/io/persisted.py | e9d0ba5d6c88845a9db085bab050536c5fa3a1736a4cf80d408eda1001be0885 |
| reconforge/infrastructure/postgres_reconciliation.py | f6752357cf53fff13d28bc0e7dfb109ee7312b63d868678eb5b65d1221874c2c |
| reconforge/workers/postgres_reconciliation.py | d235279964fba21edc6ba16ead5f34f4ff4db3e8a680c05d16007f29b47be08e |
| tests/test_postgres_reconciliation_persisted_json.py | 12582181ad4623f2480863fa4a65c0f74ea9d76fdc0730cefd8204870d450cea |
| docs/schemas/postgres_reconciliation_object.schema.json | b836c61a09b642cf80677caaf40be3981ab6c74f67f4cf58a192b883c48a86b3 |
| docs/security/file-ingestion-inventory.v1.yaml | 553c47e867e0eaef17033a68bf9933b612ab6f9e1a894e749cc6c8bbd9d6087c |
| docs/adr/0089-bound-postgresql-reconciliation-jsonb.md | 6476ab4684258abe764ce27677e65613a42f046ec533559c02f6ba3722319889 |
| MANIFEST.in | abfb0d1dc46f3690f74c9c1902d59195167566315d11792e064948cd99ba81ba |

Verification evidence:

| Command | Result |
| --- | --- |
| Checksum-verified uv, isolated Python 3.11.15, locked all-extra sync | Pass; uv 0.11.32 commit 3010295ae; 104-package resolution and 102 installed packages |
| Focused reconciliation/persisted/governance target | 130 collected; 129 passed, one live-PostgreSQL skip, zero failures/errors; 12.358s; JUnit SHA-256 `58283a51e6591c54453c8bcad5e5439cc22267aa9642ab4f56e3d39d7b7bda40` |
| Full locked Python 3.11.15 suite | 1,220 collected; 1,210 passed, 10 skipped, zero failures/errors; eight warnings; 237.626s JUnit / 237.68s wrapper; JUnit SHA-256 `b013b9fb49ff599c96152f2ef0fbb7ddb6fd862e66e3fe9610680106ae89695b` |
| Locked Ruff 0.16.0 / Mypy 2.3.0 | Pass; Mypy found no issues in 213 source files |
| Locked Bandit 1.9.4 / pip-audit 2.10.1 | Pass; no Bandit findings, same three B608 nosec notices; no known dependency vulnerabilities and local project not found on PyPI |
| Python 3.11 build --no-isolation | Pass with existing setuptools metadata warnings |
| Package membership | Pass; affected runtime files are in the 465-entry sdist and 220-entry wheel; reconciliation schema and dedicated test are sdist-only; ADR 0089 is repository-only |
| Built final sdist after governance updates | 894,384 bytes; SHA-256 `4d830edb53d9f8c32cf4ce858bbf67714c1c0ac305fe1cd875d77ed0ce464f77` |
| Built final wheel after governance updates | 640,571 bytes; SHA-256 `7e2a2d766b6ac3943957760902cb3050565a76a4973075895f1a27fb6b034f8b` |
| doctor / sample validate / local demo | Pass; validation retained zero errors/ten synthetic warnings and demo wrote the established artifacts |
| Governance schemas and exact AST inventory | Pass; five direct JSON calls remain and linked FI-013/risk/architecture/threat/ASVS/SSDF records validate |

Observed failures and corrections: one initial PowerShell search command had a
quoting error and performed no mutation. The first new focused test exposed a
real fingerprint bug in the initial implementation: text decoding retained
JSONB display whitespace instead of canonical producer bytes. The decoder now
re-encodes validated objects canonically, and the fingerprint regression passes.
That run also found one unused Mypy ignore, which was removed. The first
inventory-governance run rejected a limitation string longer than its 500
character schema ceiling; the text was split into two bounded entries. Because
a later command in that PowerShell chain returned zero, the combined shell exit
could have hidden the pytest failure; pytest was rerun independently and passed
52/52. No failed command is counted as passing evidence.

Inventory before cleanup: 213 Python source files, 134 test modules, 57 JSON
schemas, 89 ADRs, six workflows, 205 tracked status entries, and 266 untracked
status entries including the E-074 root. No unrelated dirty changes were
removed.

Security and claim boundary: E-074 proves local structural/resource contracts,
simulated repository rows, pre-mutation ordering, worker non-invocation, and
canonical fingerprint compatibility. The live PostgreSQL test was skipped. It
does not prove stored-row authenticity, centralized actor/disclosure
authorization, business-semantic correctness, supported throughput, the three
remaining FI-013 decoders, malware absence, hosted enforcement, compliance,
certification, enterprise readiness, bank-grade quality, or production
readiness. P0-SEC-009 and R-018 remain open/partial. No customer data, secret,
remote write/run, publication, or production mutation occurred. The next safe
slice is E-075 bounded SQLite matching-rule producer/consumer parity.

Cleanup: eight `e074*` roots resolved exactly beneath
`F:\reconforge-erp\.codex-test-tmp`. The main environment's sole Python-version
junction was verified to target a sibling version directory inside that root
and removed without traversing the target. Every verified root then contained
zero reparse points and was recursively deleted; zero `e074*` targets remain.
An ambient 95-test post-cleanup target records 94 passes and one live-service
skip; Ruff, Mypy across 213 source files, and `git diff --check` passed. The
worktree retains 205 tracked and 265 untracked status entries; no unrelated
dirty changes were removed.

## E-075: Bounded SQLite matching-rule JSON

Implemented boundary:

- Added `sqlite-matching-rule-object-v1` and
  `sqlite-matching-rule-json-v1`: 4,194,304 UTF-8 bytes, 100,000 nodes, depth
  32, 25,000 items per collection, 262,144 characters per scalar, unique keys,
  finite values, and an object root.
- The producer encodes once before `BEGIN IMMEDIATE` and supplies the identical
  text to `match_jobs` and `match_rules`. New binary floats, cycles, non-finite
  values, invalid roots, and resource excess fail before transaction/business,
  audit, or outbox effects.
- The encoder deliberately retains the established sorted ASCII JSON with
  default spaces. Stored valid text returned by `job_status`/`list_jobs`, rule
  fields, matching/result identities, matching digests, and idempotency keys do
  not change.
- Idempotent replay uses the same bounded decoder. Historical finite JSON
  floats remain readable for compatibility, and rules missing the financial
  input or record identity fields retain their established legacy defaults.
  Corruption fails before a new matching effect.
- Public matching job readers validate stored rules before returning their raw
  valid text. Invalid state is an explicit path-free integrity failure, not a
  sentinel object.
- The matching `json.loads` leaves the exact AST allowlist. Four direct calls
  remain: two FI-013 consumers, one central bounded parser, and one packaged
  currency-registry parser.

Artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| uv 0.11.32 Windows archive | acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984 |
| reconforge/io/persisted.py | 0ff5fd118aca1b05e37f13fa8d46e1b8b0f5933690f919f4bba2a75c997c960b |
| reconforge/platform/matching.py | adbcd2975e268e9c30e4e4321c55cf8ba741e0c8ef281979e304bb548df497b2 |
| tests/test_sqlite_matching_rule_json.py | 6bb8de68ac1690585b0a208752bbd3b0d9ad0e7433f1e8f278909bfeb66fee71 |
| docs/schemas/sqlite_matching_rule.schema.json | 3bb3c898441705aaf1a7bca7068cb61c25f1941cc77b57151e30e19724f6b8a2 |
| docs/security/file-ingestion-inventory.v1.yaml | 3bbc9beec1872dc4d0f7a3709fb951ff427bbde7d03cf68bcd2a0696861e55cd |
| docs/adr/0090-bound-sqlite-matching-rule-json.md | c2fcf102c84f71908e84cdb632d0dd9992970f6074bd23fd6f543f64a0560dd2 |
| MANIFEST.in | adb70496557d93d59a5970196d06f49e401dae9b33beaac22fe9e5fecf8ea8f8 |

Verification evidence:

| Command | Result |
| --- | --- |
| Checksum-verified uv, isolated Python 3.11.15, locked all-extra sync | Pass; uv 0.11.32 commit 3010295ae; 104-package resolution and 102 installed packages |
| Focused matching/persisted/governance target | 115 collected/passed, zero skips/failures/errors; 54.995s; JUnit SHA-256 `b5f3856276aa441616334c427b28179b2fea7b45e5a381b60c23ef67f4d58c97` |
| Full locked Python 3.11.15 suite | 1,234 collected; 1,224 passed, 10 skipped, zero failures/errors; eight warnings; 468.111s JUnit; JUnit SHA-256 `b38e4d2bb460a698c9d2b179529eba41c539fb193c82ed480ae6c3ca9f5df2be` |
| Locked Ruff 0.16.0 / Mypy 2.3.0 | Pass; Mypy found no issues in 213 source files |
| Locked Bandit 1.9.4 / pip-audit 2.10.1 | Pass; no Bandit findings, same three B608 nosec notices; 103 policy packages and no known dependency vulnerabilities; local project excluded from the hashed export |
| Python 3.11 build --no-isolation | Pass with existing setuptools metadata warnings |
| Package membership | Pass; affected runtime files are in the 467-entry sdist and 220-entry wheel; matching schema, inventory, and dedicated test are sdist-only; ADR 0090 is repository-only |
| Built sdist | 897,691 bytes; SHA-256 `ed60c169b1b3a8b4b6065b521bae90a58d5e0bcc3c35449d945cdea93fe72ead` |
| Built wheel | 641,034 bytes; SHA-256 `8def603020d343fecd4cdb15705939b7cf2474ccaafbc01aeacaec275fd7e7a7` |
| doctor / sample validate / local demo | Pass; validation retained zero errors/ten synthetic warnings and demo wrote the established artifacts |
| Governance schemas and exact AST inventory | Pass; four direct JSON calls remain and linked FI-013/risk/architecture/threat/ASVS/SSDF records validate |

Observed failures and corrections: the first broad focused run failed two new
rollback assertions because its test-only snapshot helper named a nonexistent
`match_exceptions` table. The helper was corrected to count only tables the
matching path can affect, and all 14 dedicated cases then passed. The initial
uv sync created the repository-standard ignored `.venv` even though a separate
interpreter path was supplied; its reported interpreter is Python 3.11.15 and
all locked gates use that exact executable. No failed or ambient-Python command
is counted as passing evidence.

Inventory before cleanup: 213 Python source files, 135 test modules, 58 JSON
schemas, 90 ADRs, six workflows, 205 tracked status entries, and 269 untracked
status entries including the E-075 root. No unrelated dirty changes were
removed.

Security and claim boundary: E-075 proves local structural/resource contracts,
SQLite rollback/order behavior, exact stored-text and legacy-policy
compatibility, and fail-closed replay/public readers. It does not prove
stored-row authenticity, centralized actor/disclosure authorization,
business-semantic correctness, supported throughput, the two remaining FI-013
decoders, malware absence, hosted enforcement, compliance, certification,
enterprise readiness, bank-grade quality, or production readiness.
P0-SEC-009 and R-018 remain open/partial. No customer data, secret, remote
write/run, publication, or production mutation occurred. The next safe slice
is E-076 bounded tenant-scoped Redis session JSON.

Cleanup: all 16 `e075*` test, environment, tool, report, build, and demo roots
were resolved beneath `F:\reconforge-erp\.codex-test-tmp`. The sole junction
was verified to point to the sibling managed Python 3.11.15 directory and was
removed without traversing its target; the generated repository `.venv` had no
reparse points and was removed separately. The command guard rejected two
PowerShell deletion attempts before execution, so the same already-verified
targets were removed with a local path-asserting fallback. A 70-test ambient
post-cleanup governance target, Ruff, Mypy across 213 source files, and
`git diff --check` passed. The final post-test root was verified to contain no
reparse points and removed; zero `e075*` targets and no `.venv` remain. The
worktree retains 205 tracked and 268 untracked status entries—the net three new
untracked entries are the E-075 ADR, schema, and test. No unrelated dirty
changes were removed.

## E-076: Bounded tenant-scoped Redis session JSON

Implemented boundary:

- Added the closed `redis-session-object-v1` schema and
  `redis-session-json-v1` profile: 16,384 UTF-8 bytes, 16 nodes, depth two,
  four properties, and 256 characters/scalar.
- Exactly four strings are accepted: non-empty/control-free bounded session
  and user IDs, a lowercase 64-character SHA-256 token digest, and an explicit
  UTC ISO expiry ending in `Z` or `+00:00`. Raw tokens, implicit/non-UTC time,
  non-string coercion, unknown/missing fields, duplicates, non-finite values,
  and over-budget structures fail closed.
- `put_session` retains the prior compact sorted ASCII bytes and normalizes the
  token digest as before, but validates/encodes before Redis client access.
  Rejection therefore performs no Redis operation.
- `get_session` uses the same bounded contract. Corrupt state is not deleted,
  rewritten, extended, or replaced with a sentinel. The established key/session
  identifier equality check remains separate and fail closed.
- Tenant key hashing, namespaces, TTL values/units, missing-key behavior, the
  `RedisSessionRecord` shape, and fake/live cleanup behavior are unchanged.
- The existing service-backed Redis test now covers session write/read, tenant
  isolation, and a positive at-most-requested TTL when
  `RECONFORGE_TEST_REDIS_URL` is configured. It remained skipped locally.
- The Redis `json.loads` leaves the exact AST allowlist. Three total direct
  calls remain: one FI-013 generic export decoder, one central bounded parser,
  and one packaged currency-registry parser.

Artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| uv 0.11.32 Windows archive | acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984 |
| reconforge/io/persisted.py | eb71eb4325fc0aedf41a29d5c83285df664847f9c3b44d7424e09e286756e5dc |
| reconforge/infrastructure/redis.py | aa17dc833b5061740273633d78bd6ea407dca6a50abb1034452d37fe6baa5a20 |
| tests/test_redis_session_json.py | ffc14a090726189dc859957cc190c57050a8a1db4a4f9b954303971fed77d822 |
| tests/test_redis_foundation.py | 5e7e502dfdc02863d9c910e8caa1c7514affc77924b5291a5d68e4754dbde153 |
| docs/schemas/redis_session.schema.json | 40762983d8061438e64a6da0fa88a194a190a718d77d134ec7a51aa84b3cf36e |
| docs/security/file-ingestion-inventory.v1.yaml | ba48a39db317b675927cec2e8e9c74415d38ad75a675f9d8d755b022d2fc6bc2 |
| docs/adr/0091-bound-redis-session-json.md | 4cff95f5db5128d214f1701f8eb68137746842ab4f4766d15ab675aed244fde9 |
| MANIFEST.in | d619e41002151b3e86ceca1882b6fa57f1f9b92dd7656be8dc5a824da027d039 |

Verification evidence:

| Command | Result |
| --- | --- |
| Checksum-verified uv, isolated Python 3.11.15, locked all-extra sync | Pass; uv 0.11.32 commit 3010295ae; 104-package resolution and 102 installed packages |
| Focused Redis/API/persisted/governance target | 91 collected; 90 passed, one live-Redis skip, zero failures/errors; 18.428s; JUnit SHA-256 `f637f523a153273813927412bbc926e233f50a0e13a2ffd451f3e4982b761766` |
| Full locked Python 3.11.15 suite | 1,251 collected; 1,241 passed, 10 skipped, zero failures/errors; eight warnings; 206.395s JUnit; JUnit SHA-256 `61ca3791e090ac747ee3d26c805ac36f760bb62aba6eeeef8a3ca54e5d5a8dc5` |
| Locked Ruff 0.16.0 / Mypy 2.3.0 | Pass; Mypy found no issues in 213 source files |
| Locked Bandit 1.9.4 / pip-audit 2.10.1 | Pass; no Bandit findings, same three B608 nosec notices; 103 policy packages and no known dependency vulnerabilities; local project excluded from the hashed export |
| Python 3.11 build --no-isolation | Pass with existing setuptools metadata warnings |
| Package membership | Pass; affected runtime files are in the 469-entry sdist and 220-entry wheel; Redis schema, inventory, and dedicated test are sdist-only; ADR 0091 is repository-only |
| Built sdist | 900,377 bytes; SHA-256 `ad1655bf21726802ab4e05e3406d8fb82c50eaf00b28eeee0018f0dd6b3baedc` |
| Built wheel | 641,668 bytes; SHA-256 `4ad7c8de4a011e9ce9dec42a063bfeb96c569fb5d1e2acfb35e617b617d530af` |
| doctor / sample validate / local demo | Pass; validation retained zero errors/ten synthetic warnings and demo wrote the established artifacts |
| Governance schemas and exact AST inventory | Pass; three direct JSON calls remain and linked FI-013/risk/architecture/threat/ASVS/SSDF records validate |

Observed failures and corrections: the first new test run expected the
closed-field error for a fifth property, but the narrower four-item collection
budget correctly rejected it earlier. The assertion now records the actual
resource-bound code while missing-field tests retain closed-schema evidence.
The first environment setup command used a `New-Item -LiteralPath` option not
available in the installed PowerShell; it failed before download or environment
creation and was rerun with the compatible `-Path` option. No failed command or
ambient-Python result is counted as locked passing evidence.

Inventory before cleanup: 213 Python source files, 136 test modules, 59 JSON
schemas, 91 ADRs, and six workflows. The worktree remains broad and dirty; its
final tracked/untracked counts are recorded after verified E-076 cleanup.

Security and claim boundary: E-076 proves a local closed structural/semantic
session contract, fake-client pre-access/non-mutation behavior, tenant-key and
TTL argument compatibility, and exact parser inventory. The live Redis test was
skipped. It does not prove live service behavior, integration into the main
login/session lifecycle, stored-value authenticity, centralized authorization,
supported throughput, the generic-export FI-013 decoder, malware absence,
hosted enforcement, compliance, certification, enterprise readiness,
bank-grade quality, or production readiness. P0-SEC-009 and R-018 remain
open/partial. No customer data, secret, remote write/run, publication, or
production mutation occurred. The next safe slice is E-077 bounded generic
database export JSON decoding.

Cleanup: all 12 `e076*` environment/tool/report/build/demo roots resolved
exactly beneath `F:\reconforge-erp\.codex-test-tmp`. The sole junction was
verified to target the sibling managed Python 3.11.15 directory and removed
without traversing its target. The generated repository `.venv` contained no
reparse points and was removed separately. A 91-test ambient post-cleanup
Redis/API/governance target records 90 passes and the one live-Redis skip;
Ruff, Mypy across 213 source files, and `git diff --check` passed. Its final
test root was verified to contain no reparse points and removed. Zero `e076*`
targets and no `.venv` remain. The worktree retains 207 tracked and 271
untracked status entries—the net slice delta is two tracked files and three new
untracked ADR/schema/test files. No unrelated dirty changes were removed.

## E-077: Bounded public SQLite database export JSON

Implemented boundary:

- Enumerated the exact five `(table, column)` JSON fields reachable through
  the public SQLite export: audit metadata, legacy-import summary, both
  matching-rule fields, and match-result lineage. A migration-backed contract
  fails if an exported `_json` column is not in this registry.
- Reused `audit-metadata-json-v1` and `sqlite-matching-rule-json-v1`; added
  `sqlite-legacy-import-summary-json-v1` and
  `sqlite-matching-lineage-json-v1`. The new profiles require finite,
  unique-key object JSON under 4,194,304 UTF-8 bytes, 100,000 nodes, depth 32,
  25,000 items/collection, and 262,144 characters/scalar.
- Routed legacy-summary and local matching-lineage producers through their
  respective profiles while retaining established compact ASCII and compact
  UTF-8 text. Cycles, non-finite values, non-object state, duplicate keys,
  non-text SQLite values, and resource excess fail visibly.
- The exporter materializes and validates every payload before resolving or
  creating the destination and before any file write. It no longer emits the
  plausible `invalid_json` sentinel. Rejected exports append no `db_exported`
  event and leave an existing unrelated destination marker unchanged.
- Export format version 1, filenames, and valid field shapes remain unchanged:
  metadata/summary/rules are objects and `lineage_json` remains its historical
  validated string rather than receiving an unversioned rename/type change.
- The exporter direct `json.loads` call leaves the exact AST allowlist. Two
  direct production calls remain: the central bounded structured parser and
  the separately governed packaged currency-registry parser; neither is a
  direct FI-013 persisted decoder.

Artifact inputs before temporary cleanup:

| Artifact | SHA-256 |
| --- | --- |
| uv 0.11.32 Windows archive | acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984 |
| reconforge/io/persisted.py | d0eaea641ddba112c322bdd47f3d3e97df6776c0eadb0febb912811d290c8e71 |
| reconforge/db/exporter.py | b01bff442a61d1c8bc36175b895b2653ddec4d98e1c9aac433d735b5ad5b30e2 |
| reconforge/db/importers.py | 09b81b9c6e8f76fd89f8fc0f5ef781f87375ebcfc19aa91aed8d75b20e5982bd |
| reconforge/platform/matching.py | 225d50df76f2f70f9aef4863d9c496689d4df98893915f0635cce88ff498d02e |
| tests/test_db_export_persisted_json.py | b6cace9642bacaff21b953f73d92ceb092bfe942da664ea0a0551b14912c6bf6 |
| docs/schemas/sqlite_legacy_import_summary.schema.json | de98e8f14da12838e861082ca0913ec962f225e3feb887dcb0cad5aa6e0b955c |
| docs/schemas/sqlite_matching_lineage.schema.json | ef880d5f828b53b0a7bdc49c581d5314bf7dd71ebce3f4565ac0f53e371e1b28 |
| docs/security/file-ingestion-inventory.v1.yaml | bdfdb3ba50a776a9a6939a6a9d2badce43d8a041ab69fcba793dfd00af48ca9e |
| docs/adr/0092-bound-public-database-export-json.md | 544f404ac36051ffba6f66a2df1d292aebf83fc3135b874cade1d821d97870e3 |
| MANIFEST.in | a0d026acf56b7f5544f3e189be654c606982c1b2c2a03ce61f778283678ddda7 |

Verification evidence:

| Command | Result |
| --- | --- |
| Checksum-verified uv, isolated Python 3.11.15, locked all-extra sync | Pass; final exact-snapshot rerun used uv 0.11.32 commit 3010295ae; 104-package resolution and 102 installed packages; 683.131s including downloads and one successful transient cache-rename retry |
| Focused export/matching/inventory target | Final exact snapshot: 81 collected/passed, zero skips/failures/errors; 38.192s JUnit test time; JUnit SHA-256 `5fde0801c0a2bed1feb5e5cc3227cf55422ea07f04a2dcbb6d7fa3bbdc44cfe6` |
| Full locked Python 3.11.15 suite | Final exact snapshot: 1,266 collected; 1,256 passed, 10 skipped, zero failures/errors; 381.748s JUnit test time / 388.797s wrapper; JUnit SHA-256 `3c406faa6312ea9c7d0165fd27c415b956a4810ffc08b43794e9ffb7b45afb3a` |
| Locked Ruff 0.16.0 / Mypy 2.3.0 | Pass in 2.787s / 11.421s; Mypy found no issues in 213 source files |
| Locked Bandit 1.9.4 / pip-audit 2.10.1 | Pass; no Bandit findings and the same three B608 nosec notices; hash-exported 103-package view SHA-256 `d49d99f1e5cebdfdd7226b32aec039f31b15beaec573477b0847bf9dfd95488c`; no known vulnerabilities |
| Python 3.11 build --no-isolation | Final exact snapshot passed in 28.058s with existing setuptools metadata warnings |
| Package membership | Pass; four affected runtime files are in wheel/sdist; both schemas, inventory, and dedicated test are sdist-only; ADR 0092 is repository-only |
| Built sdist | 472 entries; 904,179 bytes; SHA-256 `24e96aff153b3782028e1815eec0a960cb975b7077220ca6ee6c702c869a72ab` |
| Built wheel | 220 entries; 642,278 bytes; SHA-256 `61604cee0bd737d71ed4beca1ad4aa62f3c4763effa6ca175a3f9ff6a6153bb4` |
| doctor / sample validate / local demo | Pass; validation retained zero errors/ten synthetic warnings and demo wrote the established artifacts |
| Governance schemas, exact export-field inventory, direct-parser AST inventory, and `git diff --check` | Pass before final governance refresh; two direct JSON calls remain and neither is FI-013 |

Observed failures and corrections: the first ambient focused run found an
unused importer `json` import/import-order error and two fixture failures. The
fixture assumed workspace creation emitted an audit event, so audit metadata
was absent and its corruption case could not mutate a row. The unused import
was removed, imports were ordered, and the fixture now appends one explicit
synthetic audit event. The corrected ambient target and both retained locked
targets pass. No failed or ambient-Python run is counted as locked passing
evidence.

The final full-suite PowerShell timing wrapper retained JUnit but did not retain
pytest console warning text. Therefore E-077 records exact test/skip/error
counts from JUnit and makes no new exact warning-count claim; the prior eight
warnings remain historical evidence, not an inferred current count.

Inventory before cleanup: 213 Python source files, 137 test modules, 61 JSON
schemas, 92 ADRs, and six workflows. The worktree had 207 tracked and 276
untracked status entries including the E-077 root; no unrelated dirty changes
were removed.

Security and claim boundary: E-077 proves local structural/resource contracts,
exact current exported-field coverage, producer compatibility for two fields,
pre-publication corruption refusal, absence of a sentinel/audit effect, and
format-v1 field-shape compatibility. It does not prove stored-row or source
authenticity, centralized actor/disclosure authorization, malware absence,
crash-atomic multi-file publication, supported throughput, hosted enforcement,
compliance, certification, enterprise readiness, bank-grade quality, or
production readiness. P0-SEC-009 and R-018 remain open/partial. No customer
data, secret, remote write/run, publication, or production mutation occurred.
The next safe slice is E-078 staged, integrity-bound public database export
publication and bounded recovery.

An initial E-077 environment was safely cleaned as described below. A final
exact-snapshot environment was then created after the export registry became
read-only; its full/focused suites, static/security gates, build, and package
membership supersede the earlier JUnit/package measurements above. Its sole uv
Python junction likewise targeted the sibling versioned interpreter within the
verified `e077-final` root; the junction was removed without traversal, a scan
proved zero remaining reparse points, and the explicit root was then removed.

Cleanup: the initial E-077 root resolved exactly to
`F:\reconforge-erp\.codex-test-tmp\e077`, beneath the verified workspace. Its
sole reparse point was a uv-managed Python 3.11 junction targeting the sibling
versioned interpreter inside the same E-077 root; the junction was removed
without traversal, the managed target remained present, and a second scan
proved zero reparse points before the explicit recursive directory deletion.
The repository `.venv` did not exist. A 62-test ambient post-cleanup
export/governance target, Ruff, Mypy across 213 source files, and
`git diff --check` passed. Zero `e077*` roots and no `.venv` remain. The
worktree retains 207 tracked and 275 untracked status entries—the net slice
delta is four new untracked ADR/schema/test files while all tracked changes
remain preserved. Two initial `Remove-Item` attempts were rejected by the
execution guard before running; no target changed until the verified explicit
path fallback. No unrelated dirty change was removed.

## E-078: Integrity-bound database export publication and recovery

Implemented boundary:

- The nine existing format-v1 payloads are written only into a same-parent
  private staging directory. `export_manifest.json` adds the exact closed
  basename set, byte lengths, SHA-256 digests, DB schema version, export format
  version, and manifest version; staged bytes are verified before publication.
- A fresh destination is published by one same-filesystem directory rename.
  Existing output is independently bounded/digested, moved to a transaction-
  specific rollback sibling, and replaced only by the verified staged tree.
  Handled failure restores the prior tree and removes transaction artifacts.
- The path-minimized marker carries only sibling basenames, transaction phase,
  both tree digests, and an explicit "not authentication" boundary. Unexpected
  siblings, reparse points, unsupported nested prior entries, marker change,
  tree change, invalid state, more than 32 prior files, or more than 1 GiB of
  prior bytes fail closed.
- `reconforge db export-recover --output ...` accepts only one self-consistent
  interrupted transaction and either aborts before swap, restores the previous
  tree, finalizes the verified new tree, or confirms publication. CLI success
  output does not disclose the local path.
- The existing nine filenames and payload shapes remain format-v1 compatible.
  The tenth manifest is additive and successful replacement intentionally
  removes stale prior files. `db_exported` is appended only after filesystem
  publication, but the filesystem and SQLite audit commit are not atomic.

Verification evidence:

| Command | Result |
| --- | --- |
| Checksum-verified uv 0.11.32 / locked all-extra Python 3.11.15 sync | Pass; uv commit `3010295ae`, archive SHA-256 `acfde570...b0984`, 104-package resolution and 102 installed packages |
| Focused publication/export/inventory/maturity target | 39 collected/passed, zero skips/failures/errors; JUnit SHA-256 `1e2c2abd7958f43fcbfd91978153191edf850022a307b8acffaa867d07626df2` |
| Full locked Python suite | 1,274 collected; 1,264 passed, ten service skips, zero failures/errors; 235.317s JUnit / 237.337s wrapper; eight known warnings; JUnit SHA-256 `9f1c23fd881d1ded25cfa03d629bf3ff555512552f491f769ef9a3311c3d7a9b` |
| Ruff 0.16.0 / Mypy 2.3.0 / Bandit 1.9.4 / git diff --check | Pass; Mypy covers 213 source files; Bandit has no findings and retains three reviewed B608 nosec notices; only the existing `.gitignore` line-ending warning remains |
| Hash-exported dependency audit | Requirements SHA-256 `ca41d86bb42a9fcb369d9109ffbdd9b1154d5c558a2eef5d08891410c6f9598f`; pip-audit 2.10.1 reports no known vulnerabilities |
| Build/package boundary | Pass `--no-isolation`; sdist 474 entries/909,191 bytes/SHA-256 `917824430709f33ec10dfa63e38c6a7bcfb4924a4eeddbc4001a47c966e93977`; wheel 220 entries/645,923 bytes/`f3951e00206730f5de0c2518732be387dc549f4eaf591dd0b00cea0e6fc89ba9`; runtime exporter/CLI in both, schema/test sdist-only, schema absent from wheel |
| doctor / validate / demo | Pass; validation retains zero errors/ten expected synthetic warnings and demo emits its established local artifacts |

Security and claim boundary: this proves deterministic local staging, closed
artifact change detection, tested handled rollback, and integrity-checked
recovery for modeled crash phases. It does not prove SHA-256 authentication,
source/actor/disclosure authorization, malware absence, remote-filesystem
semantics, atomic visibility while replacing an existing directory, durability
under real host/power/filesystem loss, cross-resource audit atomicity, supported
throughput, hosted enforcement, compliance, certification, enterprise readiness,
bank-grade quality, or production readiness. R-018 and P0-SEC-009 remain open.
No customer data, secret, GitHub write, release publication, or production
mutation occurred. Cleanup resolved `e078-final` beneath the workspace, found
one uv-managed Python 3.11 junction targeting its sibling versioned interpreter,
removed the junction without traversal, proved zero remaining reparse points,
and deleted the explicit root through the same PowerShell/.NET process. The
target and repository `.venv` no longer exist. The first two guarded
`Remove-Item` attempts were rejected before execution and changed no target.

## E-079: Deny-by-default authorization scopes and closed approval SoD

Implemented boundary:

- `CentralPolicyEngine` refuses identity without a named permission and checks
  every supplied tenant, workspace, entity, and period against immutable
  principal grants. Creator approve/review checks default on.
- One non-empty, whitespace-trimmed, case-folded actor comparator is used by an
  exact inventory of all nine current platform approve/review service methods.
  Generic override text cannot authorize self-approval, while requester
  rejection remains possible with a reason.
- Trusted-local workflow labels participate in history-based SoD instead of
  bypassing it when no persisted user ID exists. AP, AR, account,
  certification, inventory-count, valuation, and reversal paths have direct
  or inventory-backed regression coverage.
- The synthetic enterprise demo now names separate preparer, reviewer, and
  completer actors, so demo evidence follows the same policy as application
  workflows rather than relying on a local compatibility label.

Verification evidence:

| Command | Result |
| --- | --- |
| Official uv archive checksum plus isolated locked environment | Pass; official sidecar and downloaded archive SHA-256 `acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984`; uv 0.11.32 commit `3010295ae`; Python 3.11.15; 104-package resolution and 102 installed packages. The prior 65-character documentation typo ending `...b0984e` was corrected before this evidence was accepted. |
| Authorization/SoD/security-governance focus | 85 collected/passed, zero skips/failures/errors; 31.60s pytest / 44.860s wrapper; JUnit SHA-256 `5e290da89f3dfdb23386b726cb7de05ab59cbd85d359965b9840058d83a240f4` |
| Enterprise-demo plus core SoD regression after correction | 34 collected/passed; JUnit SHA-256 `6614279a4c882fa6523448a551b8fae2618f1217acaaa3d622f5e7332b794d44` |
| Full locked Python suite | 1,287 collected; 1,277 passed, ten service skips, zero failures/errors; 301.50s pytest / 303.539s wrapper; eight warnings; JUnit SHA-256 `429b2cb3fe1d665c5eb830b6984d6078ecd849aada95cfe2b8220cb808d56ac9` |
| Ruff 0.16.0 / Mypy 2.3.0 / Bandit 1.9.4 / `git diff --check` | Pass in 2.286s / 7.145s / 9.311s / 0.402s; Mypy covers 213 sources; Bandit has no findings and retains three reviewed B608 nosec notices; only the existing `.gitignore` line-ending warning remains |
| Locked dependency audit | `uv lock --check` passes; hash-exported requirements are 115,729 bytes/SHA-256 `4e266804426a0a02aec73fa9d920bb187b2d82632b681667c5da7b49d7bfe88d`; pip-audit 2.10.1 reports no known vulnerabilities |
| Build/package boundary | `build --no-isolation` passes; sdist 476 entries/912,975 bytes/SHA-256 `38c59d03d41dd3b25bb377779e344ceed8a7d516b433c3af0c2098955b490718`; wheel 220 entries/646,819 bytes/SHA-256 `adb76d236ec3037e1ea6c9f8db14a26d98b1e527c75a7d25a2ffc14cb48a8296`; affected auth/approval/demo runtime files are in the wheel and the three dedicated policy/SoD tests are sdist-only; ADR 0094 remains repository-only under the current manifest |
| doctor / sample validate / local demo | Pass; validation retains zero errors/ten expected synthetic warnings and demo emits its established local artifacts |

Observed failure and correction: the first full locked run collected 1,287
tests and produced five enterprise-demo failures because both submit and
complete used the same `local-cli` actor. That is the intended new policy
refusal, not a flaky test. The demo was changed to explicit distinct synthetic
actors, the 34-test regression passed, and the complete locked suite was rerun
successfully. The failed JUnit SHA-256
`3925ce10c642ce8b3c845852ab24cd476adb1346dbe3722cbf3e27e6edc1e28b`
is retained as correction evidence and is not counted as a passing gate.

Worktree disclosure: an earlier broad `ruff format reconforge/platform ...`
invocation mechanically reformatted 19 platform files, including pre-existing
dirty files not semantically targeted by E-079. Because those files may contain
user work and the baseline was already dirty, they were not blindly reverted.
No semantic claim is made for the formatting-only delta; the full locked suite,
Ruff, Mypy, Bandit, build, and runtime gates cover the resulting snapshot. This
must be reviewed during later change isolation before any commit or publication.

Security and claim boundary: E-079 proves repository-level generated
permission/scope and creator-action properties plus the exact current local
approval/review inventory. It does not prove universal route/repository ABAC,
amount/region/data-class rules, assignments or delegation, privileged emergency
access, external identity governance, continuous deployed effectiveness,
penetration-test results, compliance, certification, enterprise readiness, or
production readiness. No customer data, secret, GitHub write, release
publication, or production mutation occurred. Cleanup resolved `e079-final`
exactly beneath the workspace, verified its sole uv-managed Python junction
targeted the sibling versioned interpreter inside that root, removed the
junction without traversal, proved zero remaining reparse points, and deleted
the explicit root. The repository `.venv` does not exist. The first guarded
`Remove-Item` cleanup attempt was rejected before execution and changed no
target.

## E-080: Evidence-defined hostile file-ingress exit audit

This governance audit closes P0-SEC-009 only for the exit evidence written in
the backlog. The direct focused target covers size, type/signature, non-regular
and reparse paths, CSV shape and field budgets, XLSX archive traversal,
duplicates, encryption/compression/decompression, active content, XML
DTD/entities/external relationships, formulas, sparse/aggregate sheet limits,
JSON/YAML encoding, duplicates, non-finite values, depth/collection/scalar
budgets, YAML merges/cycles/aliases/unsafe tags/multiple documents, stable
path/source-free rejection wording, runtime-policy parity, and exact AST parser
inventories.

| Evidence | Result |
| --- | --- |
| Direct P0-SEC-009 exit focus on ambient Python 3.14.6 | 61 collected/passed, zero skips/failures/errors; 24.002s JUnit; SHA-256 `69a0b37cd14dad417da1de2f40838d012d649c5c1fadda2f3a1e99afb3ccca0a` |
| Supported locked regression | E-079 Python 3.11.15 full suite retained 1,287 collected, 1,277 passed, ten service skips, zero failures/errors; JUnit SHA-256 `429b2cb3fe1d665c5eb830b6984d6078ecd849aada95cfe2b8220cb808d56ac9` |

Claim boundary: this is repository-level bounded parser/abuse evidence. FI-012
and FI-013 stay partial and R-018 stays open. The result does not prove complete
legacy-XLS internals, malware absence or quarantine, source/actor authenticity,
disclosure approval, redaction completeness, safe redistribution, secure
uploads/connectors, real process/host/filesystem durability, declared
throughput, deployed effectiveness, compliance, certification, or production
readiness. ADR 0095 records why those are not silently folded into this finite
Phase 0 exit gate. No code behavior, customer data, secret, GitHub state,
release, or production system changed.

## E-081: Bounded stable source-lineage identity exit audit

The direct exit target exercises the generated stock/GL permutation property,
Pandas/DuckDB full-scan/forced-partition digest equivalence, fixed partition
row-order invariance, signature-v3 contracts, and reconciliation-hardening
regressions. It passes 34/34 on ambient Python 3.14.6 in 35.614s with JUnit
SHA-256 `c63420af1c23a1527c59304d1e758ce03fb402b0f23194e8c13956bc92f3a233`.
The supported locked E-079 full regression remains 1,287 collected, 1,277
passed, ten service skips, zero failures/errors, with JUnit SHA-256
`429b2cb3fe1d665c5eb830b6984d6078ecd849aada95cfe2b8220cb808d56ac9`.

This closes only the P0-006 exit sentence: the bounded stock/GL identity does
not derive from row index and remains stable across declared permutations,
full/partition execution, and the locally tested Pandas/DuckDB path. It does
not prove supported Python/dependency versions, every strategy/backend,
upstream source authenticity, or distinguish duplicate physical copies when
the source supplies no distinguishing evidence. Those limitations remain
under P0-009 and ADRs 0042, 0044, 0050, and 0096. No code behavior, customer
data, secret, GitHub state, release, or production system changed.

## E-082: Strict-v2 financial defaults and explicit legacy replay

Implemented boundary:

- All 52 `FinancialInputPolicy` defaults across 23 runtime files select
  `strict-financial-input-v2`. Direct parser, configuration/model, rule,
  reconciliation, Studio, anonymizer, generator, variance, review, report, and
  evidence calls reject Python/NumPy floating scalars unless legacy is selected
  explicitly.
- `Money` construction and multiplication/division are strict by default.
  Exact strings, `Decimal`, integers, and minor units remain valid. Named legacy
  scalar helpers explicitly pass the legacy policy and remain forbidden at
  production call sites.
- Versioned historical artifact/persisted readers retain their established
  legacy inference. New direct artifacts default to current strict schemas and
  record the strict policy.
- ADR 0097, the changelog, and `docs/financial-input-v2-migration.md` record the
  breaking direct-Python migration and the bounded explicit replay option.

Verification evidence:

| Command | Result |
| --- | --- |
| Official uv sidecar/archive check and locked environment | Pass; SHA-256 `acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984`; uv 0.11.32 commit `3010295ae`; Python 3.11.15; 104-package resolution and 102 installed packages |
| Strict-default financial focus | 190 collected/passed, zero skips/failures/errors; 67.71s pytest; six explicit-legacy warnings; JUnit SHA-256 `abb912c42e3684b34b5fa2e9f92cda3f0b30f907fbcc389298b2229699174c42` |
| Full locked Python suite | 1,288 collected; 1,278 passed, ten service skips, zero failures/errors; 292.04s pytest / 294.234s wrapper; seven warnings; JUnit SHA-256 `b4684cb7b1d420b3f8b06c9354a41b891323326f876c34f48c06511395997873` |
| Ruff 0.16.0 / Mypy 2.3.0 / Bandit 1.9.4 / `git diff --check` | Pass; Mypy covers 213 sources; Bandit has no findings and retains three reviewed B608 nosec notices; only the existing `.gitignore` line-ending warning remains |
| Locked dependency audit | `uv lock --check` passes; hash-exported requirements are 115,729 bytes/SHA-256 `e8719ade423be504122358150424bd79e04d1ac2428d719d9de9a532273e0c97`; pip-audit 2.10.1 reports no known vulnerabilities |
| Build/package boundary | `build --no-isolation` passes; sdist 477 entries/913,546 bytes/SHA-256 `643214edb029cbf906a3a6b60b163efc56d88c054929c1c7b34c73adea91b535`; wheel 220 entries/646,824 bytes/SHA-256 `1f84fde76b4b81a0596754579745c81fcc2c69d4cd2ed512771d01c5a98fef07`; affected runtime files are in the wheel and the migration guide plus strict-default regression are in the sdist; ADR 0097 remains repository-only |
| doctor / sample validate / local demo | Pass; validation retains zero errors/ten expected synthetic warnings and demo emits its established artifacts under strict defaults |

Observed failures and correction: the first ambient migration run exposed 14
expected compatibility-test/default-artifact assumptions; the first complete
ambient suite then exposed 16 additional implicit float fixtures/callers,
including the synthetic enterprise demo. Current fixtures were converted to
exact text and tests of historical compatibility now select legacy explicitly.
No default was reverted. The corrected ambient 1,288-test collection and the
complete locked rerun pass. Failed runs are retained as correction history and
are not counted as passing evidence.

Claim boundary: this proves the repository snapshot has no annotated
`FinancialInputPolicy` legacy default and the tested current paths reject binary
float before financial conversion. The 16 lexical compatibility lines remain
explicit aliases/helpers/historical policy types or rejection/tag annotations;
they are not removed. This does not prove every external caller has migrated,
supported-version/backend parity, live service behavior, source authenticity,
compliance, certification, or production readiness. No customer data, secret,
GitHub write, release publication, or production mutation occurred.
Cleanup resolved `e082-final` exactly beneath the workspace, verified its sole
uv-managed Python junction targeted the sibling versioned interpreter inside
that root, removed the junction without traversal, proved zero remaining
reparse points, and deleted the explicit root. The repository `.venv` does not
exist.

## E-083: Local execution of the supported engine matrix

The exact `supported-engine-parity-v1` matrix was executed in four isolated
uv-managed environments with uv 0.11.32 (archive SHA-256
`acfde570451cfdb8689fa159a138ee805ba4e241c466432750302c86254b0984`).
Every declared cell ran the five required test files and completed with 53
passes and zero failures, errors, or skips.

| Python | Dependency profile | NumPy / Pandas / DuckDB | Result | JUnit SHA-256 |
| --- | --- | --- | --- | --- |
| 3.11.15 | lower-bounds | 1.26.4 / 2.2.0 / 1.0.0 | 53 passed; 0 skipped; 26.632s JUnit | `d6bb90066c0652a965d943c11dbfd1559b99598edf29c2fc317d43322c0b41e0` |
| 3.12.13 | lower-bounds | 1.26.4 / 2.2.0 / 1.0.0 | 53 passed; 0 skipped; 37.837s JUnit | `a37871549f2f7995f900d0658f193e9808a0a865091aa479bad3f2f143361c76` |
| 3.11.15 | current-compatible-2026-07-25 | 2.4.3 / 3.0.5 / 1.5.5 | 53 passed; 0 skipped; 31.996s JUnit | `aaef911ad8db0f89b59a319d2fd8fd36a95b43be9c04856159f910b4f3108ce1` |
| 3.12.13 | current-compatible-2026-07-25 | 2.4.3 / 3.0.5 / 1.5.5 | 53 passed; 0 skipped; 35.138s JUnit | `50b0e91ef9ecbd7448c2a4a9179b5c5f5343fae2d1cf30c516e10f45dc12a9e8` |

The first lower-bound attempt is retained as correction history. The CI
override used `--no-deps`, so downgrading from locked Pandas 3 to Pandas 2.2
omitted `pytz` and collection failed. After dependency-aware installation, 26
tests still failed because `DataFrame.fillna(value=None)` is invalid in Pandas
2.2. Removing that redundant call left one digest mismatch: DuckDB 1.0
materialized a blank CSV `work_order` as `None`, which required-text coercion
had stringified as `"None"`. Normalizing missing required text to the existing
empty-string contract restored record-instance identity and cross-engine
digest equality. No golden output or expected digest was rewritten.

Post-remediation regression evidence: the matrix/schema plus reader focus is
5/5; the locked Python 3.11 full suite collected 1,289 tests, passed 1,279 and
skipped ten live-service cases with zero failures/errors in 253.383s JUnit
(SHA-256 `f29008d3789b90bad9dbd9c4d9d5635ac75e0da28addcbce94871d6e7f789134`).
Ruff 0.16.0, Mypy 2.3.0 over 213 sources, Bandit 1.9.4, and
`git diff --check` pass; Bandit retains the three reviewed B608 notices and the
existing `.gitignore` line-ending warning remains.

Claim boundary: this is complete local execution evidence for the declared
matrix, not the backlog's required identified GitHub Actions result. P0-009
therefore remains in progress until all four hosted cells pass on an isolated,
committed revision. It does not prove Linux/Windows equivalence, arbitrary
dependency versions, performance, scale, every backend/strategy, or live
PostgreSQL recovery. No customer data, secret, release, or production system
was changed.

## E-084: Identified all-green hosted engine and platform gates

GitHub Actions run `30239994946` executed committed revision
`aaf2110c1f0d68e3253c6d9f837bc674a7d6ff9b` from Draft PR #54. The four
closed `supported-engine-parity-v1` cells all passed their exact version check
and no-skip parity command:

| Hosted job | Result |
| --- | --- |
| Python 3.11 / lower NumPy 1.26.4, Pandas 2.2.0, DuckDB 1.0.0 (`89895023766`) | Pass, 46s |
| Python 3.12 / lower NumPy 1.26.4, Pandas 2.2.0, DuckDB 1.0.0 (`89895023754`) | Pass, 53s |
| Python 3.11 / current NumPy 2.4.3, Pandas 3.0.5, DuckDB 1.5.5 (`89895023857`) | Pass, 50s |
| Python 3.12 / current NumPy 2.4.3, Pandas 3.0.5, DuckDB 1.5.5 (`89895023779`) | Pass, 45s |
| Full Python 3.11 / 3.12 (`89895023781`, `89895023745`) | Pass, 3m37s / 3m50s |
| Live PostgreSQL/Redis server boundaries (`89895023773`) | Pass, 49s |
| Docker parity (`89895562480`) | Pass, 40s |

The same revision also passed Docker build run `30239994942`, security-policy
run `30239994948` (both locked Python audits and secret/npm policy), CodeQL run
`30239994933`, and its Python analysis job. The earlier Docker uv-version and
PostgreSQL date/upsert/audit-hash failures remain visible in prior runs and
were corrected with regression coverage rather than hidden or retried.

This closes only P0-009's declared datasets/supported-version digest exit. It
does not establish arbitrary engine compatibility, Windows/Linux identity,
performance or scale, every matcher/backend, or live crash recovery. The two
uv setup annotations report mirror HTTP 403 followed by the action's normal
GitHub Releases fallback; installation and every affected job passed.

## E-085: Zero-gap npm registry integrity lock

The npm v3 lock was regenerated from the unchanged reviewed package manifest.
All 209 non-root entries retain the resolved dependency graph and now carry an
HTTPS registry location plus SRI; the policy count changes from 155 known gaps
to zero. No dependency range, application source, expected output, or audit
threshold was weakened.

| Command | Result |
| --- | --- |
| Supply-chain policy validator | Valid; 103 Python packages, 209 npm packages, zero npm integrity gaps, zero active exceptions |
| Release/SBOM/policy/readiness tests | 39 passed |
| `npm ci --ignore-scripts --no-audit --no-fund` | Pass; 158 packages installed from the committed lock |
| `npm audit --package-lock-only --audit-level=high` | Zero vulnerabilities |
| Web typecheck / unit / production build | Pass; 17 unit tests and Vite production build |

Hosted verification on committed revision
`d5433097317c77bfaae86acc654e7d10a11489b5` is all-green:

| Hosted run | Result |
| --- | --- |
| Security `30240642293` | Pass; both locked Python audits and the secret/npm policy gate |
| Docker `30240642306` | Pass; checksum-pinned container build |
| CI `30240642321` | Pass; Python 3.11/3.12, four engine cells, live server boundaries, and Docker parity |
| CodeQL `30240642386` | Pass; Python analysis |

This completes P0-SEC-008's exact lock/constraint, secret scanning, update
cadence, exception workflow, and CI-gate exit. It proves committed checksum
coverage and current advisory results, not publisher identity, package-code
safety, reachability, licensing, malware absence, registry availability, or
artifact provenance.

## E-086: Clean protected v0.7.1 pre-merge candidate

The `main` protection API requires strict up-to-date contexts
`python-security`, `CodeQL`, `test (3.12)`, and `test (3.11)`, plus resolved
conversations. Matrix display names had removed the literal
`python-security` check. Commit `2692133` adds one `always()` aggregate job
that succeeds only when both the two-cell locked Python audit and the complete
history/tree secret plus npm policy job succeed. It does not bypass, duplicate,
or mark a failed/cancelled prerequisite successful.

Existing annotated tag v0.7.0 points at an older revision and GitHub reports
it unsigned. Because the candidate workflow requires the tag to equal the
project version exactly, commit `6d33f32` advances only current candidate
metadata and links to v0.7.1, retains v0.7.0 historical documents, and adds a
conservative v0.7.1 note. Local release/readiness/SBOM/policy tests pass 39/39;
the supply-chain validator reports 103 Python packages, 209 npm packages, zero
integrity gaps, and zero active exceptions. A no-isolation build produces
`reconforge_erp-0.7.1-py3-none-any.whl` and
`reconforge_erp-0.7.1.tar.gz` with matching metadata.

| Hosted run on `6d33f3249de138acdec8c533e6d9dde8c97bd91b` | Result |
| --- | --- |
| Security `30241634766` | Pass; both locked Python audits, secret/npm gate, and protected `python-security` aggregate |
| Docker `30241634765` | Pass |
| CI `30241634773` | Pass; Python 3.11/3.12, four engine cells, live server boundary, Docker parity |
| CodeQL `30241634826` | Pass |

GitHub reports PR #54 `mergeable=true` and `mergeable_state=clean`. The PR is
currently non-draft in external state. This workstation has no configured
Git signing key or signing format, no GPG executable, and no reachable SSH
agent. No merge, key generation/enrollment, tag, tag workflow, OIDC signing,
attestation, registry push, candidate upload, GitHub Release, or package
publication occurred.

This is pre-merge readiness evidence only. P0-SEC-006/007 remain in progress
until an authorized identity merges the reviewed PR, creates a GitHub-verified
signed annotated `v0.7.1` tag on that exact `main` commit, and the retained
candidate provenance and four subject-specific SBOM bundles independently
verify.
