"""Actual nonowner source/GL closure, human review and immutable native links."""

from typing import Any

import pytest

from reconforge.application.receivables import ReceivableInvoiceLineInput
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.operational_finance import OperationalFinancePreparation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, create_receipt_runtime, receipt_database

__all__ = ["receipt_database"]


@pytest.fixture
def runtime(receipt_database: tuple[str, str]) -> tuple[ReceiptRuntime, str]:
    rt = create_receipt_runtime(receipt_database)
    with PostgresTenantBoundary(rt.factory).transaction(rt.tenant) as connection:
        finance = PostgresFinanceCoreRepository(connection, rt.tenant)
        for account, kind in (("AR", "Asset"), ("CASH", "Asset"), ("REVENUE", "Income")):
            finance.upsert_account(
                account_code=account, name=account, account_type=kind, chart_code="DEFAULT", workspace="work"
            )
    with rt.actor("maker") as (connection, _, actor):
        identities = PostgresIdentityRepository(connection)
        for permission in (
            "receivables.manage",
            "receivables.approve",
            "finance_core.manage",
            "finance_core.post",
            "finance_core.validate",
            "finance_core.read",
        ):
            identities.create_permission(tenant_id=rt.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=rt.tenant, role_name="receipt-operator", permission_name=permission)
        ar = PostgresReceivablesRepository(connection, rt.tenant)
        ar.upsert_customer(
            customer_code="CUSTOMER",
            name="Synthetic",
            currency_code="USD",
            credit_limit_minor=1000000,
            workspace="work",
            organization_code="ORG",
            entity_code="ENTITY",
            actor_label=actor.username,
        )
        invoice = ar.create_invoice(
            invoice_number="INV-1",
            customer_code="CUSTOMER",
            invoice_date="2026-10-08",
            currency_code="USD",
            tax_minor=0,
            lines=[
                ReceivableInvoiceLineInput(
                    description="Service", quantity="1", unit_price_minor=12000, line_total_minor=12000
                )
            ],
            workspace="work",
            organization_code="ORG",
            entity_code="ENTITY",
            actor_label=actor.username,
        )
        ar.submit_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.username)
    return rt, invoice["id"]


def preparation(invoice_id: str, kind: str = "ARInvoice") -> OperationalFinancePreparation:
    return OperationalFinancePreparation(
        "work",
        "org",
        "entity",
        "ORG",
        "ENTITY",
        kind,
        invoice_id,
        "STOCK",
        "period",
        "2026-10-08",
        "CASH" if kind == "ARReceipt" else "AR",
        "AR" if kind == "ARReceipt" else "REVENUE",
        "Native operational source",
    )


def prepare_review(runtime: tuple[ReceiptRuntime, str]) -> dict[str, Any]:
    rt, invoice = runtime
    with rt.actor("maker") as (connection, _, actor):
        plan = PostgresOperationalFinanceRepository(connection, rt.tenant).prepare(
            preparation(invoice), command_id="prepare", actor=actor
        )
        checked = dict(
            connection.execute(
                """SELECT p.payload->'source_snapshot'=reconforge.ops_source(p.tenant_id,p.source_kind,p.source_id) AS source,
        reconforge.irp_digest(p.payload)=p.plan_digest AS digest,p.payload->>'id'=p.id AS id,p.payload->>'entry_id'=p.entry_id AS entry,
        p.payload->>'preparer_actor_id'=p.preparer_actor_id AS actor,
        (e.workspace_id,e.entry_number,e.preparer_actor_id,e.total_debit_minor,e.total_credit_minor,e.currency_code,e.currency_precision)
        IS NOT DISTINCT FROM (p.workspace_id,p.entry_number,p.preparer_actor_id,p.amount_minor,p.amount_minor,p.currency_code,p.currency_precision) AS header,
        e.source_type='Manual' AS manual,e.reverses_posting_id IS NULL AS original
        FROM reconforge.operational_finance_plans p JOIN reconforge.finance_entries e ON e.tenant_id=p.tenant_id AND e.id=p.entry_id WHERE p.tenant_id=%s AND p.id=%s""",
                (rt.tenant, plan["id"]),
            ).fetchone()
        )
        assert all(checked.values()), checked
    with rt.actor("checker") as (connection, _, actor):
        ar = PostgresReceivablesRepository(connection, rt.tenant)
        ar.approve_invoice(invoice, expected_version=ar.get_invoice(invoice)["row_version"], actor_label=actor.username)
        reviewed = PostgresOperationalFinanceRepository(connection, rt.tenant).review(
            plan["id"],
            expected_plan_digest=plan["plan_digest"],
            command_id="review",
            reason="Independent source review",
            actor=actor,
        )
        assert reviewed["status"] == "Reviewed"
    return reviewed


def test_actual_source_review_post_trial_balance_same_actor_replay(runtime: tuple[ReceiptRuntime, str]) -> None:
    rt, _ = runtime
    plan = prepare_review(runtime)
    with rt.actor("poster") as (connection, _, actor):
        repository = PostgresOperationalFinanceRepository(connection, rt.tenant)
        posted = repository.post(
            plan["id"],
            expected_plan_digest=plan["plan_digest"],
            command_id="post",
            reason="Publish source",
            actor=actor,
        )
        assert posted["status"] == "Posted"
        assert (
            repository.post(
                plan["id"],
                expected_plan_digest=plan["plan_digest"],
                command_id="post",
                reason="Publish source",
                actor=actor,
            )
            == posted
        )
        assert repository.get(plan["id"], actor=actor) == posted
        trial = repository.posting.posted_trial_balance(
            period_id="period", organization_code="ORG", entity_code="ENTITY", workspace="work", actor=actor
        )
        assert trial["balance_totals"] == {"debit_minor": 12000, "credit_minor": 12000, "balanced": True}
    with rt.actor("checker") as (connection, _, actor), pytest.raises(FinancePostingError, match="another actor"):
        PostgresOperationalFinanceRepository(connection, rt.tenant).post(
            plan["id"],
            expected_plan_digest=plan["plan_digest"],
            command_id="post",
            reason="Publish source",
            actor=actor,
        )


def test_direct_generic_post_and_self_review_denied(runtime: tuple[ReceiptRuntime, str]) -> None:
    rt, invoice = runtime
    with rt.actor("maker") as (connection, _, actor):
        repository = PostgresOperationalFinanceRepository(connection, rt.tenant)
        plan = repository.prepare(preparation(invoice), command_id="prepare", actor=actor)
        with pytest.raises(FinancePostingError, match="distinct human"):
            repository.review(
                plan["id"],
                expected_plan_digest=plan["plan_digest"],
                command_id="bad-review",
                reason="Self review",
                actor=actor,
            )
    with rt.actor("checker") as (connection, _, actor), pytest.raises(FinancePostingError, match="source owner"):
        PostgresFinancePostingRepository(connection, rt.tenant).post(
            plan["entry_id"],
            command_id="bypass",
            expected_validation_digest=plan["validation_digest"],
            reason="Bypass",
            actor=actor,
        )


def test_raw_native_line_tamper_and_opaque_command_poison_rejected(runtime: tuple[ReceiptRuntime, str]) -> None:
    import psycopg

    rt, invoice = runtime
    with rt.actor("maker") as (connection, _, actor):
        plan = PostgresOperationalFinanceRepository(connection, rt.tenant).prepare(
            preparation(invoice), command_id="prepare", actor=actor
        )
    with pytest.raises(psycopg.errors.CheckViolation, match="exact native"), rt.actor("maker") as (connection, _, _):
        connection.execute(
            "UPDATE reconforge.ar_invoice_lines SET unit_price_minor=unit_price_minor+1 WHERE tenant_id=%s AND invoice_id=%s",
            (rt.tenant, invoice),
        )
    with pytest.raises(psycopg.errors.CheckViolation, match="acknowledgement"), rt.actor("maker") as (connection, _, _):
        connection.execute(
            """INSERT INTO reconforge.operational_finance_commands SELECT tenant_id,workspace_id,'poison',operation,actor_id,request_digest,request_json,plan_id,result_json||'{"amount_minor":1}'::jsonb FROM reconforge.operational_finance_commands WHERE tenant_id=%s AND plan_id=%s""",
            (rt.tenant, plan["id"]),
        )
