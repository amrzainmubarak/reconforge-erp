"""Restricted-role actual purchase-to-stock-to-AP-to-paid-GL cycle."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

from reconforge.application.payables import PurchaseOrderLineInput, SupplierInvoiceLineInput
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.inventory_receipt_posting import ReceiptReversalPreparation
from reconforge.domain.procurement_operations import ProcurementPreparation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.infrastructure.postgres_payables import PostgresPayablesRepository
from reconforge.infrastructure.postgres_payables_payment_link import PostgresPayablesPaymentLinkRepository
from reconforge.infrastructure.postgres_procurement_operations import (
    OPERATIONS,
    PERMISSIONS,
    PostgresProcurementOperationsRepository,
)
from tests.test_postgres_inventory_receipt_posting import (
    ReceiptRuntime,
    create_receipt_runtime,
    pytestmark,
    receipt_database,
)
from tests.test_postgres_inventory_receipt_posting import (
    request as receipt_request,
)

__all__ = ["receipt_database", "pytestmark"]


def seed_procurement(runtime: ReceiptRuntime) -> ReceiptRuntime:
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work", organization_id="org") as connection:
        finance = PostgresFinanceCoreRepository(connection, runtime.tenant)
        finance.upsert_account(account_code="AP", name="Accounts payable", account_type="Liability", normal_balance="Credit", chart_code="DEFAULT", workspace="work")
        finance.upsert_account(account_code="CASH", name="Cash", account_type="Asset", chart_code="DEFAULT", workspace="work")
        PostgresPayablesRepository(connection, runtime.tenant).upsert_supplier(supplier_code="SUP", name="Synthetic supplier", currency_code="USD",
            organization_code="ORG", entity_code="ENTITY", workspace="work", actor_label="maker")
        identities = PostgresIdentityRepository(connection)
        for permission in sorted(frozenset().union(*PERMISSIONS.values(), {"payables.read"})):
            identities.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
    return runtime


def create_procurement_runtime(receipt_database: tuple[str, str], base_runtime: ReceiptRuntime | None = None) -> ReceiptRuntime:
    return seed_procurement(base_runtime or create_receipt_runtime(receipt_database))


@pytest.fixture
def procurement_runtime(receipt_database: tuple[str, str]) -> ReceiptRuntime:
    return create_procurement_runtime(receipt_database)


def request(number: str = "PO-1") -> ProcurementPreparation:
    return ProcurementPreparation(number=number, supplier_code="SUP", item_code="ITEM", quantity="10", unit_price_minor=1200,
        currency_code="USD", posting_date="2026-10-03", period_id="period", location_code="MAIN/STOCK", policy_code="FIFO",
        journal_code="STOCK", ap_account_code="AP", cash_account_code="CASH", organization_code="ORG", entity_code="ENTITY", workspace="work")


def create(runtime: ReceiptRuntime, number: str = "PO-1") -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        assert dict(connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()) == {"rolsuper": False, "rolbypassrls": False}
        return PostgresProcurementOperationsRepository(connection, runtime.tenant).create(request(number), command_id="create-" + number, actor=actor)


ACTORS = ("maker", "checker", "maker", "checker", "poster", "maker", "checker", "maker", "checker", "poster", "maker", "checker", "poster")


def advance(runtime: ReceiptRuntime, view: dict[str, Any], stop: int = 13) -> dict[str, Any]:
    for index in range(view["cycle"]["row_version"] - 1, stop):
        with runtime.actor(ACTORS[index]) as (connection, _, actor):
            repository = PostgresProcurementOperationsRepository(connection, runtime.tenant)
            arguments = {"expected_version": view["cycle"]["row_version"], "command_id": "command-" + str(index), "reason": "Synthetic independent control", "actor": actor}
            view = repository.act(view["cycle"]["id"], OPERATIONS[index], **arguments)
            assert repository.act(view["cycle"]["id"], OPERATIONS[index], **arguments) == view
    return view


def complete_procurement_cycle(runtime: ReceiptRuntime, number: str = "PO-1") -> dict[str, Any]:
    return advance(runtime, create(runtime, number))


def procurement_phase_digest(connection: Any, tenant: str, *, include_audit: bool = True) -> str:
    from psycopg import sql

    from reconforge.domain.finance_posting import digest_payload

    tables = ("procurement_cycles", "procurement_commands", "ap_purchase_orders", "ap_purchase_order_lines",
              "ap_goods_receipts", "ap_goods_receipt_lines", "ap_supplier_invoices", "ap_supplier_invoice_lines",
              "ap_three_way_matches", "ap_payment_links", "ap_payment_link_commands", "operational_finance_plans",
              "operational_finance_reviews", "operational_finance_links", "operational_finance_commands",
              "inventory_receipt_plans", "inventory_receipt_reviews", "inventory_receipt_links", "inventory_receipt_commands",
              "inventory_movements", "inventory_movement_lines", "inventory_valuation_documents", "inventory_valuation_lines",
              "inventory_cost_layers", "finance_entries", "finance_entry_lines", "finance_posting_effects")
    if include_audit:
        tables += ("domain_audit_events", "domain_audit_ledger_state", "outbox_events")
    captured = {}
    for table in tables:
        rows = connection.execute(sql.SQL("SELECT to_jsonb(t) AS payload FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text")
                                  .format(sql.Identifier(table)), (tenant,)).fetchall()
        captured[table] = [row["payload"] for row in rows]
    return digest_payload(captured)


@pytest.mark.parametrize("stop", [3, 4, 7, 8, 9, 10, 11, 12])
def test_generic_participant_cannot_commit_a_detached_procurement_phase(procurement_runtime: ReceiptRuntime, stop: int) -> None:
    import psycopg

    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=stop)
    actor_name = ACTORS[stop]
    with runtime.actor(actor_name) as (connection, _, actor):
        before = procurement_phase_digest(connection, runtime.tenant)
        assert PostgresProcurementOperationsRepository(connection, runtime.tenant).get(view["cycle"]["id"], actor=actor) == view
    # Real engine participants write valid immutable review/GL/payment evidence.
    # Force deferred raw SQL closure before the owner advances: every retained
    # source, financial row and command/audit/outbox write must roll back.
    with pytest.raises(psycopg.errors.CheckViolation, match="Procurement"), runtime.actor(actor_name) as (connection, receipts, actor):
        if stop == 3:
            plan = receipts.get_plan(view["cycle"]["receipt_plan_id"], actor=actor)["plan"]
            receipts.review(plan["plan_id"], command_id="detached-review", expected_plan_digest=plan["plan_digest"], reason="Independent generic review", actor=actor)
        elif stop == 4:
            captured = receipts.get_plan(view["cycle"]["receipt_plan_id"], actor=actor)
            receipts.commit(captured["plan"]["plan_id"], command_id="detached-commit", expected_review_digest=captured["review"]["review_digest"], reason="Independent generic stock GL", actor=actor)
        else:
            owner = PostgresProcurementOperationsRepository(connection, runtime.tenant)
            row = owner._cycle(view["cycle"]["id"])
            owner._finance(row, request(), OPERATIONS[stop], "detached-finance", "Real generic financial participant", actor)
        assert connection.execute("SELECT stage FROM reconforge.procurement_cycles WHERE tenant_id=%s AND id=%s", (runtime.tenant, view["cycle"]["id"])).fetchone()["stage"] == stop
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with runtime.actor(actor_name) as (connection, _, actor):
        assert procurement_phase_digest(connection, runtime.tenant) == before
        assert PostgresProcurementOperationsRepository(connection, runtime.tenant).get(view["cycle"]["id"], actor=actor) == view
    assert advance(runtime, view)["cycle"]["stage"] == "Paid"


@pytest.mark.parametrize("stop", [2, 3, 4, 5, 7, 8, 9, 10, 11, 12])
def test_authenticated_public_engines_refuse_procurement_owned_phase_without_effects(
    procurement_runtime: ReceiptRuntime, stop: int, tmp_path: Path,
) -> None:
    from fastapi.testclient import TestClient

    from reconforge.api import create_api_app
    from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository

    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=stop)
    actor_name = "maker" if stop in (2, 5) else ACTORS[stop]
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        grants = PostgresScopeAuthorityRepository(connection)
        for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
            grants.grant(tenant_id=runtime.tenant, grant_id=f"public-{kind}", principal_type="user", principal_id=actor_name,
                         scope_type=kind, scope_id=identifier, actor_id=actor_name)
    with runtime.actor(actor_name) as (connection, receipts, actor):
        before = procurement_phase_digest(connection, runtime.tenant, include_audit=False)
        receipt = receipts.get_plan(view["cycle"]["receipt_plan_id"], actor=actor) if stop >= 3 else None
        if stop == 2:
            uri = "/api/v1/inventory-receipt-posting/plans"
            body = {"command_id": "public-reserved-prepare", "receipt_number": "GR-PO-1", "posting_date": "2026-10-03", "period_id": "period",
                    "item_code": "ITEM", "location_code": "MAIN/STOCK", "quantity": "10", "total_value_minor": "12000", "policy_code": "FIFO",
                    "organization_code": "ORG", "entity_code": "ENTITY", "workspace": "work", "reason": "Public reserved source must remain governed"}
        elif stop in (7, 10):
            clearing = connection.execute("SELECT account_code FROM reconforge.finance_accounts WHERE tenant_id=%s AND id=%s", (runtime.tenant, receipt["plan"]["mapping"]["receipt_clearing_account_id"])).fetchone()["account_code"]
            uri = "/api/v1/operational-finance/plans"
            body = {"command_id": "public-prepare", "source_kind": "APInvoice" if stop == 7 else "APPayment", "source_id": view["cycle"]["invoice_id"],
                    "journal_code": "STOCK", "period_id": "period", "posting_date": "2026-10-03", "debit_account_code": clearing if stop == 7 else "AP",
                    "credit_account_code": "AP" if stop == 7 else "CASH", "reason": "Public phase must remain governed"}
        elif stop in (3, 4, 5):
            action = {3: "review", 4: "commit", 5: "reversal"}[stop]
            uri = "/api/v1/inventory-receipt-posting/plans/" + receipt["plan"]["plan_id"] + "/" + action
            body = {"command_id": "public-receipt-" + action, "reason": "Public phase must remain governed"}
            if stop == 3:
                body["expected_plan_digest"] = receipt["plan"]["plan_digest"]
            elif stop == 4:
                body["expected_review_digest"] = receipt["review"]["review_digest"]
            else:
                body.update(reversal_number="UNOWNED-RETURN", posting_date="2026-10-04", period_id="period")
        else:
            field = "accrual_plan_id" if stop in (8, 9) else "payment_plan_id"
            plan = PostgresOperationalFinanceRepository(connection, runtime.tenant).get(view["cycle"][field], actor=actor)
            uri = "/api/v1/operational-finance/plans/" + plan["id"] + ("/review" if stop in (8, 11) else "/post")
            body = {"command_id": "public-finance-phase", "expected_plan_digest": plan["plan_digest"], "reason": "Public phase must remain governed"}
    app = create_api_app(tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants", postgres_dsn=runtime.factory.settings.dsn,
                         postgres_require_tls=False, secure_transport=True)
    scope = {"X-ReconForge-Tenant": runtime.tenant, "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity"}
    # HTTPS transport semantics in TestClient; no claim of a real TLS socket.
    with TestClient(app, base_url="https://testserver") as client:
        login = client.post("/api/v1/auth/login", headers=scope, json={"username": actor_name, "password": runtime.password})
        assert login.status_code == 200, login.text
        headers = {**scope, "Authorization": "Bearer " + login.json()["access_token"]}
        assert client.post("/api/v1/auth/step-up", headers=headers, json={"password": runtime.password}).status_code == 200
        denied = client.post(uri, headers=headers, json=body)
        assert denied.status_code == 409, denied.text
        assert "owner_required" in denied.text
        retry = client.post(uri, headers=headers, json=body)
        assert retry.status_code == 409, retry.text
        assert retry.json()["error"]["code"] == denied.json()["error"]["code"]
        assert retry.json()["error"]["message"] == denied.json()["error"]["message"]
    with runtime.actor(actor_name) as (connection, _, actor):
        assert procurement_phase_digest(connection, runtime.tenant, include_audit=False) == before
        assert PostgresProcurementOperationsRepository(connection, runtime.tenant).get(view["cycle"]["id"], actor=actor) == view
    assert advance(runtime, view)["cycle"]["stage"] == "Paid"


def test_reserved_receipt_source_cannot_be_prepared_outside_its_owner_capture(procurement_runtime: ReceiptRuntime) -> None:
    import psycopg

    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=2)
    with runtime.actor("maker") as (connection, _, _actor):
        before = procurement_phase_digest(connection, runtime.tenant)
    with pytest.raises(psycopg.errors.CheckViolation, match="exact owner phase") as refused, runtime.actor("maker") as (connection, receipts, actor):
        receipts.prepare_receipt(receipt_request("GR-PO-1"), command_id="unowned-reserved-source", actor=actor)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert refused.value.diag.constraint_name == "procurement_owner_phase"
    with runtime.actor("maker") as (connection, _, actor):
        assert procurement_phase_digest(connection, runtime.tenant) == before
        assert PostgresProcurementOperationsRepository(connection, runtime.tenant).get(view["cycle"]["id"], actor=actor) == view
    assert advance(runtime, view)["cycle"]["stage"] == "Paid"


@pytest.mark.parametrize("stop", [5, 13])
@pytest.mark.parametrize("commit_inverse", [False, True])
def test_independent_reversal_of_owned_receipt_cannot_commit_any_phase(
    procurement_runtime: ReceiptRuntime, stop: int, commit_inverse: bool,
) -> None:
    import psycopg

    from reconforge.domain.finance_posting import PostingActor
    from reconforge.platform.common import ServerPrincipal, server_principal_context

    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=stop)
    with runtime.actor("maker") as (connection, _, _actor):
        before = procurement_phase_digest(connection, runtime.tenant)
    with pytest.raises(psycopg.errors.CheckViolation, match="supplier return owner") as refused, runtime.actor("maker") as (connection, receipts, actor):
        inverse = receipts.prepare_reversal(ReceiptReversalPreparation(original_plan_id=view["cycle"]["receipt_plan_id"], reversal_number="DETACHED-RETURN",
            posting_date="2026-10-04", period_id="period", reason="Independent inverse of a governed purchase"), command_id="detached-inverse-prepare", actor=actor)
        if commit_inverse:
            # Persisted authenticated humans execute all three participants on
            # the same outer connection, producing a real inverse before the
            # deferred owner invariant rejects and rolls back the complete write.
            identities = PostgresIdentityRepository(connection)
            for name in ("checker", "poster"):
                user = identities.authenticate_user(tenant_id=runtime.tenant, username=name, password=runtime.password)
                assert user is not None
                permissions = identities.user_permissions(tenant_id=runtime.tenant, user_id=user.id)
                principal = ServerPrincipal(user=user, permissions=permissions, step_up_active=True,
                    authorized_tenant_ids=frozenset({runtime.tenant}), authorized_workspace_ids=frozenset({"work"}),
                    authorized_organization_ids=frozenset({"org"}), authorized_legal_entity_ids=frozenset({"entity"}))
                with server_principal_context(principal):
                    participant = PostingActor(user.id, user.username, permissions, step_up_active=True)
                    if name == "checker":
                        review = receipts.review(inverse["plan_id"], command_id="detached-inverse-review", expected_plan_digest=inverse["plan_digest"],
                            reason="Independent valid inverse review", actor=participant)
                    else:
                        receipts.commit(inverse["plan_id"], command_id="detached-inverse-commit", expected_review_digest=review["review_digest"],
                            reason="Independent valid inverse post", actor=participant)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert refused.value.diag.constraint_name == "procurement_owner_phase"
    with runtime.actor("maker") as (connection, _, actor):
        assert procurement_phase_digest(connection, runtime.tenant) == before
        assert PostgresProcurementOperationsRepository(connection, runtime.tenant).get(view["cycle"]["id"], actor=actor) == view
    assert advance(runtime, view)["cycle"]["stage"] == "Paid"


def native_source_body(runtime: ReceiptRuntime, view: dict[str, Any], kind: str) -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, _actor):
        order = PostgresPayablesRepository(connection, runtime.tenant).get_purchase_order(view["cycle"]["purchase_order_id"])
    if kind == "receipt":
        return {"receipt_number": "DETACHED-GOODS", "purchase_order_id": order["id"], "receipt_date": "2026-10-03",
                "quantities": {order["lines"][0]["id"]: "10"}, "workspace": "work", "idempotency_key": "external-source"}
    return {"invoice_number": "DETACHED-INVOICE", "supplier_code": "SUP", "invoice_date": "2026-10-03", "currency_code": "USD", "total_minor": 12000,
            "lines": [{"purchase_order_line_id": order["lines"][0]["id"], "invoiced_quantity": "10", "unit_price_minor": 1200, "line_total_minor": 12000}],
            "purchase_order_id": order["id"], "workspace": "work", "organization_code": "ORG", "entity_code": "ENTITY", "idempotency_key": "external-source"}


def scoped_source_client(runtime: ReceiptRuntime, tmp_path: Path) -> Any:
    from fastapi.testclient import TestClient

    from reconforge.api import create_api_app
    from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository

    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        grants = PostgresScopeAuthorityRepository(connection)
        for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
            grants.grant(tenant_id=runtime.tenant, grant_id=f"source-{kind}", principal_type="user", principal_id="maker",
                scope_type=kind, scope_id=identifier, actor_id="maker")
    app = create_api_app(tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants", postgres_dsn=runtime.factory.settings.dsn,
        postgres_require_tls=False, secure_transport=True)
    return TestClient(app, base_url="https://testserver")


def scoped_source_headers(client: Any, runtime: ReceiptRuntime) -> dict[str, str]:
    scope = {"X-ReconForge-Tenant": runtime.tenant, "X-ReconForge-Workspace": "work", "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity"}
    response = client.post("/api/v1/auth/login", headers=scope, json={"username": "maker", "password": runtime.password})
    assert response.status_code == 200, response.text
    headers = {**scope, "Authorization": "Bearer " + response.json()["access_token"]}
    assert client.post("/api/v1/auth/step-up", headers=headers, json={"password": runtime.password}).status_code == 200
    return headers


@pytest.mark.parametrize("kind", ["receipt", "invoice"])
def test_native_ap_source_cannot_consume_owned_po_before_source_capture(procurement_runtime: ReceiptRuntime, kind: str) -> None:
    import psycopg

    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=2 if kind == "receipt" else 5)
    body = native_source_body(runtime, view, kind)
    with runtime.actor("maker") as (connection, _, _actor):
        before = procurement_phase_digest(connection, runtime.tenant)
    with pytest.raises(psycopg.errors.CheckViolation, match="exact atomic owner source") as refused, runtime.actor("maker") as (connection, _, actor):
        ap = PostgresPayablesRepository(connection, runtime.tenant)
        if kind == "receipt":
            ap.post_receipt(**body, actor_label=actor.user_id)
        else:
            ap.create_supplier_invoice(**{**body, "lines": [SupplierInvoiceLineInput(**line) for line in body["lines"]]}, actor_label=actor.user_id)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert refused.value.diag.constraint_name == "procurement_owner_phase"
    with runtime.actor("maker") as (connection, _, actor):
        assert procurement_phase_digest(connection, runtime.tenant) == before
        assert PostgresProcurementOperationsRepository(connection, runtime.tenant).get(view["cycle"]["id"], actor=actor) == view
    assert advance(runtime, view)["cycle"]["stage"] == "Paid"


@pytest.mark.parametrize("kind", ["receipt", "invoice"])
def test_authenticated_native_ap_source_capture_is_refused_atomically_with_safe_conflict(
    procurement_runtime: ReceiptRuntime, kind: str, tmp_path: Path,
) -> None:
    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=2 if kind == "receipt" else 5)
    body = native_source_body(runtime, view, kind)
    with scoped_source_client(runtime, tmp_path) as client:
        headers = scoped_source_headers(client, runtime)
        with runtime.actor("maker") as (connection, _, _actor):
            before = procurement_phase_digest(connection, runtime.tenant, include_audit=False)
        uri = "/api/v1/payables/" + ("receipts" if kind == "receipt" else "invoices")
        for _ in range(2):
            refused = client.post(uri, headers=headers, json=body)
            assert refused.status_code == 409, refused.text
            assert refused.json()["error"]["code"] == "operational_owner_required"
    with runtime.actor("maker") as (connection, _, actor):
        assert procurement_phase_digest(connection, runtime.tenant, include_audit=False) == before
        assert PostgresProcurementOperationsRepository(connection, runtime.tenant).get(view["cycle"]["id"], actor=actor) == view
    assert advance(runtime, view)["cycle"]["stage"] == "Paid"


def prior_reserved_receipt(runtime: ReceiptRuntime, posted: bool) -> dict[str, Any]:
    with runtime.actor("maker") as (_, receipts, actor):
        plan = receipts.prepare_receipt(receipt_request("GR-PO-1"), command_id="prior-independent-receipt", actor=actor)
    if posted:
        post_prior_receipt(runtime, plan)
    return plan


def post_prior_receipt(runtime: ReceiptRuntime, plan: dict[str, Any]) -> None:
    with runtime.actor("checker") as (_, receipts, actor):
        review = receipts.review(plan["plan_id"], command_id="prior-independent-review", expected_plan_digest=plan["plan_digest"], reason="Independent prior source", actor=actor)
    with runtime.actor("poster") as (_, receipts, actor):
        receipts.commit(plan["plan_id"], command_id="prior-independent-commit", expected_review_digest=review["review_digest"], reason="Post prior independent source", actor=actor)


@pytest.mark.parametrize("posted", [False, True])
def test_cycle_creation_cannot_claim_prior_reserved_receipt_history(procurement_runtime: ReceiptRuntime, posted: bool) -> None:
    import psycopg

    runtime = procurement_runtime
    plan = prior_reserved_receipt(runtime, posted)
    with runtime.actor("maker") as (connection, _, _actor):
        before = procurement_phase_digest(connection, runtime.tenant)
    with pytest.raises(psycopg.errors.CheckViolation, match="reserved receipt source must be absent") as refused, runtime.actor("maker") as (connection, _, actor):
        PostgresProcurementOperationsRepository(connection, runtime.tenant).create(request(), command_id="create-PO-1", actor=actor)
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
    assert refused.value.diag.constraint_name == "procurement_owner_phase"
    with runtime.actor("maker") as (connection, receipts, actor):
        assert procurement_phase_digest(connection, runtime.tenant) == before
        assert receipts.get_plan(plan["plan_id"], actor=actor)["plan"] == plan
    if not posted:
        post_prior_receipt(runtime, plan)
    assert advance(runtime, create(runtime, "PO-2"))["cycle"]["stage"] == "Paid"


def test_authenticated_cycle_creation_conflict_preserves_prior_posted_receipt(procurement_runtime: ReceiptRuntime, tmp_path: Path) -> None:
    runtime = procurement_runtime
    plan = prior_reserved_receipt(runtime, True)
    body = {**asdict(request()), "unit_price_minor": "1200", "command_id": "public-conflicting-create"}
    with scoped_source_client(runtime, tmp_path) as client:
        headers = scoped_source_headers(client, runtime)
        with runtime.actor("maker") as (connection, _, _actor):
            before = procurement_phase_digest(connection, runtime.tenant, include_audit=False)
        for _ in range(2):
            refused = client.post("/api/v1/procurement-operations/cycles", headers=headers, json=body)
            assert refused.status_code == 409, refused.text
            assert refused.json()["error"]["code"] == "operational_owner_required"
    with runtime.actor("maker") as (connection, receipts, actor):
        assert procurement_phase_digest(connection, runtime.tenant, include_audit=False) == before
        assert receipts.get_plan(plan["plan_id"], actor=actor)["plan"] == plan
    assert advance(runtime, create(runtime, "PO-2"))["cycle"]["stage"] == "Paid"


def seed_distinct_procurement_identities(runtime: ReceiptRuntime) -> None:
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identities = PostgresIdentityRepository(connection)
        for name in ("maker", "checker", "poster"):
            identities.create_user(tenant_id=runtime.tenant, user_id="erp-" + name, username="login-" + name,
                password=runtime.password, role_name="receipt-operator")


def test_distinct_login_and_id_cannot_self_approve_through_native_ap_and_full_cycle_succeeds(procurement_runtime: ReceiptRuntime) -> None:
    import psycopg

    runtime = procurement_runtime
    seed_distinct_procurement_identities(runtime)
    with runtime.actor("login-maker") as (connection, _, actor):
        assert actor.user_id == "erp-maker" and actor.username == "login-maker"
        view = PostgresProcurementOperationsRepository(connection, runtime.tenant).create(request(), command_id="alias-create", actor=actor)
    for index, actor_name in enumerate(ACTORS):
        if index in (1, 6):
            # Native API passes the canonical current_user.id. Same-person
            # approval must fail even though the user's login is different.
            with runtime.actor("login-maker") as (connection, _, actor):
                ap = PostgresPayablesRepository(connection, runtime.tenant)
                with pytest.raises(Exception, match="Separation of duties"):
                    if index == 1:
                        ap.approve_purchase_order(view["cycle"]["purchase_order_id"], expected_version=2, actor_label=actor.user_id)
                    else:
                        invoice = ap.get_supplier_invoice(view["cycle"]["invoice_id"])
                        ap.approve_supplier_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.user_id)
            # Even an independent native approval cannot advance the source
            # without its procurement command, audit and stage in the owner.
            with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("login-checker") as (connection, _, actor):
                ap = PostgresPayablesRepository(connection, runtime.tenant)
                if index == 1:
                    ap.approve_purchase_order(view["cycle"]["purchase_order_id"], expected_version=2, actor_label=actor.user_id)
                else:
                    invoice = ap.get_supplier_invoice(view["cycle"]["invoice_id"])
                    ap.approve_supplier_invoice(invoice["id"], expected_version=invoice["row_version"], actor_label=actor.user_id)
        with runtime.actor("login-" + actor_name) as (connection, _, actor):
            repository = PostgresProcurementOperationsRepository(connection, runtime.tenant)
            arguments = {"expected_version": index + 1, "command_id": "alias-" + str(index), "reason": "Independent canonical actor", "actor": actor}
            view = repository.act(view["cycle"]["id"], OPERATIONS[index], **arguments)
            assert repository.act(view["cycle"]["id"], OPERATIONS[index], **arguments) == view
    assert view["cycle"]["stage"] == "Paid"
    with runtime.actor("login-poster") as (connection, _, actor):
        ap = PostgresPayablesRepository(connection, runtime.tenant)
        po = ap.get_purchase_order(view["cycle"]["purchase_order_id"])
        invoice = ap.get_supplier_invoice(view["cycle"]["invoice_id"])
        assert (po["created_by"], po["approved_by"], invoice["created_by"], invoice["approved_by"]) == ("erp-maker", "erp-checker", "erp-maker", "erp-checker")
        assert invoice["status"] == "Paid"
        assert connection.execute("SELECT count(*) AS n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 3
        rows = connection.execute("SELECT actor_id FROM reconforge.procurement_commands WHERE tenant_id=%s ORDER BY cycle_version", (runtime.tenant,)).fetchall()
        assert [row["actor_id"] for row in rows] == ["erp-maker", *["erp-" + name for name in ACTORS]]
        assert PostgresProcurementOperationsRepository(connection, runtime.tenant).get(view["cycle"]["id"], actor=actor) == view


def test_retained_approval_cannot_be_reassigned_to_another_real_identity(procurement_runtime: ReceiptRuntime) -> None:
    import psycopg

    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=2)
    with pytest.raises(psycopg.errors.CheckViolation, match="retained command actor"), runtime.actor("poster") as (connection, _, _actor):
        connection.execute("UPDATE reconforge.ap_purchase_orders SET approved_by='poster' WHERE tenant_id=%s AND id=%s", (runtime.tenant, view["cycle"]["purchase_order_id"]))
    with runtime.actor("checker") as (connection, _, actor):
        assert PostgresProcurementOperationsRepository(connection, runtime.tenant).get(view["cycle"]["id"], actor=actor) == view


def test_retained_line_cannot_move_to_unrelated_native_order_before_receiving(procurement_runtime: ReceiptRuntime) -> None:
    import psycopg

    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=2)
    with runtime.actor("maker") as (connection, _, actor):
        ap = PostgresPayablesRepository(connection, runtime.tenant)
        other = ap.create_purchase_order(po_number="UNRELATED", supplier_code="SUP", order_date="2026-10-03", currency_code="USD",
            lines=[PurchaseOrderLineInput(item_code="ITEM", ordered_quantity="1", unit_price_minor=1200)],
            workspace="work", organization_code="ORG", entity_code="ENTITY", actor_label=actor.user_id)
        original = ap.get_purchase_order(view["cycle"]["purchase_order_id"])
    with pytest.raises(psycopg.errors.CheckViolation, match="source differs from its exact purchase order"), runtime.actor("maker") as (connection, _, _actor):
        connection.execute("UPDATE reconforge.ap_purchase_order_lines SET purchase_order_id=%s,line_number=2 WHERE tenant_id=%s AND purchase_order_id=%s",
            (other["id"], runtime.tenant, original["id"]))
    with runtime.actor("poster") as (connection, _, actor):
        assert PostgresPayablesRepository(connection, runtime.tenant).get_purchase_order(original["id"]) == original
        assert PostgresProcurementOperationsRepository(connection, runtime.tenant).get(view["cycle"]["id"], actor=actor) == view
        assert connection.execute("SELECT count(*) AS n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0


def test_historical_actor_resolution_retains_disabled_identity_and_denies_ambiguous_alias(procurement_runtime: ReceiptRuntime) -> None:
    import psycopg

    runtime = procurement_runtime
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identities = PostgresIdentityRepository(connection)
        identities.create_user(tenant_id=runtime.tenant, user_id="retired-id", username="retired-login", password=runtime.password, role_name="receipt-operator")
        connection.execute("UPDATE reconforge.identity_users SET disabled=TRUE,disabled_at=now(),disabled_by='poster' WHERE tenant_id=%s AND id='retired-id'", (runtime.tenant,))
        assert connection.execute("SELECT reconforge.procurement_actor_id(%s,'retired-login') AS id", (runtime.tenant,)).fetchone()["id"] == "retired-id"
        assert connection.execute("SELECT reconforge.procurement_actor_id(%s,'retired-id') AS id", (runtime.tenant,)).fetchone()["id"] == "retired-id"
        identities.create_user(tenant_id=runtime.tenant, user_id="other-id", username="retired-id", password=runtime.password, role_name="receipt-operator")
    with pytest.raises(psycopg.errors.CheckViolation, match="absent or ambiguous"), runtime.actor("poster") as (connection, _, _actor):
        connection.execute("SELECT reconforge.procurement_actor_id(%s,'retired-id')", (runtime.tenant,))


def test_options_are_named_json_serializable_scoped_and_bounded(procurement_runtime: ReceiptRuntime) -> None:
    runtime = procurement_runtime
    with runtime.actor("maker") as (connection, _, actor):
        suppliers = PostgresPayablesRepository(connection, runtime.tenant)
        for index in range(201):
            suppliers.upsert_supplier(supplier_code=f"Z-{index:03d}", name=f"Synthetic vendor {index}", currency_code="USD",
                workspace="work", organization_code="ORG", entity_code="ENTITY", actor_label=actor.username)
        value = PostgresProcurementOperationsRepository(connection, runtime.tenant).options("work", "ORG", "ENTITY", actor=actor)
        response = json.loads(json.dumps(value))
        assert set(response) == {"suppliers", "items", "locations", "policies", "periods", "journals", "accounts"}
        assert len(response["suppliers"]) == 200
        assert all(isinstance(row, dict) for rows in response.values() for row in rows)
        assert all(len(rows) <= 200 for rows in response.values())
        assert response["suppliers"][0] == {"code": "SUP", "name": "Synthetic supplier", "currency_code": "USD"}
        assert response["items"][0]["code"] == "ITEM" and response["locations"][0]["code"] == "MAIN/STOCK"
        assert response["policies"][0] == {"code": "FIFO", "currency_code": "USD"}
        assert response["periods"] == [{"id": "period", "name": "2026-10", "start_date": "2026-10-01", "end_date": "2026-10-31"}]
        assert response["journals"][0]["code"] == "STOCK" and response["journals"][0]["chart_code"] == "DEFAULT"
        assert {row["code"] for row in response["accounts"]} >= {"AP", "CASH"}
        assert all(row["chart_code"] == "DEFAULT" for row in response["accounts"])


def test_options_exclude_accounts_without_reviewed_manual_posting_authority(procurement_runtime: ReceiptRuntime) -> None:
    runtime = procurement_runtime
    # Workspace financial masters require broader authority than an entity-selected read.
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant, workspace_id="work", organization_id="org") as connection:
        finance = PostgresFinanceCoreRepository(connection, runtime.tenant)
        finance.upsert_account(account_code="BLOCKED", name="Synthetic blocked manual account", account_type="Liability",
            normal_balance="Credit", chart_code="DEFAULT", workspace="work", allow_manual_posting=False)
        finance.upsert_account(account_code="INACTIVE", name="Synthetic inactive account", account_type="Asset",
            chart_code="DEFAULT", workspace="work", active=False)
    with runtime.actor("maker") as (connection, _, actor):
        value = PostgresProcurementOperationsRepository(connection, runtime.tenant).options("work", "ORG", "ENTITY", actor=actor)
        codes = {row["code"] for row in value["accounts"]}
        assert {"BLOCKED", "INACTIVE"}.isdisjoint(codes) and {"AP", "CASH"} <= codes


def test_actual_full_cycle_has_fifo_stock_cleared_accrual_paid_ap_and_exact_gl(procurement_runtime: ReceiptRuntime) -> None:
    runtime = procurement_runtime
    view = complete_procurement_cycle(runtime)
    assert view["cycle"]["stage"] == "Paid" and view["cycle"]["total_minor"] == "12000"
    with runtime.actor("poster") as (connection, _, actor):
        repository = PostgresProcurementOperationsRepository(connection, runtime.tenant)
        assert repository.get(view["cycle"]["id"], actor=actor) == view
        invoice = PostgresPayablesRepository(connection, runtime.tenant).get_supplier_invoice(view["cycle"]["invoice_id"])
        assert invoice["status"] == "Paid"
        layers = connection.execute("SELECT remaining_quantity_scaled,remaining_value_minor FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchall()
        assert [dict(layer) for layer in layers] == [{"remaining_quantity_scaled": 10, "remaining_value_minor": 12000}]
        effects = connection.execute("SELECT count(*) AS n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()
        assert effects["n"] == 3
        balances = connection.execute("""SELECT a.account_code,sum(l.debit_minor-l.credit_minor) AS balance
            FROM reconforge.finance_entry_lines l JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id
            JOIN reconforge.finance_posting_effects e ON e.tenant_id=l.tenant_id AND e.entry_id=l.entry_id WHERE l.tenant_id=%s GROUP BY a.account_code""", (runtime.tenant,)).fetchall()
        assert {row["account_code"]: int(row["balance"]) for row in balances} == {"INVENTORY": 12000, "CLEARING": 0, "AP": 0, "CASH": -12000}
        assert connection.execute("SELECT count(*) AS n FROM reconforge.procurement_commands WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 14


def test_same_actor_order_approval_and_altered_replay_are_denied(procurement_runtime: ReceiptRuntime) -> None:
    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=1)
    with runtime.actor("maker") as (connection, _, actor):
        repository = PostgresProcurementOperationsRepository(connection, runtime.tenant)
        with pytest.raises(Exception, match="Separation of duties"):
            repository.act(view["cycle"]["id"], "approve-order", expected_version=2, command_id="bad-approve", reason="Invalid self approval", actor=actor)
        with pytest.raises(FinancePostingError, match="exact request"):
            repository.create(replace(request(), unit_price_minor=1201), command_id="create-PO-1", actor=actor)
        assert repository.get(view["cycle"]["id"], actor=actor)["cycle"]["stage"] == "Submitted"


def test_receiving_late_ap_failure_rolls_back_stock_fifo_gl_and_then_safe_retry(procurement_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=4)
    original = PostgresPayablesRepository.post_receipt
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Synthetic late AP receipt failure")
    monkeypatch.setattr(PostgresPayablesRepository, "post_receipt", fail)
    with runtime.actor("poster") as (connection, _, actor):
        with pytest.raises(RuntimeError, match="late AP"):
            PostgresProcurementOperationsRepository(connection, runtime.tenant).act(view["cycle"]["id"], "receive", expected_version=5, command_id="receive-fail", reason="Synthetic receipt", actor=actor)
        for table in ("inventory_movements", "inventory_cost_layers", "finance_posting_effects", "ap_goods_receipts"):
            assert connection.execute("SELECT count(*) AS n FROM reconforge." + table + " WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
    monkeypatch.setattr(PostgresPayablesRepository, "post_receipt", original)
    assert advance(runtime, view, stop=5)["cycle"]["stage"] == "Received"


def test_payment_late_settlement_failure_keeps_invoice_unpaid_and_rolls_back_new_gl(procurement_runtime: ReceiptRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=12)
    original = PostgresPayablesPaymentLinkRepository.link_finance_payment
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Synthetic late settlement failure")
    monkeypatch.setattr(PostgresPayablesPaymentLinkRepository, "link_finance_payment", fail)
    with runtime.actor("poster") as (connection, _, actor):
        with pytest.raises(RuntimeError, match="late settlement"):
            PostgresProcurementOperationsRepository(connection, runtime.tenant).act(view["cycle"]["id"], "pay", expected_version=13, command_id="payment-fail", reason="Synthetic payment", actor=actor)
        assert connection.execute("SELECT count(*) AS n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 2
        assert PostgresPayablesRepository(connection, runtime.tenant).get_supplier_invoice(view["cycle"]["invoice_id"])["status"] == "Approved"
    monkeypatch.setattr(PostgresPayablesPaymentLinkRepository, "link_finance_payment", original)
    assert advance(runtime, view)["cycle"]["stage"] == "Paid"


def test_six_connections_one_create_command_produces_one_po_and_ack(procurement_runtime: ReceiptRuntime) -> None:
    runtime = procurement_runtime
    with ThreadPoolExecutor(max_workers=6) as pool:
        views = list(pool.map(lambda _: create(runtime, "CONCURRENT"), range(6)))
    assert all(view == views[0] for view in views)
    with runtime.actor("maker") as (connection, _, _actor):
        assert connection.execute("SELECT count(*) AS n FROM reconforge.procurement_cycles WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) AS n FROM reconforge.ap_purchase_orders WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1


def test_raw_stage_without_command_evidence_rolls_back_order_transition(procurement_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = procurement_runtime
    view = create(runtime)
    with pytest.raises(psycopg.errors.CheckViolation, match="exactly one retained command"), runtime.actor("maker") as (connection, _, _actor):
        PostgresPayablesRepository(connection, runtime.tenant).submit_purchase_order(view["cycle"]["purchase_order_id"], expected_version=1, actor_label="maker")
        connection.execute("UPDATE reconforge.procurement_cycles SET stage=1,row_version=2 WHERE tenant_id=%s AND id=%s", (runtime.tenant, view["cycle"]["id"]))
    with runtime.actor("maker") as (connection, _, actor):
        assert PostgresProcurementOperationsRepository(connection, runtime.tenant).get(view["cycle"]["id"], actor=actor)["cycle"]["stage"] == "Draft"


def test_retained_po_line_change_and_command_evidence_delete_are_refused(procurement_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=5)
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("maker") as (connection, _, _actor):
        connection.execute("UPDATE reconforge.ap_purchase_order_lines SET ordered_quantity=11,ordered_quantity_text='11' WHERE tenant_id=%s AND purchase_order_id=%s", (runtime.tenant, view["cycle"]["purchase_order_id"]))
    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"), runtime.actor("maker") as (connection, _, _actor):
        connection.execute("DELETE FROM reconforge.procurement_commands WHERE tenant_id=%s AND cycle_id=%s", (runtime.tenant, view["cycle"]["id"]))


def test_real_stock_effect_cannot_be_attached_as_invoice_accrual(procurement_runtime: ReceiptRuntime) -> None:
    import psycopg
    runtime = procurement_runtime
    view = advance(runtime, create(runtime), stop=9)
    with pytest.raises(psycopg.errors.CheckViolation, match="accrual effect must belong"), runtime.actor("poster") as (connection, _, _actor):
        effect = connection.execute("SELECT posting_effect_id FROM reconforge.inventory_receipt_links WHERE tenant_id=%s AND plan_id=%s", (runtime.tenant, view["cycle"]["receipt_plan_id"])).fetchone()["posting_effect_id"]
        connection.execute("UPDATE reconforge.procurement_cycles SET stage=10,row_version=row_version+1,accrual_effect_id=%s WHERE tenant_id=%s AND id=%s", (effect, runtime.tenant, view["cycle"]["id"]))


def test_entity_alias_confusion_hides_both_cycle_and_commands(procurement_runtime: ReceiptRuntime) -> None:
    runtime = procurement_runtime
    view = create(runtime)
    with runtime.actor("maker") as (connection, _, _actor):
        connection.execute("SELECT set_config('app.entity_id','foreign',true)")
        for table in ("procurement_cycles", "procurement_commands"):
            assert connection.execute("SELECT count(*) AS n FROM reconforge." + table + " WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0
    assert view["cycle"]["stage"] == "Draft"


def test_populated_downgrade_refuses_erasing_retained_sources(procurement_runtime: ReceiptRuntime) -> None:
    import psycopg

    from reconforge.infrastructure.postgres_procurement_operations_schema import DOWNGRADE_SQL
    runtime = procurement_runtime
    create(runtime)
    with psycopg.connect(runtime.admin_dsn) as admin, pytest.raises(psycopg.errors.RaiseException, match="Retained procurement cycles prohibit downgrade"), admin.transaction():
        admin.execute(DOWNGRADE_SQL)
