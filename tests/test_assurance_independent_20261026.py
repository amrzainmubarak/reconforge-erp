"""Independent acceptance probes for CRM persisted authority and workspace boundaries."""
from __future__ import annotations

import sqlite3

from reconforge.domain.crm_contracts import CustomerQuotation, QuotationLineItem
from reconforge.infrastructure.sqlite_crm_contracts import SqliteCRMContractsRepository


def _quote(workspace: str, amount: int) -> CustomerQuotation:
    return CustomerQuotation(
        "SAME-ID", "OP", workspace, "CUSTOMER", "USD", "2026-12-31",
        "immutable-user", "draft",
        (QuotationLineItem(1, "SERVICE", "Synthetic service", 1, amount),),
    )


def test_repository_initializes_quotation_authority_contract() -> None:
    with sqlite3.connect(":memory:") as connection:
        repository = SqliteCRMContractsRepository(connection)
        repository.save_quotation(_quote("work-a", 100), author_user_id="immutable-user")
        assert repository.quotation_author_id("work-a", "SAME-ID") == "immutable-user"


def test_quotation_lines_are_isolated_between_workspaces() -> None:
    with sqlite3.connect(":memory:") as connection:
        repository = SqliteCRMContractsRepository(connection)
        repository.save_quotation(_quote("work-a", 100))
        repository.save_quotation(_quote("work-b", 900))
        retained = repository.get_quotation("work-a", "SAME-ID")
        assert retained is not None
        assert retained.total_net_minor == 100


def test_repository_initialization_does_not_commit_callers_transaction() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE caller_owned (value TEXT NOT NULL)")
        connection.commit()
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("INSERT INTO caller_owned VALUES ('pending')")
        SqliteCRMContractsRepository(connection)
        assert connection.in_transaction
        connection.rollback()
        assert connection.execute("SELECT count(*) FROM caller_owned").fetchone()[0] == 0
