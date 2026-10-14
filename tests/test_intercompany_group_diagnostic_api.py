"""Strict bounded explicit selection; native authenticated gate is separate."""

import json
from dataclasses import asdict

import pytest
from fastapi import APIRouter, FastAPI, routing

from reconforge.api import create_api_app
from reconforge.api.errors import APIError
from reconforge.api.routes.intercompany_group_diagnostic import parse_selection
from reconforge.api.routes.intercompany_group_diagnostic import router as diagnostic_router
from tests.api_route_registration import registered_http_operations
from tests.test_intercompany_group_diagnostic import fixture


def test_explicit_canonical_original_selection_round_trips_without_inferred_opening():
    selection, _, _ = fixture()
    assert parse_selection(json.dumps(asdict(selection))) == selection


@pytest.mark.parametrize("attack", ["float", "bool", "missing_opening", "unknown", "duplicate_source", "oversize", "duplicate_json", "deeply_nested"])
def test_ambiguous_or_unbounded_selected_source_query_is_rejected(attack):
    selection, _, _ = fixture()
    value = asdict(selection)
    pin = value["pins"][0]
    if attack == "float":
        pin["opening"]["seller_minor"] = 0.0
    elif attack == "bool":
        pin["opening"]["buyer_minor"] = False
    elif attack == "missing_opening":
        del pin["opening"]["basis"]
    elif attack == "unknown":
        pin["whole_group_complete"] = True
    elif attack == "duplicate_source":
        value["pins"] = value["pins"] * 2
    raw = json.dumps(value)
    if attack == "oversize":
        raw += " " * 32_768
    if attack == "duplicate_json":
        raw = raw.replace('"seller_minor": 0', '"seller_minor": 1,"seller_minor": 0')
    if attack == "deeply_nested":
        raw = '{"pins":' + "[" * 4_000 + "0" + "]" * 4_000 + "}"
        assert len(raw) < 32_768
    with pytest.raises(APIError) as error:
        parse_selection(raw)
    assert error.value.status_code == 400 and error.value.code == "intercompany_group_selection_invalid"


def test_real_application_retains_exactly_one_effective_group_and_fx_operation(tmp_path):
    app = create_api_app(tmp_path / "unused.db")
    operations = registered_http_operations(app)
    assert operations[("GET", "/api/v1/intercompany-group-diagnostic/report")] == 1
    assert operations[("GET", "/api/v1/intercompany-group-diagnostic/evidence")] == 1
    assert operations[("GET", "/api/v1/intercompany-fx/sources")] == 1
    app.include_router(diagnostic_router, prefix="/api/v1")
    duplicated = registered_http_operations(app)
    assert duplicated[("GET", "/api/v1/intercompany-group-diagnostic/report")] == 2
    assert duplicated[("GET", "/api/v1/intercompany-group-diagnostic/evidence")] == 2


def test_effective_registration_counter_preserves_nested_and_local_duplicates():
    leaf = APIRouter()

    def endpoint():
        return {}

    leaf.add_api_route("/same", endpoint, methods=["GET", "POST"])
    leaf.add_api_route("/same", endpoint, methods=["GET"])
    parent = APIRouter()
    parent.include_router(leaf, prefix="/child")
    app = FastAPI()
    app.include_router(parent, prefix="/parent")
    operations = registered_http_operations(app)
    assert operations[("GET", "/parent/child/same")] == 2
    assert operations[("POST", "/parent/child/same")] == 1


def test_flat_registration_counter_remains_compatible_without_context_iterator(monkeypatch):
    monkeypatch.setattr(routing, "iter_route_contexts", None, raising=False)
    app = FastAPI()

    def endpoint():
        return {}

    app.add_api_route("/flat", endpoint, methods=["GET"])
    app.add_api_route("/flat", endpoint, methods=["GET"])
    assert registered_http_operations(app)[("GET", "/flat")] == 2
