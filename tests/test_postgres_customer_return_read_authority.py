"""Genuine fractional KWD3 CR1 source price admission, with no source edits."""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql

from reconforge.auth.policy import evaluate_principal_access
from reconforge.domain.customer_returns import CustomerReturnPreparation
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.inventory_receipt_posting import ReceiptPreparation
from reconforge.domain.sales_revenue import SalesInvoicePreparation
from reconforge.domain.stock_sales import StockOrder
from reconforge.infrastructure import postgres_operational_finance as policy_module
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_customer_returns import READ, PostgresCustomerReturnsRepository
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_inventory_valuation import PostgresInventoryValuationRepository
from reconforge.infrastructure.postgres_master_data import PostgresMasterDataRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.infrastructure.postgres_stock_sales import PostgresStockSalesRepository
from reconforge.platform.common import ServerPrincipal, server_principal_context
from tests.test_postgres_customer_returns import configure_runtime
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database
from tests.test_postgres_stock_sales import create_stock_runtime

_ = receipt_database
SCOPE = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "kwd-entity"}


@dataclass
class KwdRuntime(ReceiptRuntime):
    @contextmanager
    def actor(self, name: str) -> Iterator[tuple[Any, Any, PostingActor]]:
        boundary = PostgresTenantBoundary(self.factory)
        with boundary.transaction(self.tenant) as connection:
            identities = PostgresIdentityRepository(connection)
            user = identities.authenticate_user(tenant_id=self.tenant, username=name, password=self.password)
            assert user is not None
            permissions = identities.user_permissions(tenant_id=self.tenant, user_id=user.id)
        with boundary.transaction(self.tenant, **SCOPE) as connection:
            principal = ServerPrincipal(user=user, permissions=permissions, step_up_active=True,
                authorized_tenant_ids=frozenset({self.tenant}), authorized_workspace_ids=frozenset({"work"}),
                authorized_organization_ids=frozenset({"org"}), authorized_legal_entity_ids=frozenset({"kwd-entity"}))
            with server_principal_context(principal):
                yield connection, None, PostingActor(user.id, user.username, permissions, step_up_active=True)


def _stock(connection: Any, runtime: KwdRuntime) -> PostgresStockSalesRepository:
    return PostgresStockSalesRepository(connection, runtime.tenant, **SCOPE,
        organization_code="ORG", entity_code="ENTITY-KWD")


def _act(runtime: KwdRuntime, source: dict[str, Any], operation: str, person: str,
         parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    with runtime.actor(person) as (connection, _, actor):
        return _stock(connection, runtime).act(source["id"], operation, expected_version=source["row_version"],
            command_id="KWD-ORIGINAL:" + operation, reason="Actual fractional KWD original " + operation,
            parameters=parameters or {}, actor=actor)


def _setup(database: tuple[str, str]) -> tuple[KwdRuntime, dict[str, Any]]:
    # Existing USD entity remains unchanged; a fresh native KWD entity/journals carry this source.
    base = create_stock_runtime(database, seed_stock=False)
    configure_runtime(base)
    runtime = KwdRuntime(base.factory, base.admin_dsn, base.tenant, base.password)
    with PostgresTenantBoundary(base.factory).transaction(base.tenant) as connection:
        masters = PostgresMasterDataRepository(connection)
        masters.upsert_currency(tenant_id=base.tenant, code="KWD", name="Synthetic Kuwaiti dinar", minor_units=3)
        masters.upsert_legal_entity(tenant_id=base.tenant, organization_id="org", entity_id="kwd-entity",
            entity_code="ENTITY-KWD", name="Synthetic fractional source", currency_code="KWD")
        finance = PostgresFinanceCoreRepository(connection, base.tenant)
        for journal in ("KWD_STOCK", "KWD_SALES", "KWD_CASH"):
            finance.upsert_journal(journal_code=journal, name=journal, organization_code="ORG", currency_code="KWD", workspace="work")
        inventory = PostgresInventoryCoreRepository(connection, base.tenant)
        inventory.upsert_uom(uom_code="KG", name="Kilogram", decimal_places=3, workspace="work")
        inventory.upsert_item(item_code="KWD_ITEM", name="Synthetic original fractional item", organization_code="ORG",
            uom_code="KG", inventory_account_code="INVENTORY", workspace="work")
        inventory.upsert_warehouse(warehouse_code="KWD_MAIN", name="Synthetic original KWD warehouse",
            organization_code="ORG", entity_code="ENTITY-KWD", workspace="work")
        inventory.upsert_location(warehouse_code="KWD_MAIN", location_code="STOCK", name="Synthetic KWD stock",
            organization_code="ORG", workspace="work")
        PostgresInventoryValuationRepository(connection, base.tenant).upsert_policy(policy_code="KWD_FIFO",
            organization_code="ORG", entity_code="ENTITY-KWD", journal_code="KWD_STOCK",
            receipt_clearing_account_code="CLEARING", cogs_account_code="COGS", adjustment_account_code="ADJUSTMENT", workspace="work")
        PostgresReceivablesRepository(connection, base.tenant).upsert_customer(customer_code="KWD_CUSTOMER",
            name="Synthetic fractional source customer", currency_code="KWD", credit_limit_minor=10000000,
            payment_terms_days=30, workspace="work", organization_code="ORG", entity_code="ENTITY-KWD")
        authority = PostgresScopeAuthorityRepository(connection)
        for person in ("maker", "checker", "poster"):
            for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "kwd-entity")):
                authority.grant(tenant_id=base.tenant, grant_id="kwd-" + person + "-" + kind,
                    principal_type="user", principal_id=person, scope_type=kind, scope_id=identifier, actor_id=person)
    from reconforge.infrastructure.postgres_inventory_receipt_posting import PostgresInventoryReceiptPostingRepository

    receipt = ReceiptPreparation(receipt_number="KWD_ORIGINAL_IRP", posting_date="2026-10-03", period_id="period",
        item_code="KWD_ITEM", location_code="KWD_MAIN/STOCK", quantity="1.000", total_value_minor=1000,
        policy_code="KWD_FIFO", organization_code="ORG", entity_code="ENTITY-KWD", workspace="work", reason="Actual KWD3 approved stock")
    with runtime.actor("maker") as (connection, _, actor):
        original = PostgresInventoryReceiptPostingRepository(connection, runtime.tenant).prepare_receipt(receipt, command_id="kwd-irp-prepare", actor=actor)
    with runtime.actor("checker") as (connection, _, actor):
        review = PostgresInventoryReceiptPostingRepository(connection, runtime.tenant).review(original["plan_id"],
            command_id="kwd-irp-review", expected_plan_digest=original["plan_digest"], reason="Original KWD quantity/value", actor=actor)
    with runtime.actor("poster") as (connection, _, actor):
        PostgresInventoryReceiptPostingRepository(connection, runtime.tenant).commit(original["plan_id"],
            command_id="kwd-irp-post", expected_review_digest=review["review_digest"], reason="Publish original KWD stock", actor=actor)
    with runtime.actor("maker") as (connection, _, actor):
        sale = _stock(connection, runtime).create(StockOrder("KWD_FRACTIONAL", "KWD_CUSTOMER", "SYNTHETIC",
            "KWD_ITEM", "KWD_MAIN", "STOCK", "0.001", 3000000, "KWD", "2026-10-09", "Original 0.001KG merchandise"),
            command_id="kwd-source-create", actor=actor)
    for operation, person, parameters in (
        ("submit", "maker", {}), ("approve", "checker", {}), ("reserve", "maker", {}),
        ("prepare-issue", "maker", {"posting_date": "2026-10-09", "period_id": "period", "policy_code": "KWD_FIFO"}),
        ("review-issue", "checker", {}), ("deliver", "poster", {}),
        ("prepare-invoice", "maker", {key: value for key, value in SalesInvoicePreparation("KWD_ORIGINAL_AR",
            "2026-10-09", "2026-10-31", "KWD_SALES", "period", "AR", "REVENUE", "Original KWD sale").payload().items() if key != "reason"}),
        ("review-invoice", "checker", {}), ("invoice", "poster", {}),
        ("prepare-collection", "maker", {"receipt_number": "KWD_ORIGINAL_CASH", "receipt_date": "2026-10-10",
            "journal_code": "KWD_CASH", "period_id": "period", "cash_account_code": "CASH"}),
        ("review-collection", "checker", {}), ("collect", "poster", {}),
    ):
        sale = _act(runtime, sale, operation, person, parameters)
    assert sale["status"] == "Paid" and sale["total_minor"] == "3000"
    return runtime, sale


def _return_request(source: dict[str, Any]) -> CustomerReturnPreparation:
    return CustomerReturnPreparation(**SCOPE, organization_code="ORG", entity_code="ENTITY-KWD", source_order_id=source["id"],
        period_id="period", posting_date="2026-10-10", journal_code="KWD_CASH", refund_liability_account_code="REFUND",
        cash_account_code="CASH", reason="Original complete fractional KWD credit")


def _original_tables(runtime: KwdRuntime) -> dict[str, str]:
    with runtime.actor("maker") as (connection, _, _):
        tables = connection.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema='reconforge'
            AND table_type='BASE TABLE' AND table_name ~ '^(customer_return_|stock_|finance_|ar_|inventory_|operational_finance_|domain_audit_|outbox_)'
            ORDER BY table_name""").fetchall()
        return {row["table_name"]: connection.execute(sql.SQL(
            "SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY to_jsonb(r)::text),'[]'::jsonb)::text value FROM reconforge.{} r WHERE tenant_id=%s")
            .format(sql.Identifier(row["table_name"])), (runtime.tenant,)).fetchone()["value"] for row in tables}


def _retain(name: str, value: Any) -> None:
    if root := os.environ.get("RECONFORGE_CR1_READ_PROOF_DIR"):
        with (Path(root) / name).open("x", encoding="utf-8", newline="\n") as target:
            json.dump(value, target, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            target.write("\n")


class _RollbackProbe(RuntimeError):
    """Successful unexpected new ACK is captured then its whole savepoint rolled back."""


def test_actual_fractional_kwd3_whole_exposed_price_requires_each_current_read_amount_cap(
        receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    from reconforge.infrastructure import postgres_customer_returns as original_owner

    root = Path(__file__).resolve().parents[1]
    assert Path(original_owner.__file__).resolve().is_relative_to(root)
    assert Path(policy_module.__file__).resolve().is_relative_to(root)
    runtime, sale = _setup(receipt_database)
    with psycopg.connect(runtime.admin_dsn) as admin:
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0146_pg_inventory_transfer"
    with runtime.actor("maker") as (connection, _, _):
        assert dict(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == {"rolsuper": False, "rolbypassrls": False}
    request = _return_request(sale)
    violations: list[str] = []
    observations: list[dict[str, str | None]] = []
    selected_permission, maximum = "finance_core.read", Decimal("20")

    def policy(principal: Any, **context: Any) -> Any:
        if context["required_permission"] == selected_permission:
            observations.append({"permission": selected_permission, "amount": str(context["amount"]) if context["amount"] is not None else None})
            return evaluate_principal_access(principal, maximum_amount=maximum, **context)
        return evaluate_principal_access(principal, **context)

    baseline = _original_tables(runtime)
    with monkeypatch.context() as cap:
        cap.setattr(policy_module, "evaluate_principal_access", policy)
        for permission in sorted(READ):
            selected_permission = permission
            with runtime.actor("maker") as (connection, _, actor):
                try:
                    with connection.transaction():
                        result = PostgresCustomerReturnsRepository(connection, runtime.tenant).prepare(request,
                            command_id="kwd-lowcap-new-" + permission, actor=actor)
                        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
                        _retain("unexpected-new-ack-" + permission + ".json", result)
                        violations.append(permission + ":new-prepare-ack")
                        raise _RollbackProbe()
                except _RollbackProbe:
                    pass
                except FinancePostingError as refused:
                    assert "denied" in refused.code
    assert _original_tables(runtime) == baseline
    with runtime.actor("maker") as (connection, _, actor):
        prepared = PostgresCustomerReturnsRepository(connection, runtime.tenant).prepare(request, command_id="kwd-original-return", actor=actor)
    assert prepared["currency_code"] == "KWD" and prepared["currency_precision"] == 3
    assert prepared["source_snapshot"]["stock"]["source"]["unit_price_minor"] == 3000000
    assert prepared["credit_minor"] == prepared["refund_entitlement_minor"] == 3000
    assert prepared["cogs_restored_minor"] == 1 and prepared["amount_minor"] == 6001
    with runtime.actor("checker") as (connection, _, actor):
        reviewed = PostgresCustomerReturnsRepository(connection, runtime.tenant).review(prepared["id"], expected_plan_digest=prepared["plan_digest"],
            command_id="kwd-return-review", reason="Original independent KWD credit", actor=actor)
    with runtime.actor("poster") as (connection, _, actor):
        posted = PostgresCustomerReturnsRepository(connection, runtime.tenant).post(reviewed["id"], expected_plan_digest=reviewed["plan_digest"],
            command_id="kwd-return-post", reason="Original third-human KWD credit", actor=actor)
    assert posted["status"] == "Posted" and len(posted["posting_effect_ids"]) == 3
    with runtime.actor("maker") as (connection, _, actor):
        assert connection.execute("SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 7
        retained_source = connection.execute("SELECT reconforge.customer_return_source(%s,%s)::text value", (runtime.tenant, sale["id"])).fetchone()["value"]
        commands = connection.execute("SELECT request_json::text request,response_json::text response FROM reconforge.customer_return_commands WHERE tenant_id=%s ORDER BY command_id", (runtime.tenant,)).fetchall()
        invoice = PostgresReceivablesRepository(connection, runtime.tenant).get_invoice(sale["invoice_id"])
        assert invoice["total_minor"] == invoice["allocated_minor"] == invoice["credited_minor"] == 3000
        assert invoice["outstanding_minor"] == 0 and invoice["refund_due_minor"] == 3000
    baseline = _original_tables(runtime)
    with monkeypatch.context() as cap:
        cap.setattr(policy_module, "evaluate_principal_access", policy)
        for permission in sorted(READ):
            selected_permission = permission
            for operation in ("get-with-embedded-evidence", "list", "historical-prepare-replay"):
                with runtime.actor("maker") as (connection, _, actor):
                    owner = PostgresCustomerReturnsRepository(connection, runtime.tenant)
                    try:
                        if operation == "list":
                            result = owner.list_plans(SCOPE, actor=actor)["plans"][0]
                        elif operation == "historical-prepare-replay":
                            result = owner.prepare(request, command_id="kwd-original-return", actor=actor)
                            assert result == prepared
                        else:
                            result = owner.get(posted["id"], actor=actor)
                            assert result["evidence"] and result["entries"]
                        assert result["source_snapshot"]["stock"]["source"]["unit_price_minor"] == 3000000
                        violations.append(permission + ":" + operation)
                    except FinancePostingError as refused:
                        assert "denied" in refused.code
            maximum = Decimal("4000")
            with runtime.actor("maker") as (connection, _, actor):
                assert PostgresCustomerReturnsRepository(connection, runtime.tenant).get(posted["id"], actor=actor) == posted
            maximum = Decimal("20")
    assert _original_tables(runtime) == baseline
    _retain("original-posted-kwd3-compatibility.json", {"schema_version": "cr1-original-kwd3-read-compatibility-v1",
        "tenant_id": runtime.tenant, "scope": SCOPE, "sale": sale, "prepared_ack": prepared, "reviewed_ack": reviewed,
        "posted_ack": posted, "original_source_json": retained_source, "original_commands": [dict(row) for row in commands],
        "original_tables_json": baseline, "table_sha256": {name: hashlib.sha256(raw.encode()).hexdigest() for name, raw in baseline.items()},
        "unknown_new147_metadata_allowed": False, "new147_native_executed": False})
    _retain("read-cap-observations.json", {"unit_price_minor": 3000000, "invoice_minor": 3000,
        "cogs_minor": 1, "whole_credit_turnover_minor": 6001, "currency_precision": 3,
        "cap_major": "20", "whole_unit_price_major": "3000.000", "observations": observations,
        "unexpected_admissions": violations, "financial_rows_unchanged_after_probes": True,
        "evidence_route": "Existing get embeds original source/entries/evidence; no standalone CR1 evidence route exists"})
    assert not violations, "Whole original KWD unit price was disclosed above current cap: " + ", ".join(violations)
