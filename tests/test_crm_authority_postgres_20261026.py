"""Native official-migration authority persistence under a restricted database role."""
from __future__ import annotations

import os

import pytest

from reconforge.domain.crm_contracts import CustomerQuotation, QuotationLineItem
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_crm_contracts import PostgresCRMContractsRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_operations import POSTGRES_MIGRATION_REVISIONS
from tests.test_postgres_enterprise_migrations import migrate
from tests.test_postgres_inventory_receipt_posting import create_receipt_runtime, receipt_database  # noqa: F401

pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"),
    reason="Independent CRM authority gate requires disposable native PostgreSQL; review2026-10-26",
)


def test_migrated_crm_authority_is_scoped_and_immutable(receipt_database: tuple[str, str]) -> None:  # noqa: F811
    import psycopg
    from psycopg.rows import tuple_row

    runtime = create_receipt_runtime(receipt_database)
    foreign = create_receipt_runtime(receipt_database)
    author_id, username = "crm-author-stable-id", "crm-author-display-name"
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        PostgresIdentityRepository(connection).create_user(
            tenant_id=runtime.tenant, user_id=author_id, username=username,
            password=runtime.password, role_name="receipt-operator",
        )
        connection.execute(
            "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,'sibling','Synthetic sibling')",
            (runtime.tenant,),
        )

    with runtime.actor(username) as (connection, _receipts, actor):
        connection.row_factory = tuple_row
        assert actor.user_id == author_id and actor.user_id != username
        assert connection.execute(
            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user",
        ).fetchone() == (False, False)
        assert connection.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='reconforge.crm_quotation_authorities'::regclass",
        ).fetchone() == (True, True)
        repository = PostgresCRMContractsRepository(connection, runtime.tenant)
        quote = CustomerQuotation(
            "Q-AUTHORITY", "OP", "work", "CUSTOMER", "USD", "2026-12-31",
            author_id, "draft", (QuotationLineItem(1, "SERVICE", "Synthetic service", 1, 1001),),
        )
        repository.save_quotation(quote, author_user_id=author_id)
        assert repository.quotation_author_id("work", quote.quote_id) == author_id
        with pytest.raises(FinancePostingError, match="authenticated immutable identity"):
            repository.save_quotation(quote, author_user_id=username)
        for statement in (
            "UPDATE reconforge.crm_quotation_authorities SET user_id='checker' WHERE quote_id='Q-AUTHORITY'",
            "DELETE FROM reconforge.crm_quotation_authorities WHERE quote_id='Q-AUTHORITY'",
        ):
            with pytest.raises(psycopg.Error, match="immutable"), connection.transaction():
                connection.execute(statement)
            assert repository.quotation_author_id("work", quote.quote_id) == author_id
        for tenant, workspace in ((foreign.tenant, "work"), (runtime.tenant, "sibling")):
            # Deliberately hostile SQL tests RLS, not authenticated creation authority.
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                connection.execute(
                    "INSERT INTO reconforge.crm_quotation_authorities VALUES(%s,%s,'Q-AUTHORITY',%s,'canonical-user-v1')",
                    (tenant, workspace, author_id),
                )
        assert repository.quotation_author_id("work", quote.quote_id) == author_id

    for tenant, workspace in ((foreign.tenant, "work"), (runtime.tenant, "sibling")):
        with PostgresTenantBoundary(runtime.factory).transaction(tenant, workspace_id=workspace) as connection:
            assert connection.execute(
                "SELECT user_id FROM reconforge.crm_quotation_authorities WHERE quote_id='Q-AUTHORITY'",
            ).fetchall() == []

    with runtime.actor(username) as (connection, _receipts, _actor):
        connection.row_factory = tuple_row
        before = connection.execute(
            "SELECT tenant_id,workspace_id,quote_id,user_id,identity_contract FROM reconforge.crm_quotation_authorities WHERE quote_id='Q-AUTHORITY'",
        ).fetchall()
        assert before == [(runtime.tenant, "work", "Q-AUTHORITY", author_id, "canonical-user-v1")]
    with psycopg.connect(runtime.admin_dsn) as connection:
        before_revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        assert before_revision == (POSTGRES_MIGRATION_REVISIONS[-1],)
    refused = migrate(runtime.admin_dsn, "downgrade", "0154_pg_enterprise_finance")
    assert refused.returncode != 0
    assert "Populated CRM authority prevents downgrade" in refused.stderr
    with psycopg.connect(runtime.admin_dsn) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == before_revision
    with runtime.actor(username) as (connection, _receipts, _actor):
        connection.row_factory = tuple_row
        assert connection.execute(
            "SELECT tenant_id,workspace_id,quote_id,user_id,identity_contract FROM reconforge.crm_quotation_authorities WHERE quote_id='Q-AUTHORITY'",
        ).fetchall() == before
