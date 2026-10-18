"""Exact intent, retained source hydration and append-only owned reversals."""

from dataclasses import asdict, replace
from fractions import Fraction
from typing import Any

import pytest

from reconforge.domain.customer_partial_return_commands import CustomerPartialReturnPreparation
from reconforge.domain.customer_partial_returns import (
    PartialReturnHistory,
    apply_partial_return,
    collect_partial_return,
    partial_return_balance,
    prepare_partial_return,
    refund_partial_return,
    reverse_partial_return_event,
)
from reconforge.domain.finance_posting import FinancePostingError, canonical_json, digest_payload
from reconforge.infrastructure.postgres_customer_partial_returns import _hydrate_event, _hydrate_source, _source_payload
from tests.test_customer_partial_return_design import DESIGN
from tests.test_customer_partial_returns_domain import source_for


def request() -> CustomerPartialReturnPreparation:
    return CustomerPartialReturnPreparation("work", "org", "entity", "ORG", "ENTITY", "ORDER", 2,
        "period", "2026-10-15", "CASH", "REFUND", "CASH", "Actual scoped credit intent", 0)


@pytest.mark.parametrize("field,value", [
    ("quantity_scaled", True), ("quantity_scaled", 1.0), ("quantity_scaled", "2"), ("quantity_scaled", 0),
    ("expected_history_version", True), ("expected_history_version", -1), ("expected_history_version", 256),
    ("expected_history_version", "0"), ("expected_history_version", 0.0), ("reason", " "), ("reason", None),
])
def test_strict_native_intent_never_infers_financial_or_history_values(field: str, value: Any) -> None:
    with pytest.raises((FinancePostingError, ValueError)):
        replace(request(), **{field: value}).payload()


def test_retained_source_round_trip_uses_captured_context_and_preserves_original_fingerprint() -> None:
    source = source_for(DESIGN["cases"][0])
    retained = _source_payload(source, {"original": "private-observed-envelope"}, [])
    original = canonical_json(retained)
    hydrated = _hydrate_source(retained)
    assert hydrated.fingerprint == source.fingerprint == digest_payload(source.fingerprint_payload)
    assert hydrated.registry_context.snapshot() == source.registry_context.snapshot()
    assert canonical_json(retained) == original


def test_return_inverse_appends_history_and_restores_only_its_own_latest_economics() -> None:
    source = source_for(DESIGN["cases"][0])
    before = PartialReturnHistory(source)
    plan = prepare_partial_return(before, source.quantity_scaled)
    returned = apply_partial_return(before, plan)
    reversed_history = reverse_partial_return_event(returned, 1)
    balance = partial_return_balance(reversed_history)
    assert (balance.returned_quantity_scaled, balance.credited_minor, balance.cogs_restored_minor, balance.refund_due_minor) == (0, 0, 0, 0)
    assert balance.collected_minor == source.collected_minor
    assert balance.outstanding_minor == source.gross_minor-source.collected_minor
    assert before.events == () and returned.events[0] == reversed_history.events[0]
    assert len(reversed_history.events) == 2 and reversed_history.events[1].kind == "ReverseReturn"
    assert _hydrate_event(asdict(reversed_history.events[-1])) == reversed_history.events[-1]
    assert Fraction(plan.credit_minor, source.gross_minor) == 1


def test_refund_must_be_reversed_before_credit_and_cannot_be_reversed_twice() -> None:
    source = source_for(DESIGN["cases"][1])
    history = PartialReturnHistory(source)
    history = apply_partial_return(history, prepare_partial_return(history, source.quantity_scaled))
    assert source.collected_minor > 0
    history = refund_partial_return(history, source.collected_minor)
    with pytest.raises(FinancePostingError, match="latest"):
        reverse_partial_return_event(history, 1)
    corrected = reverse_partial_return_event(history, 2)
    assert partial_return_balance(corrected).refunded_minor == 0
    with pytest.raises(FinancePostingError, match="latest"):
        reverse_partial_return_event(corrected, 2)
    corrected = reverse_partial_return_event(corrected, 1)
    assert partial_return_balance(corrected).credited_minor == 0
    assert len(corrected.events) == 4 and history.events == corrected.events[:2]


def test_later_real_cash_collection_cannot_be_erased_by_reversing_earlier_return() -> None:
    source = source_for(DESIGN["cases"][0])
    history = PartialReturnHistory(source)
    take = DESIGN["cases"][0]["steps"][0]["quantity_scaled"]
    history = apply_partial_return(history, prepare_partial_return(history, take))
    residual = partial_return_balance(history).outstanding_minor
    assert residual > 0
    history = collect_partial_return(history, min(residual, 1))
    with pytest.raises(FinancePostingError, match="latest"):
        reverse_partial_return_event(history, 1)


def test_coherently_resealed_reverse_magnitudes_are_recomputed_and_refused() -> None:
    source = source_for(DESIGN["cases"][0])
    history = PartialReturnHistory(source)
    history = apply_partial_return(history, prepare_partial_return(history, source.quantity_scaled))
    reversed_history = reverse_partial_return_event(history, 1)
    event = reversed_history.events[-1]
    assert event.return_values is not None
    changed = replace(event, return_values=replace(event.return_values, credit_minor=event.return_values.credit_minor-1))
    with pytest.raises(FinancePostingError):
        partial_return_balance(PartialReturnHistory(source, (*history.events, changed)))
