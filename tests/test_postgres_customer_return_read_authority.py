"""Genuine fractional KWD3 CR1 source price admission, with no source edits."""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from queue import Queue
from threading import Event
from time import monotonic, sleep
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
from reconforge.infrastructure.postgres_customer_returns import PERMISSIONS, READ, PostgresCustomerReturnsRepository
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_inventory_core import PostgresInventoryCoreRepository
from reconforge.infrastructure.postgres_inventory_valuation import PostgresInventoryValuationRepository
from reconforge.infrastructure.postgres_master_data import PostgresMasterDataRepository
from reconforge.infrastructure.postgres_operations import POSTGRES_MIGRATION_REVISIONS
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.infrastructure.postgres_stock_sales import PostgresStockSalesRepository
from reconforge.platform.common import ServerPrincipal, current_server_principal, server_principal_context
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
    runtime = KwdRuntime(base.factory, base.admin_dsn, base.tenant, base.password)
    with PostgresTenantBoundary(base.factory).transaction(base.tenant) as connection:
        # This independent KWD fixture owns its three explicit grants. Reuse the
        # normal identity/finance repositories without inheriting USD grants.
        identities = PostgresIdentityRepository(connection)
        for permission in sorted(set().union(*PERMISSIONS.values())):
            identities.create_permission(tenant_id=base.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=base.tenant, role_name="receipt-operator", permission_name=permission)
        PostgresFinanceCoreRepository(connection, base.tenant).upsert_account(account_code="REFUND",
            name="Customer refund obligation", account_type="Liability", normal_balance="Credit", workspace="work")
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
    # This ordinary SQL custody snapshot does not authenticate a retired human.
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection:
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
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == POSTGRES_MIGRATION_REVISIONS[-1]
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


def _prepared_original(database: tuple[str, str]) -> tuple[KwdRuntime, CustomerReturnPreparation, dict[str, Any], PostingActor, ServerPrincipal]:
    runtime, sale = _setup(database)
    request = _return_request(sale)
    with runtime.actor("maker") as (connection, _, actor):
        prepared = PostgresCustomerReturnsRepository(connection, runtime.tenant).prepare(request,
            command_id="kwd-current-authority-original", actor=actor)
        principal = current_server_principal()
        assert principal is not None
        assert PostgresCustomerReturnsRepository(connection, runtime.tenant).get(prepared["id"], actor=actor) == prepared
    return runtime, request, prepared, actor, principal


def _original_read(connection: Any, runtime: KwdRuntime, request: CustomerReturnPreparation,
                   prepared: dict[str, Any], actor: PostingActor, operation: str) -> dict[str, Any]:
    owner = PostgresCustomerReturnsRepository(connection, runtime.tenant)
    if operation == "get":
        return owner.get(prepared["id"], actor=actor)
    assert operation == "historical-prepare-replay"
    return owner.prepare(request, command_id="kwd-current-authority-original", actor=actor)


def _retire(connection: Any, tenant: str, kind: str) -> int:
    if kind == "human":
        query = """UPDATE reconforge.identity_users SET disabled=TRUE,lifecycle_version=lifecycle_version+1,
            disabled_at=now(),disabled_by='poster' WHERE tenant_id=%s AND id='maker' AND NOT disabled"""
        parameters = (tenant,)
    elif kind == "assignment":
        query = """UPDATE reconforge.identity_user_roles SET active=FALSE,lifecycle_version=lifecycle_version+1,
            revoked_at=now(),revoked_by='poster',revocation_reason_code='security_response'
            WHERE tenant_id=%s AND user_id='maker' AND active"""
        parameters = (tenant,)
    elif kind == "role":
        query = """UPDATE reconforge.identity_roles SET active=FALSE,lifecycle_version=lifecycle_version+1,
            retired_at=now(),retired_by='poster' WHERE tenant_id=%s AND active AND id IN
            (SELECT role_id FROM reconforge.identity_user_roles WHERE tenant_id=%s AND user_id='maker' AND active)"""
        parameters = (tenant, tenant)
    elif kind == "permission":
        query = """UPDATE reconforge.identity_role_permissions SET active=FALSE,lifecycle_version=lifecycle_version+1,
            revoked_at=now(),revoked_by='poster',revocation_reason_code='security_response'
            WHERE tenant_id=%s AND permission_name='finance_core.read' AND active"""
        parameters = (tenant,)
    else:
        assert kind in {"workspace", "organization", "legal_entity"}
        query = """UPDATE reconforge.principal_scope_grants SET revoked_at=now(),revoked_by='poster',
            revocation_reason='security_response' WHERE tenant_id=%s AND id=%s AND revoked_at IS NULL"""
        parameters = (tenant, "kwd-maker-" + kind)
    return connection.execute(query, parameters).rowcount


def _denied_original_reads(connection: Any, runtime: KwdRuntime, request: CustomerReturnPreparation,
                           prepared: dict[str, Any], actor: PostingActor) -> list[str]:
    admissions = []
    for operation in ("get", "historical-prepare-replay"):
        try:
            assert _original_read(connection, runtime, request, prepared, actor, operation) == prepared
            admissions.append(operation)
        except FinancePostingError as refused:
            assert "denied" in refused.code
    return admissions


def test_actual_cached_read_and_original_ack_recheck_all_persisted_authority(receipt_database: tuple[str, str]) -> None:
    runtime, request, prepared, actor, principal = _prepared_original(receipt_database)
    original = _original_tables(runtime)
    admissions: list[str] = []
    observations = []
    for kind in ("human", "assignment", "role", "permission", "workspace", "organization", "legal_entity"):
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection, server_principal_context(principal):
            try:
                with connection.transaction():
                    touched = _retire(connection, runtime.tenant, kind)
                    assert touched > 0
                    unexpected = _denied_original_reads(connection, runtime, request, prepared, actor)
                    observations.append({"retirement": kind, "touched": touched, "unexpected_admissions": unexpected})
                    admissions.extend(kind + ":" + operation for operation in unexpected)
                    # Each supported lifecycle change is real within this transaction;
                    # savepoint rollback permits independent retirement controls.
                    raise _RollbackProbe()
            except _RollbackProbe:
                pass
            for operation in ("get", "historical-prepare-replay"):
                assert _original_read(connection, runtime, request, prepared, actor, operation) == prepared
        assert _original_tables(runtime) == original
    assert len(original) == 67
    _retain("persisted-authority-retirement-observations.json", {"original_ack": prepared,
        "observations": observations, "unexpected_admissions": admissions,
        "original_67_financial_tables_unchanged": True, "persisted_sql_amount_ceiling_proven": False})
    assert not admissions, "Cached original authority admitted retired subjects: " + ", ".join(admissions)


def test_actual_fresh_empty_scope_after_all_grants_retired_is_not_legacy_global(receipt_database: tuple[str, str]) -> None:
    runtime, request, prepared, actor, cached = _prepared_original(receipt_database)
    original = _original_tables(runtime)
    # A genuinely never-granted human retains the original global read contract.
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identities = PostgresIdentityRepository(connection)
        identities.create_user(tenant_id=runtime.tenant, user_id="legacy", username="legacy",
            password=runtime.password, role_name="receipt-operator")
        legacy = identities.authenticate_user(tenant_id=runtime.tenant, username="legacy", password=runtime.password)
        assert legacy is not None
        permissions = identities.user_permissions(tenant_id=runtime.tenant, user_id=legacy.id)
        assert not connection.execute("SELECT id FROM reconforge.principal_scope_grants WHERE tenant_id=%s AND principal_id='legacy'",
            (runtime.tenant,)).fetchall()
    legacy_principal = replace(cached, user=legacy, permissions=permissions, authorized_workspace_ids=frozenset(),
        authorized_organization_ids=frozenset(), authorized_legal_entity_ids=frozenset())
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection, server_principal_context(legacy_principal):
        legacy_actor = PostingActor(legacy.id, legacy.username, permissions, step_up_active=True)
        assert PostgresCustomerReturnsRepository(connection, runtime.tenant).get(prepared["id"], actor=legacy_actor) == prepared
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        for kind in ("workspace", "organization", "legal_entity"):
            assert _retire(connection, runtime.tenant, kind) == 1
        identities = PostgresIdentityRepository(connection)
        fresh_user = identities.authenticate_user(tenant_id=runtime.tenant, username="maker", password=runtime.password)
        assert fresh_user is not None and not fresh_user.disabled
        fresh_permissions = identities.user_permissions(tenant_id=runtime.tenant, user_id=fresh_user.id)
        snapshot = PostgresScopeAuthorityRepository(connection).active_for_principal(
            tenant_id=runtime.tenant, principal_type="user", principal_id=fresh_user.id)
        assert not (snapshot.workspace_ids | snapshot.organization_ids | snapshot.legal_entity_ids)
        history = connection.execute("""SELECT scope_type,scope_id FROM reconforge.principal_scope_grants
            WHERE tenant_id=%s AND principal_id='maker' AND revoked_at IS NOT NULL ORDER BY scope_type""", (runtime.tenant,)).fetchall()
        assert len(history) == 3
    fresh = replace(cached, user=fresh_user, permissions=fresh_permissions, authorized_workspace_ids=snapshot.workspace_ids,
        authorized_organization_ids=snapshot.organization_ids, authorized_legal_entity_ids=snapshot.legal_entity_ids)
    admissions = []
    for label, principal in (("cached", cached), ("fresh-empty", fresh)):
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection, server_principal_context(principal):
            admissions.extend(label + ":" + operation for operation in _denied_original_reads(connection, runtime, request, prepared, actor))
    assert _original_tables(runtime) == original
    _retain("fresh-empty-scope-retirement-observations.json", {"unexpected_admissions": admissions,
        "historical_revoked_parent_count": len(history), "fresh_active_parent_count": 0,
        "never_granted_legacy_get_allowed": True, "original_ack": prepared,
        "original_67_financial_tables_unchanged": True, "persisted_sql_amount_ceiling_proven": False})
    assert not admissions, "Prior scoped history cannot become global through empty fresh capture: " + ", ".join(admissions)


def test_actual_fresh_partial_scope_preserves_each_previously_bounded_parent(receipt_database: tuple[str, str]) -> None:
    runtime, request, prepared, actor, cached = _prepared_original(receipt_database)
    original = _original_tables(runtime)
    admissions = []
    observations = []
    for kind in ("workspace", "organization", "legal_entity"):
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection:
            try:
                with connection.transaction():
                    assert _retire(connection, runtime.tenant, kind) == 1
                    snapshot = PostgresScopeAuthorityRepository(connection).active_for_principal(
                        tenant_id=runtime.tenant, principal_type="user", principal_id="maker")
                    fresh = replace(cached, authorized_workspace_ids=snapshot.workspace_ids,
                        authorized_organization_ids=snapshot.organization_ids, authorized_legal_entity_ids=snapshot.legal_entity_ids)
                    captured = {"workspace": sorted(snapshot.workspace_ids), "organization": sorted(snapshot.organization_ids),
                        "legal_entity": sorted(snapshot.legal_entity_ids)}
                    assert captured[kind] == [] and sum(bool(value) for value in captured.values()) == 2
                    with server_principal_context(fresh):
                        unexpected = _denied_original_reads(connection, runtime, request, prepared, actor)
                    observations.append({"retired_parent_kind": kind, "fresh_captured_sets": captured,
                        "unexpected_admissions": unexpected})
                    admissions.extend(kind + ":" + operation for operation in unexpected)
                    raise _RollbackProbe()
            except _RollbackProbe:
                pass
        assert _original_tables(runtime) == original
    # Explicit workspace-only history keeps the old never-granted child fallback.
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identities = PostgresIdentityRepository(connection)
        identities.create_user(tenant_id=runtime.tenant, user_id="workspace-only", username="workspace-only",
            password=runtime.password, role_name="receipt-operator")
        user = identities.authenticate_user(tenant_id=runtime.tenant, username="workspace-only", password=runtime.password)
        assert user is not None
        permissions = identities.user_permissions(tenant_id=runtime.tenant, user_id=user.id)
        PostgresScopeAuthorityRepository(connection).grant(tenant_id=runtime.tenant, grant_id="legacy-workspace-only",
            principal_type="user", principal_id=user.id, scope_type="workspace", scope_id="work", actor_id="poster")
        snapshot = PostgresScopeAuthorityRepository(connection).active_for_principal(
            tenant_id=runtime.tenant, principal_type="user", principal_id=user.id)
        assert snapshot.workspace_ids == frozenset({"work"}) and not (snapshot.organization_ids | snapshot.legal_entity_ids)
    principal = replace(cached, user=user, permissions=permissions, authorized_workspace_ids=snapshot.workspace_ids,
        authorized_organization_ids=snapshot.organization_ids, authorized_legal_entity_ids=snapshot.legal_entity_ids)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection, server_principal_context(principal):
        assert PostgresCustomerReturnsRepository(connection, runtime.tenant).get(prepared["id"],
            actor=PostingActor(user.id, user.username, permissions, step_up_active=True)) == prepared
    assert _original_tables(runtime) == original
    _retain("fresh-partial-scope-retirement-observations.json", {"observations": observations,
        "unexpected_admissions": admissions, "never_granted_child_fallback_allowed": True,
        "original_ack": prepared, "original_67_financial_tables_unchanged": True})
    assert not admissions, "A formerly bounded parent cannot be omitted from fresh partial scope: " + ", ".join(admissions)


def test_actual_read_price_and_phase_write_amount_use_distinct_original_policy_contexts(
        receipt_database: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, sale = _setup(receipt_database)
    request = _return_request(sale)
    selected_permission, maximum = "finance_core.manage", Decimal("6")
    observations = []

    def policy(principal: Any, **context: Any) -> Any:
        if context["required_permission"] == selected_permission:
            observations.append({"permission": selected_permission, "maximum": str(maximum),
                "amount": str(context["amount"]) if context["amount"] is not None else None})
            return evaluate_principal_access(principal, maximum_amount=maximum, **context)
        return evaluate_principal_access(principal, **context)

    monkeypatch.setattr(policy_module, "evaluate_principal_access", policy)
    plans = []
    for operation, person, permission in (("prepare", "maker", "finance_core.manage"),
            ("review", "checker", "finance_core.validate"), ("post", "poster", "finance_core.post")):
        selected_permission, maximum = permission, Decimal("6")
        original = _original_tables(runtime)
        with runtime.actor(person) as (connection, _, actor), pytest.raises(FinancePostingError) as denied:
            owner = PostgresCustomerReturnsRepository(connection, runtime.tenant)
            if operation == "prepare":
                owner.prepare(request, command_id="phase-value-low-prepare", actor=actor)
            else:
                getattr(owner, operation)(plans[-1]["id"], expected_plan_digest=plans[-1]["plan_digest"],
                    command_id="phase-value-low-" + operation, reason="Refuse below original turnover", actor=actor)
        assert "denied" in denied.value.code and _original_tables(runtime) == original
        maximum = Decimal("20")
        with runtime.actor(person) as (connection, _, actor):
            owner = PostgresCustomerReturnsRepository(connection, runtime.tenant)
            try:
                if operation == "prepare":
                    result = owner.prepare(request, command_id="phase-value-high-prepare", actor=actor)
                else:
                    result = getattr(owner, operation)(plans[-1]["id"], expected_plan_digest=plans[-1]["plan_digest"],
                        command_id="phase-value-high-" + operation, reason="Publish within original turnover cap", actor=actor)
            except FinancePostingError as refused:
                _retain("phase-write-context-refusal.json", {"operation": operation, "code": refused.code,
                    "observations": observations, "invoice_minor": 3000, "cogs_minor": 1,
                    "original_turnover_minor": 6001, "quoted_unit_minor": 3000000, "precision": 3,
                    "policy_max_major": "20", "persisted_sql_amount_ceiling_proven": False})
                pytest.fail("Original 6.001 KWD phase amount must fit WRITE cap20 independently of READ price3000.")
            assert result["amount_minor"] == 6001 and result["source_snapshot"]["stock"]["source"]["unit_price_minor"] == 3000000
            plans.append(result)
    assert plans[-1]["status"] == "Posted" and len(plans[-1]["posting_effect_ids"]) == 3
    # The initial immutable source preview carries invoice3; the fully captured
    # return plan and all later phases carry original aggregate turnover6.001.
    assert observations and {value["amount"] for value in observations} == {"3.000", "6.001"}
    _retain("phase-write-context-admission.json", {"observations": observations, "original_acks": plans,
        "write_cap6_denied_cap20_allowed": True, "original_turnover_minor": 6001, "whole_read_price_minor": 3000000,
        "precision": 3, "persisted_sql_amount_ceiling_proven": False})


def _wait_on(admin_dsn: str, waiter: int, blocker: int) -> None:
    deadline = monotonic() + 6
    with psycopg.connect(admin_dsn) as probe:
        while blocker not in probe.execute("SELECT pg_blocking_pids(%s)", (waiter,)).fetchone()[0]:
            assert monotonic() < deadline, "The exact native waiter/blocker relationship was not observed."
            sleep(0.02)


@pytest.mark.parametrize("kind", ["permission", "legal_entity"])
def test_actual_queued_retirement_before_authority_locks_denies_without_source_lock(
        receipt_database: tuple[str, str], kind: str) -> None:
    runtime, request, prepared, actor, principal = _prepared_original(receipt_database)
    original = _original_tables(runtime)
    started: Queue[int] = Queue()

    def reader() -> list[str]:
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection, server_principal_context(principal):
            connection.execute("SET LOCAL statement_timeout='12s'")
            started.put(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
            return _denied_original_reads(connection, runtime, request, prepared, actor)

    with psycopg.connect(runtime.admin_dsn) as revoker, ThreadPoolExecutor(max_workers=1) as workers:
        revoker_pid = revoker.execute("SELECT pg_backend_pid()").fetchone()[0]
        if kind == "permission":
            assert revoker.execute("""SELECT permission_name FROM reconforge.identity_role_permissions
                WHERE tenant_id=%s AND permission_name='finance_core.read' AND active FOR UPDATE""", (runtime.tenant,)).fetchall()
        else:
            assert revoker.execute("""SELECT id FROM reconforge.principal_scope_grants
                WHERE tenant_id=%s AND id='kwd-maker-legal_entity' AND revoked_at IS NULL FOR UPDATE""", (runtime.tenant,)).fetchone()
        future = workers.submit(reader)
        try:
            reader_pid = started.get(timeout=6)
            _wait_on(runtime.admin_dsn, reader_pid, revoker_pid)
            # Authority-first admission holds no plan row while retirement is queued.
            with psycopg.connect(runtime.admin_dsn) as probe:
                assert probe.execute("""SELECT id FROM reconforge.customer_return_plans
                    WHERE tenant_id=%s AND id=%s FOR UPDATE NOWAIT""", (runtime.tenant, prepared["id"])).fetchone()
            assert _retire(revoker, runtime.tenant, kind) > 0
        finally:
            revoker.commit()
        assert future.result(timeout=15) == []
    assert _original_tables(runtime) == original
    _retain("queued-authority-first-" + kind + ".json", {"retirement": kind, "reader_pid": reader_pid,
        "revoker_pid": revoker_pid, "exact_blocking_observed": True, "plan_update_nowait_succeeded": True,
        "get_and_original_prepare_replay_denied": True, "original_ack": prepared,
        "original_67_financial_tables_unchanged": True})


@pytest.mark.parametrize("kind", ["permission", "legal_entity"])
def test_actual_source_wait_pins_authority_until_read_commits_then_denies_cached_replay(
        receipt_database: tuple[str, str], kind: str) -> None:
    runtime, request, prepared, actor, principal = _prepared_original(receipt_database)
    original = _original_tables(runtime)
    readers: Queue[int] = Queue()
    revokers: Queue[int] = Queue()
    admitted, release_reader = Event(), Event()

    def reader() -> None:
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection, server_principal_context(principal):
            connection.execute("SET LOCAL statement_timeout='12s'")
            readers.put(connection.execute("SELECT pg_backend_pid() pid").fetchone()["pid"])
            for operation in ("get", "historical-prepare-replay"):
                assert _original_read(connection, runtime, request, prepared, actor, operation) == prepared
            admitted.set()
            assert release_reader.wait(timeout=6)

    def revoker() -> None:
        with psycopg.connect(runtime.admin_dsn) as connection:
            connection.execute("SET LOCAL statement_timeout='12s'")
            revokers.put(connection.execute("SELECT pg_backend_pid()").fetchone()[0])
            assert _retire(connection, runtime.tenant, kind) > 0

    with psycopg.connect(runtime.admin_dsn) as source_holder, ThreadPoolExecutor(max_workers=2) as workers:
        source_pid = source_holder.execute("SELECT pg_backend_pid()").fetchone()[0]
        assert source_holder.execute("""SELECT id FROM reconforge.customer_return_plans
            WHERE tenant_id=%s AND id=%s FOR UPDATE""", (runtime.tenant, prepared["id"])).fetchone()
        read_future = workers.submit(reader)
        try:
            reader_pid = readers.get(timeout=6)
            _wait_on(runtime.admin_dsn, reader_pid, source_pid)
            revoke_future = workers.submit(revoker)
            revoker_pid = revokers.get(timeout=6)
            _wait_on(runtime.admin_dsn, revoker_pid, reader_pid)
            source_holder.commit()
            assert admitted.wait(timeout=6)
            assert not revoke_future.done(), "Held authority SHARE prevents retirement committing through this read."
        finally:
            source_holder.rollback()
            release_reader.set()
        read_future.result(timeout=15)
        revoke_future.result(timeout=15)
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, **SCOPE) as connection, server_principal_context(principal):
        assert _denied_original_reads(connection, runtime, request, prepared, actor) == []
    assert _original_tables(runtime) == original
    _retain("queued-source-first-" + kind + ".json", {"retirement": kind, "source_holder_pid": source_pid,
        "reader_pid": reader_pid, "revoker_pid": revoker_pid, "both_exact_blocking_edges_observed": True,
        "original_reads_completed_before_retirement_commit": True, "cached_reads_denied_after_retirement": True,
        "original_ack": prepared, "original_67_financial_tables_unchanged": True})
