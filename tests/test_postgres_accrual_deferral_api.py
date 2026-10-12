"""Actual authenticated native AD1 commands; router bootstrap is conditional."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from reconforge.api.routes.accrual_deferral import router
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_accrual_deferral import (
    ScheduleRuntime,
    accrual_deferral_database,
    preparation,
    pytestmark,
    receipt_database,
    runtime,
    write_original,
)
from tests.test_postgres_operational_finance_api import client_for

__all__ = ["accrual_deferral_database", "runtime", "pytestmark", "receipt_database"]
ROOT = "/api/v1/accrual-deferral"


@contextmanager
def client(rt: ScheduleRuntime, database: tuple[str, str], path: Path, actor: str, *, step_up: bool = True) -> Iterator[tuple[TestClient, dict[str, str]]]:
    with client_for(rt.base, database, path, actor, step_up=step_up) as (session, headers):
        if not any(getattr(route, "path", None) == ROOT + "/sources" for route in session.app.routes):
            session.app.include_router(router, prefix="/api/v1")
        yield session, headers


def body() -> dict[str, Any]:
    value = preparation().payload()
    for key in ("schema_version", "workspace_id", "organization_id", "legal_entity_id", "organization_code", "entity_code", "allocation_policy"):
        value.pop(key)
    value["amount_minor"] = str(value["amount_minor"])
    for tranche in value["tranches"]:
        tranche.pop("amount_minor")
        tranche["weight"] = str(tranche["weight"])
    return {**value, "command_id": "http-original"}


def phase(rt: ScheduleRuntime, database: tuple[str, str], path: Path, plan: dict[str, Any], suffix: str) -> dict[str, Any]:
    for actor, operation in (("checker", "review"), ("poster", "post")):
        with client(rt, database, path / actor, actor) as (session, headers):
            payload = {"command_id": "http-" + operation + "-" + suffix, "expected_plan_digest": plan["plan_digest"],
                "reason": "Independent actual HTTP " + operation}
            result = session.post(ROOT + "/plans/" + plan["id"] + "/" + operation, headers=headers, json=payload)
            assert result.status_code == 200, result.text
            assert session.post(ROOT + "/plans/" + plan["id"] + "/" + operation, headers=headers, json=payload).json() == result.json()
    return result.json()["plan"]


def test_actual_http_source_three_humans_tranche_exact_inverse_and_evidence(runtime: ScheduleRuntime, accrual_deferral_database: tuple[str, str], tmp_path: Path) -> None:
    with client(runtime, accrual_deferral_database, tmp_path / "initial", "maker") as (session, headers):
        result = session.post(ROOT + "/sources", headers=headers, json=body())
        assert result.status_code == 200, result.text
        prepared = result.json()["plan"]
        assert session.post(ROOT + "/sources", headers=headers, json=body()).json()["plan"] == prepared
        assert prepared["snapshot"]["entry"]["currency_rounding_policy"] == "ROUND_HALF_UP"
    source = phase(runtime, accrual_deferral_database, tmp_path / "source", prepared, "source")
    with client(runtime, accrual_deferral_database, tmp_path / "tranche", "maker") as (session, headers):
        result = session.post(ROOT + "/sources/" + source["source_id"] + "/tranches", headers=headers,
            json={"command_id": "http-tranche", "tranche_id": "T1"})
        assert result.status_code == 200, result.text
    tranche = phase(runtime, accrual_deferral_database, tmp_path / "tranche-publication", result.json()["plan"], "tranche")
    with client(runtime, accrual_deferral_database, tmp_path / "inverse", "maker") as (session, headers):
        result = session.post(ROOT + "/sources/" + source["source_id"] + "/reversals", headers=headers,
            json={"command_id": "http-inverse", "original_plan_id": tranche["id"], "period_id": "p2", "posting_date": "2026-11-01",
                "reason": "Exact original HTTP native tranche inverse"})
        assert result.status_code == 200, result.text
    inverse = phase(runtime, accrual_deferral_database, tmp_path / "inverse-publication", result.json()["plan"], "inverse")
    assert inverse["equation"]["original_posting_effect_id"] == tranche["posting_effect_id"]
    with client(runtime, accrual_deferral_database, tmp_path / "evidence", "poster") as (session, headers):
        catalog = session.get(ROOT + "/catalog", headers=headers)
        assert catalog.status_code == 200, catalog.text
        assert catalog.json()["entity"]["currency_code"] == "USD"
        assert len(session.get(ROOT + "/sources", headers=headers).json()["items"]) == 1
        proof = session.get(ROOT + "/sources/" + source["source_id"] + "/evidence", headers=headers)
        assert proof.status_code == 200, proof.text
        assert len(proof.json()["native_effects"]) == 3
        write_original(proof.json(), "actual-http-tranche-inverse")


def test_actual_http_strict_money_stepup_and_cached_grant_revocation_refuse_new_and_replayed_commands(runtime: ScheduleRuntime, accrual_deferral_database: tuple[str, str], tmp_path: Path) -> None:
    with client(runtime, accrual_deferral_database, tmp_path / "without-stepup", "maker", step_up=False) as (session, headers):
        assert session.post(ROOT + "/sources", headers=headers, json=body()).status_code == 403
    with client(runtime, accrual_deferral_database, tmp_path / "strict", "maker") as (session, headers):
        assert session.post(ROOT + "/sources", headers=headers, json={**body(), "amount_minor": 10001}).status_code == 422
        result = session.post(ROOT + "/sources", headers=headers, json=body())
        assert result.status_code == 200, result.text
        source = result.json()["plan"]["source_id"]
        with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
            PostgresScopeAuthorityRepository(connection).revoke(tenant_id=runtime.base.tenant, grant_id="ad1-makerentity", actor_id="poster", reason="Withdraw current native entity source grant")
        assert session.get(ROOT + "/sources/" + source, headers=headers).status_code == 403
        assert session.post(ROOT + "/sources", headers=headers, json=body()).status_code == 403
