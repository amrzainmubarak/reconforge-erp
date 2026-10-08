"""Actual owner phase closure against detached Finance and native AR commands."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.application.receivables import ReceiptAllocationInput
from reconforge.auth.policy import verify_policy_decision_evidence
from reconforge.domain.finance_posting import FinancePostingError, PostingActor
from reconforge.domain.operational_finance import OperationalFinancePreparation
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_operational_finance import PostgresOperationalFinanceRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesError, PostgresReceivablesRepository
from reconforge.infrastructure.postgres_sales_revenue_schema import POSTGRES_SALES_RECEIPT_NAMESPACE_BACKFILL_SQL
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.platform.common import current_server_principal, server_principal_context
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, create_receipt_runtime
from tests.test_postgres_operational_finance_api import retained_business
from tests.test_postgres_sales_revenue import (
    create_complete_sales_cycle,
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
            "business_rows": retained_business(runtime),
            "receipt_names": [dict(row) for row in connection.execute(
                "SELECT scope,idempotency_key,response_json FROM reconforge.ar_idempotency_keys "
                "WHERE tenant_id=%s AND left(scope,length('sales_receipt_name_v1:'))='sales_receipt_name_v1:' "
                "ORDER BY scope,idempotency_key",
                (runtime.tenant,),
            ).fetchall()],
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
                (SELECT count(*) FROM reconforge.domain_audit_events WHERE tenant_id=%s
                 AND object_type<>'authorization.policy_decision') audits,
                (SELECT count(*) FROM reconforge.outbox_events WHERE tenant_id=%s) outbox""",
                    (runtime.tenant,) * 9,
                ).fetchone()
            ),
        }


def authorization_evidence(runtime: ReceiptRuntime) -> dict[str, Any]:
    with runtime.actor("checker") as (connection, _, _actor):
        return {
            row["id"]: row["evidence"]
            for row in connection.execute(
                """SELECT id, metadata_json->'policy_decision_evidence' evidence
            FROM reconforge.domain_audit_events WHERE tenant_id=%s
            AND object_type='authorization.policy_decision' AND action='evaluated'""",
                (runtime.tenant,),
            ).fetchall()
        }


def assert_authorization_was_retained(runtime: ReceiptRuntime, before: dict[str, Any]) -> None:
    after = authorization_evidence(runtime)
    assert before.keys() < after.keys()
    assert all(after[identifier] == payload for identifier, payload in before.items())
    for identifier in after.keys() - before.keys():
        verify_policy_decision_evidence(after[identifier])


def authenticated_headers(
    client: TestClient, runtime: ReceiptRuntime, actor_name: str, legal_entity_id: str = "entity"
) -> dict[str, str]:
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        authority = PostgresScopeAuthorityRepository(connection)
        for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", legal_entity_id)):
            authority.grant(
                tenant_id=runtime.tenant,
                grant_id=actor_name + "-" + kind + "-" + identifier,
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
        "X-ReconForge-Legal-Entity": legal_entity_id,
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
        policy_before = authorization_evidence(runtime)
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
    assert_authorization_was_retained(runtime, policy_before)


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
        policy_before = authorization_evidence(runtime)
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
    assert_authorization_was_retained(runtime, policy_before)


@pytest.mark.parametrize("phase", ["existing", "prepared", "reviewed"])
def test_collection_name_affinity_rejects_detached_unallocated_native_receipt(
    receipt_database: tuple[str, str],
    sales_runtime: ReceiptRuntime,
    tmp_path: Path,
    phase: str,
) -> None:
    runtime = sales_runtime
    number = "NAME-" + phase.upper()
    document = (
        invoiced_sale(runtime, number) if phase == "existing" else
        pending_collection(runtime, number) if phase == "prepared" else
        create_reviewed_collection(runtime, number)
    )
    app = create_api_app(
        tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants",
        postgres_dsn=receipt_database[1], postgres_require_tls=False, secure_transport=True,
        policy_cache_enabled=True,
    )
    with TestClient(app, base_url="https://testserver") as client:
        headers = authenticated_headers(client, runtime, "poster")
        before = retained_state(runtime, document["id"])
        policy_before = authorization_evidence(runtime)
        if phase != "existing":
            with pytest.raises((PostgresReceivablesError, psycopg.Error)) as conflict, runtime.actor("poster") as (connection, _, actor):
                PostgresReceivablesRepository(connection, runtime.tenant).post_receipt(
                    receipt_number=number + "-RECEIPT", customer_code="CUSTOMER", receipt_date="2026-10-09",
                    currency_code="USD", amount_minor=18000, allocations=[], workspace="work", organization_code="ORG", entity_code="ENTITY",
                    idempotency_key=number + "-DIRECT", actor_label=actor.username,
                )
            original = conflict.value.__cause__ if isinstance(conflict.value, PostgresReceivablesError) else conflict.value
            assert isinstance(original, psycopg.Error)
            assert original.sqlstate == "23514", str(original)
            assert original.diag.constraint_name == "sales_revenue_owner_phase", str(original)
            assert retained_state(runtime, document["id"]) == before
        response = client.post(
            "/api/v1/receivables/receipts", headers=headers,
            json={"receipt_number": number + "-RECEIPT", "customer_code": "CUSTOMER",
                  "receipt_date": "2026-10-09", "currency_code": "USD", "amount_minor": "18000",
                  "workspace": "work", "organization_code": "ORG", "entity_code": "ENTITY",
                  "idempotency_key": number + "-DETACHED", "allocations": []},
        )
        if phase == "existing":
            assert response.status_code == 200, response.text
            before = retained_state(runtime, document["id"])
            policy_before = authorization_evidence(runtime)
            maker_headers = authenticated_headers(client, runtime, "maker")
            response = client.post(
                "/api/v1/sales-revenue/documents/" + document["id"] + "/collection/prepare",
                headers=maker_headers,
                json={"expected_version": 8, "command_id": number + "-COLLECTION",
                      "reason": "Capture one exact unoccupied native receipt name",
                      "receipt_number": number + "-RECEIPT", "receipt_date": "2026-10-09",
                      "journal_code": "CASH", "period_id": "period", "cash_account_code": "CASH"},
            )
    assert response.status_code == 409, response.text
    assert retained_state(runtime, document["id"]) == before
    assert_authorization_was_retained(runtime, policy_before)


class SiblingSalesRuntime(ReceiptRuntime):
    """The same persisted humans and workspace, with another canonical entity."""

    sales_entity_id = "sibling"
    sales_entity_code = "SIBLING"
    sales_customer_code = "CUSTOMER-SIBLING"

    @contextmanager
    def actor(self, name: str) -> Iterator[tuple[Any, Any, PostingActor]]:
        with super().actor(name) as (connection, participant, actor):
            connection.execute("SELECT set_config('app.legal_entity_id','sibling',true)")
            connection.execute("SELECT set_config('app.entity_id','sibling',true)")
            principal = current_server_principal()
            assert principal is not None
            with server_principal_context(replace(principal, authorized_legal_entity_ids=frozenset({"sibling"}))):
                yield connection, participant, actor


def sibling_runtime(runtime: ReceiptRuntime) -> SiblingSalesRuntime:
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        connection.execute(
            "INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) "
            "VALUES(%s,'sibling','org','SIBLING','Synthetic sibling','USD')", (runtime.tenant,),
        )
        PostgresReceivablesRepository(connection, runtime.tenant).upsert_customer(
            customer_code="CUSTOMER-SIBLING", name="Synthetic sibling customer", currency_code="USD",
            credit_limit_minor=1000000, payment_terms_days=30, workspace="work", organization_code="ORG", entity_code="SIBLING",
        )
    return SiblingSalesRuntime(runtime.factory, runtime.admin_dsn, runtime.tenant, runtime.password)


def prepare_named_collection(runtime: ReceiptRuntime, document: dict[str, Any], number: str, command: str) -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        return repository(connection, runtime).prepare_collection(
            document["id"], expected_version=8, command_id=command, reason="Reserve the exact shared native name",
            receipt_number=number, receipt_date="2026-10-09", journal_code="CASH", period_id="period", cash_account_code="CASH", actor=actor,
        )


def complete_named_collection(runtime: ReceiptRuntime, document: dict[str, Any], command: str) -> dict[str, Any]:
    with runtime.actor("checker") as (connection, _, actor):
        document = repository(connection, runtime).review_collection(
            document["id"], expected_version=9, command_id=command + "-review", reason="Independent full cash review", actor=actor,
        )
    with runtime.actor("poster") as (connection, _, actor):
        return repository(connection, runtime).post_collection(
            document["id"], expected_version=10, command_id=command + "-post", reason="Publish one full native and GL effect", actor=actor,
        )


@pytest.mark.parametrize("cross_entity", [False, True])
def test_six_concurrent_sales_captures_reserve_one_workspace_name_and_both_recover_paid(
    sales_runtime: ReceiptRuntime, cross_entity: bool,
) -> None:
    runtimes = [sales_runtime, sibling_runtime(sales_runtime) if cross_entity else sales_runtime]
    documents = [invoiced_sale(runtime, "RACE-DOC-" + str(index)) for index, runtime in enumerate(runtimes)]
    if cross_entity:
        with sales_runtime.actor("maker") as (connection, _, _actor):
            assert connection.execute(
                "SELECT id FROM reconforge.sales_revenue_documents WHERE tenant_id=%s AND id=%s",
                (sales_runtime.tenant, documents[1]["id"]),
            ).fetchone() is None
    barrier = Barrier(6)

    def capture(index: int) -> tuple[int, dict[str, Any] | str]:
        barrier.wait(timeout=30)
        try:
            return index, prepare_named_collection(runtimes[index], documents[index], "SHARED-CASH-NAME", "race-capture-" + str(index))
        except FinancePostingError as exc:
            return index, exc.code

    with ThreadPoolExecutor(max_workers=6) as workers:
        outcomes = list(workers.map(capture, [0, 1, 0, 1, 0, 1]))
    successes = [(index, result) for index, result in outcomes if isinstance(result, dict)]
    rejected = [(index, result) for index, result in outcomes if isinstance(result, str)]
    assert len(successes) == len(rejected) == 3
    winner = successes[0][0]
    loser = 1 - winner
    assert all(index == winner and result == successes[0][1] for index, result in successes)
    assert all(index == loser and result == "sales_collection_conflict" for index, result in rejected)
    paid = complete_named_collection(runtimes[winner], successes[0][1], "winner")
    assert paid["status"] == "Paid" and paid["receipt"]["receipt_number"] == "SHARED-CASH-NAME"
    recovered = prepare_named_collection(runtimes[loser], documents[loser], "SECOND-CASH-NAME", "loser-safe-recovery")
    paid_recovered = complete_named_collection(runtimes[loser], recovered, "loser-safe-recovery")
    assert paid_recovered["status"] == "Paid" and paid_recovered["receipt"]["receipt_number"] == "SECOND-CASH-NAME"
    with PostgresTenantBoundary(sales_runtime.factory).transaction(sales_runtime.tenant, workspace_id="work") as connection:
        assert connection.execute(
            "SELECT count(*) n FROM reconforge.ar_receipts WHERE tenant_id=%s", (sales_runtime.tenant,),
        ).fetchone()["n"] == 2
        assert connection.execute(
            "SELECT count(*) n FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (sales_runtime.tenant,),
        ).fetchone()["n"] == 4


def test_hidden_sibling_native_receipt_blocks_sales_capture_and_reserved_sales_blocks_sibling_native(
    receipt_database: tuple[str, str], sales_runtime: ReceiptRuntime, tmp_path: Path,
) -> None:
    runtime = sales_runtime
    sibling = sibling_runtime(runtime)
    document = invoiced_sale(runtime, "SIBLING-NAME")
    app = create_api_app(tmp_path / "unused.db", tenant_db_root=tmp_path / "tenants", postgres_dsn=receipt_database[1],
                         postgres_require_tls=False, secure_transport=True, policy_cache_enabled=True)
    with TestClient(app, base_url="https://testserver") as client:
        headers = authenticated_headers(client, sibling, "poster", "sibling")
        body = {"receipt_number": "HIDDEN-NATIVE-NAME", "customer_code": "CUSTOMER-SIBLING", "receipt_date": "2026-10-09",
                "currency_code": "USD", "amount_minor": "18000", "workspace": "work", "organization_code": "ORG", "entity_code": "SIBLING",
                "idempotency_key": "sibling-unowned", "allocations": []}
        response = client.post("/api/v1/receivables/receipts", headers=headers, json=body)
        assert response.status_code == 200, response.text
        with runtime.actor("maker") as (connection, _, _actor):
            assert connection.execute("SELECT id FROM reconforge.ar_receipts WHERE tenant_id=%s", (runtime.tenant,)).fetchone() is None
        before = retained_state(runtime, document["id"])
        with pytest.raises(FinancePostingError) as conflict:
            prepare_named_collection(runtime, document, "HIDDEN-NATIVE-NAME", "blocked-hidden-name")
        assert conflict.value.code == "sales_collection_conflict"
        assert retained_state(runtime, document["id"]) == before
        captured = prepare_named_collection(runtime, document, "RESERVED-SALES-NAME", "reserve-cross-entity")
        body.update(receipt_number="reserved-sales-name", idempotency_key="blocked-sibling")
        response = client.post("/api/v1/receivables/receipts", headers=headers, json=body)
        assert response.status_code == 409, response.text
    assert complete_named_collection(runtime, captured, "cross-entity-complete")["status"] == "Paid"


def test_canonical_sales_name_rejects_nonreplayable_capture_and_raw_sql_but_unowned_unicode_stays_valid(
    sales_runtime: ReceiptRuntime,
) -> None:
    runtime = sales_runtime
    document = invoiced_sale(runtime, "CANONICAL-NAME")
    before = retained_state(runtime, document["id"])
    for number in ("not a receipt", "-starts-invalid", "ß" * 64, "إيصال"):
        with pytest.raises(FinancePostingError):
            prepare_named_collection(runtime, document, number, "invalid-capture")
        assert retained_state(runtime, document["id"]) == before
    for number in ("raw-lowercase", "BAD SPACE", "ß", "A" * 65):
        with pytest.raises(psycopg.errors.CheckViolation) as conflict, runtime.actor("maker") as (connection, _, _actor):
            connection.execute("SELECT set_config('app.sales_actor_id','maker',true)")
            connection.execute(
                "UPDATE reconforge.sales_revenue_documents SET status='CollectionPrepared',row_version=row_version+1,"
                "collection_plan_id='not-a-plan',collection_parameters=jsonb_build_object('receipt_number',%s::text) WHERE tenant_id=%s AND id=%s",
                (number, runtime.tenant, document["id"]),
            )
        assert conflict.value.diag.constraint_name == "sales_revenue_owner_phase"
        assert retained_state(runtime, document["id"]) == before
    with runtime.actor("poster") as (connection, _, actor):
        ar = PostgresReceivablesRepository(connection, runtime.tenant)
        native = ar.post_receipt(receipt_number="ß١", customer_code="CUSTOMER", receipt_date="2026-10-09", currency_code="USD",
                                 amount_minor=1, allocations=[], workspace="work", organization_code="ORG", entity_code="ENTITY",
                                 idempotency_key="native-unicode", actor_label=actor.username)
        assert native["receipt_number"] == "SS١"
        assert ar.post_receipt(receipt_number="ß١", customer_code="CUSTOMER", receipt_date="2026-10-09", currency_code="USD",
                               amount_minor=1, allocations=[], workspace="work", organization_code="ORG", entity_code="ENTITY",
                               idempotency_key="native-unicode", actor_label=actor.username) == native
    captured = prepare_named_collection(runtime, document, "sales-lowercase-01", "canonical-capture")
    assert captured["collection_parameters"]["receipt_number"] == "SALES-LOWERCASE-01"
    assert complete_named_collection(runtime, captured, "canonical-complete")["status"] == "Paid"


def test_reserved_native_namespace_cannot_be_forged_reparented_deleted_or_renamed(sales_runtime: ReceiptRuntime) -> None:
    runtime = sales_runtime
    document = pending_collection(runtime, "IMMUTABLE-NAME")
    before = retained_state(runtime, document["id"])
    commands = [
        ("UPDATE reconforge.ar_idempotency_keys SET response_json=jsonb_build_object('schema_version',1,'owner_kind','Sales','owner_id','forged') WHERE tenant_id=%s AND scope='sales_receipt_name_v1:work'", (runtime.tenant,)),
        ("DELETE FROM reconforge.ar_idempotency_keys WHERE tenant_id=%s AND scope='sales_receipt_name_v1:work'", (runtime.tenant,)),
        ("UPDATE reconforge.ar_idempotency_keys SET scope='receipt:work' WHERE tenant_id=%s AND scope='sales_receipt_name_v1:work'", (runtime.tenant,)),
        ("INSERT INTO reconforge.ar_idempotency_keys(tenant_id,workspace_id,scope,idempotency_key,response_json) VALUES(%s,'work','sales_receipt_name_v1:work','POISONED',jsonb_build_object('schema_version',1,'owner_kind','Sales','owner_id',%s::text))", (runtime.tenant, document["id"])),
    ]
    for statement, parameters in commands:
        with pytest.raises(psycopg.errors.CheckViolation) as conflict, runtime.actor("maker") as (connection, _, _actor):
            connection.execute(statement, parameters)
        assert conflict.value.diag.constraint_name == "sales_revenue_owner_phase"
        assert retained_state(runtime, document["id"]) == before
    paid = complete_named_collection(runtime, document, "immutable-complete")
    for statement in (
        "UPDATE reconforge.ar_receipts SET receipt_number='RENAMED' WHERE tenant_id=%s AND id=%s",
        "DELETE FROM reconforge.ar_receipts WHERE tenant_id=%s AND id=%s",
    ):
        with pytest.raises(psycopg.Error), runtime.actor("poster") as (connection, _, _actor):
            connection.execute(statement, (runtime.tenant, paid["receipt_id"]))
        with runtime.actor("checker") as (connection, _, actor):
            assert repository(connection, runtime).get(document["id"], actor=actor) == paid


def test_namespace_backfill_preserves_paid_and_pending_sales_ownership_and_refuses_collisions(
    sales_runtime: ReceiptRuntime,
) -> None:
    runtime = sales_runtime
    paid = create_complete_sales_cycle(runtime, "BACKFILL-PAID")
    pending = pending_collection(runtime, "BACKFILL-PENDING")
    reviewed = create_reviewed_collection(runtime, "BACKFILL-REVIEWED")
    before = retained_state(runtime, paid["id"])
    # A migration administrator restores only the new bridge from real source
    # history, with its insert closure installed after the backfill, as in 0110.
    with psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute("ALTER TABLE reconforge.ar_idempotency_keys DISABLE TRIGGER sales_receipt_name_immutable")
        admin.execute("ALTER TABLE reconforge.ar_idempotency_keys DISABLE TRIGGER sales_receipt_name_key_closure")
        admin.execute("DELETE FROM reconforge.ar_idempotency_keys WHERE tenant_id=%s AND scope='sales_receipt_name_v1:work'", (runtime.tenant,))
        admin.execute(POSTGRES_SALES_RECEIPT_NAMESPACE_BACKFILL_SQL)
        admin.execute("ALTER TABLE reconforge.ar_idempotency_keys ENABLE TRIGGER sales_receipt_name_immutable")
        admin.execute("ALTER TABLE reconforge.ar_idempotency_keys ENABLE TRIGGER sales_receipt_name_key_closure")
    after = retained_state(runtime, paid["id"])
    assert after == before
    with pytest.raises(psycopg.errors.CheckViolation), psycopg.connect(runtime.admin_dsn) as admin:
        admin.execute("ALTER TABLE reconforge.ar_idempotency_keys DISABLE TRIGGER sales_receipt_name_immutable")
        admin.execute(
            "UPDATE reconforge.ar_idempotency_keys SET response_json=jsonb_build_object('schema_version',1,'owner_kind','ARReceipt','owner_id',%s::text) "
            "WHERE tenant_id=%s AND scope='sales_receipt_name_v1:work' AND idempotency_key='BACKFILL-PENDING-RECEIPT'", (paid["receipt_id"], runtime.tenant),
        )
        admin.execute(POSTGRES_SALES_RECEIPT_NAMESPACE_BACKFILL_SQL)
    after = retained_state(runtime, paid["id"])
    assert after == before
    assert complete_named_collection(runtime, pending, "backfilled-pending")["status"] == "Paid"
    with runtime.actor("poster") as (connection, _, actor):
        assert repository(connection, runtime).post_collection(
            reviewed["id"], expected_version=10, command_id="backfilled-reviewed", reason="Publish retained original source", actor=actor,
        )["status"] == "Paid"


def test_empty_sales_downgrade_and_upgrade_preserve_unowned_native_unicode_and_replay_keys() -> None:
    iterator = receipt_database.__wrapped__()
    try:
        database = next(iterator)
        runtime = create_receipt_runtime(database)
        with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
            PostgresReceivablesRepository(connection, runtime.tenant).upsert_customer(
                customer_code="CUSTOMER", name="Synthetic", currency_code="USD", credit_limit_minor=1000000,
                payment_terms_days=30, workspace="work", organization_code="ORG", entity_code="ENTITY",
            )
        with runtime.actor("poster") as (connection, _, actor):
            native = PostgresReceivablesRepository(connection, runtime.tenant).post_receipt(
                receipt_number="ß١", customer_code="CUSTOMER", receipt_date="2026-10-09", currency_code="USD", amount_minor=1,
                allocations=[], workspace="work", organization_code="ORG", entity_code="ENTITY", idempotency_key="preserve-native", actor_label=actor.username,
            )
            ordinary = [dict(row) for row in connection.execute(
                "SELECT scope,idempotency_key,response_json FROM reconforge.ar_idempotency_keys WHERE tenant_id=%s AND scope='receipt:work'", (runtime.tenant,),
            ).fetchall()]
        migration_env = {**os.environ, "RECONFORGE_POSTGRES_DSN": runtime.admin_dsn}
        for operation, revision in (("downgrade", "0109_pg_operational_finance"), ("upgrade", "head")):
            result = subprocess.run([sys.executable, "-m", "alembic", operation, revision],
                                    cwd=Path(__file__).resolve().parents[1], env=migration_env, capture_output=True, text=True, timeout=180)
            assert result.returncode == 0, result.stderr
            with psycopg.connect(runtime.admin_dsn) as admin:
                retained = admin.execute("SELECT receipt_number FROM reconforge.ar_receipts WHERE tenant_id=%s AND id=%s", (runtime.tenant, native["id"])).fetchone()
                assert retained == ("SS١",)
                count = admin.execute("SELECT count(*) FROM reconforge.ar_idempotency_keys WHERE tenant_id=%s AND scope='sales_receipt_name_v1:work'", (runtime.tenant,)).fetchone()[0]
                assert count == (0 if operation == "downgrade" else 1)
                if operation == "downgrade":
                    assert admin.execute("SELECT to_regprocedure('reconforge.sales_receipt_name_claim(text,text,text,text,text)')").fetchone() == (None,)
                else:
                    app_user = psycopg.conninfo.conninfo_to_dict(database[1])["user"]
                    admin.execute(psycopg.sql.SQL("GRANT SELECT ON reconforge.sales_revenue_documents,reconforge.procurement_cycles TO {}").format(psycopg.sql.Identifier(app_user)))
        with runtime.actor("poster") as (connection, _, actor):
            assert [dict(row) for row in connection.execute(
                "SELECT scope,idempotency_key,response_json FROM reconforge.ar_idempotency_keys WHERE tenant_id=%s AND scope='receipt:work'", (runtime.tenant,),
            ).fetchall()] == ordinary
            assert PostgresReceivablesRepository(connection, runtime.tenant).post_receipt(
                receipt_number="ß١", customer_code="CUSTOMER", receipt_date="2026-10-09", currency_code="USD", amount_minor=1,
                allocations=[], workspace="work", organization_code="ORG", entity_code="ENTITY", idempotency_key="preserve-native", actor_label=actor.username,
            ) == native
            assert dict(connection.execute(
                "SELECT has_table_privilege(current_user,'reconforge.sales_revenue_documents','INSERT') i,"
                "has_table_privilege(current_user,'reconforge.sales_revenue_documents','UPDATE') u,"
                "has_table_privilege(current_user,'reconforge.sales_revenue_documents','DELETE') d"
            ).fetchone()) == {"i": False, "u": False, "d": False}
    finally:
        iterator.close()
