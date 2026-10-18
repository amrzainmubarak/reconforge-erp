"""Independent rational checks for allocated originals and carrying release."""

from dataclasses import asdict, replace
from decimal import localcontext
from fractions import Fraction
from random import Random
from typing import Any

import pytest

from reconforge.domain.finance_policy import FinanceCurrencyPolicy
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.monetary_customer_partial_return_commands import (
    MonetaryPartialRefundPreparation,
    MonetaryPartialReturnPreparation,
    MonetaryPartialReversePreparation,
)
from reconforge.domain.monetary_customer_returns import (
    MonetaryComponent,
    MonetaryConsumption,
    MonetaryEvent,
    MonetaryHistory,
    MonetaryMovement,
    MonetaryPosition,
    MonetaryReturnSource,
    allocate_revenue,
    apply_monetary_event,
    prepare_monetary_event,
    replay_monetary_history,
)
from reconforge.domain.operational_fx_tax import (
    ForeignInvoicePreparation,
    HistoricalRate,
    TaxComponent,
    invoice_equation,
)
from reconforge.utils.money import CurrencyRegistryContext

DAY = "2026-10-15"


def rate(value: str) -> HistoricalRate:
    return HistoricalRate(value, "Synthetic reviewed source", DAY + "T09:00:00Z")


def original(*, foreign: str = "EUR", functional: str = "USD", amount: int = 10000,
             exchange: str = "1.25", quantity: int = 10, cost: int = 6000, tax: str | None = "0.14") -> MonetaryReturnSource:
    context = CurrencyRegistryContext.from_installed()
    request = ForeignInvoicePreparation("work", "org", "entity", "ORG", "ENTITY", "CUSTOMER", "INVOICE", DAY,
        "2026-11-15", "period", "GENERAL", foreign, amount, None if foreign == functional else rate(exchange),
        "EG", "SyntheticGoods", () if tax is None else (TaxComponent("synthetic-tax", "EG", "SyntheticGoods",
            "2026-01-01", "2026-12-31", tax, "TAX", "Synthetic illustrative fraction; not statutory"),),
        "AR", "REVENUE", "CASH", "FXGAIN", "FXLOSS", "Synthetic monetary Stock original")
    equation = invoice_equation(request, functional, context, allow_currency_identity=True)
    components: tuple[MonetaryComponent, ...] = (MonetaryComponent(0, "Net", "revenue-account", equation["foreign_net_minor"], equation["functional_net_minor"], "a" * 64),)
    components += tuple(MonetaryComponent(index, "Tax", "tax-account-" + str(index), part["foreign_tax_minor"],
        part["functional_tax_minor"], part["policy_digest"]) for index, part in enumerate(equation["tax_components"], 1))
    return MonetaryReturnSource("origin", "stock", "invoice", DAY, "b" * 64, quantity, 0,
        FinanceCurrencyPolicy.capture(foreign, context), FinanceCurrencyPolicy.capture(functional, context), context,
        components, (MonetaryConsumption(1, "consumption", "valuation-line", "layer", quantity, cost),),
        "c" * 64 if cost == 0 else None)


def append(history: MonetaryHistory, kind: Any, **kwargs: Any) -> tuple[MonetaryHistory, MonetaryEvent]:
    event = prepare_monetary_event(history, kind, posting_date=DAY, **kwargs)
    return apply_monetary_event(history, event), event


def nearest(value: Fraction, *, even: bool = False) -> int:
    quotient, remainder = divmod(value.numerator, value.denominator)
    if remainder * 2 > value.denominator or (remainder * 2 == value.denominator and (not even or quotient % 2)):
        quotient += 1
    return quotient


def test_full_taxed_foreign_original_two_credits_cash_gain_loss_and_refund() -> None:
    source = original()
    assert [(part.transaction_minor, part.functional_minor) for part in source.components] == [(10000, 12500), (1400, 1750)]
    history, first = append(MonetaryHistory(source), "Collection", amount_minor=4000, settlement_rate=rate("1.30"))
    assert (first.monetary.functional_cash_minor, first.monetary.functional_receivable_released_minor,
            first.monetary.functional_fx_gain_minor) == (5200, 5000, 200)
    history, credit = append(history, "Return", quantity_scaled=5)
    assert (credit.monetary.transaction_credit_minor, credit.monetary.functional_credit_minor,
            credit.monetary.functional_cost_minor) == (5700, 7125, 3000)
    assert (credit.after.transaction_outstanding_minor, credit.after.functional_outstanding_minor) == (1700, 2125)
    assert credit.monetary.transaction_refund_delta_minor == credit.monetary.functional_refund_delta_minor == 0
    history, second = append(history, "Collection", amount_minor=1700, settlement_rate=rate("1.20"))
    assert (second.monetary.functional_cash_minor, second.monetary.functional_receivable_released_minor,
            second.monetary.functional_fx_loss_minor) == (2040, 2125, 85)
    history, last = append(history, "Return", quantity_scaled=5)
    assert (last.monetary.transaction_refund_delta_minor, last.monetary.functional_refund_delta_minor) == (5700, 7125)
    history, refund = append(history, "Refund", amount_minor=5700, settlement_rate=rate("1.10"))
    assert (refund.monetary.functional_refund_released_minor, refund.monetary.functional_cash_minor,
            refund.monetary.functional_fx_gain_minor) == (7125, 6270, 855)
    final, _ = replay_monetary_history(history)
    assert (final.remaining_quantity_scaled, final.transaction_outstanding_minor, final.functional_outstanding_minor,
            final.transaction_refund_due_minor, final.functional_refund_due_minor) == (0, 0, 0, 0, 0)
    assert sum(event.monetary.functional_cost_minor for event in history.events) == 6000
    assert sum(event.monetary.transaction_credit_minor for event in history.events) == 11400
    assert sum(event.monetary.functional_credit_minor for event in history.events) == 14250


def test_zero_foreign_credit_is_explicit_alignment_and_never_functional_refund_liability() -> None:
    source = original(amount=1, exchange="2", quantity=3, cost=1, tax=None)
    history, first = append(MonetaryHistory(source), "Return", quantity_scaled=1)
    assert (first.monetary.transaction_credit_minor, first.monetary.functional_credit_minor,
            first.monetary.functional_alignment_gain_minor) == (0, 1, 1)
    assert first.monetary.transaction_refund_delta_minor == first.monetary.functional_refund_delta_minor == 0
    assert (first.after.transaction_outstanding_minor, first.after.functional_outstanding_minor) == (1, 2)
    history, second = append(history, "Return", quantity_scaled=1)
    assert (second.monetary.transaction_credit_minor, second.monetary.functional_credit_minor,
            second.monetary.functional_receivable_released_minor, second.monetary.functional_alignment_loss_minor) == (1, 1, 2, 1)
    history, final = append(history, "Return", quantity_scaled=1)
    assert final.monetary.functional_turnover_minor == final.monetary.functional_cost_minor == 1
    assert final.after.remaining_quantity_scaled == 0
    assert all(value == 0 for value in final.after.component_transaction_minor + final.after.component_functional_minor)


def test_positive_foreign_credit_with_zero_local_credit_and_zero_local_refund_preserves_physical_history() -> None:
    source = original(amount=2, exchange="0.5", quantity=3, cost=0, tax=None)
    history, paid = append(MonetaryHistory(source), "Collection", amount_minor=2, settlement_rate=rate("0.5"))
    assert paid.monetary.functional_cash_minor == 1
    history, credit = append(history, "Return", quantity_scaled=1)
    assert (credit.monetary.transaction_credit_minor, credit.monetary.functional_credit_minor,
            credit.monetary.transaction_refund_delta_minor, credit.monetary.functional_refund_delta_minor) == (1, 0, 1, 0)
    history, refund = append(history, "Refund", amount_minor=1, settlement_rate=rate("0.000001"))
    assert refund.monetary.functional_turnover_minor == 0
    assert refund.after.transaction_refund_due_minor == refund.after.functional_refund_due_minor == 0
    assert history.events[1].portions[0].quantity_scaled == 1


def test_latest_inverse_copies_exact_original_basis_and_does_not_reround() -> None:
    history, credit = append(MonetaryHistory(original()), "Return", quantity_scaled=3)
    restored, reverse = append(history, "ReverseReturn", quantity_scaled=3, original_sequence=credit.sequence)
    assert reverse.before == credit.after and reverse.after == credit.before
    assert reverse.monetary == credit.monetary and reverse.components == credit.components and reverse.portions == credit.portions
    again, repeated = append(restored, "Return", quantity_scaled=3)
    assert repeated.monetary == credit.monetary
    assert repeated.previous_history_fingerprint != credit.previous_history_fingerprint
    assert replay_monetary_history(again)[0] == credit.after


def test_intervening_collection_blocks_return_inverse_and_refund_inverse_restores_exact_carrying() -> None:
    history, paid = append(MonetaryHistory(original()), "Collection", amount_minor=11400, settlement_rate=rate("1.25"))
    history, credit = append(history, "Return", quantity_scaled=3)
    history, refund = append(history, "Refund", amount_minor=1000, settlement_rate=rate("1.3"))
    with pytest.raises(FinancePostingError):
        append(history, "ReverseReturn", quantity_scaled=3, original_sequence=credit.sequence)
    history, inverse = append(history, "ReverseRefund", amount_minor=1000, original_sequence=refund.sequence)
    assert inverse.after == refund.before and inverse.monetary == refund.monetary
    assert paid.after.transaction_outstanding_minor == 0
    assert replay_monetary_history(history)[0] == credit.after


@pytest.mark.parametrize(("foreign", "local", "exchange"), [("JPY", "KWD", "0.007"), ("KWD", "JPY", "487.123"), ("EUR", "USD", "1.24993")])
def test_component_prefix_fifo_and_final_residual_match_independent_fractions_at_all_scales(foreign: str, local: str, exchange: str) -> None:
    random = Random(17071)
    for _ in range(25):
        quantity = random.randrange(2, 13)
        source = original(foreign=foreign, functional=local, exchange=exchange, amount=100001,
                          quantity=quantity, cost=random.randrange(1, 50000), tax="0.14")
        q = quantity
        f = [part.transaction_minor for part in source.components]
        local_remaining = [part.functional_minor for part in source.components]
        cost = source.consumptions[0].value_minor
        history = MonetaryHistory(source)
        with localcontext() as context:
            context.prec = 6
            while q:
                selected = random.randrange(1, q + 1)
                history, event = append(history, "Return", quantity_scaled=selected)
                expected_f = [nearest(Fraction(value * selected, q)) for value in f]
                expected_l = [nearest(Fraction(value * selected, q)) for value in local_remaining]
                expected_cost = nearest(Fraction(cost * selected, q), even=True)
                assert [part.transaction_minor for part in event.components] == expected_f
                assert [part.functional_minor for part in event.components] == expected_l
                assert event.monetary.functional_cost_minor == expected_cost
                assert event.monetary.functional_credit_minor + event.monetary.functional_alignment_loss_minor == (
                    event.monetary.functional_receivable_released_minor + event.monetary.functional_refund_delta_minor
                    + event.monetary.functional_alignment_gain_minor)
                f = [value - cut for value, cut in zip(f, expected_f, strict=True)]
                local_remaining = [value - cut for value, cut in zip(local_remaining, expected_l, strict=True)]
                q -= selected
                cost -= expected_cost
        assert q == cost == sum(f) == sum(local_remaining) == 0


@pytest.mark.parametrize("value", [True, False, 1.0, "1", None, -1, 9_000_000_000_000_000_001])
def test_untrusted_quantities_and_amounts_refuse_type_confusion(value: object) -> None:
    history = MonetaryHistory(original())
    with pytest.raises(FinancePostingError):
        append(history, "Return", quantity_scaled=value)
    with pytest.raises(FinancePostingError):
        append(history, "Collection", amount_minor=value, settlement_rate=rate("1.25"))


@pytest.mark.parametrize("field", ["source_fingerprint", "previous_history_fingerprint", "quantity_scaled", "before", "after", "monetary", "components", "portions"])
def test_balanced_caller_tamper_cannot_replace_original_or_before_values(field: str) -> None:
    history = MonetaryHistory(original(amount=1, exchange="2", quantity=3, cost=1, tax=None))
    event = prepare_monetary_event(history, "Return", posting_date=DAY, quantity_scaled=1)
    changed: Any = {"source_fingerprint": "f" * 64, "previous_history_fingerprint": "f" * 64, "quantity_scaled": True,
        "before": replace(event.before, transaction_collected_minor=True),
        "after": replace(event.after, remaining_quantity_scaled=1),
        "monetary": replace(event.monetary, functional_credit_minor=True),
        "components": (replace(event.components[0], before_transaction_minor=True),),
        "portions": (replace(event.portions[0], before_value_minor=True),)}[field]
    with pytest.raises(FinancePostingError):
        apply_monetary_event(history, replace(event, **{field: changed}))


def test_source_replay_survives_allocation_context_and_does_not_mutate_original() -> None:
    source = original()
    fingerprint = source.fingerprint
    components, consumptions = asdict(source.components[0]), asdict(source.consumptions[0])
    history, _ = append(MonetaryHistory(source), "Return", quantity_scaled=2)
    assert history.source.fingerprint == fingerprint == source.fingerprint
    assert asdict(source.components[0]) == components and asdict(source.consumptions[0]) == consumptions


def test_exact_large_ratio_does_not_pre_round_before_half_up() -> None:
    context = CurrencyRegistryContext.from_installed()
    value, quantity, selected = 9_000_000_000_000, 9_000_000_000_000_000_000, 4_499_999_999_999_499_999
    assert allocate_revenue(value, quantity, selected, currency="USD", context=context) == 4_499_999_999_999
    assert allocate_revenue(value, quantity, quantity - 1, currency="USD", context=context) == value


def test_currency_identity_has_explicit_absent_rate_and_no_fabricated_fx_observation() -> None:
    source = original(foreign="USD", functional="USD")
    assert [(part.transaction_minor, part.functional_minor) for part in source.components] == [(10000, 10000), (1400, 1400)]
    history, paid = append(MonetaryHistory(source), "Collection", amount_minor=4000)
    assert paid.settlement_rate is None and paid.monetary.functional_cash_minor == 4000
    assert paid.monetary.functional_fx_gain_minor == paid.monetary.functional_fx_loss_minor == 0
    with pytest.raises(FinancePostingError):
        append(history, "Collection", amount_minor=1, settlement_rate=rate("1"))


def test_old_foreign_invoice_owner_still_refuses_absent_or_identity_rate() -> None:
    request = ForeignInvoicePreparation("work", "org", "entity", "ORG", "ENTITY", "CUSTOMER", "INV", DAY,
        "2026-11-15", "period", "GENERAL", "USD", 100, None, "EG", "SyntheticGoods", (),
        "AR", "REVENUE", "CASH", "FXGAIN", "FXLOSS", "Synthetic identity")
    context = CurrencyRegistryContext.from_installed()
    with pytest.raises(FinancePostingError):
        invoice_equation(request, "USD", context)
    with pytest.raises(FinancePostingError):
        invoice_equation(replace(request, original_rate=rate("1")), "USD", context)
    with pytest.raises(FinancePostingError):
        invoice_equation(replace(request, original_rate=rate("1")), "USD", context, allow_currency_identity=True)
    assert invoice_equation(request, "USD", context, allow_currency_identity=True)["functional_gross_minor"] == 100


def test_backdated_first_event_and_event_with_false_original_witness_refuse() -> None:
    source = original()
    with pytest.raises(FinancePostingError):
        prepare_monetary_event(MonetaryHistory(source), "Return", posting_date="2026-10-14", quantity_scaled=1)
    history, event = append(MonetaryHistory(source), "Return", quantity_scaled=1)
    with pytest.raises(FinancePostingError):
        prepare_monetary_event(history, "ReverseReturn", posting_date=DAY, quantity_scaled=1, original_sequence=True)
    assert event.sequence == 1


def test_mixed_original_cost_zero_requires_explicit_factual_admission() -> None:
    source = original()
    portions = (replace(source.consumptions[0], quantity_scaled=5, value_minor=0),
                MonetaryConsumption(2, "second", "valuation-line", "layer-2", 5, 6000))
    with pytest.raises(FinancePostingError):
        replace(source, consumptions=portions)
    source = replace(source, consumptions=portions, original_cost_admission_digest="a" * 64)
    history, first = append(MonetaryHistory(source), "Return", quantity_scaled=5)
    assert first.monetary.functional_cost_minor == 0 and first.portions[0].before_value_minor == 0
    _, second = append(history, "Return", quantity_scaled=5)
    assert second.monetary.functional_cost_minor == 6000


def test_full_history_is_readable_but_no_new_economic_intent_is_prepared() -> None:
    source = original(foreign="USD", functional="USD", amount=256, quantity=1, cost=1, tax=None)
    history = MonetaryHistory(source)
    chain = history.seed_fingerprint
    events = []
    for sequence in range(1, 257):
        before = MonetaryPosition(1, (256,), (256,), (1,), (1,), 257 - sequence, 257 - sequence, 0, 0,
                                  sequence - 1, 0, 0, 0)
        after = replace(before, transaction_outstanding_minor=256 - sequence, functional_outstanding_minor=256 - sequence,
                        transaction_collected_minor=sequence)
        movement = MonetaryMovement(transaction_receivable_released_minor=1, functional_receivable_released_minor=1,
                                    functional_cash_minor=1, functional_turnover_minor=1)
        event = MonetaryEvent("Collection", sequence, source.fingerprint, chain, DAY, 0, 1, None, None,
                              before, after, movement, (), ())
        chain = event.fingerprint
        events.append(event)
    history = MonetaryHistory(source, tuple(events))
    final, actual_chain = replay_monetary_history(history)
    assert final.transaction_outstanding_minor == final.functional_outstanding_minor == 0
    assert actual_chain == chain
    with pytest.raises(FinancePostingError, match="history is full"):
        prepare_monetary_event(history, "Return", posting_date=DAY, quantity_scaled=1)


def test_new_command_intents_retain_exact_rate_without_client_accounts_or_allocation() -> None:
    command = MonetaryPartialReturnPreparation("work", "org", "entity", "ORG", "ENTITY", "stock", 3,
                                              "period", DAY, "Synthetic return intent", 0)
    assert command.payload() == {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity",
        "organization_code": "ORG", "entity_code": "ENTITY", "source_order_id": "stock", "quantity_scaled": 3,
        "period_id": "period", "posting_date": DAY, "reason": "Synthetic return intent", "expected_history_version": 0}
    refund = MonetaryPartialRefundPreparation("parent", 1, "period", DAY, rate("1.25"), "Synthetic refund", 0)
    assert refund.payload()["settlement_rate"] == {"rate": "1.25", "source": "Synthetic reviewed source", "effective_at": DAY + "T09:00:00Z"}
    assert replace(refund, settlement_rate=None).payload()["settlement_rate"] is None
    inverse = MonetaryPartialReversePreparation("parent", "period", DAY, "Synthetic inverse", 0)
    assert "settlement_rate" not in inverse.payload()
    for field, value in (("quantity_scaled", True), ("quantity_scaled", 1.0), ("expected_history_version", True),
                         ("expected_history_version", 256), ("posting_date", "2026-02-30")):
        changed: Any = {field: value}
        with pytest.raises(FinancePostingError):
            replace(command, **changed).payload()
