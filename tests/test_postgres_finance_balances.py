"""Real application-role opening, cross-period reversal and scope boundaries."""

from typing import Any

import pytest

from reconforge.domain.finance_balances import verify_posted_balances
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.platform.common import server_principal_context
from tests.test_postgres_finance_posting import CHECKER, MAKER, SCOPE, posting_database, principal, reviewed
from tests.test_postgres_finance_scope import finance_database, isolated_postgres_migration_dsn

__all__ = ["posting_database", "finance_database", "isolated_postgres_migration_dsn"]


def test_live_opening_as_of_future_exclusion_reversal_and_narrowed_authority(posting_database: dict[str, Any]):
    import psycopg

    db = posting_database
    entry_id, digest = reviewed(db, "BALANCE-JULY")
    with psycopg.connect(db["admin"], autocommit=True) as admin:
        for identifier, start, end in (("aug", "2026-08-01", "2026-08-31"), ("sep", "2026-09-01", "2026-09-30")):
            admin.execute("INSERT INTO reconforge.fiscal_periods(tenant_id,id,name,start_date,end_date,fiscal_year,period_number,application_workspace_id) VALUES('finance_scope',%s,%s,%s,%s,2026,8,'shared')", (identifier, identifier, start, end))
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        posting = PostgresFinancePostingRepository(connection, "finance_scope")
        finance = PostgresFinanceCoreRepository(connection, "finance_scope")
        original = posting.post(entry_id, command_id="balance-july", expected_validation_digest=digest, reason="Verified opening funding", actor=CHECKER)
        reversal = posting.prepare_reversal(original["id"], command_id="balance-inverse", entry_number="BALANCE-AUG-REV", period_id="aug", posting_date="2026-08-10", reason="Later period correction", actor=MAKER)
        with server_principal_context(principal(CHECKER)):
            finance.validate_entry(reversal["entry_id"], reason="Independent inverse review", actor_label="checker")
        posting.post(reversal["entry_id"], command_id="balance-inverse-post", expected_validation_digest=posting.preview(reversal["entry_id"], actor=CHECKER)["validation_digest"], reason="Explicit inverse", actor=CHECKER)
        for number, period, business_date, amount, post_it in (("AUG-FUND", "aug", "2026-08-20", "25.00", True), ("SEP-FUND", "sep", "2026-09-01", "50.00", True), ("AUG-DRAFT", "aug", "2026-08-01", "1.00", False)):
            with server_principal_context(principal(MAKER)):
                draft = finance.create_entry(entry_number=number, organization_code="ORG_A", entity_code="A1", period_id=period, journal_code="J_A", posting_date=business_date, description="Synthetic as-of source", workspace="shared", actor_label="maker", lines=[{"account_code": "A_CASH", "debit": amount, "dimensions": {"D_A": "V", "D_SHARED": "V"}}, {"account_code": "A_CAPITAL", "credit": amount}])
            if post_it:
                with server_principal_context(principal(CHECKER)):
                    finance.validate_entry(draft["id"], reason="Independent later funding", actor_label="checker")
                posting.post(draft["id"], command_id=number, expected_validation_digest=posting.preview(draft["id"], actor=CHECKER)["validation_digest"], reason="Explicit later funding", actor=CHECKER)
        args = dict(period_id="aug", organization_code="ORG_A", entity_code="A1", workspace="shared", actor=CHECKER)
        reports = [posting.posted_balances_as_of(as_of_date=day, **args) for day in ("2026-08-05", "2026-08-15", "2026-08-31")]
        assert [value["totals"]["closing"]["balance_totals"]["debit_minor"] for value in reports] == [10000, 0, 2500]
        assert [value["totals"]["closing"]["effect_count"] for value in reports] == [1, 2, 3]
        cash = next(row for row in reports[-1]["accounts"] if row["account_id"] == db["ids"]["A_CASH"])
        assert [cash[phase]["balance_minor"] for phase in ("opening", "activity", "closing")] == [10000, -7500, 2500]
        for report in reports:
            verify_posted_balances(report)
        scope_before = tuple(connection.execute("SELECT current_setting('app.tenant_id'),current_setting('app.organization_id'),current_setting('app.workspace_id'),current_setting('app.legal_entity_id')").fetchone())
        assert posting.posted_balances_as_of(as_of_date="2026-08-31", **args) == reports[-1]
        assert tuple(connection.execute("SELECT current_setting('app.tenant_id'),current_setting('app.organization_id'),current_setting('app.workspace_id'),current_setting('app.legal_entity_id')").fetchone()) == scope_before
        for forbidden in ({"entity_code": "A2"}, {"organization_code": "ORG_B", "entity_code": "B1"}, {"period_id": "other_period"}):
            with pytest.raises(FinancePostingError) as denied:
                posting.posted_balances_as_of(as_of_date="2026-08-31", **{**args, **forbidden})
            assert denied.value.code == "posting_scope_denied"
        with pytest.raises(FinancePostingError) as denied:
            posting.posted_balances_as_of(as_of_date="2026-08-31", **{**args, "actor": PostingActor("reader", "reader", frozenset())})
        assert denied.value.code == "posting_permission_denied"
