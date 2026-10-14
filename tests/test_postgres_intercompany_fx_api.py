"""Actual authenticated HTTP multi-currency owner and retained scope contracts."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.api_route_registration import registered_http_operations
from tests.test_postgres_intercompany_fx import (
    FxRuntime,
    intercompany_fx_database,
    preparation,
    pytestmark,
    receipt_database,
    runtime,
)
from tests.test_postgres_operational_finance_api import client_for

__all__ = ["receipt_database", "intercompany_fx_database", "runtime", "pytestmark"]
ROOT = "/api/v1/intercompany-fx"


@contextmanager
def client(rt: FxRuntime, database: tuple[str, str], path: Path, actor: str, *, step_up: bool = True) -> Iterator[tuple[TestClient, dict[str, str]]]:
    with client_for(rt.base, database, path, actor, step_up=step_up) as (session, headers):
        # Exercise the real application assembly, never inject an extra router.
        assert registered_http_operations(session.app)[("GET", ROOT + "/sources")] == 1
        yield session, {key: value for key, value in headers.items() if key != "X-ReconForge-Legal-Entity"}


def body() -> dict[str, Any]:
    request = preparation().payload()
    request.pop("workspace_id")
    request.pop("organization_id")
    request.pop("organization_code")
    request["command_id"] = "http-original"
    request["transaction_minor"] = str(request["transaction_minor"])
    for book in ("seller", "buyer", "adjustment"):
        request[book].pop("entity_code")
        request[book].pop("currency_code")
    return request


def test_actual_http_native_source_three_humans_evidence_and_exact_ack(runtime: FxRuntime, intercompany_fx_database: tuple[str, str], tmp_path: Path) -> None:
    with client(runtime, intercompany_fx_database, tmp_path / "maker", "maker") as (session, headers):
        wrong = session.post(ROOT + "/sources", headers={**headers, "X-ReconForge-Legal-Entity": "seller"}, json=body())
        assert wrong.status_code == 403
        prepared = session.post(ROOT + "/sources", headers=headers, json=body())
        assert prepared.status_code == 200, prepared.text
        plan = prepared.json()["plan"]
        assert session.post(ROOT + "/sources", headers=headers, json=body()).json()["plan"] == plan
        assert {entry["snapshot"]["entry"]["currency_code"] for entry in plan["entries"]} == {"EUR", "GBP"}
        assert {entry["snapshot"]["entry"]["currency_rounding_policy"] for entry in plan["entries"]} == {"ROUND_HALF_UP"}
    with client(runtime, intercompany_fx_database, tmp_path / "checker", "checker") as (session, headers):
        reviewed = session.post(ROOT + "/plans/" + plan["id"] + "/review", headers=headers,
            json={"command_id": "http-review", "expected_plan_digest": plan["plan_digest"], "reason": "Actual review of both functional books"})
        assert reviewed.status_code == 200, reviewed.text
    with client(runtime, intercompany_fx_database, tmp_path / "poster", "poster") as (session, headers):
        request = {"command_id": "http-post", "expected_plan_digest": plan["plan_digest"], "reason": "Actual third human publication"}
        posted = session.post(ROOT + "/plans/" + plan["id"] + "/post", headers=headers, json=request)
        assert posted.status_code == 200, posted.text
        assert session.post(ROOT + "/plans/" + plan["id"] + "/post", headers=headers, json=request).json() == posted.json()
        proof = session.get(ROOT + "/plans/" + plan["id"] + "/evidence", headers=headers)
        assert proof.status_code == 200, proof.text
        assert [row["actor_id"] for row in proof.json()["evidence"]["phases"]] == ["maker", "checker", "poster"]
        assert len(proof.json()["evidence"]["native_effects"]) == 2
        catalog = session.get(ROOT + "/catalog", headers=headers)
        assert catalog.status_code == 200, catalog.text
        assert {row["code"] for row in catalog.json()["catalog"]["currencies"]} == {"USD", "EUR", "GBP"}
        page = session.get(ROOT + "/sources", headers=headers)
        assert page.status_code == 200, page.text
        assert page.json()["sources"]["items"][0]["id"] == plan["source_id"]


def test_actual_http_cached_grant_revocation_refuses_source_and_lost_ack(runtime: FxRuntime, intercompany_fx_database: tuple[str, str], tmp_path: Path) -> None:
    with client(runtime, intercompany_fx_database, tmp_path, "maker") as (session, headers):
        created = session.post(ROOT + "/sources", headers=headers, json=body())
        assert created.status_code == 200, created.text
        plan = created.json()["plan"]
        with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
            PostgresScopeAuthorityRepository(connection).revoke(tenant_id=runtime.base.tenant, grant_id="ic2-maker-group", actor_id="poster", reason="Withdraw current reporting adjustment scope")
        assert session.get(ROOT + "/sources/" + plan["source_id"], headers=headers).status_code == 403
        assert session.post(ROOT + "/sources", headers=headers, json=body()).status_code == 403


def test_http_rejects_unreviewed_number_coercion_and_requires_step_up(runtime: FxRuntime, intercompany_fx_database: tuple[str, str], tmp_path: Path) -> None:
    with client(runtime, intercompany_fx_database, tmp_path, "maker", step_up=False) as (session, headers):
        assert session.post(ROOT + "/sources", headers=headers, json=body()).status_code == 403
    with client(runtime, intercompany_fx_database, tmp_path / "confirmed", "maker") as (session, headers):
        unsafe = {**body(), "transaction_minor": 10001}
        result = session.post(ROOT + "/sources", headers=headers, json=unsafe)
        assert result.status_code == 422, result.text
