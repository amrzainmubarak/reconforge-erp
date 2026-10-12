# Production objective audit — 2026-10-03

Baseline source: `1551e8ae69a2982961a315c40be1c4ac2b8c8bc5`.
Implementation branch: `codex/production-foundation-audit`.
Existing unrelated untracked files were preserved. `main` was fast-forwarded to
the fetched `origin/main` reference without resetting the active checkout or its
185 local commits. The new upstream commit is a merge with no new content
relative to this baseline; this report does not assert hosted CI of local work.

## Baseline environment and results

Windows 11 build 26200; fresh locked all-extras environment, Python 3.12.13,
uv 0.11.32; Node 26.3.0, npm 11.16.0, Docker Engine 29.8.1. The ambient Python
3.14.6 was not used for the main regression: supported policy versions are
3.11/3.12. Raw logs and command timing JSON are in
`output/baseline-2026-10-03/`. The retained machine-readable snapshot is
`BASELINE_2026-10-03.json`, with raw-log hashes.

| Command/gate | Baseline observation | Seconds |
| --- | --- | ---: |
| `python -m ruff check .` | passed | 0.209 |
| `python -m mypy reconforge` | passed | 1.549 |
| `python -m pytest -ra --tb=short` | 3366 passed, 124 skipped, 23 warnings in 817.57s (0:13:37) | 822.764 |
| `python -m bandit -q -r reconforge` | passed | 18.281 |
| `python -m pip_audit` | failed: 11 reported advisories, 7 distinct IDs, in urllib3 and virtualenv; local unpublished package not audited by PyPI | 35.690 |
| `python -m build --no-isolation` | passed, wheel and sdist | 33.973 |
| `git diff --check` | passed at baseline | 0.038 |
| `npm --prefix apps/web ci` | passed; installation reported vulnerabilities | 11.549 |
| `npm --prefix apps/web run typecheck` | passed | 1.637 |
| `npm --prefix apps/web run test:run` | 77 passed, 15 files | 10.850 |
| `npm --prefix apps/web run build` | passed | 1.821 |
| `npm --prefix apps/web run e2e` | 16 passed, 5 declared capability skips | 53.557 |
| opt-in real HTTPS production-bundle E2E | 1 passed | 8.992 |
| opt-in real PostgreSQL browser administration E2E | 4 passed after fixture supplementation described below | 18.521 |
| `npm --prefix apps/web audit --json` | failed: 2 moderate / 1 high development dependency packages | 3.704 |
| `npm --prefix apps/web audit --omit=dev --json` | passed: zero production dependency findings | 1.331 |
| `reconforge doctor` | passed | 7.301 |
| `reconforge validate examples/sample_data` | passed; synthetic warnings retained | 3.536 |
| `reconforge demo run --output output/baseline-2026-10-03/demo` | passed | 11.897 |
| `docker build -t reconforge:baseline-20261003 .` | passed | 11.327 |
| `docker run --rm reconforge:baseline-20261003 reconforge doctor` | passed | 13.749 |
| Clean PostgreSQL Alembic upgrade to head | passed: `0092_pg_close_lock_evidence` | see snapshot |
| Live PostgreSQL foundation, migrations, Finance Core, AP/AR and AP/AR HTTP selection | 70 passed, zero skipped | 18.80 pytest runtime |

The four browser administration mutation scenarios were separately provisioned
in an isolated synthetic PostgreSQL database and passed. Fresh Alembic head did
not create `metric_definitions` or `metric_snapshots`: provisioning failed with
UndefinedTable. The existing additive metrics installer supplemented this test
database so the browser checks could proceed; this workaround does not close the
production migration gap. HTTPS was separately opted in and verified.
No hosted, production, independent security, company or reviewer outcome follows
from these local results.

## Inventory and inspection coverage

Tracked inventory at the baseline: 540 Python runtime files, 474 Python test
files, 92 PostgreSQL revisions, 46 SQLite migrations, 121 JSON schemas,
781 ADR files, seven tracked CI workflows, and 24 control-pack directories.
An existing eighth untracked workflow is user-owned and excluded from that count.

Inspection covered README/build/dependency configuration, application/domain/
infrastructure modules, platform, reconciliation, rules, evidence, identity,
authorization, audit, workflow, API, both Studios, database migrations, contracts,
test/CI surfaces, container configuration and architecture/security/execution
documentation. Migration AST/history checks establish a single linear PostgreSQL
head and upgrade/downgrade definitions; they do not establish every downgrade is
safe for populated data. Focused live tests separately exercise migration paths.

The disposable PostgreSQL 16 fixture has 167 application tables: all 167 enable
and force RLS. Its application role has `rolsuper=false`, `rolbypassrls=false`.
Catalog coverage is structural evidence, not proof of every authorization policy.

## Five leading risk groups

| Priority | Finding | Code/test evidence | Required change |
| --- | --- | --- | --- |
| P0 | Historical monetary interpretation can change when currency precision is edited | `sqlite_master_data.py` currency upsert permits minor-unit changes; Finance Core trial balance reads current registry; public-service reproduction changes EGP 100.00 to 10.000 | Bind/freeze referenced currency precision and rounding; snapshot/replay and multi-currency tests before GL expansion |
| P0 | AP liability and quantity invariants are incomplete | Two separate invoices can both match/approve against one received quantity; `_decimal_text(...normalize())` rounds using ambient context; concurrent PG receipt sums are unlocked | Exact quantities and aggregate approved consumption under a transaction lock; duplicate-line, partial, concurrent and rollback tests |
| P0 | Runtime isolation still depends on an operator choosing a safe database role | `infrastructure/postgres.py` documents but does not enforce no SUPERUSER/BYPASSRLS; health validates schema only | Dedicated runtime role gate on pooled checkout, separate migration administration, fail-closed readiness and adversarial tests |
| P0 | Intended live CI coverage is silently filtered out | Actual collection selects 4/384 tests and deselects 380; proposed general selection collects 370 tests in 50 modules | Separate parity and benchmark commands; verify actual selected nodes, not filename presence |
| P0 | New security disclosures invalidate old clean dependency claims | Fresh Python and npm audit logs | Review upstream fixes, update only affected lock entries, retain baseline failure and post-fix evidence |

Additional confirmed gaps:

- AR approval does not recheck customer Active status; updating customer currency
  can relabel exposure while existing invoices retain another currency.
- Live React metrics requests omit `X-ReconForge-Tenant`, which server identity
  requires. Admin authentication/tenant state is isolated in another component.
- Expired step-up errors do not restore the admin reauthentication form.
- Generic exception/workflow HTTP routes intentionally return 501 in PostgreSQL
  mode. Keep that rejection until workspace/entity scope is supported end to end.
- AP/AR do not post an integrated stock/subledger/GL cycle. Finance Core is a
  control ledger; its current validated/void behavior is not a complete immutable
  operational GL.
- React financial pages use synthetic contracts; administration has real writes.
  Rule Studio approval is local state with a typed reviewer name, not persisted
  server-enforced financial approval.
- A fresh Alembic database lacks metrics tables. Direct schema installation in
  test fixtures masked this production boot gap; add a versioned migration and
  compute/read test that runs only the production migration path.

## Claims and documentation drift

| Claim | Code evidence | Test evidence | Runtime evidence | Maturity | Allowed wording |
| --- | --- | --- | --- | --- | --- |
| PostgreSQL adapters | `infrastructure/postgres_*.py`, application ports | foundation/parity/API tests | this baseline: 70 focused passes, clean head migration | experimental | Selected PostgreSQL workflows verified on one disposable host |
| Hard isolation everywhere | transaction-local scope + forced RLS | selected cross-tenant tests; CI coverage defect | structural 167/167 coverage only | incomplete | Forced-RLS foundation; runtime-role and complete workflow gates open |
| Full GL | finance_core and ledger modules | balanced-entry/TB/reversal-control tests | selected control-ledger runtime only | foundation | Balanced finance-control ledger; integrated operational posting planned |
| Full purchase/sales cycles | AP/AR/inventory modules | separate module suites | financial invariant defects reproduced | planned integration | Bounded AP/AR/inventory foundations |
| React writes | admin mutation APIs/components | 77 component tests, standard browser checks | real HTTPS hosting; 4 live PostgreSQL admin browser tests after manual metrics-schema supplementation | experimental | Administrative writes verified in a synthetic fixture; clean bootstrap and financial journeys incomplete |
| Five million customer transactions and 30 reconciliations | no qualifying company artifact found | no customer acceptance evidence | none | planned | Proposed acceptance workload; no customer capacity/ROI claim |

Public README currently calls all modern Studio mutation workflows future work
and lists 19 packs. Current code has real admin writes and 24 pack directories.
`docs/payables.md` and `docs/receivables.md` still exclude PostgreSQL despite
implemented adapters and live HTTP tests. `POSTGRES_PARITY_INVENTORY.yaml` records
source head 0089 and historical broad evidence under `current_live_gate`; source
head is 0092. Preserve historical results with their dates while making current
boundaries explicit. Old zero-advisory statements are historical snapshots.

## Performance and company evidence

Historical checked-in synthetic reports include one million grouped input records
in 250,000 small partitions (617.0014 seconds, 77.5685 MiB traced memory), and one
million durable-job effects in 2,500 jobs (1932.3678 seconds). Neither report is a
five-million-transaction company deployment, total process RSS measurement, or
external-auditor acceptance. These workloads were not rerun for this baseline.
The current date's command times are diagnostics under concurrent audit activity,
not a throughput benchmark. See the [production roadmap](PRODUCTION_ROADMAP_2026-10-03.md)
for workload definitions, pilot metrics, dependencies and exit gates.

## Execution status

PROD-001 baseline collection is complete and the command snapshot is retained.
Dependency audits failed and the reproduced domain defects remain open; completion
of this audit does not mean the product gates are green. Runtime feature edits
had not started when this baseline was recorded. The first
implementation slices are exact/cumulative AP invariants, the PostgreSQL CI gate,
dependency remediation, and shared React session/scope. Remaining work is tracked
in `BACKLOG.yaml`; no goal-completion or production-readiness claim is made.
