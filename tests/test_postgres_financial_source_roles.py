"""Mandatory native Core metadata privileges without private operating access."""

import os
from typing import Any

import psycopg

from tests.test_postgres_finance_posting import finance_database, isolated_postgres_migration_dsn, posting_database

__all__ = ["finance_database", "isolated_postgres_migration_dsn", "posting_database"]


def test_current_core_directory_fixture_privileges_preserve_operating_owner_privacy(posting_database: dict[str, Any]) -> None:
    role = psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_DSN"])["user"]
    with psycopg.connect(posting_database["admin"]) as admin:
        for table, expected in (
            ("financial_effect_claim_gates", (True, True, True, False)),
            ("financial_effect_ownership_guards", (True, False, False, False)),
            ("financial_effect_ownership_releases", (True, False, False, False)),
            ("manufacturing_execution_v2_orders", (False, False, False, False)),
            ("hc_payrun_private", (False, False, False, False)),
            ("hc_employee_private", (False, False, False, False)),
        ):
            assert tuple(admin.execute(
                "SELECT has_table_privilege(%s,%s,'SELECT'),has_table_privilege(%s,%s,'INSERT'),"
                "has_table_privilege(%s,%s,'UPDATE'),has_table_privilege(%s,%s,'DELETE')",
                (role, "reconforge." + table) * 4,
            ).fetchone()) == expected
