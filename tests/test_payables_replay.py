"""Backend-independent AP replay identity and legacy verification boundaries."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from reconforge.domain.payables_replay import PayablesReplayError, creation_identity, replay_envelope, verify_replay


def _order() -> dict[str, Any]:
    return {
        "id": "PO-1",
        "workspace_id": "workspace",
        "organization_id": "org",
        "legal_entity_id": "entity",
        "branch_id": None,
        "supplier_id": "supplier",
        "po_number": "PO-1",
        "order_date": "2026-07-28",
        "expected_date": None,
        "currency_code": "EGP",
        "created_by": "maker",
        "created_at": "2026-07-28T00:00:00+00:00",
        "updated_at": "2026-07-28T00:00:00+00:00",
        "row_version": 1,
        "status": "Draft",
        "approved_by": "",
        "approved_at": None,
        "lines": [
            {
                "id": "line-1",
                "purchase_order_id": "PO-1",
                "line_number": 1,
                "item_code": "ITEM",
                "description": "Exact source",
                "ordered_quantity": "2",
                "unit_price_minor": 9007199254740993,
                "tax_minor": 0,
                "created_at": "2026-07-28T00:00:00+00:00",
            }
        ],
    }


def test_historical_create_receipt_verifies_against_later_authoritative_state() -> None:
    old = _order()
    request = creation_identity("purchase_order", old)
    current = {
        **old,
        "status": "Approved",
        "row_version": 3,
        "approved_by": "checker",
        "approved_at": "2026-07-29T00:00:00+00:00",
        "updated_at": "2026-07-29T00:00:00+00:00",
    }
    verify_replay("purchase_order", old, request, current)
    verify_replay("purchase_order", replay_envelope("purchase_order", request, old), request, current)
    assert old["status"] == "Draft" and current["status"] == "Approved"


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": True},
        {"schema_version": 2},
        {"kind": "other"},
        {"request_digest": "0" * 64},
        {"response": []},
        {"unknown": "field"},
    ],
)
def test_unknown_or_malformed_replay_contract_is_not_legacy(change: dict[str, Any]) -> None:
    old = _order()
    request = creation_identity("purchase_order", old)
    with pytest.raises(PayablesReplayError):
        verify_replay("purchase_order", {**replay_envelope("purchase_order", request, old), **change}, request, old)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "PO-2"),
        ("workspace_id", "other"),
        ("organization_id", "other"),
        ("legal_entity_id", "other"),
        ("created_by", "other"),
        ("expected_date", "2026-08-01"),
    ],
)
def test_legacy_response_never_stands_in_for_another_source(field: str, value: object) -> None:
    old = _order()
    request = creation_identity("purchase_order", old)
    with pytest.raises(PayablesReplayError):
        verify_replay("purchase_order", {**old, field: value}, request, old)


def test_exact_money_and_initial_source_version_are_preserved() -> None:
    old = _order()
    request = creation_identity("purchase_order", old)
    for value in (9007199254740992, True):
        changed = deepcopy(old)
        changed["lines"][0]["unit_price_minor"] = value
        with pytest.raises(PayablesReplayError):
            verify_replay("purchase_order", changed, request, old)
    for version in (True, 0, 2):
        with pytest.raises(PayablesReplayError):
            verify_replay(
                "purchase_order",
                {**old, "row_version": version},
                request,
                {**old, "row_version": 3, "status": "Approved"},
            )
    incomplete = {key: value for key, value in old.items() if key != "created_by"}
    with pytest.raises(PayablesReplayError):
        verify_replay("purchase_order", incomplete, request, old)
