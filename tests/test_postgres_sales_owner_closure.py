"""Actual owner phase closure against detached Finance and native AR commands."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.application.receivables import ReceiptAllocationInput
from reconforge.domain.operational_finance import OperationalFinancePreparation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_sales_revenue import (
    create_fulfilled_sale,
    create_reviewed_collection,
    create_reviewed_invoice,
    invoice_preparation,
    receipt_database,
    repository,
    sales_runtime,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"),
    reason="Owned native PostgreSQL prerequisite; docs/operations/sales-revenue.md; review 2026-10-08",
)
_ = receipt_database, sales_runtime


def prepared_invoice(runtime: ReceiptRuntime, number: str) -> dict[str, Any]:
    document = create_fulfilled_sale(runtime, number)
    with runtime.actor("maker") as (connection, _, actor):
        return repository(connection, runtime).prepare_invoice(
            document["id"],
            invoice_preparation(number + "-INV"),
            expected_version=5,
            command_id=number + "-prepare",
            actor=actor,
        )


def invoiced_sale(runtime: ReceiptRuntime, number: str) -> dict[str, Any]:
    document = create_reviewed_invoice(runtime, number)
    with runtime.actor("poster") as (connection, _, actor):
        return repository(connection, runtime).post_invoice(
            document["id"],
            expected_version=7,
            command_id=number + "-post",
            reason="Publish actual service revenue",
            actor=actor,
        )


def pending_collection(runtime: ReceiptRuntime, number: str) -> dict[str, Any]:
    document = invoiced_sale(runtime, number)
    with runtime.actor("maker") as (connection, _, actor):
        return repository(connection, runtime).prepare_collection(
            document["id"],
            expected_version=8,
            command_id=number + "-collection",
            reason="Capture actual complete payment evidence",
            receipt_number=number + "-RECEIPT",
            receipt_date="2026-10-09",
            journal_code="CASH",
            period_id="period",
            cash_account_code="CASH",
            actor=actor,
        )


def retained_state(runtime: ReceiptRuntime, identifier: str) -> dict[str, Any]:
    with runtime.actor("checker") as (connection, _, actor):
        return {
            "document": repository(connection, runtime).get(identifier, actor=actor),
            "native_counts": dict(
                connection.execute(
                    """SELECT
                (SELECT count(*) FROM reconforge.ar_receipts WHERE tenant_id=%s) receipts,
                (SELECT count(*) FROM reconforge.ar_receipt_allocations WHERE tenant_id=%s) allocations,
                (SELECT count(*) FROM reconforge.operational_finance_plans WHERE tenant_id=%s) plans,
                (SELECT count(*) FROM reconforge.operational_finance_reviews WHERE tenant_id=%s) reviews,
                (SELECT count(*) FROM reconforge.operational_finance_links WHERE tenant_id=%s) links,
                (SELECT count(*) FROM reconforge.operational_finance_commands WHERE tenant_id=%s) commands,
                (SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s) effects,
                (SELECT count(*) FROM reconforge.domain_audit_events WHERE tenant_id=%s) audits,
                (SELECT count(*) FROM reconforge.outbox_events WHERE tenant_id=%s) outbox""",
                    (runtime.tenant,) * 9,
                ).fetchone()
            ),
        }


def authenticated_headers(client: TestClient, runtime: ReceiptRuntime, actor_name: str) -> dict[str, str]:
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        authority = PostgresScopeAuthorityRepository(connection)
        for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
            authority.grant(
                tenant_id=runtime.tenant,
                grant_id=actor_name + "-" + kind,
                principal_type="user",
                principal_id=actor_name,
                scope_type=kind,
                scope_id=identifier,
                actor_id=actor_name,
            )
    login = client.post(
        "/api/v1/auth/login",
        headers={"X-ReconForge-Tenant": runtime.tenant},
        json={"username": actor_name, "password": runtime.password},
    )
    assert login.status_code == 200, login.text
    headers = {
        "X-ReconForge-Tenant": runtime.tenant,
        "X-ReconForge-Workspace": "work",
        "X-ReconForge-Organization": "org",
        "X-ReconForge-Legal-Entity": "entity",
        "Authorization": "Bearer " + login.json()["access_token"],
    }
    assert client.post("/api/v1/auth/step-up", headers=headers, json={"password": runtime.password}).status_code == 200
    return headers


@pytest.mark.parametrize("phase", ["invoice_review", "invoice_post", "collection_review", "collection_post"])
def test_detached_operational_repository_phase_rolls_back_every_effect(
    sales_runtime: ReceiptRuntime,
    phase: str,
) -> None:
    runtime = sales_runtime
    number = "DETACHED-" + phase
    if phase == "invoice_review":
        document = prepared_invoice(runtime, number)
    elif phase == "invoice_post":
        document = create_reviewed_invoice(runtime, number)
    elif phase == "collection_review":
        document = pending_collection(runtime, number)
    else:
        document = create_reviewed_collection(runtime, number)
    plan = document["collection_plan" if phase.startswith("collection") else "invoice_plan"]
    before = retained_state(runtime, document["id"])
    actor_name = "checker" if phase.endswith("review") else "poster"
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="Sales (invoice stage|collection financial phase)"),
        runtime.actor(actor_name) as (connection, _, actor),
    ):
        finance = PostgresOperationalFinanceRepository(connection, runtime.tenant)
        if phase.endswith("review"):
            finance.review(
                plan["id"],
                expected_plan_digest=plan["plan_digest"],
                command_id=number,
                reason="Detached independent review",
                actor=actor,
            )
        else:
            receipt = None
            if phase.startswith("collection"):
                receipt = PostgresReceivablesRepository(connection, runtime.tenant).post_receipt(
                    receipt_number=number,
                    customer_code="CUSTOMER",
                    receipt_date="2026-10-09",
                    currency_code="USD",
                    amount_minor=18000,
                    allocations=[ReceiptAllocationInput(document["invoice_id"], 18000)],
                    workspace="work",
                    organization_code="ORG",
                    entity_code="ENTITY",
                    idempotency_key=number,
                    actor_label=actor.username,
                )
            finance.post(
                plan["id"],
                expected_plan_digest=plan["plan_digest"],
                command_id=number,
                reason="Detached source posting",
                actor=actor,
                source_effect_id=None if receipt is None else receipt["id"],
            )
    assert retained_state(runtime, document["id"]) == before


@pytest.mark.parametrize("path", ["repository", "raw_sql"])
def test_native_invoice_approval_requires_coordinated_sales_review(
    sales_runtime: ReceiptRuntime,
    path: str,
) -> None:
    runtime = sales_runtime
    document = prepared_invoice(runtime, "NATIVE-APPROVAL-" + path)
    before = retained_state(runtime, document["id"])
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="Sales invoice stage"),
        runtime.actor("checker") as (connection, _, actor),
    ):
        if path == "repository":
            ar = PostgresReceivablesRepository(connection, runtime.tenant)
            ar.approve_invoice(
                document["invoice_id"],
                expected_version=document["invoice"]["row_version"],
                actor_label=actor.username,
            )
        else:
            connection.execute(
                """UPDATE reconforge.ar_invoices SET status='Approved', approved_by=%s,
                approved_at=now(), row_version=row_version+1 WHERE tenant_id=%s AND id=%s""",
                (actor.username, runtime.tenant, document["invoice_id"]),
            )
    assert retained_state(runtime, document["id"]) == before


@pytest.mark.parametrize("amount", [9000, 18000])
@pytest.mark.parametrize("path", ["post_with_allocation", "allocate_existing", "raw_allocation"])
def test_external_partial_or_full_native_allocation_cannot_consume_owned_invoice(
    sales_runtime: ReceiptRuntime,
    path: str,
    amount: int,
) -> None:
    runtime = sales_runtime
    number = "NATIVE-COLLECTION-" + path + "-" + str(amount)
    document = invoiced_sale(runtime, number)
    receipt = None
    if path != "post_with_allocation":
        with runtime.actor("poster") as (connection, _, actor):
            receipt = PostgresReceivablesRepository(connection, runtime.tenant).post_receipt(
                receipt_number=number,
                customer_code="CUSTOMER",
                receipt_date="2026-10-09",
                currency_code="USD",
                amount_minor=amount,
                workspace="work",
                organization_code="ORG",
                entity_code="ENTITY",
                idempotency_key=number,
                actor_label=actor.username,
            )
    before = retained_state(runtime, document["id"])
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="Sales invoice stage"),
        runtime.actor("poster") as (connection, _, actor),
    ):
        ar = PostgresReceivablesRepository(connection, runtime.tenant)
        if path == "post_with_allocation":
            ar.post_receipt(
                receipt_number=number,
                customer_code="CUSTOMER",
                receipt_date="2026-10-09",
                currency_code="USD",
                amount_minor=amount,
                allocations=[ReceiptAllocationInput(document["invoice_id"], amount)],
                workspace="work",
                organization_code="ORG",
                entity_code="ENTITY",
                idempotency_key=number,
                actor_label=actor.username,
            )
        elif path == "allocate_existing":
            assert receipt is not None
            ar.allocate_receipt(
                receipt["id"],
                invoice_id=document["invoice_id"],
                amount_minor=amount,
                expected_version=receipt["row_version"],
                actor_label=actor.username,
            )
        else:
            assert receipt is not None
            connection.execute(
                """INSERT INTO reconforge.ar_receipt_allocations
                (tenant_id,id,workspace_id,receipt_id,invoice_id,amount_minor) VALUES(%s,%s,%s,%s,%s,%s)""",
                (runtime.tenant, number + "-ALLOCATION", "work", receipt["id"], document["invoice_id"], amount),
            )
    assert retained_state(runtime, document["id"]) == before


def test_generic_collection_plan_cannot_reserve_sales_invoice_outside_owner(sales_runtime: ReceiptRuntime) -> None:
    runtime = sales_runtime
    document = invoiced_sale(runtime, "DETACHED-COLLECTION-PLAN")
    before = retained_state(runtime, document["id"])
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="Sales native invoice requires its exact owned"),
        runtime.actor("maker") as (connection, _, actor),
    ):
        PostgresOperationalFinanceRepository(connection, runtime.tenant).prepare(
            OperationalFinancePreparation(
                "work",
                "org",
                "entity",
                "ORG",
                "ENTITY",
                "ARReceipt",
                document["invoice_id"],
                "CASH",
                "period",
                "2026-10-09",
                "CASH",
                "AR",
                "Detached collection plan",
            ),
            command_id="DETACHED-COLLECTION-PLAN",
            actor=actor,
        )
    assert retained_state(runtime, document["id"]) == before


@pytest.mark.parametrize("phase", ["review", "post"])
def test_normal_https_public_ops_cannot_advance_sales_owned_phase(
    receipt_database: tuple[str, str],
    sales_runtime: ReceiptRuntime,
    tmp_path: Path,
    phase: str,
) -> None:
    runtime = sales_runtime
    document = (
        prepared_invoice(runtime, "PUBLIC-REVIEW")
        if phase == "review"
        else create_reviewed_invoice(runtime, "PUBLIC-POST")
    )
    actor_name = "checker" if phase == "review" else "poster"
    plan = document["invoice_plan"]
    app = create_api_app(
        tmp_path / "unused.db",
        tenant_db_root=tmp_path / "tenants",
        postgres_dsn=receipt_database[1],
        postgres_require_tls=False,
        secure_transport=True,
        policy_cache_enabled=True,
    )
    with TestClient(app, base_url="https://testserver") as client:
        headers = authenticated_headers(client, runtime, actor_name)
        before = retained_state(runtime, document["id"])
        response = client.post(
            "/api/v1/operational-finance/plans/" + plan["id"] + "/" + phase,
            headers=headers,
            json={
                "command_id": "PUBLIC-" + phase,
                "expected_plan_digest": plan["plan_digest"],
                "reason": "Public finance mutation must preserve the Sales owner",
            },
        )
    assert response.status_code == 409, response.text
    assert retained_state(runtime, document["id"]) == before


@pytest.mark.parametrize("phase", ["approve", "partial_receipt", "full_allocation"])
def test_normal_https_native_ar_cannot_advance_or_consume_sales_owned_invoice(
    receipt_database: tuple[str, str],
    sales_runtime: ReceiptRuntime,
    tmp_path: Path,
    phase: str,
) -> None:
    runtime = sales_runtime
    number = "PUBLIC-NATIVE-" + phase
    document = prepared_invoice(runtime, number) if phase == "approve" else invoiced_sale(runtime, number)
    actor_name = "checker" if phase == "approve" else "poster"
    receipt = None
    if phase == "full_allocation":
        with runtime.actor("poster") as (connection, _, actor):
            receipt = PostgresReceivablesRepository(connection, runtime.tenant).post_receipt(
                receipt_number=number,
                customer_code="CUSTOMER",
                receipt_date="2026-10-09",
                currency_code="USD",
                amount_minor=18000,
                workspace="work",
                organization_code="ORG",
                entity_code="ENTITY",
                idempotency_key=number,
                actor_label=actor.username,
            )
    app = create_api_app(
        tmp_path / "unused.db",
        tenant_db_root=tmp_path / "tenants",
        postgres_dsn=receipt_database[1],
        postgres_require_tls=False,
        secure_transport=True,
        policy_cache_enabled=True,
    )
    with TestClient(app, base_url="https://testserver") as client:
        headers = authenticated_headers(client, runtime, actor_name)
        before = retained_state(runtime, document["id"])
        if phase == "approve":
            response = client.post(
                "/api/v1/receivables/invoices/" + document["invoice_id"] + "/approve",
                headers=headers,
                json={"expected_version": document["invoice"]["row_version"]},
            )
        elif phase == "partial_receipt":
            response = client.post(
                "/api/v1/receivables/receipts",
                headers=headers,
                json={
                    "receipt_number": number,
                    "customer_code": "CUSTOMER",
                    "receipt_date": "2026-10-09",
                    "currency_code": "USD",
                    "amount_minor": "9000",
                    "workspace": "work",
                    "organization_code": "ORG",
                    "entity_code": "ENTITY",
                    "idempotency_key": number,
                    "allocations": [{"invoice_id": document["invoice_id"], "amount_minor": "9000"}],
                },
            )
        else:
            assert receipt is not None
            response = client.post(
                "/api/v1/receivables/receipts/" + receipt["id"] + "/allocate",
                headers=headers,
                json={
                    "invoice_id": document["invoice_id"],
                    "amount_minor": "18000",
                    "expected_version": receipt["row_version"],
                },
            )
    assert response.status_code == 409, response.text
    assert retained_state(runtime, document["id"]) == before
