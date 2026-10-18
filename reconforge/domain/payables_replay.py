"""AP creation replay identity, with explicitly verified legacy response readers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

KIND = "payables.command.request-response"
_HEADERS = {
    "purchase_order": (
        "id",
        "workspace_id",
        "organization_id",
        "legal_entity_id",
        "branch_id",
        "supplier_id",
        "po_number",
        "order_date",
        "expected_date",
        "currency_code",
        "created_by",
    ),
    "goods_receipt": (
        "id",
        "workspace_id",
        "organization_id",
        "legal_entity_id",
        "purchase_order_id",
        "receipt_number",
        "receipt_date",
        "created_by",
    ),
    "supplier_invoice": (
        "id",
        "workspace_id",
        "organization_id",
        "legal_entity_id",
        "supplier_id",
        "purchase_order_id",
        "invoice_number",
        "invoice_date",
        "due_date",
        "currency_code",
        "tax_minor",
        "total_minor",
        "created_by",
    ),
}
_LINES = {
    "purchase_order": ("item_code", "description", "ordered_quantity", "unit_price_minor", "tax_minor"),
    "goods_receipt": ("purchase_order_line_id", "received_quantity"),
    "supplier_invoice": (
        "purchase_order_line_id",
        "description",
        "invoiced_quantity",
        "unit_price_minor",
        "tax_minor",
        "line_total_minor",
    ),
}
_WORKFLOW_FIELDS = {"status", "updated_at", "row_version", "approved_by", "approved_at", "three_way_match"}


class PayablesReplayError(ValueError):
    """A receipt cannot establish the requested authoritative AP creation."""


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def creation_identity(operation: str, value: Mapping[str, Any]) -> dict[str, Any]:
    """Exclude workflow state while retaining every normalized creation input."""
    try:
        result = {key: value[key] for key in _HEADERS[operation]}
        result["lines"] = [{key: line[key] for key in _LINES[operation]} for line in value["lines"]]
        if operation == "goods_receipt":
            result["lines"].sort(key=lambda line: line["purchase_order_line_id"])
        return result
    except (KeyError, TypeError, AttributeError) as exc:
        raise PayablesReplayError(
            "Stored Payables replay identity is incomplete; inspect the existing document."
        ) from exc


def request_digest(operation: str, request: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical({"kind": KIND, "operation": operation, "request": request}).encode()).hexdigest()


def replay_envelope(operation: str, request: Mapping[str, Any], response: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": KIND,
        "request_digest": request_digest(operation, request),
        "response": dict(response),
    }


def verify_replay(
    operation: str,
    stored: Mapping[str, Any],
    request: Mapping[str, Any],
    authoritative: Mapping[str, Any],
    *,
    receipt_scope: Mapping[str, Any] | None = None,
) -> None:
    """Verify a historical create acknowledgement, then let callers return current state.

    Legacy objects contain all creation fields, but do not prove any missing actor,
    field or source. No upgrade invents that missing information.
    """
    if "schema_version" in stored or "kind" in stored or "response" in stored:
        if (
            set(stored) != {"schema_version", "kind", "request_digest", "response"}
            or type(stored.get("schema_version")) is not int
            or stored["schema_version"] != 1
            or stored.get("kind") != KIND
            or not isinstance(stored.get("response"), dict)
        ):
            raise PayablesReplayError("Stored Payables replay version is unsupported; inspect the existing document.")
        if stored["request_digest"] != request_digest(operation, request):
            raise PayablesReplayError("Payables idempotency key belongs to a different request.")
        cached = stored["response"]
    else:
        cached = stored
    source_identity = dict(authoritative)
    if operation == "goods_receipt":
        if receipt_scope is None or set(receipt_scope) != {"organization_id", "legal_entity_id"}:
            raise PayablesReplayError("Payables receipt replay requires its authorized purchase-order scope.")
        source_identity.update(receipt_scope)
    if _canonical(creation_identity(operation, source_identity)) != _canonical(request):
        raise PayablesReplayError("Payables replay request does not match the authoritative source.")
    if set(cached) != set(authoritative):
        raise PayablesReplayError("Stored Payables replay response is incomplete or has unknown fields.")
    if operation != "goods_receipt":
        old_version, current_version = cached.get("row_version"), authoritative.get("row_version")
        if type(old_version) is not int or old_version != 1 or type(current_version) is not int or current_version < 1:
            raise PayablesReplayError("Stored Payables replay source version is invalid.")
        if cached.get("status") != "Draft":
            raise PayablesReplayError("Stored Payables replay source status is invalid.")
        cached = {key: value for key, value in cached.items() if key not in _WORKFLOW_FIELDS}
        authoritative = {key: value for key, value in authoritative.items() if key not in _WORKFLOW_FIELDS}
    if _canonical(cached) != _canonical(authoritative):
        raise PayablesReplayError("Stored Payables replay response does not match its authoritative source.")
