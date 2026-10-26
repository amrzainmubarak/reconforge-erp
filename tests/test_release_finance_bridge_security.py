"""Independent restricted-role hostile writes against the source-owned ledger.

The real PostgreSQL fixture applies the official migration chain. No mocks or
direct inserts are used to create the financial source or its canonical entry.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from tests.test_postgres_enterprise_finance_bridge import BridgeRuntime, prepare, source

pytest_plugins = ("tests.test_postgres_enterprise_finance_bridge",)
pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"),
    reason="BC-GL-SEC-01 requires owned native PostgreSQL; review2026-10-25",
)


def test_prepared_ledger_rejects_direct_line_and_dimension_writes(bridge_runtime: BridgeRuntime) -> None:
    runtime = bridge_runtime
    plan = prepare(runtime, "ProjectMilestone", source(runtime, "ProjectMilestone"))
    with runtime.actor("maker", private=False) as (connection, _, _actor):
        role = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=session_user").fetchone()
        assert role[0] is False and role[1] is False
        before_rows = connection.execute(
            "SELECT id,account_id,debit_minor,credit_minor,currency_code FROM reconforge.finance_entry_lines "
            "WHERE tenant_id=%s AND entry_id=%s ORDER BY line_number",
            (runtime.base.tenant, plan["entry_id"]),
        ).fetchall()
        before = [tuple(row[index] for index in range(5)) for row in before_rows]
        assert len(before) == 2
        tenant, entry, line = runtime.base.tenant, plan["entry_id"], before[0][0]
        attacks = [
            ("UPDATE reconforge.finance_entry_lines SET description='hostile' WHERE tenant_id=%s AND id=%s", (tenant, line)),
            ("DELETE FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND id=%s", (tenant, line)),
            ("INSERT INTO reconforge.finance_entry_lines "
             "(tenant_id,id,entry_id,line_number,account_id,debit_minor,credit_minor,currency_code) "
             "VALUES(%s,'hostile-line',%s,99,%s,1,0,%s)", (tenant, entry, before[0][1], before[0][4])),
            ("INSERT INTO reconforge.finance_entry_line_dimensions "
             "(tenant_id,entry_line_id,dimension_id,dimension_value_id) VALUES(%s,%s,'hostile','hostile')", (tenant, line)),
        ]
        for statement, values in attacks:
            with pytest.raises(psycopg.errors.CheckViolation, match="Prepared source ledger is immutable"), connection.transaction():
                connection.execute(statement, values)
        # A visible GUC is not enough to alter monetary contents of a sealed entry.
        connection.execute("SELECT set_config('app.enterprise_finance_binding',%s,true)", (plan["binding_id"],))
        with pytest.raises(psycopg.errors.CheckViolation, match="Original source ledger values"), connection.transaction():
            connection.execute("UPDATE reconforge.finance_entries SET description='hostile' WHERE tenant_id=%s AND id=%s", (tenant, entry))
        after_rows = connection.execute(
            "SELECT id,account_id,debit_minor,credit_minor,currency_code FROM reconforge.finance_entry_lines "
            "WHERE tenant_id=%s AND entry_id=%s ORDER BY line_number", (tenant, entry),
        ).fetchall()
        after = [tuple(row[index] for index in range(5)) for row in after_rows]
        assert after == before
        assert sum(row[2] for row in after) == sum(row[3] for row in after) == 3001
        assert connection.execute(
            "SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s AND entry_id=%s", (tenant, entry),
        ).fetchone()[0] == 0
