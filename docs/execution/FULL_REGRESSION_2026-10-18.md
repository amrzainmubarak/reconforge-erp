# Full regression follow-up — 2026-10-18

Status: in progress. Work is exclusively in `F:\reconforge-erp`, on
`amr/full-regression-20261018`, without new worktrees. Financial arithmetic and
migrations remain identical to the consolidated `bfc138a1` source. API scope
audit and monetary UI corrections are under verification.

## Completed initial run and remaining integration failures

The unfiltered Windows run completed in 2039.88 pytest seconds (2045.400 wall
seconds): 9652 passed, 886 skipped, 3 failed and 555 setup errors. Every one of
the 558 negative outcomes is the same missing
`RECONFORGE_TEST_POSTGRES_ADMIN_DSN` prerequisite. All affected files belong to
the existing 97-file mandatory-native CI selection. The remaining generic
profile accounts for 9577 passes and 665 existing prerequisite skips.

Draft PR141, Actions run39089488421, tests head `0d74989b` through merge
`f071c836`; their Git trees both equal
`667a86071b1698bf883fa727f34b0dd737e988c0`. Both Python profiles pass9581 cases
with663 existing prerequisite skips. Python3.11 takes858.68s; Python3.12
takes1131.74s. Security, Docker and CodeQL pass. Three actual integration gates
remain negative: restituted Return POST exceeds the unchanged15s bound;
foreign monetary valuation has428px page overflow at320px; identity monetary
browser and347-table restore pass before independent original verification
refuses. Their original job logs and hash-verified artifacts are retained.

The responsive correction constrains monetary grid children, form controls,
long identifiers and evidence to their container while keeping table scrolling
and all values visible. The existing actual foreign-cycle viewport/RTL/axe
assertions remain unchanged.28 monetary component tests, typecheck and build
pass; the actual corrected cycle is still pending. A closed diagnostic adds
only a reader stage and source line on refusal.45 reader/CI-contract tests pass,
including private-value non-disclosure tests. No financial guard, timeout,
reader budget, retry or skip policy is relaxed. Backend operation profiling and
complete successor-source integration acceptance remain required.

## Full-run provenance

The initial unfiltered command selects 11,096 cases using Python 3.12.13 and
pytest 9.1.1 from `.venv-amr-sprint`:

```powershell
.venv-amr-sprint\Scripts\python.exe -u -m pytest -o addopts=--capture=sys -v --durations=30 -ra --junitxml=output/full-regression-20261018T014707Z/pytest.xml
```

Evidence directory: `F:\reconforge-erp\output\full-regression-20261018T014707Z`.
It contains the initial source/environment, full log, progress and eventual XML
and terminal-result JSON. Missing native fixture configuration is retained as
negative evidence, not reclassified as success. The 439.729-second interrupted
run from the consolidation remains historical; this is a new complete run.

## Reproduced defects and repairs

| Defect | Repair | Verification |
| --- | --- | --- |
| Local TLS CLI test inherited `RECONFORGE_POSTGRES_DSN`, selecting the server profile without tenant storage | Explicitly isolate its local-profile environment | Original failure retained; repaired case passes in the same configured environment |
| Legacy AR test's no-monetary-grant assertion inherited a preceding test's grants | Fresh least-privilege login for that test, removed on teardown | Actual native AR lifecycle passes while the previously shared role still has its old grants |
| Service-account test cleanup failed on audit foreign keys and used fixed tenant IDs | Unique tenants; declared child-first audit/service cleanup through existing scoped helper | Actual native service credential/auth/revocation/cleanup case passes |
| Live service-account test expected a local workflow backend in the server profile | Assert ADR0637's existing explicit 501 refusal, matching its non-live counterpart | Actual native case passes without changing product route behavior |

`native-api-repaired-final.xml`: 2 passed, zero skips, 17.124 wall seconds.
`repaired-api-and-cleanup.xml`: 36 passed, 3 live cases deliberately deselected,
29.391 wall seconds; live outcomes are separately retained. `tls-repaired.xml`:
1 passed, zero skips, 7.892 wall seconds. Existing cleanup scope/rollback tests
now exercise both payables and service-account plans. Ruff and Mypy pass;
Mypy covers 828 application files. `pip check` reports no broken requirements.

## Native verification and limits

The repository's general CI pytest command separates 97 mandatory native files
into dedicated server-boundary jobs. Their actual selection is captured in
`ci-generic-selection.json`. Local native checks use an empty freshly migrated
PostgreSQL 16.15 template and a separate synthetic database for each file,
with the unchanged `tests.mandatory_native_gate` plugin rejecting skips,
xfails and empty collection. Per-file commands, source, XML, logs and exit
codes are retained under `mandatory-native/`. The fixed image is the same
digest declared in the server-boundary CI job. No existing PostgreSQL container
or customer database is modified by the local harness.

A secondary all-in-one PostgreSQL diagnostic exposed the fixture defects above
and was replaced by isolated native execution. Its interrupted result is
explicitly retained under `postgres-enabled/`; it is not full acceptance.
The unfiltered original run completed; its terminal result and fixture-only
negative-outcome classification are retained above.
Final native/full/CI results are pending; prior M7 HTTPS/restore and release
acceptance limits remain unchanged. ADR0864 records the test-only decision.

## Read admission follow-up

Three deferred-response component regressions reproduce mutation admission
while a selected plan or source balance is still loading. The partial-return
components now gate both controls and command dispatch until current reads
finish. Typed command responses update the selected plan and catalog entry
without redundant full catalog reloads; explicit refresh and fresh balance
reads remain. The original red result is `read-admission-red.log`; complete web
and actual browser verification follow. The instrumented local monetary post
takes9.89s, including7.485s deferred constraints. Database guards and15s browser
limits are unchanged; avoiding overlapping reads is not yet full acceptance.

The fixed UI passes1109 tests in129.43s, typecheck and build. Its actual owned
identity browser completes1/0skip in485.99s; the whole623.234s gate still refuses
the missing audited scope-denial witness. The retained input remains unchanged.
Direct diagnostic qualification of its raw cycle succeeds (12 effects,28 lines);
adding observations refuses at reader1422. The actual403 observation has
`entity_scope_denied`, but its audit suffix contains only allowed decisions.
ADR0865 fixes the route's early unaudited hierarchy refusal without weakening
the reader. Native workspace/organization/entity regressions first fail3/0skip
in133.86s because zero persisted policy rows exist. Their corrected run and
final-source complete browser/restore proof remain required.

The corrected actual ordinary-role cases pass3/0skip (154.687s wall), including
one persisted bound denial per request, verified audit chains and unchanged
business digests.113 related execution-scope, monetary transport and route
authorization checks pass. Ruff, Mypy and web typecheck pass after the change.

Ruff, Mypy (828 files), Bandit, pip-audit, pip-check and package build pass.
CLI doctor, sample validation and demo pass through the declared executable
entrypoint. An initial unsupported `python -m reconforge` invocation is retained
as a command error, not a product failure. General browser checks with actual
local HTTPS pass20 cases, zero failures, and8 existing fixture-dependent skips
owned by the dedicated CI jobs (77.50s test,79.103s wall). The ab789 foreign
browser reduces overflow to18px but remains negative; structural-only dimensions
will identify the remaining element without publishing field values.

Actual04af foreign diagnostics reproduce10px overflow on Windows (same mandatory
320px zero-overflow predicate): the surrounding stock form's paragraph reaches
330px and fieldset328px. Its intrinsic grid/control widths, rather than monetary
values, exceed available width. The scoped stock CSS now bounds those minima
and inline margins and wraps controls; production build passes. Complete foreign
acceptance on the corrected build remains required. All negative captures,
source bindings and owned-container cleanup are retained.
