"""Closed invoice recovery evidence, immutable lines, and legacy due-date intent."""
from __future__ import annotations

from copy import deepcopy

import pytest

from reconforge.domain.receivables_replay import (
    InvoiceReplayError,
    invoice_creation_request,
    invoice_replay_envelope,
    verify_invoice_replay,
)


def ack() -> dict:
    return dict(id="invoice", workspace_id="work", organization_id=None, legal_entity_id=None,
                customer_id="customer", invoice_number="INV", invoice_date="2026-10-03", due_date="2026-10-31",
                currency_code="USD", subtotal_minor=100, tax_minor=0, total_minor=100,
                status="Draft", row_version=1, created_by="original-maker", created_at="2026-10-03T00:00:00Z",
                updated_at="2026-10-03T00:00:00Z", approved_by="", approved_at=None, credit_override_reason="",
                cancelled_by="", cancelled_at=None, cancel_reason="", allocated_minor=0, outstanding_minor=100,
                currency_precision=None, currency_rounding_policy=None, currency_registry_version=None,
                currency_registry_digest=None, monetary_policy={"status": "unverified"},
                lines=[dict(id="line", invoice_id="invoice", line_number=1, description="Synthetic", quantity="1",
                            unit_price_minor=100, tax_minor=0, line_total_minor=100, created_at="2026-10-03T00:00:00Z")])


def test_historical_ack_ignores_only_explicit_current_workflow_differences() -> None:
    original = ack()
    request = invoice_creation_request(original)
    envelope = invoice_replay_envelope(request, original)
    current = {**original, "status": "Paid", "row_version": 9, "approved_by": "checker", "approved_at": "later",
               "updated_at": "later", "allocated_minor": 100, "outstanding_minor": 0, "credit_override_reason": "approved"}
    assert verify_invoice_replay(envelope, request, current) == original
    cancelled = {**original, "status": "Cancelled", "row_version": 3, "cancelled_by": "checker",
                 "cancelled_at": "later", "cancel_reason": "Synthetic cancellation", "updated_at": "later"}
    assert verify_invoice_replay(envelope, request, cancelled) == original


@pytest.mark.parametrize("field,value", [
    ("schema_version", True), ("schema_version", 2), ("kind", "receivables.receipt.request-response"),
    ("request_digest", "0" * 64), ("response", []), ("extra", 1),
])
def test_wrapper_changes_are_refused(field: str, value: object) -> None:
    original = ack()
    request = invoice_creation_request(original)
    envelope = invoice_replay_envelope(request, original)
    envelope[field] = value
    with pytest.raises(InvoiceReplayError):
        verify_invoice_replay(envelope, request, original)


@pytest.mark.parametrize("field,value", [
    ("id", "foreign"), ("workspace_id", "foreign"), ("organization_id", "foreign"), ("legal_entity_id", "foreign"),
    ("customer_id", "foreign"), ("invoice_number", "other"), ("invoice_date", "2026-10-04"), ("due_date", "2026-12-01"),
    ("created_by", "other-human"), ("created_at", "later"), ("updated_at", "later"),
    ("currency_code", "JPY"), ("total_minor", 200), ("tax_minor", False), ("subtotal_minor", True),
    ("status", "Approved"), ("row_version", True), ("approved_by", "checker"), ("cancelled_at", "later"),
    ("allocated_minor", 1), ("outstanding_minor", 99), ("currency_precision", 2), ("monetary_policy", {}), ("extra", 1),
])
def test_cached_header_and_initial_workflow_are_exact(field: str, value: object) -> None:
    original = ack()
    request = invoice_creation_request(original)
    envelope = invoice_replay_envelope(request, deepcopy(original))
    envelope["response"][field] = value
    with pytest.raises(InvoiceReplayError):
        verify_invoice_replay(envelope, request, original)


@pytest.mark.parametrize("field,value", [("id", "other"), ("invoice_id", "other"), ("line_number", True),
                                       ("description", "other"), ("quantity", "2"), ("unit_price_minor", 200),
                                       ("tax_minor", False), ("line_total_minor", 200), ("created_at", "later"), ("extra", 1)])
def test_cached_line_evidence_is_exact(field: str, value: object) -> None:
    original = ack()
    request = invoice_creation_request(original)
    envelope = invoice_replay_envelope(request, deepcopy(original))
    envelope["response"]["lines"][0][field] = value
    with pytest.raises(InvoiceReplayError):
        verify_invoice_replay(envelope, request, original)


def test_legacy_requires_explicit_due_date_and_complete_independent_fields() -> None:
    original = ack()
    request = invoice_creation_request(original)
    assert verify_invoice_replay(original, request, original) == original
    omitted = {**request, "due_date": None}
    with pytest.raises(InvoiceReplayError, match="omitted due-date"):
        verify_invoice_replay(original, omitted, original)
    assert verify_invoice_replay(invoice_replay_envelope(omitted, original), omitted, original) == original
    for key in original:
        partial = dict(original)
        partial.pop(key)
        with pytest.raises(InvoiceReplayError):
            verify_invoice_replay(partial, request, original)


def test_pre_policy_legacy_reader_does_not_infer_missing_interpretation() -> None:
    original = ack()
    request = invoice_creation_request(original)
    old = {key: value for key, value in original.items() if not key.startswith("currency_") or key == "currency_code"}
    old.pop("monetary_policy")
    assert verify_invoice_replay(old, request, original) == old
    with pytest.raises(InvoiceReplayError):
        verify_invoice_replay(old, request, {**original, "currency_precision": 2})


def test_request_digest_does_not_authorize_foreign_source_or_swapped_lines() -> None:
    original = ack()
    request = invoice_creation_request(original)
    foreign = {**original, "customer_id": "foreign"}
    with pytest.raises(InvoiceReplayError, match="authoritative source"):
        verify_invoice_replay(invoice_replay_envelope(request, foreign), request, foreign)
    original["lines"].append({**original["lines"][0], "id": "second", "line_number": 2, "description": "Second"})
    original.update(subtotal_minor=200, total_minor=200, outstanding_minor=200)
    request = invoice_creation_request(original)
    envelope = invoice_replay_envelope(request, deepcopy(original))
    envelope["response"]["lines"].reverse()
    with pytest.raises(InvoiceReplayError):
        verify_invoice_replay(envelope, request, original)
