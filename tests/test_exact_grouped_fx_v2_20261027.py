"""Independent fractional oracle for experimental grouped FX matching."""
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, Inexact, localcontext
from fractions import Fraction

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from reconforge.domain.exact_grouped_matching import (
    ExactGroupedMatchingError,
    GroupedFxRateV2,
    match_exact_groups_fx_v2,
    match_exact_groups_v2,
)
from reconforge.domain.grouped_matching import GroupedMatchPolicy, GroupedRecord
from reconforge.utils.money import CurrencyRegistryContext

REGISTRY = CurrencyRegistryContext.from_installed()
DAY = date(2026, 10, 27)
END = date(2026, 12, 31)


def record(identity: str, amount: str, currency: str, fee: str = "0") -> GroupedRecord:
    return GroupedRecord(identity, Decimal(amount), Decimal(fee), currency, DAY, "partition")


def oracle_half_up(amount: Fraction, precision: int) -> Decimal:
    scaled = abs(amount) * 10**precision
    whole, remainder = divmod(scaled.numerator, scaled.denominator)
    rounded = whole + int(2 * remainder >= scaled.denominator)
    signed = -rounded if amount < 0 else rounded
    return Decimal((int(signed < 0), tuple(map(int, str(abs(signed)))), -precision))


def test_inverse_fx_uses_exact_original_rate_and_binds_context() -> None:
    rate = GroupedFxRateV2("USD", "EUR", Decimal("3"), "synthetic", "spot", DAY, END)
    left = (record("L", "1.00", "EUR"),)
    right = (record("R", "0.33", "USD"),)
    policy = GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01"))
    expected = oracle_half_up(Fraction(1, 3), 2)
    assert expected == Decimal("0.33")
    outcomes = []
    for rounding in (ROUND_HALF_EVEN, ROUND_FLOOR):
        with localcontext() as context:
            context.prec = 3
            context.rounding = rounding
            context.traps[Inexact] = True
            outcomes.append(match_exact_groups_fx_v2(left, right, policy, target_currency="USD", rates=(rate,), registry_context=REGISTRY, rounding_scope="per-record-per-component"))
    assert outcomes[0].decision.status == "matched"
    assert outcomes[0].conversions[0].direction == "inverse"
    assert outcomes[0].conversions[0].converted_amount == expected
    assert outcomes[0].artifact_digest == outcomes[1].artifact_digest
    assert outcomes[0].registry_digest == REGISTRY.registry_manifest.digest


@pytest.mark.parametrize("amount,rate", [("1.00", "3"), ("1.00", "200"), ("-1.00", "200"), ("12345.67", "7")])
def test_inverse_fx_rounds_once_against_fraction(amount: str, rate: str) -> None:
    oracle = oracle_half_up(Fraction(Decimal(amount)) / Fraction(Decimal(rate)), 2)
    result = match_exact_groups_fx_v2(
        (record("L", amount, "EUR"),), (record("R", str(oracle), "USD"),),
        GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01")), target_currency="USD",
        rates=(GroupedFxRateV2("USD", "EUR", Decimal(rate), "synthetic", "spot", DAY, END),), registry_context=REGISTRY, rounding_scope="per-record-per-component",
    )
    assert result.decision.status == "matched"
    assert result.conversions[0].converted_amount == oracle


def test_unknown_or_ambiguous_fx_is_refused() -> None:
    args = ((record("L", "1", "EUR"),), (record("R", "1", "USD"),), GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01")))
    with pytest.raises(ExactGroupedMatchingError):
        match_exact_groups_fx_v2(*args, target_currency="USD", rates=(), registry_context=REGISTRY, rounding_scope="per-record-per-component")
    with pytest.raises(ExactGroupedMatchingError):
        match_exact_groups_fx_v2(*args, target_currency="USD", rates=(
            GroupedFxRateV2("USD", "EUR", Decimal("3"), "a", "spot", DAY, END),
            GroupedFxRateV2("EUR", "USD", Decimal("0.4"), "b", "spot", DAY, END),
        ), registry_context=REGISTRY, rounding_scope="per-record-per-component")


def test_original_rate_source_and_registry_are_part_of_artifact_digest() -> None:
    args = ((record("L", "1.00", "EUR"),), (record("R", "0.33", "USD"),), GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01")))
    def run(source: str, registry: CurrencyRegistryContext):
        return match_exact_groups_fx_v2(*args, target_currency="USD", rates=(
            GroupedFxRateV2("USD", "EUR", Decimal("3"), source, "spot", DAY, END),
        ), registry_context=registry, rounding_scope="per-record-per-component")
    snapshot = REGISTRY.snapshot()
    snapshot.pop("digest")
    snapshot["registry_version"] = "synthetic-fx-v2-other"
    other = CurrencyRegistryContext.from_snapshot(snapshot)
    assert run("a", REGISTRY).artifact_digest != run("b", REGISTRY).artifact_digest
    assert run("a", REGISTRY).artifact_digest != run("a", other).artifact_digest


@pytest.mark.parametrize("target,rate,precision", [("JPY", "2", 0), ("KWD", "400", 3)])
def test_target_currency_precision_controls_inverse_rounding(target: str, rate: str, precision: int) -> None:
    oracle = oracle_half_up(Fraction(1, int(rate)), precision)
    tolerance = Decimal("1") if precision == 0 else Decimal("0.001")
    result = match_exact_groups_fx_v2(
        (record("L", "1.00", "EUR"),), (record("R", str(oracle), target),),
        GroupedMatchPolicy(mode="one-to-one", amount_tolerance=tolerance), target_currency=target,
        rates=(GroupedFxRateV2(target, "EUR", Decimal(rate), "synthetic", "spot", DAY, END),),
        registry_context=REGISTRY, rounding_scope="per-record-per-component",
    )
    assert result.decision.status == "matched"
    assert result.conversions[0].converted_amount == oracle


def test_direct_rate_and_fees_are_independently_rounded_once() -> None:
    result = match_exact_groups_fx_v2(
        (record("L", "2.00", "EUR", "0.01"),), (record("R", "2.98", "USD"),),
        GroupedMatchPolicy(mode="one-to-one", netting_mode="net", amount_tolerance=Decimal("0.01")), target_currency="USD",
        rates=(GroupedFxRateV2("EUR", "USD", Decimal("1.5"), "synthetic", "spot", DAY, END),),
        registry_context=REGISTRY, rounding_scope="per-record-per-component",
    )
    assert result.decision.status == "matched"
    assert result.conversions[0].direction == "direct"
    assert result.conversions[0].converted_amount == oracle_half_up(Fraction(2) * Fraction(3, 2), 2)
    assert result.conversions[0].converted_fee == oracle_half_up(Fraction(1, 100) * Fraction(3, 2), 2)


def test_unsupported_scope_and_inexact_source_currency_are_refused() -> None:
    rate = (GroupedFxRateV2("USD", "EUR", Decimal("3"), "synthetic", "spot", DAY, END),)
    kwargs = {"target_currency": "USD", "rates": rate, "registry_context": REGISTRY}
    with pytest.raises(ExactGroupedMatchingError, match="explicit"):
        match_exact_groups_fx_v2((record("L", "1", "EUR"),), (record("R", "0.33", "USD"),),
                                 GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01")), rounding_scope="after-group", **kwargs)
    with pytest.raises(ExactGroupedMatchingError, match="one-to-one"):
        match_exact_groups_fx_v2((record("L", "1", "EUR"),), (record("R", "0.33", "USD"),),
                                 GroupedMatchPolicy(mode="many-to-one"), rounding_scope="per-record-per-component", **kwargs)
    with pytest.raises(ExactGroupedMatchingError, match="currency precision"):
        match_exact_groups_fx_v2((record("L", "1.001", "EUR"),), (record("R", "0.33", "USD"),),
                                 GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01")), rounding_scope="per-record-per-component", **kwargs)
    with pytest.raises(ExactGroupedMatchingError, match="absent"):
        match_exact_groups_fx_v2((record("L", "1", "EUR"),), (record("R", "1", "ZZZ"),),
                                 GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01")), target_currency="ZZZ", rates=(),
                                 registry_context=REGISTRY, rounding_scope="per-record-per-component")


def test_future_rate_and_unbounded_rate_are_refused() -> None:
    args = ((record("L", "1", "EUR"),), (record("R", "0.33", "USD"),), GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01")))
    kwargs = {"target_currency": "USD", "registry_context": REGISTRY, "rounding_scope": "per-record-per-component"}
    with pytest.raises(ExactGroupedMatchingError, match="exactly one"):
        match_exact_groups_fx_v2(*args, rates=(GroupedFxRateV2("USD", "EUR", Decimal("3"), "s", "spot", date(2027, 1, 1), date(2027, 12, 31)),), **kwargs)
    with pytest.raises(ExactGroupedMatchingError, match="budget"):
        match_exact_groups_fx_v2(*args, rates=(GroupedFxRateV2("USD", "EUR", Decimal("1E+201"), "s", "spot", DAY, END),), **kwargs)


def test_digest_binds_original_amount_and_rate_direction_even_when_outputs_match() -> None:
    policy = GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01"))
    kwargs = {"target_currency": "USD", "registry_context": REGISTRY, "rounding_scope": "per-record-per-component"}
    inverse = (GroupedFxRateV2("USD", "EUR", Decimal("100"), "s", "spot", DAY, END),)
    first = match_exact_groups_fx_v2((record("L", "1.00", "EUR"),), (record("R", "0.01", "USD"),), policy, rates=inverse, **kwargs)
    second = match_exact_groups_fx_v2((record("L", "1.01", "EUR"),), (record("R", "0.01", "USD"),), policy, rates=inverse, **kwargs)
    assert first.decision.status == second.decision.status == "matched"
    assert first.artifact_digest != second.artifact_digest
    direct = (GroupedFxRateV2("EUR", "USD", Decimal("0.01"), "s", "spot", DAY, END),)
    third = match_exact_groups_fx_v2((record("L", "1.00", "EUR"),), (record("R", "0.01", "USD"),), policy, rates=direct, **kwargs)
    assert third.conversions[0].direction == "direct"
    assert third.artifact_digest != first.artifact_digest


def test_signed_zero_is_canonical_in_fx_artifact() -> None:
    args = ((record("R", "0.00", "USD"),), GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01")))
    kwargs = {"target_currency": "USD", "rates": (GroupedFxRateV2("USD", "EUR", Decimal("3"), "s", "spot", DAY, END),),
              "registry_context": REGISTRY, "rounding_scope": "per-record-per-component"}
    first = match_exact_groups_fx_v2((record("L", "0.00", "EUR"),), *args, **kwargs)
    second = match_exact_groups_fx_v2((record("L", "-0.00", "EUR"),), *args, **kwargs)
    assert first.decision.status == second.decision.status == "matched"
    assert first.artifact_digest == second.artifact_digest


def test_quantization_collision_is_not_an_exact_match() -> None:
    rate = GroupedFxRateV2("EUR", "USD", Decimal("0.1"), "synthetic", "spot", DAY, END)
    with pytest.raises(ExactGroupedMatchingError, match="beyond the declared tolerance"):
        match_exact_groups_fx_v2(
            (record("L", "1.00", "EUR"),), (record("R", "1.01", "EUR"),),
            GroupedMatchPolicy(mode="one-to-one"), target_currency="USD", rates=(rate,),
            registry_context=REGISTRY, rounding_scope="per-record-per-component",
        )


def test_rounding_cannot_silently_lose_a_candidate_within_tolerance() -> None:
    rate = GroupedFxRateV2("EUR", "USD", Decimal("0.5"), "synthetic", "spot", DAY, END)
    # +0.005 and -0.005 USD differ by exactly 0.01 before rounding. Half-up
    # rounds them to +0.01 and -0.01, which would falsely look unmatched.
    with pytest.raises(ExactGroupedMatchingError, match="candidate set differs"):
        match_exact_groups_fx_v2(
            (record("L", "0.01", "EUR"),), (record("R", "-0.01", "EUR"),),
            GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01")),
            target_currency="USD", rates=(rate,), registry_context=REGISTRY,
            rounding_scope="per-record-per-component",
        )


def test_rounding_cannot_silently_change_candidate_ranking() -> None:
    rate = GroupedFxRateV2("EUR", "USD", Decimal("0.1"), "synthetic", "spot", DAY, END)
    with pytest.raises(ExactGroupedMatchingError, match="candidate ranking differs"):
        match_exact_groups_fx_v2(
            (record("L", "1.00", "EUR"),), (record("R1", "0.10", "USD"), record("R2", "1.01", "EUR")),
            GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01")),
            target_currency="USD", rates=(rate,), registry_context=REGISTRY,
            rounding_scope="per-record-per-component",
        )


def test_rounding_loss_requires_explicit_tolerance_and_fx_bound_identity() -> None:
    rate = GroupedFxRateV2("USD", "EUR", Decimal("3"), "synthetic", "spot", DAY, END)
    args = ((record("L", "1.00", "EUR"),), (record("R", "0.33", "USD"),))
    kwargs = {"target_currency": "USD", "rates": (rate,), "registry_context": REGISTRY,
              "rounding_scope": "per-record-per-component"}
    with pytest.raises(ExactGroupedMatchingError, match="beyond the declared tolerance"):
        match_exact_groups_fx_v2(*args, GroupedMatchPolicy(mode="one-to-one"), **kwargs)
    result = match_exact_groups_fx_v2(*args, GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01")), **kwargs)
    assert result.decision.status == "matched"
    assert result.exact_difference_numerator == 1 and result.exact_difference_denominator == 300
    assert result.decision.decision_digest == result.artifact_digest
    assert result.decision.group_id == f"MG-{result.artifact_digest[:20].upper()}"
    assert not hasattr(result, "match")
    assert result.decision.registry_context.registry_manifest.digest == REGISTRY.registry_manifest.digest
    assert result.decision.rates == (rate,)
    assert result.decision.source_records[0].record.amount == Decimal("1.00")
    assert result.decision.conversions == result.conversions
    assert result.decision.exact_difference_numerator == 1
    assert result.decision.exact_difference_denominator == 300
    assert result.verification_evaluations == result.decision.verification_evaluations == 1
    usd_only = match_exact_groups_v2((record("L", "0.33", "USD"),), (record("R", "0.33", "USD"),),
                                    GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01")),
                                    registry_context=REGISTRY)
    assert result.artifact_digest != usd_only.artifact_digest
    assert result.decision.decision_digest != usd_only.decision.decision_digest


def test_exact_fx_conversion_matches_without_tolerance() -> None:
    rate = GroupedFxRateV2("EUR", "USD", Decimal("0.1"), "synthetic", "spot", DAY, END)
    result = match_exact_groups_fx_v2(
        (record("L", "1.00", "EUR"),), (record("R", "0.10", "USD"),),
        GroupedMatchPolicy(mode="one-to-one"), target_currency="USD", rates=(rate,),
        registry_context=REGISTRY, rounding_scope="per-record-per-component",
    )
    assert result.decision.status == "matched"
    assert result.exact_difference_numerator == 0
    assert result.exact_difference_denominator == 1


def test_ambiguous_fx_decision_retains_lineage_and_candidates() -> None:
    rate = GroupedFxRateV2("EUR", "USD", Decimal("0.1"), "synthetic", "spot", DAY, END)
    result = match_exact_groups_fx_v2(
        (record("L", "1.00", "EUR"),), (record("R1", "0.10", "USD"), record("R2", "0.10", "USD")),
        GroupedMatchPolicy(mode="one-to-one"), target_currency="USD", rates=(rate,),
        registry_context=REGISTRY, rounding_scope="per-record-per-component",
    )
    assert result.decision.status == "ambiguous"
    assert len(result.decision.ambiguous_candidate_sets) == 2
    assert len(result.decision.source_records) == 3
    assert result.decision.rates == (rate,)
    assert result.decision.decision_digest == result.artifact_digest
    assert result.verification_evaluations == 2


def test_fx_verification_never_exceeds_declared_search_budget() -> None:
    with pytest.raises(ExactGroupedMatchingError, match="independent search budget"):
        match_exact_groups_fx_v2(
            (record("L", "1", "USD"),),
            (record("R1", "1", "USD"), record("R2", "2", "USD"), record("R3", "3", "USD")),
            GroupedMatchPolicy(mode="one-to-one", max_search_evaluations=2),
            target_currency="USD", rates=(), registry_context=REGISTRY,
            rounding_scope="per-record-per-component",
        )


def test_fx_expiry_is_required_and_enforced() -> None:
    with pytest.raises(TypeError):
        GroupedFxRateV2("USD", "EUR", Decimal("3"), "synthetic", "spot", DAY)
    expired = GroupedFxRateV2("USD", "EUR", Decimal("3"), "synthetic", "spot", date(2026, 1, 1), date(2026, 10, 26))
    with pytest.raises(ExactGroupedMatchingError, match="exactly one"):
        match_exact_groups_fx_v2((record("L", "1", "EUR"),), (record("R", "0.33", "USD"),),
                                 GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01")), target_currency="USD", rates=(expired,),
                                 registry_context=REGISTRY, rounding_scope="per-record-per-component")
    invalid = GroupedFxRateV2("USD", "EUR", Decimal("3"), "synthetic", "spot", DAY, date(2026, 1, 1))
    with pytest.raises(ExactGroupedMatchingError, match="effective date"):
        match_exact_groups_fx_v2((record("L", "1", "EUR"),), (record("R", "0.33", "USD"),),
                                 GroupedMatchPolicy(mode="one-to-one"), target_currency="USD", rates=(invalid,),
                                 registry_context=REGISTRY, rounding_scope="per-record-per-component")


@settings(max_examples=100, deadline=None)
@given(cents=st.integers(min_value=-100_000, max_value=100_000), divisor=st.integers(min_value=1, max_value=500))
def test_inverse_rate_matches_integer_fraction_oracle(cents: int, divisor: int) -> None:
    source = Decimal((int(cents < 0), tuple(map(int, str(abs(cents)))), -2))
    expected = oracle_half_up(Fraction(cents, 100 * divisor), 2)
    result = match_exact_groups_fx_v2(
        (record("L", str(source), "EUR"),), (record("R", str(expected), "USD"),),
        GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.01")), target_currency="USD",
        rates=(GroupedFxRateV2("USD", "EUR", Decimal(divisor), "synthetic", "spot", DAY, END),),
        registry_context=REGISTRY, rounding_scope="per-record-per-component",
    )
    assert result.conversions[0].converted_amount == expected
    assert result.decision.status == "matched"
