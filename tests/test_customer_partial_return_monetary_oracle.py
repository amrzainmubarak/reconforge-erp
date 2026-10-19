"""Literal independent monetary witnesses, not native/tax jurisdiction acceptance."""
import itertools
from dataclasses import asdict
from fractions import Fraction

import pytest

from tests.customer_partial_return_monetary_oracle import (
    MonetaryOracleError,
    converted_cash,
    integer,
    nearest,
    portion,
    reference_cash,
    reference_credit,
)


def test_literal_taxed_foreign_cycle_has_ten_effects_twenty_six_lines_and_60950() -> None:
    cash1 = reference_cash(carrying_foreign=11400, carrying_functional=14250,
                           selected_foreign=4000, functional_cash=5200, refund=False)
    assert asdict(cash1) == dict(foreign_released=4000, functional_released=5000,
        functional_cash=5200, fx_gain=200, fx_loss=0, remaining_foreign=7400,
        remaining_functional=9250, journal_turnover=5200)
    credit1 = reference_credit(remaining_quantity=10, selected_quantity=5,
        components=((10000, 12500), (1400, 1750)), fifo=((10, 6000),),
        ar_foreign=7400, ar_functional=9250)
    assert credit1.component_cuts == ((5000, 6250), (700, 875))
    assert (credit1.foreign_ar_release, credit1.functional_ar_release,
            credit1.foreign_liability, credit1.functional_liability,
            credit1.restored_cost, credit1.alignment_gain, credit1.alignment_loss) == (5700, 7125, 0, 0, 3000, 0, 0)
    cash2 = reference_cash(carrying_foreign=1700, carrying_functional=2125,
                           selected_foreign=1700, functional_cash=2040, refund=False)
    assert (cash2.fx_gain, cash2.fx_loss, cash2.remaining_foreign, cash2.remaining_functional) == (0, 85, 0, 0)
    credit2 = reference_credit(remaining_quantity=5, selected_quantity=5,
        components=credit1.remaining_components, fifo=credit1.remaining_fifo,
        ar_foreign=0, ar_functional=0)
    assert (credit2.foreign_liability, credit2.functional_liability, credit2.restored_cost) == (5700, 7125, 3000)
    assert credit2.remaining_components == ((0, 0), (0, 0)) and credit2.remaining_fifo == ((0, 0),)
    refund = reference_cash(carrying_foreign=5700, carrying_functional=7125,
                           selected_foreign=5700, functional_cash=6270, refund=True)
    assert (refund.fx_gain, refund.fx_loss, refund.remaining_foreign, refund.remaining_functional) == (855, 0, 0, 0)
    # Receipt, issue, recognition, two collections, two two-entry credits, refund.
    turnover = [6000, 6000, 14250, 5200, 7125, 3000, 2125, 7125, 3000, 7125]
    lines = [2, 2, 3, 3, 3, 2, 3, 3, 2, 3]
    assert (len(turnover), sum(lines), sum(turnover)) == (10, 26, 60950)
    assert 5200 + 2040 - 6270 == 970
    assert 6000 - 6000 + 970 - (200 + 855) + 85 == 0


def test_each_tax_component_and_both_currencies_uses_its_actual_remaining_value() -> None:
    components, fifo, af, al, observed = ((5, 7), (1, 2), (2, 1)), ((3, 5),), 8, 10, []
    for q in [3, 2, 1]:
        cut = reference_credit(remaining_quantity=q, selected_quantity=1,
            components=components, fifo=fifo, ar_foreign=af, ar_functional=al)
        observed.append((cut.component_cuts, cut.restored_cost, cut.alignment_gain, cut.alignment_loss))
        components, fifo = cut.remaining_components, cut.remaining_fifo
        af -= cut.foreign_ar_release
        al -= cut.functional_ar_release
    assert observed == [(((2, 2), (0, 1), (1, 0)), 2, 0, 1),
                        (((2, 3), (1, 1), (1, 1)), 2, 0, 0),
                        (((1, 2), (0, 0), (0, 0)), 1, 1, 0)]
    assert (af, al, components, fifo) == (0, 0, ((0, 0), (0, 0), (0, 0)), ((0, 0),))


def test_finite_active_prefix_bounds_preserve_refundable_overcollection_of_credit() -> None:
    # C <= G is required. C + credited <= G is deliberately NOT required:
    # cash collected before a later credit creates a genuine refund entitlement.
    for originals, chunks, initial_cash, scales in itertools.product(
        [((1, 2),), ((2, 1),), ((5, 7), (1, 2), (2, 1))],
        [(1, 1, 1), (2, 1), (1, 2)], range(3), [(0, 3), (2, 2), (3, 0)],
    ):
        gross_f, gross_l = sum(f for f, _ in originals), sum(v for _, v in originals)
        if initial_cash > gross_f:
            continue
        remaining, components, fifo = 3, originals, ((3, 5),)
        af, al, collected, credited, ef, el, refunded, released = gross_f, gross_l, 0, 0, 0, 0, 0, 0

        def cash(amount: int, selected_scales: tuple[int, int] = scales) -> int:
            return converted_cash(amount, foreign_scale=selected_scales[0], functional_scale=selected_scales[1],
                                  quote_per_foreign="1.234567")

        if initial_cash:
            receipt = reference_cash(carrying_foreign=af, carrying_functional=al,
                selected_foreign=initial_cash, functional_cash=cash(initial_cash), refund=False)
            af, al, collected = receipt.remaining_foreign, receipt.remaining_functional, initial_cash
        for quantity in chunks:
            cut = reference_credit(remaining_quantity=remaining, selected_quantity=quantity,
                components=components, fifo=fifo, ar_foreign=af, ar_functional=al)
            remaining -= quantity
            components, fifo = cut.remaining_components, cut.remaining_fifo
            af, al = af - cut.foreign_ar_release, al - cut.functional_ar_release
            credited += cut.foreign_credit
            ef, el = ef + cut.foreign_liability, el + cut.functional_liability
            assert 0 <= collected <= gross_f and 0 <= el <= gross_l
            assert ef != 0 or el == 0
            if ef > refunded:
                payout = reference_cash(carrying_foreign=ef - refunded, carrying_functional=el - released,
                    selected_foreign=1, functional_cash=cash(1), refund=True)
                refunded, released = refunded + 1, released + payout.functional_released
            if af:
                receipt = reference_cash(carrying_foreign=af, carrying_functional=al,
                    selected_foreign=1, functional_cash=cash(1), refund=False)
                af, al, collected = receipt.remaining_foreign, receipt.remaining_functional, collected + 1
            assert collected <= gross_f and el <= gross_l
            assert refunded != 0 or released == 0
            assert af == max(gross_f - collected - credited, 0)
            assert ef == max(collected + credited - gross_f, 0)
            assert ef - refunded != 0 or el - released == 0
        assert credited == gross_f and remaining == af == al == 0
        if initial_cash:
            assert collected + credited > gross_f and ef == collected


def test_zero_foreign_credit_never_creates_hidden_functional_liability() -> None:
    cut = reference_credit(remaining_quantity=3, selected_quantity=1,
        components=((1, 2),), fifo=((3, 0),), ar_foreign=1, ar_functional=2)
    assert (cut.foreign_credit, cut.functional_credit, cut.foreign_ar_release,
            cut.functional_ar_release, cut.foreign_liability, cut.functional_liability,
            cut.alignment_gain, cut.alignment_loss, cut.functional_credit_journal_turnover) == (0, 1, 0, 0, 0, 0, 1, 0, 1)


def test_zero_functional_credit_can_require_a_real_alignment_loss_journal() -> None:
    cut = reference_credit(remaining_quantity=4, selected_quantity=1,
        components=((2, 1),), fifo=((4, 0),), ar_foreign=2, ar_functional=1)
    assert (cut.foreign_credit, cut.functional_credit, cut.functional_ar_release,
            cut.alignment_loss, cut.functional_credit_journal_turnover) == (1, 0, 1, 1, 1)


def test_zero_functional_liability_refund_can_have_real_cash_and_fx_loss() -> None:
    cash = reference_cash(carrying_foreign=2, carrying_functional=0,
                          selected_foreign=2, functional_cash=3, refund=True)
    assert (cash.functional_released, cash.fx_loss, cash.fx_gain, cash.journal_turnover,
            cash.remaining_foreign, cash.remaining_functional) == (0, 3, 0, 3, 0, 0)


@pytest.mark.parametrize(("fscale", "lscale", "amount", "rate", "expected"), [
    (0, 3, 1000, "0.007", 7000), (3, 0, 1000, "487.123", 487),
    (2, 2, 12500, "1.24993", 15624), (3, 2, 1, "1.5", 0),
])
def test_exact_spot_conversion_has_captured_zero_two_three_scales(fscale: int, lscale: int,
        amount: int, rate: str, expected: int) -> None:
    assert converted_cash(amount, foreign_scale=fscale, functional_scale=lscale,
                          quote_per_foreign=rate) == expected


def test_large_half_boundary_and_near_integer_do_not_double_round() -> None:
    assert portion(9_000_000_000_000, 9_000_000_000_000_000_000,
                   4_499_999_999_999_499_999) == 4_499_999_999_999
    assert portion(9_000_000_000_000, 9_000_000_000_000_000_000,
                   8_999_999_999_999_999_999) == 9_000_000_000_000


def test_fifo_half_even_and_revenue_half_up_keep_different_original_residuals() -> None:
    assert [portion(1001, 3, 1, fifo=True), portion(667, 2, 1, fifo=True), portion(333, 1, 1, fifo=True)] == [334, 334, 333]
    assert [portion(1001, 3, 2, fifo=True), portion(334, 1, 1, fifo=True)] == [667, 334]
    assert [portion(5, 2, 1), portion(2, 1, 1)] == [3, 2]
    assert [portion(5, 2, 1, fifo=True), portion(3, 1, 1, fifo=True)] == [2, 3]


def test_all_small_prefixes_exhaust_every_original_component_without_a_plug() -> None:
    for quantity, value, fifo in itertools.product(range(1, 8), range(10), [False, True]):
        q, v, cuts = quantity, value, []
        while q:
            take = portion(v, q, 1, fifo=fifo)
            assert 0 <= take <= v
            cuts.append(take)
            q, v = q - 1, v - take
        assert sum(cuts) == value and v == 0


@pytest.mark.parametrize("bad", [True, False, 1.0, Fraction(1, 1), "1", None, -1, 9_000_000_000_000_000_001])
def test_money_and_witnesses_reject_exact_type_confusion(bad: object) -> None:
    with pytest.raises(MonetaryOracleError):
        integer(bad)
    with pytest.raises(MonetaryOracleError):
        reference_credit(remaining_quantity=3, selected_quantity=1,
            components=((bad, 2),), fifo=((3, 1),), ar_foreign=1, ar_functional=2)  # type: ignore[arg-type]


@pytest.mark.parametrize("rate", ["NaN", "Infinity", "1e100000000", "-1", "0", "0.0", ".1", "1.", " 1", "1" * 97])
def test_untrusted_rate_lexemes_are_bounded_before_fraction_expansion(rate: str) -> None:
    with pytest.raises(MonetaryOracleError):
        converted_cash(1, foreign_scale=2, functional_scale=2, quote_per_foreign=rate)


def test_foreign_zero_carrying_with_functional_remainder_and_unowned_quantity_refuse() -> None:
    with pytest.raises(MonetaryOracleError):
        reference_credit(remaining_quantity=3, selected_quantity=1,
            components=((1, 2),), fifo=((3, 1),), ar_foreign=0, ar_functional=1)
    with pytest.raises(MonetaryOracleError):
        reference_credit(remaining_quantity=3, selected_quantity=1,
            components=((1, 2),), fifo=((2, 1),), ar_foreign=1, ar_functional=2)


def test_reference_nearest_has_no_binary_float_or_python_default_rounding() -> None:
    assert nearest(Fraction(5, 2)) == 3 and nearest(Fraction(5, 2), half_even=True) == 2
    with pytest.raises(MonetaryOracleError):
        nearest(2.5)  # type: ignore[arg-type]


@pytest.mark.parametrize("policy", [0, 1, "HALF_UP", None])
def test_an_untrusted_policy_selector_cannot_alias_a_captured_rounding_rule(policy: object) -> None:
    with pytest.raises(MonetaryOracleError):
        nearest(Fraction(5, 2), half_even=policy)  # type: ignore[arg-type]
    with pytest.raises(MonetaryOracleError):
        portion(5, 2, 1, fifo=policy)  # type: ignore[arg-type]


def test_domain_return_credit_memo_matches_monetary_oracle_witnesses() -> None:
    from reconforge.domain.operational_fx_tax import (
        ForeignInvoicePreparation,
        HistoricalRate,
        ReturnCreditPreparation,
        TaxComponent,
        customer_refund_equation,
        invoice_equation,
        return_credit_memo_equation,
    )
    from reconforge.utils.money import CurrencyRegistryContext

    context = CurrencyRegistryContext.from_installed()
    inv = ForeignInvoicePreparation(
        workspace_id="WS", organization_id="ORG", legal_entity_id="LE", organization_code="CORP",
        entity_code="ENT", customer_code="CUST", invoice_number="INV-001", posting_date="2026-10-01",
        due_date="2026-11-01", period_id="2026-10", journal_code="SALES", foreign_currency_code="EUR",
        net_minor=10000, original_rate=HistoricalRate("1.25", "Spot", "2026-10-01T09:00:00Z"),
        country_code="EG", transaction_class="Service",
        taxes=(TaxComponent("vat", "EG", "Service", "2026-01-01", "2026-12-31", "0.14", "TAX", "VAT"),),
        receivable_account_code="AR", revenue_account_code="REV", cash_account_code="CASH",
        gain_account_code="GAIN", loss_account_code="LOSS", reason="Sale",
    )
    source = invoice_equation(inv, "USD", context)

    # 1. First credit: 5 out of 10 items returned, AR remaining is 7400 EUR (9250 USD)
    prep1 = ReturnCreditPreparation(
        invoice_source=source,
        returned_quantity=5,
        total_quantity=10,
        fifo_layers=((10, 6000),),
        ar_foreign_minor=7400,
        ar_historical_functional_minor=9250,
        posting_date="2026-10-10",
        credit_memo_number="CM-01",
        refund_liability_account_code="REFUND_LIAB",
        inventory_account_code="INV_FG",
        cogs_account_code="COGS",
    )
    cm1 = return_credit_memo_equation(prep1, context)
    assert cm1["cut_foreign_net_minor"] == 5000
    assert cm1["cut_functional_net_minor"] == 6250
    assert cm1["foreign_ar_released_minor"] == 5700
    assert cm1["functional_ar_released_minor"] == 7125
    assert cm1["foreign_liability_minor"] == 0
    assert cm1["functional_liability_minor"] == 0
    assert cm1["restored_cost_minor"] == 3000

    # 2. Second credit: remaining 5 items returned after customer settled all remaining AR
    prep2 = ReturnCreditPreparation(
        invoice_source=source,
        returned_quantity=5,
        total_quantity=10,
        fifo_layers=((5, 3000),),
        ar_foreign_minor=0,
        ar_historical_functional_minor=0,
        posting_date="2026-10-12",
        credit_memo_number="CM-02",
        refund_liability_account_code="REFUND_LIAB",
        inventory_account_code="INV_FG",
        cogs_account_code="COGS",
    )
    cm2 = return_credit_memo_equation(prep2, context)
    assert cm2["foreign_ar_released_minor"] == 0
    assert cm2["functional_ar_released_minor"] == 0
    assert cm2["foreign_liability_minor"] == 5700
    assert cm2["functional_liability_minor"] == 7125
    assert cm2["restored_cost_minor"] == 3000

    # 3. Cash Refund of the 5700 EUR liability at spot rate 1.10
    ref = customer_refund_equation(
        foreign_refund_minor=5700,
        historical_liability_functional_minor=7125,
        total_foreign_liability_minor=5700,
        refund_rate=HistoricalRate("1.10", "Spot", "2026-10-15T09:00:00Z"),
        foreign_currency="EUR",
        functional_currency="USD",
        posting_date="2026-10-15",
        refund_liability_account_code="REFUND_LIAB",
        cash_account_code="CASH",
        gain_account_code="GAIN",
        loss_account_code="LOSS",
        context=context,
    )
    assert ref["functional_cash_minor"] == 6270
    assert ref["historical_released_minor"] == 7125
    assert ref["realized_fx_minor"] == -855

