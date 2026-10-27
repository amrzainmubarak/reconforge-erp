"""Independent empty policy roundtrip and populated leave scope retention."""
import os

import pytest

from reconforge.domain.hcm_leave import LeaveEntitlementBalance
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_hcm_leave import PostgresHCMLeaveRepository
from tests.test_postgres_enterprise_migrations import migrate
from tests.test_postgres_people_project_payroll import people, personnel_database, receipt_database  # noqa: F401
from tests.test_release_authorization_postgres import leave_runtime  # noqa: F401

pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"),
    reason="Owned native PostgreSQL required for HCM policy migration; review2026-10-26",
)


def test_hcm_entity_policy_roundtrip_retains_populated_records_and_denies_missing_scope(leave_runtime) -> None:  # noqa: F811
    import psycopg

    runtime, employees = leave_runtime
    dsn = runtime.base.admin_dsn
    empty = migrate(dsn, "downgrade", "0155_pg_crm_authority")
    assert empty.returncode == 0, empty.stderr
    upgraded = migrate(dsn, "upgrade", "0156_pg_hcm_leave_entity")
    assert upgraded.returncode == 0, upgraded.stderr
    with runtime.actor("maker") as (connection, _people, _actor):
        repository = PostgresHCMLeaveRepository(connection, runtime.base.tenant)
        repository.save_balance("work", LeaveEntitlementBalance(employees["alice"], "Annual", 30, 20, 0))
        assert repository.get_balance("work", employees["alice"], "Annual") is not None
    with psycopg.connect(dsn) as connection:
        before = connection.execute(
            "SELECT to_jsonb(t)::text FROM reconforge.hcm_leave_entitlement_balances t ORDER BY to_jsonb(t)::text",
        ).fetchall()
        assert before
    refused = migrate(dsn, "downgrade", "0155_pg_crm_authority")
    assert refused.returncode != 0
    assert "Populated leave records prevent scope downgrade" in refused.stderr
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0156_pg_hcm_leave_entity",)
        assert connection.execute(
            "SELECT to_jsonb(t)::text FROM reconforge.hcm_leave_entitlement_balances t ORDER BY to_jsonb(t)::text",
        ).fetchall() == before
    with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant, workspace_id="work") as connection:
        assert connection.execute("SELECT employee_id FROM reconforge.hcm_leave_entitlement_balances").fetchall() == []
