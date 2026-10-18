"""Exact source-to-GL plans, closed evidence and full physical/value inverse."""
from __future__ import annotations

from copy import deepcopy

import pytest

from reconforge.domain.finance_posting import PostingActor, digest_payload
from reconforge.domain.inventory_receipt_posting import (
    InventoryReceiptPostingError,
    make_effect,
    make_plan,
    make_review,
    verify_effect,
    verify_inverse,
    verify_plan,
    verify_review,
)
from reconforge.io.inventory_receipt_posting import decode_receipt_json, encode_receipt_json


def plan(*, inverse_of=None, precision=2):
    original = None if inverse_of is None else {"plan_id": inverse_of["plan_id"], "posting_effect_id": inverse_of["artifacts"]["posting_effect_id"],
                                               "valuation_document_id": inverse_of["artifacts"]["valuation_document_id"],
                                               "valuation_line_id": inverse_of["artifacts"]["valuation_line_id"], "cost_layer_id": inverse_of["artifacts"]["cost_layer_id"]}
    return make_plan(operation="Receipt" if original is None else "FullReceiptReversal",
                     scope=dict(workspace_id="work", organization_id="org", legal_entity_id="entity", organization_code="ORG", entity_code="ENTITY"),
                     source=dict(number="RECEIPT" if original is None else "INVERSE", posting_date="2026-10-03", period_id="period", item_id="item", uom_id="unit", location_id="location", quantity_scaled=10, quantity_precision=0, quantity_text="10", total_value_minor=12000),
                     mapping=dict(policy_id="mapping", costing_method="FIFO", currency_code="USD", journal_id="journal", inventory_account_id="stock", receipt_clearing_account_id="clearing", cogs_account_id="cogs", adjustment_account_id="adjustment"),
                     currency_policy=dict(currency_code="USD", currency_precision=precision, currency_rounding_policy="ROUND_HALF_UP", currency_registry_version="synthetic-v1", currency_registry_digest="a" * 64),
                     actor=PostingActor("maker", "original-maker", frozenset()), prepared_at="2026-10-03T00:00:00Z", reason="Synthetic receipt", audit_event_id="audit", outbox_event_id="outbox", original=original)


@pytest.mark.parametrize("precision", [0, 2, 3])
def test_exact_receipt_golden_and_inverse_do_not_reinterpret_currency(precision):
    receipt = plan(precision=precision)
    assert verify_plan(decode_receipt_json(encode_receipt_json(receipt))) == receipt
    first, second = receipt["finance_snapshot"]["lines"]
    assert (first["account_id"], first["debit_minor"], first["credit_minor"]) == ("stock", 12000, 0)
    assert (second["account_id"], second["debit_minor"], second["credit_minor"]) == ("clearing", 0, 12000)
    inverse = plan(inverse_of=receipt, precision=precision)
    verify_inverse(inverse, receipt)
    assert inverse["artifacts"]["cost_layer_id"] == receipt["artifacts"]["cost_layer_id"]
    assert inverse["artifacts"]["valuation_document_id"] is None
    assert inverse["finance_snapshot"]["lines"][0]["credit_minor"] == 12000
    assert inverse["finance_snapshot"]["lines"][1]["debit_minor"] == 12000
    for name in ("movement_id", "finance_entry_id", "posting_effect_id", "finance_line_1_id", "finance_line_2_id"):
        assert inverse["artifacts"][name] != receipt["artifacts"][name]


@pytest.mark.parametrize("field,value", [("quantity_scaled", True), ("quantity_precision", False), ("total_value_minor", 12000.0),
                                       ("quantity_text", "1E1"), ("quantity_scaled", 0), ("quantity_precision", 7), ("total_value_minor", 9_000_000_000_000_000_001)])
def test_receipt_source_exact_types_and_supported_scale(field, value):
    corrupt = deepcopy(plan())
    corrupt["source"][field] = value
    with pytest.raises(InventoryReceiptPostingError):
        verify_plan(corrupt)


@pytest.mark.parametrize("field", ["movement_id", "movement_number", "finance_entry_id", "finance_entry_number", "finance_line_1_id", "finance_line_2_id", "posting_effect_id"])
def test_reserved_output_identity_cannot_name_or_launder_legacy_artifact(field):
    corrupt = deepcopy(plan())
    corrupt["artifacts"][field] = "LEGACY"
    # Recomputing a digest is not proof of ownership or canonical source identity.
    corrupt["plan_digest"] = digest_payload({key: value for key, value in corrupt.items() if key not in {"plan_digest", "preparation_audit_event_id", "preparation_outbox_event_id"}})
    with pytest.raises(InventoryReceiptPostingError):
        verify_plan(corrupt)


def test_independent_review_keeps_exact_future_finance_content():
    receipt = plan()
    args = dict(reviewed_at="2026-10-03T00:01:00Z", reason="Synthetic independent review", audit_event_id="review-audit", outbox_event_id="review-outbox")
    with pytest.raises(InventoryReceiptPostingError):
        make_review(receipt, actor=PostingActor("maker", "renamed-maker", frozenset()), **args)
    review = make_review(receipt, actor=PostingActor("checker", "checker", frozenset()), **args)
    assert verify_review(review, receipt) == review
    corrupt = {**review, "finance_validation_digest": "0" * 64}
    with pytest.raises(InventoryReceiptPostingError):
        verify_review(corrupt, receipt)


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":1.0}', '{"x":NaN}', '{"x":1e2}', '[]', '{"x":"' + 'a' * 2049 + '"}'])
def test_receipt_codec_rejects_ambiguous_lossy_or_unbounded_evidence(text):
    with pytest.raises(InventoryReceiptPostingError):
        decode_receipt_json(text)


def test_closed_plan_refuses_unknown_fields_and_partial_inverse():
    receipt = plan()
    with pytest.raises(InventoryReceiptPostingError):
        verify_plan({**receipt, "extra": "unknown"})
    inverse = plan(inverse_of=receipt)
    corrupt = deepcopy(inverse)
    corrupt["source"]["quantity_scaled"] = 9
    corrupt["source"]["quantity_text"] = "9"
    corrupt["plan_digest"] = digest_payload({key: value for key, value in corrupt.items() if key not in {"plan_digest", "preparation_audit_event_id", "preparation_outbox_event_id"}})
    verify_plan(corrupt)
    with pytest.raises(InventoryReceiptPostingError):
        verify_inverse(corrupt, receipt)


def complete_effect():
    receipt = plan()
    review = make_review(receipt, actor=PostingActor("checker", "checker", frozenset()), reviewed_at="2026-10-03T00:01:00Z", reason="Review", audit_event_id="ra", outbox_event_id="ro")
    finance = {"id": receipt["artifacts"]["posting_effect_id"], **{k: receipt["scope"][k] for k in ("workspace_id", "organization_id", "legal_entity_id")},
               "entry_id": receipt["artifacts"]["finance_entry_id"], "source_kind": "InventoryReceipt", "source_id": receipt["plan_id"], "purpose": "operational_posting",
               "reverses_effect_id": None, "validation_digest": receipt["finance_validation_digest"], "validation_contract_version": "finance-entry-review-v1",
               **receipt["currency_policy"], "snapshot": receipt["finance_snapshot"], "posted_actor_id": "poster", "posted_at": "2026-10-03T00:02:00Z",
               "reason": "Post", "audit_event_id": "fa", "outbox_event_id": "fo"}
    return receipt, review, make_effect(receipt, review, finance, audit_event_id="ca", outbox_event_id="co")


def test_effect_requires_closed_full_finance_projection_and_survives_codec():
    receipt, review, effect = complete_effect()
    assert verify_effect(decode_receipt_json(encode_receipt_json(effect)), receipt, review) == effect
    for key in effect["finance_effect"]:
        malformed = deepcopy(effect)
        del malformed["finance_effect"][key]
        with pytest.raises(InventoryReceiptPostingError):
            verify_effect(malformed, receipt, review)
    malformed = deepcopy(effect)
    malformed["finance_effect"]["private"] = "unreviewed"
    malformed["effect_digest"] = digest_payload({k: v for k, v in malformed.items() if k != "effect_digest"})
    with pytest.raises(InventoryReceiptPostingError):
        verify_effect(malformed, receipt, review)


@pytest.mark.parametrize("field,value", [("currency_precision", True), ("source_id", "other"), ("purpose", "other"), ("posted_actor_id", "maker"), ("reason", "x" * 501)])
def test_resealed_effect_cannot_change_source_policy_or_human_proof(field, value):
    receipt, review, effect = complete_effect()
    malformed = deepcopy(effect)
    malformed["finance_effect"][field] = value
    malformed = make_effect(receipt, review, malformed["finance_effect"], audit_event_id="ca", outbox_event_id="co")
    with pytest.raises(InventoryReceiptPostingError):
        verify_effect(malformed, receipt, review)
