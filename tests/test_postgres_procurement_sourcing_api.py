"""Actual password/step-up/scope guarded sourcing API; no substituted business repository."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from reconforge.api.routes.procurement_sourcing import router
from tests.test_postgres_procurement_partial import CHECKER, MAKER, POSTER
from tests.test_postgres_procurement_partial_api import partial_client, post
from tests.test_postgres_procurement_sourcing import receipt_database, sourcing_runtime
from tests.test_procurement_multiline import enterprise_request

__all__ = ["receipt_database", "sourcing_runtime"]
ROOT = "/api/v1/procurement-sourcing/requisitions"


def registration(client: Any) -> None:
    if not any(getattr(route, "path", "") == ROOT for route in client.app.routes):
        client.app.include_router(router, prefix="/api/v1")


def test_actual_authenticated_sources_quotes_award_and_native_owner_api(
    sourcing_runtime: tuple[Any, dict[str, Any]], receipt_database: tuple[str, str], tmp_path: Path,
) -> None:
    runtime, budget = sourcing_runtime
    with ExitStack() as stack:
        maker, checker, poster = [stack.enter_context(partial_client(runtime, receipt_database, tmp_path / name, name)) for name in (MAKER, CHECKER, POSTER)]
        for transport, _ in (maker, checker, poster):
            registration(transport)
        body = asdict(enterprise_request("SRC5-API"))
        body["lines"] = [{**line, "unit_price_minor": str(line["unit_price_minor"])} for line in body["lines"]]
        head = post(maker, ROOT, {**body, "budget_id": budget["id"], "reason": "Retained actual API demand", "command_id": "api-source"})
        def act(client: Any, operation: str, **fields: Any) -> dict[str, Any]:
            return post(client, ROOT + "/" + head["id"] + "/" + operation, {"expected_version": head["row_version"],
                "reason": "Actual independent API control", "command_id": "api-source-" + operation, **fields})
        head = act(checker, "open-rfq")
        for supplier, prices in (("ALT", ["1300", "2000"]), ("SUP", ["1200", "2000"])):
            head = post(maker, ROOT + "/" + head["id"] + "/quotes", {"expected_version": head["row_version"], "command_id": "api-quote-" + supplier,
                "supplier_code": supplier, "unit_prices_minor": prices, "valid_until": "2026-10-31", "reason": "Original complete commercial quotation"})
        head = act(checker, "review-selection")
        head = act(poster, "award", expected_budget_version=budget["row_version"])
        result = poster[0].get(ROOT + "/" + head["id"], headers=poster[1])
        assert result.status_code == 200, result.text
        detail = result.json()
        assert detail["head"] == head and len(detail["quotations"]) == 2
        assert detail["source"]["ceiling_minor"] == "17000"
        assert detail["source"]["request"]["order"]["lines"][0]["unit_price_minor"] == "1200"
        assert isinstance(detail["canonical_source_json"], str)
        native = poster[0].get("/api/v1/procurement-partial/orders/" + head["order_id"], headers=poster[1])
        assert native.status_code == 200, native.text
        assert native.json()["order"]["number"] == "BPC1-SRC5-API" and native.json()["order"]["total_minor"] == "17000"
        owner = poster[0].get("/api/v1/procurement-commitments/orders/" + head["order_id"], headers=poster[1])
        assert owner.status_code == 200 and owner.json()["remaining_minor"] == "17000", owner.text


@pytest.mark.parametrize("prices", [[1, 2], ["1.1", "2000"], ["NaN", "2000"], ["-1", "2000"], ["0", "2000"], [True, "2000"]])
def test_api_rejects_nonexact_minor_quotation_before_business_mutation(
    sourcing_runtime: tuple[Any, dict[str, Any]], receipt_database: tuple[str, str], tmp_path: Path, prices: list[Any],
) -> None:
    runtime, _ = sourcing_runtime
    with partial_client(runtime, receipt_database, tmp_path, MAKER) as client:
        registration(client[0])
        response = client[0].post(ROOT + "/missing/quotes", headers=client[1], json={"expected_version": 2, "command_id": "bad-quote",
            "supplier_code": "SUP", "unit_prices_minor": prices, "valid_until": "2026-10-31", "reason": "Malformed exact price"})
        assert response.status_code == 422, response.text


def test_actual_api_requires_step_up_and_canonical_hierarchy(
    sourcing_runtime: tuple[Any, dict[str, Any]], receipt_database: tuple[str, str], tmp_path: Path,
) -> None:
    runtime, budget = sourcing_runtime
    with partial_client(runtime, receipt_database, tmp_path, MAKER, step_up=False) as client:
        registration(client[0])
        body = asdict(enterprise_request("SRC5-UNASSURED"))
        body["lines"] = [{**line, "unit_price_minor": str(line["unit_price_minor"])} for line in body["lines"]]
        response = client[0].post(ROOT, headers=client[1], json={**body, "budget_id": budget["id"], "reason": "Unassured actor", "command_id": "unassured"})
        assert response.status_code == 403 and response.json()["error"]["code"] == "step_up_required", response.text

