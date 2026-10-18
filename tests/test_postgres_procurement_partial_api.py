"""Actual authenticated PostgreSQL API cycles; HTTPS-origin, not wire TLS."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_procurement_operations import request
from tests.test_postgres_procurement_partial import (
    CHECKER,
    MAKER,
    POSTER,
    accrue_partial_invoice,
    create_partial,
    partial_publication_digest,
    partial_runtime,
    prepare_partial_receipt,
    pytestmark,
    receipt_database,
    receive_partial,
    reviewed_partial_publication,
)

__all__ = ["partial_runtime", "pytestmark", "receipt_database"]
ROOT = "/api/v1/procurement-partial"
INSTALLMENTS = "/api/v1/financial-installments/plans"


@contextmanager
def partial_client(runtime: ReceiptRuntime, database: tuple[str, str], tmp_path: Path,
                   username: str, *, step_up: bool = True) -> Iterator[tuple[TestClient, dict[str, str]]]:
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        user = PostgresIdentityRepository(connection).authenticate_user(tenant_id=runtime.tenant, username=username, password=runtime.password)
        assert user is not None and user.id != user.username
        authority = PostgresScopeAuthorityRepository(connection)
        for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
            if connection.execute("""SELECT 1 FROM reconforge.principal_scope_grants WHERE tenant_id=%s AND principal_type='user'
                AND principal_id=%s AND scope_type=%s AND scope_id=%s AND revoked_at IS NULL""",
                (runtime.tenant, user.id, kind, identifier)).fetchone() is None:
                authority.grant(tenant_id=runtime.tenant, grant_id="partial-" + uuid4().hex,
                    principal_type="user", principal_id=user.id, scope_type=kind, scope_id=identifier, actor_id=user.id)
    app = create_api_app(tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants", postgres_dsn=database[1],
                         postgres_require_tls=False, secure_transport=True, policy_cache_enabled=True)
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/api/v1/auth/login", headers={"X-ReconForge-Tenant": runtime.tenant},
                               json={"username": username, "password": runtime.password})
        assert response.status_code == 200, response.text
        headers = {"X-ReconForge-Tenant": runtime.tenant, "X-ReconForge-Workspace": "work",
                   "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity",
                   "Authorization": "Bearer " + response.json()["access_token"]}
        if step_up:
            response = client.post("/api/v1/auth/step-up", headers=headers, json={"password": runtime.password})
            assert response.status_code == 200, response.text
        yield client, headers


def post(client: tuple[TestClient, dict[str, str]], path: str, payload: dict[str, Any], *, replay: bool = True) -> dict[str, Any]:
    transport, headers = client
    response = transport.post(path, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    if replay:
        retried = transport.post(path, headers=headers, json=payload)
        assert retried.status_code == 200 and retried.json() == response.json(), retried.text
    return response.json()


def owner_action(client: tuple[TestClient, dict[str, str]], view: dict[str, Any], operation: str,
                 document_id: str | None = None, **fields: Any) -> dict[str, Any]:
    payload = {"command_id": "api-" + str(view["order"]["row_version"]), "expected_version": view["order"]["row_version"],
               "reason": "Actual exact source and independent approval", **fields}
    if document_id is not None:
        payload["document_id"] = document_id
    return post(client, ROOT + "/orders/" + view["order"]["id"] + "/commands/" + operation, payload)


def test_authenticated_partial_procure_to_pay_has_two_exact_installments(
    receipt_database: tuple[str, str], partial_runtime: ReceiptRuntime, tmp_path: Path,
) -> None:
    runtime = partial_runtime
    with ExitStack() as stack:
        maker, checker, poster = [stack.enter_context(partial_client(runtime, receipt_database, tmp_path / actor, actor))
                                 for actor in (MAKER, CHECKER, POSTER)]
        for route in ("scopes", "options", "orders"):
            response = maker[0].get(ROOT + "/" + route, headers=maker[1])
            assert response.status_code == 200, response.text
        prepared = asdict(request("API-PARTIAL"))
        prepared.update(quantity="10", unit_price_minor=str(prepared["unit_price_minor"]), command_id="api-create")
        view = post(maker, ROOT + "/orders", prepared)
        view = owner_action(maker, view, "submit-order")
        denied = maker[0].post(ROOT + "/orders/" + view["order"]["id"] + "/commands/approve-order", headers=maker[1],
            json={"command_id": "self-approval", "expected_version": view["order"]["row_version"], "reason": "Denied same canonical identity"})
        assert denied.status_code == 409 and denied.json()["error"]["code"] == "procurement_state_conflict", denied.text
        view = owner_action(checker, view, "approve-order")
        for received, invoiced, date in (("4", "3", "2026-10-03"), ("6", "7", "2026-10-04")):
            view = owner_action(maker, view, "prepare-receipt", quantity=received, posting_date=date, period_id="period")
            receipt = view["receipts"][-1]["id"]
            view = owner_action(checker, view, "review-receipt", receipt)
            view = owner_action(poster, view, "receive", receipt)
            view = owner_action(maker, view, "match-invoice", quantity=invoiced, posting_date=date, period_id="period")
            invoice = view["invoices"][-1]["id"]
            for operation, client in (("approve-invoice", checker), ("prepare-accrual", maker), ("review-accrual", checker), ("post-accrual", poster)):
                view = owner_action(client, view, operation, invoice)
        source = view["invoices"][0]["native_invoice_id"]
        order_version = view["order"]["row_version"]
        for index, amount in enumerate(("1500", "2100")):
            plan = post(maker, INSTALLMENTS, {"command_id": "api-payment-prepare-" + str(index), "source_id": source,
                "source_kind": "APPayment", "amount_minor": amount, "journal_code": "STOCK", "period_id": "period",
                "posting_date": "2026-10-04", "debit_account_code": "AP", "credit_account_code": "CASH", "reason": "Approved supplier partial payment"})["plan"]
            detail = maker[0].get(ROOT + "/orders/" + view["order"]["id"], headers=maker[1])
            assert detail.status_code == 200, detail.text
            assert detail.json()["invoices"][0]["installment_plans"][-1]["id"] == plan["id"]
            for phase, client in (("review", checker), ("post", poster)):
                plan = post(client, INSTALLMENTS + "/" + plan["id"] + "/" + phase,
                    {"command_id": "api-payment-" + phase + "-" + str(index), "expected_plan_digest": plan["plan_digest"],
                     "reason": "Independent exact residual review and posting"})["plan"]
            assert plan["amount_minor"] == amount and plan["payment_link_id"] and plan["posting_effect_id"]
            read = maker[0].get(ROOT + "/orders/" + view["order"]["id"], headers=maker[1])
            assert read.status_code == 200, read.text
            view = read.json()
            invoice = view["invoices"][0]
            assert invoice["native_status"] == ("Approved" if index == 0 else "Paid")
            assert invoice["outstanding_minor"] == ("2100" if index == 0 else "0")
            assert view["order"]["row_version"] == order_version and invoice["stage"] == "Accrued"
        assert view["totals"]["paid_minor"] == "3600" and view["totals"]["outstanding_minor"] == "8400"
        with runtime.actor(POSTER) as (connection, _, _):
            assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.tenant,)).fetchone()[0] == 6
            assert tuple(connection.execute("SELECT sum(debit_minor),sum(credit_minor) FROM reconforge.finance_entry_lines WHERE tenant_id=%s", (runtime.tenant,)).fetchone()) == (27600, 27600)


@pytest.mark.parametrize("phase", ["receipt", "accrual"])
def test_authenticated_partial_reviewer_publication_is_refused_before_third_poster_continues(
    receipt_database: tuple[str, str], partial_runtime: ReceiptRuntime, tmp_path: Path, phase: str,
) -> None:
    runtime = partial_runtime
    view, operation, identifier = reviewed_partial_publication(runtime, phase)
    with ExitStack() as stack:
        checker, poster = [stack.enter_context(partial_client(runtime, receipt_database, tmp_path / actor, actor)) for actor in (CHECKER, POSTER)]
        with runtime.actor(CHECKER) as (connection, _, _):
            before = partial_publication_digest(connection, runtime.tenant, include_audit=False)
        payload = {"command_id": "api-third-human-publication", "expected_version": view["order"]["row_version"],
                   "document_id": identifier, "reason": "Publication must be independent of the retained reviewer"}
        path = ROOT + "/orders/" + view["order"]["id"] + "/commands/" + operation
        for _ in range(2):
            denied = checker[0].post(path, headers=checker[1], json=payload)
            assert denied.status_code == 409 and denied.json()["error"]["code"] == "procurement_partial_duties_conflict", denied.text
        read = checker[0].get(ROOT + "/orders/" + view["order"]["id"], headers=checker[1])
        assert read.status_code == 200 and read.json() == view, read.text
        with runtime.actor(CHECKER) as (connection, _, _):
            assert partial_publication_digest(connection, runtime.tenant, include_audit=False) == before
        published = post(poster, path, payload)
        document = published["receipts" if phase == "receipt" else "invoices"][0]
        prefix = "" if phase == "receipt" else "accrual_"
        assert document[prefix + "preparer_actor_id"] == "id-" + MAKER
        assert document[prefix + "reviewer_actor_id"] == "id-" + CHECKER
        assert document[prefix + "posted_actor_id"] == "id-" + POSTER
        assert document["stage"] == ("Posted" if phase == "receipt" else "Accrued")


@pytest.mark.parametrize("participant", ["receipt-prepare", "receipt", "accrual"])
def test_public_generic_review_is_denied_without_mutating_partial_owner(
    receipt_database: tuple[str, str], partial_runtime: ReceiptRuntime, tmp_path: Path, participant: str,
) -> None:
    runtime = partial_runtime
    view = create_partial(runtime)
    if participant == "receipt-prepare":
        plan = None
        path = "/api/v1/inventory-receipt-posting/plans"
        expected = "operational_owner_required"
        payload = {"command_id": "detached-public-prepare", "receipt_number": "PPR-" + view["order"]["number"] + "-1",
                   "posting_date": "2026-10-03", "period_id": "period", "item_code": "ITEM", "location_code": "MAIN/STOCK",
                   "quantity": "4", "total_value_minor": "4800", "policy_code": "FIFO", "organization_code": "ORG",
                   "entity_code": "ENTITY", "workspace": "work", "reason": "Future partial source must be atomically captured"}
    elif participant == "receipt":
        view = prepare_partial_receipt(runtime, view, "4")
        identifier = view["receipts"][0]["receipt_plan_id"]
        with runtime.actor(CHECKER) as (_, receipts, actor):
            plan = receipts.get_plan(identifier, actor=actor)["plan"]
        path = "/api/v1/inventory-receipt-posting/plans/" + identifier + "/review"
        expected = "inventory_receipt_owner_required"
    else:
        view = accrue_partial_invoice(runtime, receive_partial(runtime, view, "4"), "3")
        identifier = view["invoices"][0]["accrual_plan_id"]
        from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
        with runtime.actor(CHECKER) as (connection, _, actor):
            plan = PostgresOperationalFinanceRepository(connection, runtime.tenant).get(identifier, actor=actor)
        path = "/api/v1/operational-finance/plans/" + identifier + "/review"
        expected = "operational_owner_required"
    if plan is not None:
        payload = {"command_id": "detached-public-review", "expected_plan_digest": plan["plan_digest"],
                   "reason": "Owner stage must not advance independently"}
    with partial_client(runtime, receipt_database, tmp_path, CHECKER) as (client, headers):
        denied = client.post(path, headers=headers, json=payload)
        assert denied.status_code == 409 and denied.json()["error"]["code"] == expected, denied.text
        read = client.get(ROOT + "/orders/" + view["order"]["id"], headers=headers)
        assert read.status_code == 200 and read.json() == view, read.text


def test_installment_preparation_cannot_reserve_an_unrelated_liability_mapping(
    receipt_database: tuple[str, str], partial_runtime: ReceiptRuntime, tmp_path: Path,
) -> None:
    from psycopg import sql

    runtime = partial_runtime
    view = accrue_partial_invoice(runtime, receive_partial(runtime, create_partial(runtime), "4"), "3")
    tables = ("financial_installment_plans", "financial_installment_reviews", "financial_installment_links",
              "financial_installment_commands", "finance_entries", "finance_entry_lines", "finance_posting_effects", "ap_payment_links")
    with runtime.actor(MAKER) as (connection, _, _):
        before = {table: connection.execute(sql.SQL("SELECT count(*) AS count FROM reconforge.{} WHERE tenant_id=%s").format(sql.Identifier(table)),
                                            (runtime.tenant,)).fetchone()["count"] for table in tables}
    with partial_client(runtime, receipt_database, tmp_path, MAKER) as (client, headers):
        denied = client.post(INSTALLMENTS, headers=headers, json={"command_id": "wrong-retained-liability",
            "source_id": view["invoices"][0]["native_invoice_id"], "source_kind": "APPayment", "amount_minor": "1500",
            "journal_code": "STOCK", "period_id": "period", "posting_date": "2026-10-04", "debit_account_code": "CLEARING",
            "credit_account_code": "CASH", "reason": "Existing liability account is unrelated to retained AP mapping"})
        assert denied.status_code == 400, denied.text
        assert denied.json()["error"]["code"] == "installment_account_invalid", denied.text
        read = client.get(ROOT + "/orders/" + view["order"]["id"], headers=headers)
        assert read.status_code == 200 and read.json() == view, read.text
    with runtime.actor(MAKER) as (connection, _, _):
        after = {table: connection.execute(sql.SQL("SELECT count(*) AS count FROM reconforge.{} WHERE tenant_id=%s").format(sql.Identifier(table)),
                                           (runtime.tenant,)).fetchone()["count"] for table in tables}
        assert after == before
