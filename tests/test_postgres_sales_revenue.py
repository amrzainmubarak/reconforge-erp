"""Native service sales using restricted PostgreSQL roles and persisted humans."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.sales_revenue import SalesInvoicePreparation, SalesLine, SalesQuotation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from reconforge.infrastructure.postgres_sales_revenue import PostgresSalesRevenueRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, create_receipt_runtime, receipt_database

pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"), reason="requires owned live PostgreSQL fixture"
)
_ = receipt_database  # Register the existing owned, migrated native database fixture.

SALES_PERMISSIONS = frozenset(
    {
        "sales.read",
        "sales.manage",
        "sales.approve",
        "receivables.read",
        "receivables.manage",
        "receivables.approve",
        "finance_core.read",
        "finance_core.manage",
        "finance_core.validate",
        "finance_core.post",
    }
)


def create_sales_runtime(database: tuple[str, str], base_runtime: ReceiptRuntime | None = None) -> ReceiptRuntime:
    """Reusable canonical fixture for real browser/native restore integration."""
    runtime = base_runtime or create_receipt_runtime(database)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in sorted(SALES_PERMISSIONS):
            identity.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identity.grant_permission(
                tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission
            )
        finance = PostgresFinanceCoreRepository(connection, runtime.tenant)
        for account, kind, balance in (
            ("AR", "Asset", "Debit"),
            ("CASH", "Asset", "Debit"),
            ("REVENUE", "Income", "Credit"),
        ):
            finance.upsert_account(
                account_code=account, name=account, account_type=kind, normal_balance=balance, workspace="work"
            )
        finance.upsert_journal(
            journal_code="SALES", name="Service revenue", organization_code="ORG", currency_code="USD", workspace="work"
        )
        finance.upsert_journal(
            journal_code="CASH", name="Collections", organization_code="ORG", currency_code="USD", workspace="work"
        )
        PostgresReceivablesRepository(connection, runtime.tenant).upsert_customer(
            customer_code="CUSTOMER",
            name="Synthetic customer",
            currency_code="USD",
            credit_limit_minor=1000000,
            payment_terms_days=30,
            workspace="work",
            organization_code="ORG",
            entity_code="ENTITY",
        )
    return runtime


def repository(connection: Any, runtime: ReceiptRuntime) -> PostgresSalesRevenueRepository:
    return PostgresSalesRevenueRepository(
        connection,
        runtime.tenant,
        workspace_id="work",
        organization_id="org",
        legal_entity_id="entity",
        organization_code="ORG",
        entity_code="ENTITY",
    )


@pytest.fixture
def sales_runtime(receipt_database: tuple[str, str]) -> ReceiptRuntime:
    return create_sales_runtime(receipt_database)


def quotation(number: str = "QUOTE-1") -> SalesQuotation:
    return SalesQuotation(
        number,
        "CUSTOMER",
        "2026-10-08",
        "2026-10-31",
        "USD",
        (SalesLine("Completed professional service", "2", 10000, 1000),),
    )


def create_fulfilled_sale(runtime: ReceiptRuntime, number: str = "QUOTE-1") -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        document = repository(connection, runtime).create(quotation(number), command_id=number + "-create", actor=actor)
        document = repository(connection, runtime).transition(
            document["id"],
            operation="submit",
            expected_version=1,
            reason="Quote ready",
            command_id=number + "-submit",
            actor=actor,
        )
    with runtime.actor("checker") as (connection, _, actor):
        document = repository(connection, runtime).transition(
            document["id"],
            operation="approve",
            expected_version=2,
            reason="Discount and terms approved",
            command_id=number + "-approve",
            actor=actor,
        )
    with runtime.actor("maker") as (connection, _, actor):
        document = repository(connection, runtime).transition(
            document["id"],
            operation="order",
            expected_version=3,
            reason="Customer accepted",
            command_id=number + "-order",
            actor=actor,
            reference="CUSTOMER-PO-1",
            business_date="2026-10-08",
        )
        return repository(connection, runtime).transition(
            document["id"],
            operation="fulfill",
            expected_version=4,
            reason="Service completion verified",
            command_id=number + "-fulfill",
            actor=actor,
            reference="DELIVERY-1",
            business_date="2026-10-08",
        )


def invoice_preparation(number: str = "INVOICE-1", period: str = "period") -> SalesInvoicePreparation:
    return SalesInvoicePreparation(
        number, "2026-10-08", "2026-11-07", "SALES", period, "AR", "REVENUE", "Invoice completed services"
    )


def create_reviewed_invoice(runtime: ReceiptRuntime, number: str = "QUOTE-1") -> dict[str, Any]:
    document = create_fulfilled_sale(runtime, number)
    with runtime.actor("maker") as (connection, _, actor):
        document = repository(connection, runtime).prepare_invoice(
            document["id"],
            invoice_preparation(number + "-INV"),
            expected_version=5,
            command_id=number + "-invoice",
            actor=actor,
        )
    with runtime.actor("checker") as (connection, _, actor):
        return repository(connection, runtime).review_invoice(
            document["id"],
            expected_version=6,
            command_id=number + "-invoice-review",
            reason="Independent customer credit and balanced GL review",
            actor=actor,
        )


def create_reviewed_collection(runtime: ReceiptRuntime, number: str = "QUOTE-1") -> dict[str, Any]:
    document = create_reviewed_invoice(runtime, number)
    with runtime.actor("poster") as (connection, _, actor):
        document = repository(connection, runtime).post_invoice(
            document["id"],
            expected_version=7,
            command_id=number + "-post-invoice",
            reason="Publish revenue",
            actor=actor,
        )
    with runtime.actor("maker") as (connection, _, actor):
        document = repository(connection, runtime).prepare_collection(
            document["id"],
            expected_version=8,
            command_id=number + "-collection",
            reason="Bank evidence confirms complete payment",
            receipt_number=number + "-RECEIPT",
            receipt_date="2026-10-09",
            journal_code="CASH",
            period_id="period",
            cash_account_code="CASH",
            actor=actor,
        )
    with runtime.actor("checker") as (connection, _, actor):
        return repository(connection, runtime).review_collection(
            document["id"],
            expected_version=9,
            command_id=number + "-collection-review",
            reason="Independent cash allocation review",
            actor=actor,
        )


def create_complete_sales_cycle(runtime: ReceiptRuntime, number: str = "QUOTE-1") -> dict[str, Any]:
    document = create_reviewed_collection(runtime, number)
    with runtime.actor("poster") as (connection, _, actor):
        return repository(connection, runtime).post_collection(
            document["id"],
            expected_version=10,
            command_id=number + "-post-collection",
            reason="Publish complete cash and AR effect",
            actor=actor,
        )


def test_service_quote_discount_fulfillment_invoice_collection_and_exact_double_entry(
    sales_runtime: ReceiptRuntime,
) -> None:
    document = create_complete_sales_cycle(sales_runtime)
    assert document["status"] == "Paid" and document["row_version"] == 11
    assert document["total_minor"] == "18000"
    assert document["invoice"]["status"] == "Paid" and document["invoice"]["outstanding_minor"] == "0"
    assert document["receipt"]["amount_minor"] == "18000"
    assert len(document["events"]) == 11
    with sales_runtime.actor("checker") as (connection, _, actor):
        assert repository(connection, sales_runtime).get(document["id"], actor=actor) == document
        amounts = list(
            connection.execute(
                """SELECT a.account_code,SUM(l.debit_minor) debit,SUM(l.credit_minor) credit
            FROM reconforge.finance_entry_lines l JOIN reconforge.finance_entries e ON e.tenant_id=l.tenant_id AND e.id=l.entry_id
            JOIN reconforge.finance_posting_effects effect ON effect.tenant_id=e.tenant_id AND effect.entry_id=e.id
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id
            WHERE e.tenant_id=%s GROUP BY a.account_code ORDER BY a.account_code""",
                (sales_runtime.tenant,),
            )
        )
        assert [(row["account_code"], int(row["debit"]), int(row["credit"])) for row in amounts] == [
            ("AR", 18000, 18000),
            ("CASH", 18000, 0),
            ("REVENUE", 0, 18000),
        ]
        assert (
            connection.execute(
                "SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (sales_runtime.tenant,)
            ).fetchone()["n"]
            == 2
        )
        assert dict(
            connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        ) == {"rolsuper": False, "rolbypassrls": False}


def test_lost_ack_replays_frozen_same_actor_once_and_changed_command_rejected(sales_runtime: ReceiptRuntime) -> None:
    document = create_complete_sales_cycle(sales_runtime)
    with sales_runtime.actor("poster") as (connection, _, actor):
        sales = repository(connection, sales_runtime)
        assert (
            sales.post_collection(
                document["id"],
                expected_version=10,
                command_id="QUOTE-1-post-collection",
                reason="Publish complete cash and AR effect",
                actor=actor,
            )
            == document
        )
        with pytest.raises(FinancePostingError, match="different"):
            sales.post_collection(
                document["id"],
                expected_version=10,
                command_id="QUOTE-1-post-collection",
                reason="Changed content",
                actor=actor,
            )
    with (
        sales_runtime.actor("checker") as (connection, _, actor),
        pytest.raises(FinancePostingError, match="different"),
    ):
        repository(connection, sales_runtime).post_collection(
            document["id"],
            expected_version=10,
            command_id="QUOTE-1-post-collection",
            reason="Publish complete cash and AR effect",
            actor=actor,
        )


def test_six_concurrent_collection_commands_have_one_ar_and_gl_effect(sales_runtime: ReceiptRuntime) -> None:
    document = create_reviewed_collection(sales_runtime)

    def post(index: int) -> str:
        try:
            with sales_runtime.actor("poster") as (connection, _, actor):
                repository(connection, sales_runtime).post_collection(
                    document["id"],
                    expected_version=10,
                    command_id=f"concurrent-{index}",
                    reason="Publish collection",
                    actor=actor,
                )
            return "posted"
        except FinancePostingError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=6) as executor:
        outcomes = list(executor.map(post, range(6)))
    assert outcomes.count("posted") == 1 and outcomes.count("sales_version_conflict") == 5
    with sales_runtime.actor("checker") as (connection, _, actor):
        assert (
            connection.execute(
                "SELECT count(*) n FROM reconforge.ar_receipts WHERE tenant_id=%s", (sales_runtime.tenant,)
            ).fetchone()["n"]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (sales_runtime.tenant,)
            ).fetchone()["n"]
            == 2
        )
        assert (
            repository(connection, sales_runtime).get(document["id"], actor=actor)["invoice"]["outstanding_minor"]
            == "0"
        )


def test_failed_gl_preparation_rolls_back_new_ar_source(sales_runtime: ReceiptRuntime) -> None:
    document = create_fulfilled_sale(sales_runtime)
    with sales_runtime.actor("maker") as (connection, _, actor):
        with pytest.raises((FinancePostingError, ValueError)):
            repository(connection, sales_runtime).prepare_invoice(
                document["id"],
                invoice_preparation(period="absent"),
                expected_version=5,
                command_id="bad-finance",
                actor=actor,
            )
        assert (
            connection.execute(
                "SELECT count(*) n FROM reconforge.ar_invoices WHERE tenant_id=%s", (sales_runtime.tenant,)
            ).fetchone()["n"]
            == 0
        )
        assert repository(connection, sales_runtime).get(document["id"], actor=actor)["status"] == "Fulfilled"


def test_self_approval_stale_version_and_cross_entity_are_denied(sales_runtime: ReceiptRuntime) -> None:
    with sales_runtime.actor("maker") as (connection, _, actor):
        sales = repository(connection, sales_runtime)
        document = sales.create(quotation(), command_id="create", actor=actor)
        sales.transition(
            document["id"], operation="submit", expected_version=1, reason="Ready", command_id="submit", actor=actor
        )
        with pytest.raises(FinancePostingError, match="creator"):
            sales.transition(
                document["id"], operation="approve", expected_version=2, reason="Self", command_id="self", actor=actor
            )
        with pytest.raises(FinancePostingError, match="version"):
            sales.transition(
                document["id"], operation="cancel", expected_version=1, reason="Stale", command_id="stale", actor=actor
            )
        foreign = PostgresSalesRevenueRepository(
            connection,
            sales_runtime.tenant,
            workspace_id="work",
            organization_id="org",
            legal_entity_id="foreign",
            organization_code="ORG",
            entity_code="FOREIGN",
        )
        with pytest.raises(FinancePostingError):
            foreign.get(document["id"], actor=actor)


def test_current_permission_revocation_and_immutable_history(sales_runtime: ReceiptRuntime) -> None:
    document = create_complete_sales_cycle(sales_runtime)
    with sales_runtime.actor("maker") as (connection, _, actor):
        import psycopg

        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                "UPDATE reconforge.sales_revenue_documents SET total_minor=1,row_version=row_version+1 WHERE tenant_id=%s AND id=%s",
                (sales_runtime.tenant, document["id"]),
            )
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                "DELETE FROM reconforge.sales_revenue_commands WHERE tenant_id=%s", (sales_runtime.tenant,)
            )
        connection.execute(
            """UPDATE reconforge.identity_role_permissions SET active=FALSE,revoked_at=now(),revoked_by='checker',
            revocation_reason_code='access_change',lifecycle_version=lifecycle_version+1 WHERE tenant_id=%s AND permission_name='sales.read'""",
            (sales_runtime.tenant,),
        )
        with pytest.raises(FinancePostingError, match="persisted"):
            repository(connection, sales_runtime).get(document["id"], actor=actor)


def test_raw_foreign_entity_hides_headers_commands_events_and_refuses_insert(sales_runtime: ReceiptRuntime) -> None:
    import psycopg

    document = create_fulfilled_sale(sales_runtime)
    with sales_runtime.actor("maker") as (connection, _, actor):
        native_quotation = connection.execute(
            "SELECT quotation FROM reconforge.sales_revenue_documents WHERE tenant_id=%s AND id=%s",
            (sales_runtime.tenant, document["id"]),
        ).fetchone()["quotation"]
        connection.execute("SELECT set_config('app.sales_actor_id',%s,true)", (actor.user_id,))
        connection.execute("SELECT set_config('app.legal_entity_id','foreign',true)")
        for table in ("sales_revenue_documents", "sales_revenue_commands", "sales_revenue_events"):
            assert (
                connection.execute(
                    f"SELECT count(*) n FROM reconforge.{table} WHERE tenant_id=%s", (sales_runtime.tenant,)
                ).fetchone()["n"]
                == 0
            )
        with pytest.raises(psycopg.errors.CheckViolation, match="customer and hierarchy"), connection.transaction():
            connection.execute(
                """INSERT INTO reconforge.sales_revenue_documents
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,customer_id,number,quotation,quotation_digest,currency_code,total_minor,created_by)
                VALUES(%s,'foreign-copy','work','org','entity',%s,%s,%s::jsonb,%s,'USD',18000,%s)""",
                (
                    sales_runtime.tenant,
                    document["customer_id"],
                    document["number"],
                    __import__("json").dumps(native_quotation),
                    document["quotation_digest"],
                    actor.user_id,
                ),
            )


def test_raw_publication_without_posted_effect_is_refused(sales_runtime: ReceiptRuntime) -> None:
    import psycopg

    document = create_reviewed_invoice(sales_runtime)
    with sales_runtime.actor("checker") as (connection, _, actor):
        # A valid state edge still requires its exact full command and finance link.
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute("SELECT set_config('app.sales_actor_id',%s,true)", (actor.user_id,))
            connection.execute(
                "UPDATE reconforge.sales_revenue_documents SET status='Invoiced',row_version=row_version+1 WHERE tenant_id=%s AND id=%s",
                (sales_runtime.tenant, document["id"]),
            )
            connection.execute("SET CONSTRAINTS reconforge.sales_revenue_source_closure IMMEDIATE")
        assert repository(connection, sales_runtime).get(document["id"], actor=actor)["status"] == "InvoiceReviewed"
        assert (
            connection.execute(
                "SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (sales_runtime.tenant,)
            ).fetchone()["n"]
            == 0
        )


def test_raw_quotation_pricing_cannot_be_rehashed_to_fabricate_value(sales_runtime: ReceiptRuntime) -> None:
    import json

    import psycopg

    from reconforge.domain.finance_posting import digest_payload

    with sales_runtime.actor("maker") as (connection, _, actor):
        document = repository(connection, sales_runtime).create(quotation(), command_id="create", actor=actor)
        forged = json.loads(json.dumps(document["quotation"]))
        # Public money is text; reconstruct the exact retained integer representation.
        for line in forged["lines"]:
            for key in ("gross_unit_price_minor", "unit_price_minor", "line_total_minor", "tax_minor"):
                line[key] = int(line[key])
        forged["number"] = "FORGED"
        forged["total_minor"], forged["tax_minor"] = 1, 0
        forged["lines"][0]["line_total_minor"] = 1
        forged["digest"] = digest_payload({key: value for key, value in forged.items() if key != "digest"})
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                """INSERT INTO reconforge.sales_revenue_documents
                (tenant_id,id,workspace_id,organization_id,legal_entity_id,customer_id,number,quotation,quotation_digest,currency_code,total_minor,created_by)
                VALUES(%s,'forged','work','org','entity',%s,'FORGED',%s::jsonb,%s,'USD',1,%s)""",
                (sales_runtime.tenant, document["customer_id"], json.dumps(forged), forged["digest"], actor.user_id),
            )


def test_customer_registry_migration_cannot_reinterpret_reviewed_quote_or_leave_invoice_effects(
    sales_runtime: ReceiptRuntime,
) -> None:
    import json

    import psycopg

    from reconforge.utils.money import CurrencyRegistryContext

    document = create_fulfilled_sale(sales_runtime)
    quoted = document["quotation"]["monetary_policy"]
    with sales_runtime.actor("maker") as (connection, _, _actor):
        snapshot = dict(connection.execute(
            "SELECT snapshot_json FROM reconforge.currency_registry_snapshots WHERE tenant_id=%s AND registry_digest=%s",
            (sales_runtime.tenant, quoted["registry_digest"]),
        ).fetchone()["snapshot_json"])
    snapshot["source"] = "Synthetic independently retained replacement source"
    snapshot.pop("digest", None)
    context = CurrencyRegistryContext.from_snapshot(snapshot)
    changed = context.registry_manifest
    # Ordinary AR mutation forbids rewriting captured policy. This explicit
    # administrator migration fixture retains a valid replacement snapshot;
    # the sales owner must still refuse to reinterpret an earlier quotation.
    with psycopg.connect(sales_runtime.admin_dsn) as admin:
        admin.execute(
            "INSERT INTO reconforge.currency_registry_snapshots(tenant_id,registry_digest,registry_version,snapshot_json,captured_by) VALUES(%s,%s,%s,%s::jsonb,'synthetic-policy-migration')",
            (sales_runtime.tenant, changed.digest, changed.registry_version, json.dumps(context.snapshot())),
        )
        with pytest.raises(psycopg.errors.RaiseException, match="immutable"), admin.transaction():
            admin.execute(
                "UPDATE reconforge.ar_customers SET currency_registry_digest=%s WHERE tenant_id=%s AND id=%s",
                (changed.digest, sales_runtime.tenant, document["customer_id"]),
            )
        admin.execute("ALTER TABLE reconforge.ar_customers DISABLE TRIGGER ar_customers_currency_policy_guard")
        admin.execute(
            "UPDATE reconforge.ar_customers SET currency_registry_digest=%s WHERE tenant_id=%s AND id=%s",
            (changed.digest, sales_runtime.tenant, document["customer_id"]),
        )
        admin.execute("ALTER TABLE reconforge.ar_customers ENABLE TRIGGER ar_customers_currency_policy_guard")
        admin.execute(
            "UPDATE reconforge.currency_registry_bindings SET registry_digest=%s WHERE tenant_id=%s AND workspace_id='work'",
            (changed.digest, sales_runtime.tenant),
        )
    with sales_runtime.actor("maker") as (connection, _, actor):
        with pytest.raises(FinancePostingError) as error:
            repository(connection, sales_runtime).prepare_invoice(
                document["id"], invoice_preparation(), expected_version=5, command_id="changed-policy-invoice", actor=actor,
            )
        assert error.value.code == "sales_monetary_policy_changed"
        for table in ("ar_invoices", "ar_invoice_lines", "ar_idempotency_keys", "operational_finance_plans", "finance_posting_effects"):
            assert connection.execute(
                f"SELECT count(*) n FROM reconforge.{table} WHERE tenant_id=%s", (sales_runtime.tenant,),
            ).fetchone()["n"] == 0
        retained = repository(connection, sales_runtime).get(document["id"], actor=actor)
        assert retained["status"] == "Fulfilled" and retained["row_version"] == 5
        assert retained["quotation"]["monetary_policy"] == quoted
        assert len(retained["events"]) == 5


@pytest.mark.parametrize("source", ["invoice", "receipt"])
def test_raw_native_update_refuses_administratively_damaged_quote_policy(
    sales_runtime: ReceiptRuntime, source: str,
) -> None:
    import psycopg

    document = create_complete_sales_cycle(sales_runtime)
    # Deliberate administrator-only history corruption models a damaged import
    # or restore. Do not weaken any runtime role, application or financial guard.
    with psycopg.connect(sales_runtime.admin_dsn) as admin:
        admin.execute("ALTER TABLE reconforge.sales_revenue_documents DISABLE TRIGGER sales_revenue_immutable")
        admin.execute("ALTER TABLE reconforge.sales_revenue_documents DISABLE TRIGGER sales_revenue_admission")
        admin.execute("ALTER TABLE reconforge.sales_revenue_documents DISABLE TRIGGER sales_revenue_source_closure")
        admin.execute(
            "UPDATE reconforge.sales_revenue_documents SET quotation=jsonb_set(quotation,'{monetary_policy,source}','\"Synthetic damaged historical source\"'::jsonb) WHERE tenant_id=%s AND id=%s",
            (sales_runtime.tenant, document["id"]),
        )
        admin.execute("ALTER TABLE reconforge.sales_revenue_documents ENABLE TRIGGER sales_revenue_immutable")
        admin.execute("ALTER TABLE reconforge.sales_revenue_documents ENABLE TRIGGER sales_revenue_admission")
        admin.execute("ALTER TABLE reconforge.sales_revenue_documents ENABLE TRIGGER sales_revenue_source_closure")
    table = "ar_invoices" if source == "invoice" else "ar_receipts"
    constraint = "sales_invoice_policy_closure" if source == "invoice" else "sales_receipt_policy_closure"
    with sales_runtime.actor("poster") as (connection, _, _actor):
        with pytest.raises(psycopg.errors.CheckViolation, match="monetary interpretation differs"), connection.transaction():
            connection.execute(
                f"UPDATE reconforge.{table} SET updated_at=updated_at WHERE tenant_id=%s AND id=%s",
                (sales_runtime.tenant, document[source + "_id"]),
            )
            connection.execute(f"SET CONSTRAINTS reconforge.{constraint} IMMEDIATE")
        assert connection.execute(
            "SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (sales_runtime.tenant,),
        ).fetchone()["n"] == 2


def test_failure_after_native_collection_allocation_rolls_back_ar_and_gl(
    sales_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository

    document = create_reviewed_collection(sales_runtime)

    def fault(*args: Any, **kwargs: Any) -> Any:
        raise FinancePostingError("synthetic_post_failure", "Injected failure after native allocation")

    with sales_runtime.actor("poster") as (connection, _, actor):
        with monkeypatch.context() as patch:
            patch.setattr(PostgresOperationalFinanceRepository, "post", fault)
            with pytest.raises(FinancePostingError, match="Injected"):
                repository(connection, sales_runtime).post_collection(
                    document["id"],
                    expected_version=10,
                    command_id="faulted-post",
                    reason="Publish collection",
                    actor=actor,
                )
        assert (
            connection.execute(
                "SELECT count(*) n FROM reconforge.ar_receipts WHERE tenant_id=%s", (sales_runtime.tenant,)
            ).fetchone()["n"]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) n FROM reconforge.ar_receipt_allocations WHERE tenant_id=%s", (sales_runtime.tenant,)
            ).fetchone()["n"]
            == 0
        )
        current = repository(connection, sales_runtime).get(document["id"], actor=actor)
        assert current["status"] == "CollectionReviewed" and current["invoice"]["outstanding_minor"] == "18000"
        assert (
            connection.execute(
                "SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (sales_runtime.tenant,)
            ).fetchone()["n"]
            == 1
        )


def test_populated_native_downgrade_preserves_financial_history(sales_runtime: ReceiptRuntime) -> None:
    import subprocess
    import sys
    from pathlib import Path

    document = create_complete_sales_cycle(sales_runtime)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0109_pg_operational_finance"],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "RECONFORGE_POSTGRES_DSN": sales_runtime.admin_dsn},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0 and "refuses to discard" in result.stderr
    with sales_runtime.actor("checker") as (connection, _, actor):
        assert repository(connection, sales_runtime).get(document["id"], actor=actor)["status"] == "Paid"
        assert (
            connection.execute(
                "SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (sales_runtime.tenant,)
            ).fetchone()["n"]
            == 2
        )


def test_scoped_master_choices_are_actual_current_customer_period_and_accounts(sales_runtime: ReceiptRuntime) -> None:
    with sales_runtime.actor("maker") as (connection, _, actor):
        choices = repository(connection, sales_runtime).options(actor=actor)
        assert choices["customers"] == [
            {"customer_code": "CUSTOMER", "name": "Synthetic customer", "currency_code": "USD"}
        ]
        assert any(row["id"] == "period" and row["start_date"] == "2026-10-01" for row in choices["periods"])
        assert {row["journal_code"] for row in choices["journals"]} >= {"SALES", "CASH"}
        assert {(row["account_code"], row["account_type"]) for row in choices["accounts"]} >= {
            ("AR", "Asset"),
            ("CASH", "Asset"),
            ("REVENUE", "Income"),
        }
