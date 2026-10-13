"""Native read-fixture qualification; browser/socket TLS remains separately gated."""

import psycopg
import pytest

from tests.project_source_reconciliation_browser import (
    PROJECT_SOURCE_RECONCILIATION_TAMPER,
    immutable_source_digest,
    project_source_reconciliation_restore_tamper_actor,
    seed_project_source_reconciliation_browser,
    verify_project_source_reconciliation_browser,
)
from tests.test_postgres_project_time_billing import PeopleRuntime

pytest_plugins = ("tests.test_postgres_project_time_billing",)


def test_actual_native_browser_fixture_reads_refuse_source_tamper_and_preserve_originals(billing: PeopleRuntime):
    base = seed_project_source_reconciliation_browser(billing.base.admin_dsn, billing.base.factory.settings.dsn)
    before = verify_project_source_reconciliation_browser(base)
    assert before["browser_financial_writes"] is False and before["native_effect_count"] == 6
    expected_constraints = ("people_payroll_owner", "project_billing_owner", "project_billing_owner")
    with project_source_reconciliation_restore_tamper_actor(base) as (connection, _, _):
        for statement, name in zip(PROJECT_SOURCE_RECONCILIATION_TAMPER, expected_constraints, strict=True):
            with pytest.raises(psycopg.errors.CheckViolation) as refused, connection.transaction():
                connection.execute(statement, (base.tenant,))
            assert refused.value.diag.constraint_name == name
    after = verify_project_source_reconciliation_browser(base)
    assert before == after
    assert before["original_evidence"]["report"] == after["original_evidence"]["report"]
    assert immutable_source_digest(before["original_evidence"]) == immutable_source_digest(after["original_evidence"])
