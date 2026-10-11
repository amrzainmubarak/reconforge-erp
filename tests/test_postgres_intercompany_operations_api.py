"""Actual native HTTP owner lifecycle and current persisted three-scope authority."""
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from reconforge.api.routes import intercompany_operations as api
from reconforge.api.routes.intercompany_operations import router
from reconforge.domain.financial_reporting import AccountClassification, ReportingScope
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_financial_reporting import PostgresFinancialReportingRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_intercompany_operations import (
    ACCOUNTS,
    IntercompanyRuntime,
    intercompany_database,
    pytestmark,
    receipt_database,
    runtime,
)
from tests.test_postgres_operational_finance_api import client_for

__all__ = ["receipt_database", "intercompany_database", "runtime", "pytestmark"]
ROOT = "/api/v1/intercompany-operations"


@contextmanager
def client(rt: IntercompanyRuntime, database: tuple[str, str], path: Path, name: str,
           *, step_up: bool = True) -> Iterator[tuple[TestClient, dict[str, str]]]:
    with PostgresTenantBoundary(rt.base.factory).transaction(rt.base.tenant) as connection:
        authority = PostgresScopeAuthorityRepository(connection)
        for entity in ("buyer", "group"):
            existing = connection.execute("SELECT id FROM reconforge.principal_scope_grants WHERE tenant_id=%s AND principal_id=%s AND principal_type='user' AND scope_type='legal_entity' AND scope_id=%s AND revoked_at IS NULL", (rt.base.tenant, name, entity)).fetchone()
            if existing is None:
                authority.grant(tenant_id=rt.base.tenant, grant_id=f"ic-{name}-{entity}", principal_type="user", principal_id=name,
                                scope_type="legal_entity", scope_id=entity, actor_id=name)
    with client_for(rt.base, database, path, name, step_up=step_up) as (session, headers):
        if not any(getattr(route, "path", None) == ROOT + "/sources" for route in session.app.routes):
            session.app.include_router(router, prefix="/api/v1")
        yield session, {key: value for key, value in headers.items() if key != "X-ReconForge-Legal-Entity"}


def body() -> dict[str, str]:
    return {"command_id": "http-original", "seller_entity_id": "entity", "buyer_entity_id": "buyer", "adjustment_entity_id": "group",
            "reference": "HTTP-IC1", "amount_minor": "10001", "period_id": "period", "posting_date": "2026-10-03", "journal_code": "STOCK",
            "receivable_account_code": "IC_AR", "payable_account_code": "IC_AP", "revenue_account_code": "IC_REVENUE", "expense_account_code": "IC_EXPENSE",
            "cash_account_code": "CASH", "reason": "Actual native paired HTTP source"}


def test_actual_http_pair_whole_review_third_human_post_and_original_ack(runtime: IntercompanyRuntime, intercompany_database: tuple[str, str], tmp_path: Path) -> None:
    with client(runtime, intercompany_database, tmp_path / "maker", "maker") as (session, headers):
        wrong = session.post(ROOT + "/sources", headers={**headers, "X-ReconForge-Legal-Entity": "entity"}, json=body())
        assert wrong.status_code == 403 and wrong.json()["error"]["code"] == "intercompany_organization_scope_required"
        prepared = session.post(ROOT + "/sources", headers=headers, json=body())
        assert prepared.status_code == 200, prepared.text
        plan = prepared.json()["plan"]
        assert session.post(ROOT + "/sources", headers=headers, json=body()).json()["plan"] == plan
        assert len(plan["entries"]) == 2 and plan["amount_minor"] == "10001"
        assert session.post(ROOT + f"/plans/{plan['id']}/review", headers=headers,
            json={"command_id": "self", "expected_plan_digest": plan["plan_digest"], "reason": "Self"}).status_code == 403
    with client(runtime, intercompany_database, tmp_path / "checker", "checker") as (session, headers):
        reviewed = session.post(ROOT + f"/plans/{plan['id']}/review", headers=headers,
            json={"command_id": "http-review", "expected_plan_digest": plan["plan_digest"], "reason": "Independent actual review"})
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["plan"]["phase"] == 1
    with client(runtime, intercompany_database, tmp_path / "poster", "poster") as (session, headers):
        request = {"command_id": "http-post", "expected_plan_digest": plan["plan_digest"], "reason": "Third actual human"}
        posted = session.post(ROOT + f"/plans/{plan['id']}/post", headers=headers, json=request)
        assert posted.status_code == 200, posted.text
        assert len(posted.json()["plan"]["posting_effect_ids"]) == 2
        assert session.post(ROOT + f"/plans/{plan['id']}/post", headers=headers, json=request).json() == posted.json()
        evidence = session.get(ROOT + f"/plans/{plan['id']}/evidence", headers=headers)
        assert evidence.status_code == 200, evidence.text
        assert [row["actor_id"] for row in evidence.json()["evidence"]["phases"]] == ["maker", "checker", "poster"]
    with client(runtime, intercompany_database, tmp_path / "maker-replay", "maker") as (session, headers):
        assert session.post(ROOT + "/sources", headers=headers, json=body()).json()["plan"] == plan


def test_actual_cached_http_source_read_and_lost_ack_refuse_revoked_group_grant(runtime: IntercompanyRuntime, intercompany_database: tuple[str, str], tmp_path: Path) -> None:
    with client(runtime, intercompany_database, tmp_path, "maker") as (session, headers):
        created = session.post(ROOT + "/sources", headers=headers, json=body())
        assert created.status_code == 200, created.text
        plan = created.json()["plan"]
        with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
            PostgresScopeAuthorityRepository(connection).revoke(tenant_id=runtime.base.tenant, grant_id="ic-maker-group", actor_id="maker", reason="Revoke retained group authority")
        denied = session.get(ROOT + f"/sources/{plan['source_id']}", headers=headers)
        assert denied.status_code == 403, denied.text
        replay = session.post(ROOT + "/sources", headers=headers, json=body())
        assert replay.status_code == 403, replay.text
    with runtime.actor("poster") as (_, repository, actor):
        assert repository.get_plan(plan["id"], actor=actor)["phase"] == 0


def test_actual_http_catalog_contains_three_current_books_and_native_master_shapes(runtime: IntercompanyRuntime, intercompany_database: tuple[str, str], tmp_path: Path, monkeypatch) -> None:
    failures = []
    original = api.execute_postgres_finance_core_scoped

    def observe(request, operation):
        def invoke(*args):
            try:
                return operation(*args)
            except Exception as exc:
                failures.append((type(exc).__name__, str(exc)))
                raise
        return original(request, invoke)

    # Preserve the actual executor/admission; only retain the synthetic failure cause.
    monkeypatch.setattr(api, "execute_postgres_finance_core_scoped", observe)
    reviewed_maps = {}
    for entity in ("entity", "buyer", "group"):
        with runtime.actor("maker") as (connection, _, actor):
            mapping = PostgresFinancialReportingRepository(connection, runtime.base.tenant).prepare_map(ReportingScope("work", "org", entity),
                name="Actual HTTP map " + entity, accounts=[AccountClassification(code, section, code == "CASH") for code, _, section in ACCOUNTS],
                command_id="http-map-" + entity, actor=actor)
        if entity != "group":
            with runtime.actor("checker") as (connection, _, actor):
                PostgresFinancialReportingRepository(connection, runtime.base.tenant).review_map(mapping["id"], expected_digest=mapping["map_digest"],
                    reason="Actual independent map review", command_id="http-map-review-" + entity, actor=actor)
            reviewed_maps[entity] = mapping["id"]
    with client(runtime, intercompany_database, tmp_path, "maker") as (session, headers):
        response = session.get(ROOT + "/catalog", headers=headers)
        assert response.status_code == 200, (response.text, failures)
        masters = response.json()["catalog"]
        assert {row["id"] for row in masters["entities"]} == {"entity", "buyer", "group"}
        assert {row["account_code"] for row in masters["accounts"]} >= {"IC_AR", "IC_AP", "IC_REVENUE", "IC_EXPENSE", "CASH"}
        assert "STOCK" in {row["journal_code"] for row in masters["journals"]}
        assert {row["id"] for row in masters["periods"]} == {"period"}
        assert {row["legal_entity_id"]: row["id"] for row in masters["maps"]} == reviewed_maps
