"""Closed, exact public DTO boundary; original financial bodies stay native."""

from collections.abc import Mapping
from datetime import date
from typing import Any

from reconforge.domain.customer_returns import MAX_MINOR

SCOPE_FIELDS = frozenset({"workspace_id", "organization_id", "legal_entity_id"})
POLICY_FIELDS = frozenset({"currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest"})
PLAN_FIELDS = SCOPE_FIELDS | POLICY_FIELDS | frozenset({
    "schema_version", "id", "operation", "phase", "status", "plan_digest", "source_id", "source_order_id", "invoice_id",
    "quantity_precision", "quantity_scaled", "credit_minor", "cogs_restored_minor", "receivable_released_minor",
    "refund_entitlement_delta_minor", "amount_minor", "expected_history_version", "posting_date", "period_id",
    "preparer_actor_id", "reviewer_actor_id", "poster_actor_id", "original_id", "entries", "audit_event_id", "outbox_event_id",
})
BALANCE_FIELDS = SCOPE_FIELDS | POLICY_FIELDS | frozenset({
    "source_order_id", "source_id", "source_fingerprint", "history_fingerprint", "history_version", "gross_minor",
    "collected_minor", "credited_minor", "returned_quantity_scaled", "remaining_quantity_scaled", "quantity_precision",
    "refund_entitlement_minor", "refunded_minor", "refund_due_minor", "outstanding_minor", "active_plan_id",
})
ENTRY_FIELDS = frozenset({"entry_id", "purpose", "validation_digest", "posting_effect_id"})
ALLOCATION_POLICY = "remaining-original-v1"
PREFIXES = {"Return": "CR2", "Refund": "CRF2", "ReverseReturn": "CR2R", "ReverseRefund": "CRF2R"}
ENTRY_PURPOSES = {"Return": ("RevenueCredit", "CostRestoration"), "Refund": ("Refund",),
                  "ReverseReturn": ("ReverseRevenueCredit", "ReverseCostRestoration"), "ReverseRefund": ("ReverseRefund",)}


class CustomerPartialReturnResponseError(ValueError):
    """An unverifiable native response must never be published as an ACK."""


def _require(condition: bool) -> None:
    if not condition:
        raise CustomerPartialReturnResponseError("The native partial-return public contract refused this response.")


def _object(value: Any, fields: frozenset[str]) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == fields)
    return dict(value)


def _text(value: Any, *, maximum: int = 160, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    _require(type(value) is str and 0 < len(value) <= maximum and value == value.strip()
             and all(ord(character) >= 32 and ord(character) != 127 for character in value))


def _integer(value: Any, *, maximum: int, minimum: int = 0) -> None:
    _require(type(value) is int and minimum <= value <= maximum)


def _digest(value: Any) -> None:
    _require(type(value) is str and len(value) == 64 and all(character in "0123456789abcdef" for character in value))


def _identity(value: Any, prefix: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    _text(value)
    _require(value.startswith(prefix + "-") and len(value) == len(prefix) + 33
             and all(character in "0123456789abcdef" for character in value[len(prefix) + 1:]))


def _scope_policy(row: Mapping[str, Any], scope: Mapping[str, Any]) -> None:
    for key in SCOPE_FIELDS:
        _text(row[key])
        _require(row[key] == scope[key])
    currency = row["currency_code"]
    _require(type(currency) is str and len(currency) == 3 and all("A" <= character <= "Z" for character in currency))
    _integer(row["currency_precision"], maximum=8)
    _require(row["currency_rounding_policy"] == "ROUND_HALF_UP")
    _text(row["currency_registry_version"])
    _digest(row["currency_registry_digest"])
    _integer(row["quantity_precision"], maximum=6)


def _money(row: dict[str, Any], *, positive: frozenset[str] = frozenset()) -> None:
    for key, value in tuple(row.items()):
        if key.endswith(("_minor", "_scaled")):
            _integer(value, maximum=MAX_MINOR, minimum=1 if key in positive else 0)
            row[key] = str(value)


def _project_partial_plan(value: Any, scope: Mapping[str, Any], *, remainder: bool) -> dict[str, Any]:
    row = _object(value, PLAN_FIELDS | {"allocation_policy"} if remainder else PLAN_FIELDS)
    _scope_policy(row, scope)
    _require(row["schema_version"] == ("customer-partial-return-v2" if remainder else "customer-partial-return-v1")
             and type(row["operation"]) is str and row["operation"] in PREFIXES)
    if remainder:
        _require(row["allocation_policy"] == ALLOCATION_POLICY)
    operation = row["operation"]
    _identity(row["id"], PREFIXES[operation])
    _identity(row["source_id"], "CRS2")
    for key in ("source_order_id", "invoice_id", "period_id", "preparer_actor_id", "audit_event_id", "outbox_event_id"):
        _text(row[key])
    _text(row["posting_date"], maximum=10)
    try:
        canonical_date = date.fromisoformat(row["posting_date"]).isoformat()
    except ValueError as exc:
        raise CustomerPartialReturnResponseError("The native partial-return business date is invalid.") from exc
    _require(canonical_date == row["posting_date"])
    _digest(row["plan_digest"])
    _integer(row["phase"], maximum=3)
    _integer(row["expected_history_version"], maximum=255)
    phase = row["phase"]
    _require(row["status"] == ("Prepared", "Reviewed", "Posted", "Cancelled")[phase])
    _text(row["reviewer_actor_id"], nullable=True)
    _text(row["poster_actor_id"], nullable=True)
    _require(row["reviewer_actor_id"] is None or row["reviewer_actor_id"] != row["preparer_actor_id"])
    _require(phase != 0 or row["reviewer_actor_id"] is None)
    _require(phase not in {1, 2} or row["reviewer_actor_id"] is not None)
    _require((row["poster_actor_id"] is not None and row["poster_actor_id"] not in {row["preparer_actor_id"], row["reviewer_actor_id"]})
             if phase == 2 else row["poster_actor_id"] is None)
    merchandise = operation in {"Return", "ReverseReturn"}
    positive = frozenset({"quantity_scaled"}) if remainder else frozenset({"amount_minor", "quantity_scaled", "credit_minor", "cogs_restored_minor"})
    _money(row, positive=positive if merchandise else frozenset({"amount_minor"}))
    if merchandise:
        _require(int(row["credit_minor"]) == int(row["receivable_released_minor"]) + int(row["refund_entitlement_delta_minor"])
                 and int(row["amount_minor"]) == int(row["credit_minor"]) + int(row["cogs_restored_minor"]))
    else:
        _require(all(row[key] == "0" for key in ("quantity_scaled", "credit_minor", "cogs_restored_minor", "receivable_released_minor", "refund_entitlement_delta_minor")))
    if operation == "Return":
        _require(row["original_id"] is None)
    else:
        _identity(row["original_id"], "CRF2" if operation == "ReverseRefund" else "CR2")
    purposes = ENTRY_PURPOSES[operation]
    if remainder and merchandise:
        purposes = tuple(purpose for purpose, amount in zip(purposes, (row["credit_minor"], row["cogs_restored_minor"]), strict=True) if amount != "0")
    _require(type(row["entries"]) is list and len(row["entries"]) == len(purposes))
    entries = []
    for value, expected_purpose in zip(row["entries"], purposes, strict=True):
        entry = _object(value, ENTRY_FIELDS)
        _text(entry["entry_id"])
        _require(entry["purpose"] == expected_purpose)
        _digest(entry["validation_digest"])
        _text(entry["posting_effect_id"], nullable=True)
        _require((phase == 2) == (entry["posting_effect_id"] is not None))
        entries.append(entry)
    _require(len({entry["entry_id"] for entry in entries}) == len(entries))
    _require(phase != 2 or len({entry["posting_effect_id"] for entry in entries}) == len(entries))
    row["entries"] = entries
    return row


def project_partial_plan(value: Any, scope: Mapping[str, Any]) -> dict[str, Any]:
    return _project_partial_plan(value, scope, remainder=False)


def project_partial_plan_v2(value: Any, scope: Mapping[str, Any]) -> dict[str, Any]:
    return _project_partial_plan(value, scope, remainder=True)


def _project_partial_balance(value: Any, scope: Mapping[str, Any], *, remainder: bool) -> dict[str, Any]:
    row = _object(value, BALANCE_FIELDS | {"schema_version", "allocation_policy"} if remainder else BALANCE_FIELDS)
    if remainder:
        _require(row["schema_version"] == "customer-partial-return-balance-v2" and row["allocation_policy"] == ALLOCATION_POLICY)
    _scope_policy(row, scope)
    _identity(row["source_id"], "CRS2", nullable=True)
    _text(row["source_order_id"])
    _digest(row["source_fingerprint"])
    _digest(row["history_fingerprint"])
    _integer(row["history_version"], maximum=256)
    if row["active_plan_id"] is not None:
        _text(row["active_plan_id"])
        _require(any(row["active_plan_id"].startswith(prefix + "-") for prefix in PREFIXES.values()))
        _identity(row["active_plan_id"], row["active_plan_id"].split("-", 1)[0])
    _require(row["source_id"] is not None or row["history_version"] == 0 and row["active_plan_id"] is None)
    _money(row, positive=frozenset({"gross_minor"}))
    gross, collected, credited = (int(row[key]) for key in ("gross_minor", "collected_minor", "credited_minor"))
    _require(collected <= gross and credited <= gross and row["outstanding_minor"] == str(max(gross - collected - credited, 0))
             and row["refund_entitlement_minor"] == str(max(collected + credited - gross, 0))
             and int(row["refunded_minor"]) + int(row["refund_due_minor"]) == int(row["refund_entitlement_minor"]))
    return row


def project_partial_balance(value: Any, scope: Mapping[str, Any]) -> dict[str, Any]:
    return _project_partial_balance(value, scope, remainder=False)


def project_partial_balance_v2(value: Any, scope: Mapping[str, Any]) -> dict[str, Any]:
    return _project_partial_balance(value, scope, remainder=True)


def _project_partial_response(value: Any, scope: Mapping[str, Any], *, union: bool) -> dict[str, Any]:
    _require(type(value) is dict)
    def plan(raw: Any) -> dict[str, Any]:
        if union and type(raw) is dict and raw.get("schema_version") == "customer-partial-return-v2":
            return project_partial_plan_v2(raw, scope)
        return project_partial_plan(raw, scope)

    if set(value) == {"plan"}:
        return {"plan": plan(value["plan"])}
    if set(value) == {"balance"}:
        if union and type(value["balance"]) is dict and value["balance"].get("schema_version") == "customer-partial-return-balance-v2":
            return {"balance": project_partial_balance_v2(value["balance"], scope)}
        return {"balance": project_partial_balance(value["balance"], scope)}
    _require(set(value) == {"plans"} and type(value["plans"]) is list and len(value["plans"]) <= 200)
    plans = [plan(raw) for raw in value["plans"]]
    _require(len({plan["id"] for plan in plans}) == len(plans))
    return {"plans": plans}


def project_partial_response(value: Any, scope: Mapping[str, Any]) -> dict[str, Any]:
    return _project_partial_response(value, scope, union=False)


def project_partial_response_v2(value: Any, scope: Mapping[str, Any]) -> dict[str, Any]:
    return _project_partial_response(value, scope, union=True)
