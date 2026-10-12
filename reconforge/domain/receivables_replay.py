"""Verify invoice creation acknowledgements against independent retained sources."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from reconforge.domain.finance_policy import POLICY_COLUMNS

INVOICE_REPLAY_KIND = "receivables.invoice.request-response"
_HEADERS = ("id", "workspace_id", "organization_id", "legal_entity_id", "customer_id",
            "invoice_number", "invoice_date", "due_date", "currency_code", "subtotal_minor",
            "tax_minor", "total_minor")
_LINES = ("description", "quantity", "unit_price_minor", "tax_minor", "line_total_minor")
_ENVELOPE = {"schema_version", "kind", "request_digest", "response"}
_INITIAL_WORKFLOW = {
    "status": "Draft", "row_version": 1, "approved_by": "", "approved_at": None,
    "credit_override_reason": "", "cancelled_by": "", "cancelled_at": None, "cancel_reason": "",
    "allocated_minor": 0,
}


class InvoiceReplayError(ValueError):
    """A retained acknowledgement cannot establish the requested creation."""


def _canonical(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise InvoiceReplayError("Stored invoice recovery evidence is malformed.") from exc


def invoice_creation_request(source: Mapping[str, Any], *, tenant_id: str | None = None) -> dict[str, Any]:
    """Select normalized financial intent; None due_date explicitly means omitted.

    The requesting actor is deliberately excluded: currently authorized humans
    may recover a workspace-global key without changing original attribution.
    Adapters resolve the customer, scope and deterministic ID independently.
    """
    try:
        request = {key: source[key] for key in _HEADERS}
        lines = source["lines"]
        if not isinstance(lines, list) or not lines or any(not isinstance(line, Mapping) for line in lines):
            raise ValueError
        request["lines"] = [{key: line[key] for key in _LINES} for line in lines]
        request["tenant_id"] = tenant_id
        for key in ("subtotal_minor", "tax_minor", "total_minor"):
            if type(request[key]) is not int or request[key] < 0:
                raise ValueError
        for line in request["lines"]:
            if not isinstance(line["quantity"], str) or not isinstance(line["description"], str):
                raise ValueError
            if any(type(line[key]) is not int or line[key] < 0 for key in ("unit_price_minor", "tax_minor", "line_total_minor")):
                raise ValueError
        if (sum(line["line_total_minor"] for line in request["lines"]) != request["subtotal_minor"]
                or sum(line["tax_minor"] for line in request["lines"]) != request["tax_minor"]
                or request["subtotal_minor"] + request["tax_minor"] != request["total_minor"]):
            raise ValueError
        return request
    except (KeyError, TypeError, ValueError) as exc:
        raise InvoiceReplayError("Invoice creation identity is incomplete or invalid.") from exc


def _request_digest(request: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical({"kind": INVOICE_REPLAY_KIND, "request": request}).encode()).hexdigest()


def invoice_replay_envelope(request: Mapping[str, Any], response: Mapping[str, Any]) -> dict[str, Any]:
    """Retain request intent separately from the historical public response."""
    return {"schema_version": 1, "kind": INVOICE_REPLAY_KIND,
            "request_digest": _request_digest(request), "response": dict(response)}


def verify_invoice_replay(
    stored: Mapping[str, Any], request: Mapping[str, Any], authoritative: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify immutable source and original lifecycle, then return the old ack.

    The adapter must load authoritative by the independently requested identity,
    under current caller authority, and verify its retained monetary policy.
    No current customer terms or current registry participates in recovery.
    """
    wrapped = bool(set(stored) & _ENVELOPE)
    if wrapped:
        if (set(stored) != _ENVELOPE or type(stored.get("schema_version")) is not int
                or stored["schema_version"] != 1 or stored.get("kind") != INVOICE_REPLAY_KIND
                or not isinstance(stored.get("response"), dict)):
            raise InvoiceReplayError("Stored invoice recovery version is invalid; read the existing invoice.")
        if stored.get("request_digest") != _request_digest(request):
            raise InvoiceReplayError("Invoice idempotency key belongs to a different request.")
        response = dict(stored["response"])
    else:
        if request.get("due_date") is None:
            raise InvoiceReplayError("Legacy invoice recovery cannot prove omitted due-date intent; read the existing invoice.")
        response = dict(stored)

    source_request = invoice_creation_request(authoritative, tenant_id=request.get("tenant_id"))
    if request.get("due_date") is None:
        source_request["due_date"] = None
    if _canonical(request) != _canonical(source_request):
        raise InvoiceReplayError("Invoice request does not match its authoritative source.")

    expected = dict(authoritative)
    missing = set(expected) - set(response)
    legacy_policy_fields = {*POLICY_COLUMNS, "monetary_policy"}
    if (not wrapped and missing == legacy_policy_fields
            and all(authoritative.get(key) is None for key in POLICY_COLUMNS)):
        expected = {key: value for key, value in expected.items() if key not in legacy_policy_fields}
    if set(response) != set(expected):
        raise InvoiceReplayError("Stored invoice acknowledgement has missing or unknown fields.")
    if type(authoritative.get("row_version")) is not int or authoritative["row_version"] < 1:
        raise InvoiceReplayError("Authoritative invoice lifecycle version is invalid.")
    expected.update(_INITIAL_WORKFLOW, updated_at=authoritative["created_at"], outstanding_minor=authoritative["total_minor"])
    if _canonical(response) != _canonical(expected):
        raise InvoiceReplayError("Stored invoice acknowledgement differs from its authoritative source.")
    return response
