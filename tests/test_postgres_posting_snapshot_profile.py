"""Native snapshot parity at 1,000 lines; no financial or RLS shortcut."""
from typing import Any

from reconforge.benchmark.enterprise_financial import MeasuredConnection
from reconforge.domain.finance_posting import make_entry_snapshot, validation_digest
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot, records
from reconforge.platform.common import server_principal_context
from tests.test_postgres_finance_posting import (
    MAKER,
    SCOPE,
    finance_database,
    isolated_postgres_migration_dsn,
    posting_database,
    principal,
)

__all__ = ["finance_database", "isolated_postgres_migration_dsn", "posting_database"]


def test_thousand_line_snapshot_matches_legacy_per_line_oracle_under_rls(posting_database: dict[str, Any]) -> None:
    db = posting_database
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        with server_principal_context(principal(MAKER)):
            entry = PostgresFinanceCoreRepository(connection, "finance_scope").create_entry(
                entry_number="SNAPSHOT-1000", organization_code="ORG_A", entity_code="A1", period_id="period",
                journal_code="J_A", posting_date="2026-07-28", description="Synthetic 1,000-line dimension parity",
                workspace="Shared", actor_label="maker", lines=[
                    {"account_code": "A_CASH" if index % 2 == 0 else "A_CAPITAL",
                     "debit" if index % 2 == 0 else "credit": "0.01",
                     "dimensions": {"D_SHARED": "V", "D_A": "V"} if index % 3 == 0 else {}}
                    for index in range(1000)])
        header = posting_entry(connection, "finance_scope", entry["id"])
        old_rows = records(connection.execute(
            "SELECT id,line_number,account_id,description,debit_minor,credit_minor FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s ORDER BY line_number",
            ("finance_scope", entry["id"])))
        for row in old_rows:
            row["dimensions"] = {link["dimension_id"]: link["dimension_value_id"] for link in records(connection.execute(
                "SELECT dimension_id,dimension_value_id FROM reconforge.finance_entry_line_dimensions WHERE tenant_id=%s AND entry_line_id=%s ORDER BY dimension_id",
                ("finance_scope", row["id"])))}
        old_snapshot = make_entry_snapshot(header, old_rows)
        measured = MeasuredConnection(connection)
        snapshot = posting_snapshot(measured, "finance_scope", header)
        assert measured.execute_calls == 2  # Current currency snapshot verification plus complete lines/dimensions.
        assert snapshot == old_snapshot
        assert validation_digest(snapshot) == validation_digest(old_snapshot)
        assert len(snapshot["lines"]) == 1000
        assert sum(line["debit_minor"] for line in snapshot["lines"]) == 500
        assert sum(line["credit_minor"] for line in snapshot["lines"]) == 500
        assert sum(bool(line["dimensions"]) for line in snapshot["lines"]) == 334
        assert tuple(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == (False, False)
    with db["boundary"].transaction("finance_scope", workspace_id="other") as connection:
        assert not connection.execute("SELECT 1 FROM reconforge.finance_entry_lines WHERE entry_id=%s", (entry["id"],)).fetchall()
        assert not connection.execute("SELECT 1 FROM reconforge.finance_entry_line_dimensions").fetchall()
