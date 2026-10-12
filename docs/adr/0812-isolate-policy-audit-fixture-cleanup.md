# 0812: Preserve policy-audit isolation in the remaining live CI fixtures

Status: accepted for the bounded fixture contract, 2026-10-03.

The actual remaining server selection reproduced nine failures in40 tests:
seven HTTP fixtures tried deleting their synthetic tenants while immutable
policy-audit rows still referenced them, and two inventory fixtures omitted
known canonical workspace attribution when creating their organization/period.

The seven fixtures explicitly grant required audit writes to their nonowner
runtime role and use one test-only cleanup helper. The helper joins the existing
administrative transaction, disables only the audit immutability trigger,
deletes only the fixture's tenant IDs, and restores/verifies that trigger before
returning. A failing transaction rolls back the DDL as well as the rows. The
ordinary application role receives no delete or trigger authority. Synthetic
inventory organizations/periods receive their known workspace at creation;
existing production rows are not backfilled.

The selected40 tests then passed with zero skips in39.98s. The discarded helper
import attempt failed during collection and remains retained. The final import
uses the existing `tests` package. The owned database and Redis container were
removed. `REMAINING_CI_FIXTURES_2026-10-03.json` binds the source files, commands,
before/after reports and logs. This does not substitute for the whole remote CI
job.

Two remote secret-scan findings were verified against Git source: they are
SHA256 digests of Python files recorded in earlier evidence. Only exact
commit/path/rule/line and current-tree fingerprints are allowed; scanning remains
enabled across the repository and history.

The Docker parity build separately rejected an upstream APK checksum mismatch.
Direct official downloads matched the original pins, both packages verified with
Alpine's trusted keys, and rerunning the same job/head succeeded. No checksum
was weakened or replaced. The delivery cause remains unestablished.

Rollback removes these fixture changes and precise false-positive dispositions;
it changes no production API, financial rows, security policy or image pin.
