# Full regression follow-up — 2026-10-18

Status: in progress. Work is exclusively in `F:\reconforge-erp`, on
`amr/full-regression-20261018`, without new worktrees. Application source and
financial migrations remain identical to the consolidated `bfc138a1` source.

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
The unfiltered original run continues independently to its terminal outcome.
Final native/full/CI results are pending; prior M7 HTTPS/restore and release
acceptance limits remain unchanged. ADR0864 records the test-only decision.
