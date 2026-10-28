# Source-bound baseline refresh — 2026-10-28

Entry: `b1ae1b5e7aad0cc9893bfda65ff44b422aaa279b`, branch
`amr/assurance-prerequisite-repair-20261025`. On entry the untracked `.serena/`,
`node_modules/`, `ERP_WORLD_CLASS_EXECUTION_MASTER_PROMPT_AR.md` and
`INDEPENDENT_COMPETITIVE_REVIEW_AND_AGENT_PROMPT_2026-10-28.md` were preserved.
Working branch: `amr/erp-vision-safety-baseline-20261028`. This is a partial
baseline, not a clean release qualification. Existing evidence and recovery
files remain in place. Output and ignored build metadata can be affected by
the tools themselves; `build` regenerated ignored egg-info.

Environment: Windows, Python 3.14.6, Node 26.3.0, npm 11.16.0, Docker CLI
29.9.2. CI specifies Python 3.11/3.12 and Node 22; local results do not replace
those environments. Entry tracked inventory: 901 files under `reconforge/`,
990 under `tests/`, 156 under `alembic/versions/`, 441 under `apps/web/`, and
10 workflow files. Counts include non-Python files and are not test counts.
The architecture includes domain, application, infrastructure, API, worker,
connector, auth, rules, evidence, DB and Studio areas. Existing detailed
inventory and migration evidence remain historical snapshots, not exhaustive
fresh validation of all 156 revisions or generated contracts.

| Command | Observed result | Duration / limitation |
| --- | --- | --- |
| `python -m ruff check . --no-cache` | pass | 2.10 s; no cache variant |
| `python -m mypy reconforge` | pass, 900 source files | 2.61 s |
| `python -m bandit -q -r reconforge` | exit 0; nosec parsing warnings | Static scan only |
| `git diff --check` | pass | 2.06 s at entry; untracked files excluded |
| `npm --prefix apps/web run typecheck` | pass | 8.38 s |
| `npm --prefix apps/web run test:run` | fail: 110 suites failed before collection with temporary `client` path ENOENT; 8 suites / 118 tests passed | 90.67 s; 110 suites' behavior unknown |
| `python -m build --no-isolation` | fail: missing `setuptools>=84.1.0`; installed 83.0.0 | 6.00 s; retry in a separately prepared locked build environment |
| `python -m pip_audit` | incomplete: HTTPS read timeout reaching PyPI | No vulnerability-free conclusion; retry with accessible index |
| `reconforge doctor` | pass | Local environment only |
| `reconforge validate examples/sample_data` | pass, 0 errors and 10 warnings | Synthetic sample only |
| `python -m pytest` | interrupted at 4% after about 3m18s | Source changed during execution; no full-suite result established; services required by skipped tests remain separate |
| `npm --prefix apps/web ci` | not run | Existing dependencies preserved; run in an isolated prepared environment |
| Web build, E2E; CLI demo; Docker build/run | not yet run | Run in a safe isolated output location and supported runtime; do not infer success |
| Real PostgreSQL migration/restore and restricted-role probe | not run locally | Test DSN and owned service required; do not use unrelated existing containers |

Hosted [draft PR 143](https://github.com/amrzainmubarak/reconforge-erp/pull/143)
reported successful Python 3.11/3.12, web, native shards, Docker and CodeQL
checks on exactly the entry SHA when queried on 2026-10-28; some checks were
skipped, including the exact-image SBOM/vulnerability/license gate. These
results do not apply to a changed source tree or prove release acceptance.

The current NCR repository and RLS are workspace-scoped and unchanged since the
historical cross-entity PostgreSQL probe at `b8374025`; that probe was not rerun
on this HEAD. Existing five-cycle evidence is partial. No current benchmark,
external review, legal claim, or production approval is inferred.

Command output was observed in tool sessions, not retained as raw log files;
durations above are measured where available and estimated where explicitly
stated. Bandit, audit, doctor and validate each took over 10 seconds; more
precise timing was not captured. The initially attempted mypy variant using
`--cache-dir NUL` failed internally; the unmodified command then passed.

An adapter-level synthetic EUR/USD FX scenario gave `Matched` after rounding
both conversions to USD 0.10 although exact converted inputs differ by 0.001
USD. Whether that is an acceptable business decision depends on the explicit
rounding policy, which v1 does not bind for replay. The local draft guard
refused FX and passed 31 focused cases, but an existing domain-diverse scale
test failed because it expects FX success; four native scale cases were skipped
without PostgreSQL. Independent review identified the compatibility break,
unverified legacy checkpoints and direct strategy entry points. The draft patch
and tests are retained under `output/erp-vision-20261028/` and are not applied
to runtime source. Resolve the versioned policy and migration before integration.
After removing that draft, the original source's grouped scale, worker
conservation and adapter tests returned 36 passed and 4 PostgreSQL prerequisite
skips (`python -m pytest -o addopts='' tests/test_postgres_grouped_matching_scale.py
tests/test_grouped_worker_conservation_20261027.py tests/test_postgres_grouped_matching.py -q`,
1.00 s reported by pytest). This confirms neither FX correctness nor native
worker recovery. Ruff passed again on the restored runtime source.

Reproduce the adapter observation from the repository root (synthetic data):

```python
from decimal import Decimal
from fractions import Fraction
from reconforge.workers.postgres_grouped_matching import PostgresGroupedMatchingAdapter
from reconforge.workers.postgres_reconciliation import ReconciliationExecutionContext

def record(identity, amount):
    return {"source_id": identity, "amount_decimal": Decimal(amount),
            "attributes_json": {"date": "2026-08-06", "currency": "EUR"}}

context = ReconciliationExecutionContext(
    run={"rule_json": {"grouped_matching_mode": "portfolio", "date_window_days": 0,
        "amount_tolerance": "0", "target_currency": "USD", "fx_rates": [{
            "base_currency": "EUR", "quote_currency": "USD", "rate": "0.1",
            "rate_type": "spot", "source": "synthetic", "effective_at": "2026-08-01"}]}},
    left_inputs=(record("L", "1.00"),), right_inputs=(record("R", "1.01"),),
    heartbeat=lambda _: {}, cancellation_requested=lambda: False)
print(PostgresGroupedMatchingAdapter()(context).results)
print("unrounded difference:", (Fraction("1.01") - Fraction("1.00")) * Fraction("0.1"))
```

This illustrates the effect of conversion rounding, not a claim that unrounded
comparison is automatically the correct business policy for every FX workflow.

## Continuation observations

On the later worktree based on `dfc9ad97`, a task-owned synthetic demo output
completed in 7.57 s with Python 3.14.6. Python 3.12.13 and setuptools 84.1.0
were already available in a retained environment; `python -m build
--no-isolation --outdir output/erp-vision-20261028/package-312` passed in
49.15 s. The build backend regenerated ignored egg-info and removed the
`build/bdist.win-amd64/wheel` intermediate; its prior contents were not
captured. The selected package output directory was new.

The local Docker build with tag `reconforge:baseline-erp-20261028-dfc9ad97`
completed in 617.48 s, followed by `docker run --rm --network none ...
reconforge doctor` in 11.79 s with 0 validation errors and 10 warnings. The
build context had the `dfc9ad97` runtime and an uncommitted msgpack lock update;
it is not a build of the later financial/quality changes or a release artifact.
The local build and doctor logs are retained in `output/erp-vision-20261028/`.
A separate local 3.11 install stalled during network download and was
interrupted; hosted 3.11 audit success on `35edcd2f` is a separate result.

Hosted `test (3.12)` on `c44a7111` completed with 10,325 passed, 665 skipped
and one failure: `test_backlog_dependencies_are_closed_and_phase_ordered`
raised `KeyError: depends_on` on tasks added in this continuation. The missing
fields are corrected in the successor; the unchanged contract test subsequently
passed locally on Python 3.12 (5 passed, 2.28 s). The hosted failure and missing
publication artifact remain historical evidence; rerun the complete hosted
suite on the successor rather than treating the focused test as a replacement.

The complete local `python -m pytest` run on `24d8862e` (Windows, Python
3.12.13, new task-owned temp/base directories) exited 1 after 1,470.13 s of
pytest time: 10,427 passed, 930 skipped, 4 failed, 567 errors, 26 warnings.
All 567 errors and three migration-test failures trace to the unset
`RECONFORGE_TEST_POSTGRES_ADMIN_DSN` in the native fixture; they are not
PostgreSQL test successes or evidence of product failure. The fourth failure,
`test_targeted_grouped_matching_source_mutations_are_killed`, reported three
surviving mutants and needs separate investigation. The raw log SHA-256 is
`fddaf78645517f6f251ecd208a561974e5ead1331b66f9fd3f2ab0946f66043c` at
`output/erp-vision-20261028/pytest-full-24d8862e.log`. Hosted tests use separately
configured services and shards; neither result substitutes for the other.

Follow-up on the mutation failure: pytest inherited an ancestor configuration
when its temporary child was created inside this checkout, placing the original
package before the isolated mutated package on the import path. The repaired
campaign uses an isolated configuration, verifies the imported file and the
baseline, and accepts only the expected assertion failures for each mutation.
At parent HEAD `24d8862e` with the changed files identified below, Windows
Python 3.12.13 and pytest 9.1.1 ran six focused cases in 11.08 s, exit 0,
including inherited configuration and injected RuntimeError cases; log
`output/erp-vision-20261028/mutation-focused-20261028.log` SHA-256
`45bfa02eb2bcc205181c91eac5bc5d585a911d72bcfda4459f29db25af6b48c9`.
The campaign alone also killed 3/3 targeted mutations with pytest 8.2.2 in an
isolated Python 3.12 environment (3.60 s), with `TEMP` inside this checkout.
The source and test SHA-256 at the focused run were respectively
`3839df72c6f6c60fa0ba23bd05fd0644c9085b9f3545a82131479e33013c3496` and
`2b9c2af37677eaaf8af2ab3feec4bf7adf34c62429f7369fd7ab9eac3df591ed`.
This is a narrow test
infrastructure repair, not a full-suite rerun or proof of production matching.

The hosted PR check rollup for exact head `24d8862eb172eb7621a6749af1ea48efe163b727`
completed with 89 successful checks and three skipped checks. The skipped checks
were two branch-name gates and the exact-image SBOM/vulnerability/license gate;
the latter is configured for scheduled or manual events, not this PR event.
The rollup snapshot is `output/erp-vision-20261028/hosted-checks-24d8862e.json`,
SHA-256 `9b80844dd49a92d8bf5469eceeab883200347bceaf8062a99ddd5c9e046e6b3b`.
It does not certify the successor commit, a release artifact, or the skipped gate.
