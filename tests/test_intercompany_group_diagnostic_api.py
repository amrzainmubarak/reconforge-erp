"""Strict bounded explicit selection; native authenticated gate is separate."""

import json
from dataclasses import asdict

import pytest

from reconforge.api.errors import APIError
from reconforge.api.routes.intercompany_group_diagnostic import parse_selection
from tests.test_intercompany_group_diagnostic import fixture


def test_explicit_canonical_original_selection_round_trips_without_inferred_opening():
    selection, _, _ = fixture()
    assert parse_selection(json.dumps(asdict(selection))) == selection


@pytest.mark.parametrize("attack", ["float", "bool", "missing_opening", "unknown", "duplicate_source", "oversize", "duplicate_json"])
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
    with pytest.raises(APIError) as error:
        parse_selection(raw)
    assert error.value.status_code == 400 and error.value.code == "intercompany_group_selection_invalid"
