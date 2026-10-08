"""HTTPS-origin TestClient API/auth/backend proofs; wire TLS is a browser gate."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime
from tests.test_postgres_operational_finance import preparation, runtime
from tests.test_postgres_sales_revenue import (
    create_fulfilled_sale,
    create_reviewed_invoice,
    invoice_preparation,
    receipt_database,
    repository,
    sales_runtime,
)

__all__ = ["receipt_database", "runtime", "sales_runtime"]
pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"),
    reason="Owned PostgreSQL integration prerequisite; review 2026-10-08",
)


@contextmanager
def client_for(
    rt: ReceiptRuntime,
    database: tuple[str, str],
    tmp_path: Path,
    username: str,
    *,
    step_up: bool = True,
) -> Iterator[tuple[TestClient, dict[str, str]]]:
    with PostgresTenantBoundary(rt.factory).transaction(rt.tenant) as connection:
        authority = PostgresScopeAuthorityRepository(connection)
        for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
            if (
                connection.execute(
                    """SELECT 1 FROM reconforge.principal_scope_grants WHERE tenant_id=%s AND principal_type='user'
                AND principal_id=%s AND scope_type=%s AND scope_id=%s AND revoked_at IS NULL""",
                    (rt.tenant, username, kind, identifier),
                ).fetchone()
                is not None
            ):
                continue
            authority.grant(
                tenant_id=rt.tenant,
                grant_id=username + "-" + kind + "-" + uuid4().hex,
                principal_type="user",
                principal_id=username,
                scope_type=kind,
                scope_id=identifier,
                actor_id=username,
            )
    app = create_api_app(
        tmp_path / "unused.db",
        tenant_db_root=tmp_path / "tenants",
        postgres_dsn=database[1],
        postgres_require_tls=False,
        secure_transport=True,
        policy_cache_enabled=True,
    )
    with TestClient(app, base_url="https://testserver") as client:
        login = client.post(
            "/api/v1/auth/login",
            headers={"X-ReconForge-Tenant": rt.tenant},
            json={"username": username, "password": rt.password},
        )
        assert login.status_code == 200, login.text
        headers = {
            "X-ReconForge-Tenant": rt.tenant,
            "X-ReconForge-Workspace": "work",
            "X-ReconForge-Organization": "org",
            "X-ReconForge-Legal-Entity": "entity",
            "Authorization": "Bearer " + login.json()["access_token"],
        }
        if step_up:
            confirmed = client.post("/api/v1/auth/step-up", headers=headers, json={"password": rt.password})
            assert confirmed.status_code == 200, confirmed.text
        yield client, headers


def retained_business(rt: ReceiptRuntime) -> dict[str, Any]:
    """Compare every native, owner, source and GL row, without auth side effects."""
    from psycopg import sql

    tables = (
        "sales_revenue_documents",
        "sales_revenue_commands",
        "sales_revenue_events",
        "ar_invoices",
        "ar_invoice_lines",
        "ar_receipts",
        "ar_receipt_allocations",
        "ar_idempotency_keys",
        "operational_finance_plans",
        "operational_finance_reviews",
        "operational_finance_links",
        "operational_finance_commands",
        "finance_entries",
        "finance_entry_lines",
        "finance_entry_line_dimensions",
        "finance_posting_effects",
        "finance_posting_commands",
    )
    with PostgresTenantBoundary(rt.factory).transaction(
        rt.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity"
    ) as connection:
        privileges = connection.execute(
            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        assert (privileges["rolsuper"], privileges["rolbypassrls"]) == (False, False)
        snapshot = {
            table: connection.execute(
                sql.SQL(
                    "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb) AS rows "
                    "FROM reconforge.{} t WHERE tenant_id=%s"
                ).format(sql.Identifier(table)),
                (rt.tenant,),
            ).fetchone()["rows"]
            for table in tables
        }
        for table, column in (("domain_audit_events", "object_type"), ("outbox_events", "aggregate_type")):
            snapshot[table] = connection.execute(
                sql.SQL(
                    "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb) AS rows "
                    "FROM reconforge.{} t WHERE tenant_id=%s AND {}='operational_finance'"
                ).format(sql.Identifier(table), sql.Identifier(column)),
                (rt.tenant,),
            ).fetchone()["rows"]
        return snapshot


@pytest.mark.parametrize("phase", ["review", "post"])
def test_public_owned_sales_phase_refuses_before_mutation_and_owner_continues(
    receipt_database: tuple[str, str], sales_runtime: ReceiptRuntime, tmp_path: Path, phase: str
) -> None:
    rt = sales_runtime
    if phase == "review":
        document = create_fulfilled_sale(rt, "PUBLIC-REVIEW")
        with rt.actor("maker") as (connection, _, actor):
            document = repository(connection, rt).prepare_invoice(
                document["id"],
                invoice_preparation("PUBLIC-REVIEW-INV"),
                expected_version=5,
                command_id="PUBLIC-PREPARE",
                actor=actor,
            )
        username = "checker"
    else:
        document = create_reviewed_invoice(rt, "PUBLIC-POST")
        username = "poster"
    plan = document["invoice_plan"]
    with client_for(rt, receipt_database, tmp_path, username) as (client, headers):
        before = retained_business(rt)
        response = client.post(
            "/api/v1/operational-finance/plans/" + plan["id"] + "/" + phase,
            headers=headers,
            json={
                "command_id": "PUBLIC-" + phase,
                "expected_plan_digest": plan["plan_digest"],
                "reason": "Preserve the owning operational cycle",
            },
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "operational_owner_required"
        assert retained_business(rt) == before
        read = client.get("/api/v1/operational-finance/plans/" + plan["id"], headers=headers)
        assert read.status_code == 200 and read.json()["plan"]["status"] == plan["status"]
    with rt.actor(username) as (connection, _, actor):
        owner = repository(connection, rt)
        action = owner.review_invoice if phase == "review" else owner.post_invoice
        completed = action(
            document["id"],
            expected_version=6 if phase == "review" else 7,
            command_id="OWNER-" + phase,
            reason="Continue the actual owner cycle",
            actor=actor,
        )
        assert completed["status"] == ("InvoiceReviewed" if phase == "review" else "Invoiced")


def test_public_prepare_owned_collection_rolls_back_journal_and_owner_can_prepare(
    receipt_database: tuple[str, str], sales_runtime: ReceiptRuntime, tmp_path: Path
) -> None:
    rt = sales_runtime
    document = create_reviewed_invoice(rt, "PUBLIC-COLLECTION")
    with rt.actor("poster") as (connection, _, actor):
        document = repository(connection, rt).post_invoice(
            document["id"], expected_version=7, command_id="OWNER-INVOICE-POST", reason="Publish revenue", actor=actor
        )
    with client_for(rt, receipt_database, tmp_path, "maker") as (client, headers):
        before = retained_business(rt)
        response = client.post(
            "/api/v1/operational-finance/plans",
            headers=headers,
            json={
                "command_id": "PUBLIC-COLLECTION-PREPARE",
                "source_kind": "ARReceipt",
                "source_id": document["invoice_id"],
                "journal_code": "CASH",
                "period_id": "period",
                "posting_date": "2026-10-09",
                "debit_account_code": "CASH",
                "credit_account_code": "AR",
                "reason": "Preserve the owning collection cycle",
            },
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "operational_owner_required"
        assert retained_business(rt) == before
    with rt.actor("maker") as (connection, _, actor):
        completed = repository(connection, rt).prepare_collection(
            document["id"],
            expected_version=8,
            command_id="OWNER-COLLECTION-PREPARE",
            reason="Bank evidence confirms complete payment",
            receipt_number="OWNER-RECEIPT",
            receipt_date="2026-10-09",
            journal_code="CASH",
            period_id="period",
            cash_account_code="CASH",
            actor=actor,
        )
        assert completed["status"] == "CollectionPrepared" and completed["collection_plan"]["status"] == "Draft"


def test_public_owner_denial_does_not_replace_current_step_up_authority(
    receipt_database: tuple[str, str], sales_runtime: ReceiptRuntime, tmp_path: Path
) -> None:
    rt = sales_runtime
    document = create_reviewed_invoice(rt, "PUBLIC-AUTHORITY")
    plan = document["invoice_plan"]
    with client_for(rt, receipt_database, tmp_path, "poster", step_up=False) as (client, headers):
        before = retained_business(rt)
        response = client.post(
            "/api/v1/operational-finance/plans/" + plan["id"] + "/post",
            headers=headers,
            json={
                "command_id": "UNCONFIRMED-POST",
                "expected_plan_digest": plan["plan_digest"],
                "reason": "Unconfirmed principal must not change any financial state",
            },
        )
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] != "operational_owner_required"
        assert retained_business(rt) == before


def test_standalone_unowned_https_prepare_review_post_has_exact_gl_and_replay(
    receipt_database: tuple[str, str], runtime: tuple[ReceiptRuntime, str], tmp_path: Path
) -> None:
    rt, invoice = runtime
    body = preparation(invoice).payload()
    for field in ("workspace_id", "organization_id", "legal_entity_id", "organization_code", "entity_code"):
        body.pop(field)
    with client_for(rt, receipt_database, tmp_path, "maker") as (client, headers):
        response = client.post(
            "/api/v1/operational-finance/plans", headers=headers, json={**body, "command_id": "PUBLIC-UNOWNED-PREPARE"}
        )
        assert response.status_code == 200, response.text
        plan = response.json()["plan"]
        assert plan["status"] == "Draft" and plan["amount_minor"] == "12000"
    with rt.actor("checker") as (connection, _, actor):
        ar = PostgresReceivablesRepository(connection, rt.tenant)
        ar.approve_invoice(invoice, expected_version=ar.get_invoice(invoice)["row_version"], actor_label=actor.username)
    for username, phase, status in (("checker", "review", "Reviewed"), ("poster", "post", "Posted")):
        with client_for(rt, receipt_database, tmp_path, username) as (client, headers):
            phase_body = {
                "command_id": "PUBLIC-UNOWNED-" + phase,
                "expected_plan_digest": plan["plan_digest"],
                "reason": "Independent native accrual " + phase,
            }
            path = "/api/v1/operational-finance/plans/" + plan["id"] + "/" + phase
            response = client.post(path, headers=headers, json=phase_body)
            assert response.status_code == 200, response.text
            plan = response.json()["plan"]
            assert plan["status"] == status
            replay = client.post(path, headers=headers, json=phase_body)
            assert replay.status_code == 200 and replay.json()["plan"] == plan
            assert sorted((line["debit_minor"], line["credit_minor"]) for line in plan["lines"]) == [
                ("0", "12000"),
                ("12000", "0"),
            ]
    with client_for(rt, receipt_database, tmp_path, "poster") as (client, headers):
        report = client.get(
            "/api/v1/finance-core/posted-trial-balance",
            headers=headers,
            params={"workspace": "work", "period_id": "period", "organization_code": "ORG", "entity_code": "ENTITY"},
        )
        assert report.status_code == 200, report.text
        trial = report.json()["trial_balance"]
        assert trial["effect_count"] == 1
        assert trial["balance_totals"] == {"debit_minor": "12000", "credit_minor": "12000", "balanced": True}
