"""Actual nonowner source/GL closure, human review and immutable native links."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

from reconforge.application.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput
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
pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"),
    reason="Owned PostgreSQL integration prerequisite; docs/operator/operational-finance.md; review 2026-10-08",
)


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


def test_reserved_gl_line_delete_rolls_back_and_unowned_number_is_denied(runtime: tuple[ReceiptRuntime, str]) -> None:
    import psycopg

    rt, invoice = runtime
    with rt.actor("maker") as (connection, _, actor):
        plan = PostgresOperationalFinanceRepository(connection, rt.tenant).prepare(
            preparation(invoice), command_id="prepare", actor=actor
        )
    with pytest.raises(psycopg.errors.CheckViolation, match="snapshot"), rt.actor("maker") as (connection, _, _):
        connection.execute(
            "DELETE FROM reconforge.finance_entry_lines WHERE tenant_id=%s AND entry_id=%s",
            (rt.tenant, plan["entry_id"]),
        )
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="no source owner"),
        rt.actor("maker") as (connection, _, actor),
    ):
        PostgresFinanceCoreRepository(connection, rt.tenant).create_entry(
            entry_number="oPs1-unowned",
            organization_code="ORG",
            entity_code="ENTITY",
            period_id="period",
            journal_code="STOCK",
            posting_date="2026-10-08",
            description="Unowned namespace",
            workspace="work",
            lines=[
                {"account_code": "AR", "debit": "1", "credit": "0"},
                {"account_code": "REVENUE", "debit": "0", "credit": "1"},
            ],
            actor_label=actor.username,
        )
    with rt.actor("maker") as (connection, _, actor):
        assert (
            PostgresOperationalFinanceRepository(connection, rt.tenant).get(plan["id"], actor=actor)["status"]
            == "Draft"
        )


def collection_plan(runtime: tuple[ReceiptRuntime, str]) -> dict[str, Any]:
    rt, invoice = runtime
    prepare_review(runtime)
    with rt.actor("maker") as (connection, _, actor):
        plan = PostgresOperationalFinanceRepository(connection, rt.tenant).prepare(
            preparation(invoice, "ARReceipt"), command_id="collection-prepare", actor=actor
        )
    with rt.actor("checker") as (connection, _, actor):
        return PostgresOperationalFinanceRepository(connection, rt.tenant).review(
            plan["id"],
            expected_plan_digest=plan["plan_digest"],
            command_id="collection-review",
            reason="Independent full collection review",
            actor=actor,
        )


def post_native_receipt(connection: Any, rt: ReceiptRuntime, invoice: str, actor: Any) -> dict[str, Any]:
    return PostgresReceivablesRepository(connection, rt.tenant).post_receipt(
        receipt_number="CASH-1",
        customer_code="CUSTOMER",
        receipt_date="2026-10-08",
        currency_code="USD",
        amount_minor=12000,
        allocations=[ReceiptAllocationInput(invoice, 12000)],
        workspace="work",
        organization_code="ORG",
        entity_code="ENTITY",
        actor_label=actor.username,
    )


def test_native_collection_and_gl_commit_together_without_partial_paid_state(
    runtime: tuple[ReceiptRuntime, str],
) -> None:
    import psycopg

    rt, invoice = runtime
    plan = collection_plan(runtime)
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="cannot commit without"),
        rt.actor("poster") as (connection, _, actor),
    ):
        post_native_receipt(connection, rt, invoice, actor)
    with rt.actor("poster") as (connection, _, actor):
        assert PostgresReceivablesRepository(connection, rt.tenant).get_invoice(invoice)["status"] == "Approved"
        receipt = post_native_receipt(connection, rt, invoice, actor)
        value = PostgresOperationalFinanceRepository(connection, rt.tenant).post(
            plan["id"],
            expected_plan_digest=plan["plan_digest"],
            command_id="collection-post",
            reason="Publish actual full collection",
            source_effect_id=receipt["id"],
            actor=actor,
        )
        assert value["source_effect_id"] == receipt["id"] and value["status"] == "Posted"
    with rt.actor("checker") as (connection, _, actor):
        assert PostgresReceivablesRepository(connection, rt.tenant).get_invoice(invoice)["status"] == "Paid"
        assert (
            PostgresOperationalFinanceRepository(connection, rt.tenant).get(plan["id"], actor=actor)[
                "posting_effect_id"
            ]
            == value["posting_effect_id"]
        )


def test_concurrent_exact_acknowledgements_have_one_financial_effect(runtime: tuple[ReceiptRuntime, str]) -> None:
    rt, _ = runtime
    plan = prepare_review(runtime)

    def run(_: int) -> dict[str, Any]:
        with rt.actor("poster") as (connection, _, actor):
            return PostgresOperationalFinanceRepository(connection, rt.tenant).post(
                plan["id"],
                expected_plan_digest=plan["plan_digest"],
                command_id="concurrent-post",
                reason="One concurrent effect",
                actor=actor,
            )

    with ThreadPoolExecutor(max_workers=6) as workers:
        values = list(workers.map(run, range(6)))
    assert all(value == values[0] for value in values)
    with rt.actor("poster") as (connection, _, _):
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (rt.tenant,)
            ).fetchone()["n"]
            == 1
        )


def test_populated_downgrade_refuses_financial_history_loss(runtime: tuple[ReceiptRuntime, str]) -> None:
    rt, _ = runtime
    plan = prepare_review(runtime)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0108_pg_receipt_admission"],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "RECONFORGE_POSTGRES_DSN": rt.admin_dsn},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode != 0 and "Operational source history cannot be discarded" in result.stdout + result.stderr
    with rt.actor("checker") as (connection, _, actor):
        assert (
            PostgresOperationalFinanceRepository(connection, rt.tenant).get(plan["id"], actor=actor)["plan_digest"]
            == plan["plan_digest"]
        )


def test_empty_migration_roundtrip_and_installer_repeat(receipt_database: tuple[str, str]) -> None:
    import psycopg
    from psycopg import sql

    from reconforge.infrastructure.postgres_operational_finance_schema import (
        install_postgres_operational_finance_schema,
    )

    control = receipt_database[0]
    name = "ops_empty_" + uuid4().hex[:12]
    dsn = psycopg.conninfo.make_conninfo(control, dbname=name)
    migration_dsn = urlunsplit(urlsplit(control)._replace(path="/" + name))
    with psycopg.connect(control, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        for target, operation in (("head", "upgrade"), ("0108_pg_receipt_admission", "downgrade"), ("head", "upgrade")):
            result = subprocess.run(
                [sys.executable, "-m", "alembic", operation, target],
                cwd=Path(__file__).resolve().parents[1],
                env={**os.environ, "RECONFORGE_POSTGRES_DSN": migration_dsn},
                capture_output=True,
                text=True,
                timeout=180,
            )
            assert result.returncode == 0, result.stdout + result.stderr
        with psycopg.connect(dsn) as connection:
            install_postgres_operational_finance_schema(connection)
            install_postgres_operational_finance_schema(connection)
            assert (
                connection.execute(
                    "SELECT count(*) FROM pg_tables WHERE schemaname='reconforge' AND tablename LIKE 'operational_finance_%'"
                ).fetchone()[0]
                == 4
            )
            assert (
                connection.execute(
                    "SELECT count(*) FROM pg_policies WHERE schemaname='reconforge' AND tablename LIKE 'operational_finance_%' AND policyname='operational_scope'"
                ).fetchone()[0]
                == 4
            )
    finally:
        with psycopg.connect(control, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.mark.parametrize("mismatch", ["currency", "registry"])
def test_raw_source_admission_requires_native_currency_and_gl_affinity(
    runtime: tuple[ReceiptRuntime, str], mismatch: str
) -> None:
    """A complete SQL plan cannot reinterpret EUR source units as functional USD."""
    import psycopg

    from reconforge.domain.finance_posting import canonical_json, digest_payload, validation_digest
    from reconforge.infrastructure.postgres_finance_posting import posting_entry, posting_snapshot
    from reconforge.utils.time import utc_now_text

    rt, existing_invoice = runtime
    if mismatch == "currency":
        with PostgresTenantBoundary(rt.factory).transaction(rt.tenant) as connection:
            connection.execute(
                "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES(%s,'EUR','Euro',2)",
                (rt.tenant,),
            )
        with rt.actor("maker") as (connection, _, actor):
            ar = PostgresReceivablesRepository(connection, rt.tenant)
            ar.upsert_customer(
                customer_code="EUR-CUSTOMER",
                name="Synthetic foreign customer",
                currency_code="EUR",
                credit_limit_minor=1000000,
                workspace="work",
                organization_code="ORG",
                entity_code="ENTITY",
                actor_label=actor.username,
            )
            invoice = ar.create_invoice(
                invoice_number="EUR-INV",
                customer_code="EUR-CUSTOMER",
                invoice_date="2026-10-08",
                currency_code="EUR",
                tax_minor=0,
                lines=[ReceivableInvoiceLineInput("Foreign services", "1", 12000, 12000)],
                workspace="work",
                organization_code="ORG",
                entity_code="ENTITY",
                actor_label=actor.username,
            )
            ar.submit_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.username)
            invoice_id = invoice["id"]
    else:
        from copy import deepcopy

        from reconforge.utils.money import CurrencyRegistryContext

        invoice_id = existing_invoice
        with rt.actor("maker") as (connection, _, actor):
            source = PostgresOperationalFinanceRepository(connection, rt.tenant)._source("ARInvoice", invoice_id)
            retained = connection.execute(
                "SELECT snapshot_json FROM reconforge.currency_registry_snapshots WHERE tenant_id=%s AND registry_digest=%s",
                (rt.tenant, source["currency_registry_digest"]),
            ).fetchone()["snapshot_json"]
            changed = deepcopy(retained)
            changed["source"] = "Synthetic new registry provenance after retained AR capture"
            changed.pop("digest", None)
            context = CurrencyRegistryContext.from_snapshot(changed)
            manifest = context.registry_manifest
            connection.execute(
                """INSERT INTO reconforge.currency_registry_snapshots
                (tenant_id,registry_digest,registry_version,snapshot_json,captured_by) VALUES(%s,%s,%s,%s::jsonb,%s)""",
                (
                    rt.tenant,
                    manifest.digest,
                    manifest.registry_version,
                    canonical_json(context.snapshot()),
                    actor.user_id,
                ),
            )
            connection.execute(
                """INSERT INTO reconforge.currency_registry_bindings(tenant_id,workspace_id,registry_digest,registry_version,bound_by)
                VALUES(%s,'work',%s,%s,%s) ON CONFLICT(tenant_id,workspace_id) DO UPDATE
                SET registry_digest=excluded.registry_digest,registry_version=excluded.registry_version,bound_by=excluded.bound_by""",
                (rt.tenant, manifest.digest, manifest.registry_version, actor.user_id),
            )

    with (
        pytest.raises(psycopg.errors.CheckViolation, match="native currency and retained monetary policy"),
        rt.actor("maker") as (connection, _, actor),
    ):
        repository = PostgresOperationalFinanceRepository(connection, rt.tenant)
        arguments = preparation(invoice_id).payload()
        request_digest, _ = repository._command(arguments, "raw-affinity", "prepare", actor, arguments)
        source = repository._source("ARInvoice", invoice_id)
        plan_id = "OPS1-" + digest_payload(["work", "ARInvoice", invoice_id])[:32]
        entry = repository.finance.create_entry(
            entry_number=plan_id.upper(),
            organization_code="ORG",
            entity_code="ENTITY",
            period_id="period",
            journal_code="STOCK",
            posting_date="2026-10-08",
            description=arguments["reason"],
            lines=[
                {"account_code": "AR", "debit": "120.00", "credit": "0", "description": arguments["reason"]},
                {"account_code": "REVENUE", "debit": "0", "credit": "120.00", "description": arguments["reason"]},
            ],
            workspace="work",
            external_reference=plan_id,
            actor_label=actor.username,
        )
        snapshot = posting_snapshot(connection, rt.tenant, posting_entry(connection, rt.tenant, entry["id"]))
        assert snapshot["entry"]["currency_code"] == "USD"
        if mismatch == "currency":
            assert source["currency_code"] == "EUR"
        else:
            assert source["currency_code"] == "USD"
            assert source["currency_registry_digest"] != snapshot["entry"]["currency_registry_digest"]
        payload = {
            "schema_version": "operational-finance-v1",
            "id": plan_id,
            "entry_id": entry["id"],
            **arguments,
            "amount_minor": source["amount_minor"],
            "currency_code": "USD",
            "currency_precision": 2,
            "preparer_actor_id": actor.user_id,
            "source_snapshot": source,
            "snapshot": snapshot,
        }
        seal, validation = digest_payload(payload), validation_digest(snapshot)
        audit, outbox = repository._event(
            payload, "operational_finance_prepared", actor, {"plan_digest": seal, "validation_digest": validation}
        )
        connection.execute(
            """INSERT INTO reconforge.operational_finance_plans(tenant_id,id,workspace_id,organization_id,legal_entity_id,
            source_kind,source_id,entry_id,entry_number,preparer_actor_id,amount_minor,currency_code,currency_precision,
            plan_digest,validation_digest,payload,audit_event_id,outbox_event_id,created_at)
            VALUES(%s,%s,'work','org','entity','ARInvoice',%s,%s,%s,%s,12000,'USD',2,%s,%s,%s::jsonb,%s,%s,%s)""",
            (
                rt.tenant,
                plan_id,
                invoice_id,
                entry["id"],
                plan_id.upper(),
                actor.user_id,
                seal,
                validation,
                canonical_json(payload),
                audit,
                outbox,
                utc_now_text(),
            ),
        )
        result = repository._get(plan_id)
        repository._remember(result, "raw-affinity", "prepare", actor, request_digest, result)
    with rt.actor("checker") as (connection, _, _):
        assert (
            connection.execute(
                "SELECT count(*) n FROM reconforge.operational_finance_plans WHERE tenant_id=%s", (rt.tenant,)
            ).fetchone()["n"]
            == 0
        )
