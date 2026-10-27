from datetime import date
from decimal import Decimal, Inexact, localcontext

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from reconforge.domain.exact_grouped_matching import ExactGroupedMatchingError
from reconforge.domain.exact_grouped_matching import match_exact_groups_v2 as _match_exact_groups_v2
from reconforge.domain.grouped_matching import GroupedMatchPolicy, GroupedMatchPortfolioResult, GroupedRecord
from reconforge.utils.money import CurrencyRegistryContext

REGISTRY = CurrencyRegistryContext.from_installed()


def match_exact_groups_v2(left, right, policy):
    return _match_exact_groups_v2(left, right, policy, registry_context=REGISTRY)


def record(identity: str, amount: str, fee: str = "0", currency: str = "USD") -> GroupedRecord:
    return GroupedRecord(identity, Decimal(amount), Decimal(fee), currency, date(2026, 10, 27), "partition")


def test_distinct_amounts_never_become_equal_under_hostile_context() -> None:
    left = (record("L", "123456789"),)
    right = (record("R", "123456780"),)
    policy = GroupedMatchPolicy(mode="one-to-one")
    with localcontext() as context:
        context.prec = 3
        context.traps[Inexact] = True
        low = match_exact_groups_v2(left, right, policy)
    with localcontext() as context:
        context.prec = 28
        high = match_exact_groups_v2(left, right, policy)
    assert low.decision.status == high.decision.status == "unmatched"
    assert low.input_digest == high.input_digest
    assert low.artifact_digest == high.artifact_digest


def test_distinct_29_digit_amounts_do_not_round_equal_at_default_precision() -> None:
    left = (record("L", "12345678901234567890123456781"),)
    right = (record("R", "12345678901234567890123456780"),)
    with localcontext() as context:
        context.prec = 28
        result = match_exact_groups_v2(left, right, GroupedMatchPolicy(mode="one-to-one"))
    assert result.decision.status == "unmatched"


def test_exact_group_and_fees_are_context_and_permutation_invariant() -> None:
    left = (record("L2", "0.002", currency="BHD"), record("L1", "123456789.001", currency="BHD"))
    right = (record("R", "123456789.003", currency="BHD"),)
    policy = GroupedMatchPolicy(mode="many-to-one")
    with localcontext() as context:
        context.prec = 2
        result = match_exact_groups_v2(left, right, policy)
    with localcontext() as context:
        context.prec = 40
        replay = match_exact_groups_v2(left[::-1], right, policy)
    assert result.decision.status == "matched"
    assert result.decision.left_total == Decimal("123456789.003")
    assert result.artifact_digest == replay.artifact_digest


def test_group_digest_is_independent_of_ambient_rounding_mode() -> None:
    left = (record("L", "10.00"),)
    right = (record("R1", "4.00"), record("R2", "6.00"))
    policy = GroupedMatchPolicy(mode="one-to-many")
    with localcontext() as context:
        context.rounding = "ROUND_HALF_EVEN"
        even = match_exact_groups_v2(left, right, policy)
    with localcontext() as context:
        context.rounding = "ROUND_FLOOR"
        floor = match_exact_groups_v2(left, right, policy)
    assert even.decision.status == floor.decision.status == "matched"
    assert even.artifact_digest == floor.artifact_digest


def test_digest_binds_unmatched_input_values_and_policy() -> None:
    policy = GroupedMatchPolicy(mode="one-to-one")
    a = match_exact_groups_v2((record("L", "1"),), (record("R", "2"),), policy)
    b = match_exact_groups_v2((record("L", "1"),), (record("R", "3"),), policy)
    assert a.decision.status == b.decision.status == "unmatched"
    assert a.artifact_digest != b.artifact_digest


def test_equal_candidates_remain_unresolved_with_versioned_evidence() -> None:
    left = (record("L", "10.00"),)
    right = (record("R1", "10.00"), record("R2", "10.00"))
    result = match_exact_groups_v2(left, right, GroupedMatchPolicy(mode="one-to-one"))
    assert result.decision.status == "ambiguous"
    assert result.decision.left_record_ids == ()
    assert len(result.decision.ambiguous_candidate_sets) == 2
    assert result.algorithm_version == "exact-bounded-grouped-matching-v2"


def test_unbounded_precision_is_refused_before_search() -> None:
    with pytest.raises(ExactGroupedMatchingError):
        match_exact_groups_v2((record("L", "1E-5000"),), (record("R", "1"),), GroupedMatchPolicy(mode="one-to-one"))


def test_discarded_left_combinations_obey_search_budget() -> None:
    left = tuple(record(f"L{i}", "1") for i in range(64))
    with pytest.raises(ExactGroupedMatchingError, match="left-group generation"):
        match_exact_groups_v2(left, (record("R", "1"),), GroupedMatchPolicy(mode="portfolio"))


def test_portfolio_generation_and_selection_share_total_budget() -> None:
    left = tuple(record(f"L{i:02}", "1") for i in range(64))
    right = tuple(record(f"R{i:02}", "1") for i in range(64))
    policy = GroupedMatchPolicy(mode="portfolio", max_left_cardinality=1, max_right_cardinality=1)
    result = match_exact_groups_v2(left, right, policy)
    assert isinstance(result.decision, GroupedMatchPortfolioResult)
    assert result.decision.status == "ambiguous"
    assert result.decision.search_evaluations <= result.total_search_limit == 25_000
    assert result.phase_search_limit == 12_499
    assert len(result.decision.unmatched_left_record_ids) == 64
    assert len(result.decision.unmatched_right_record_ids) == 64


def test_too_small_total_budget_is_refused() -> None:
    with pytest.raises(ExactGroupedMatchingError, match="budget is too small"):
        match_exact_groups_v2(
            (record("L", "1"),),
            (record("R", "1"),),
            GroupedMatchPolicy(mode="portfolio", max_search_evaluations=2),
        )


def test_record_identity_is_bounded_before_serialization() -> None:
    with pytest.raises(ExactGroupedMatchingError, match="identity or partition"):
        match_exact_groups_v2((record("L" * 257, "1"),), (record("R", "1"),), GroupedMatchPolicy(mode="one-to-one"))


def test_unregistered_currency_and_nonrepresentable_amounts_are_refused() -> None:
    policy = GroupedMatchPolicy(mode="one-to-one")
    with pytest.raises(ExactGroupedMatchingError, match="absent from the recorded registry"):
        match_exact_groups_v2((record("L", "1", currency="ZZZ"),), (record("R", "1", currency="ZZZ"),), policy)
    with pytest.raises(ExactGroupedMatchingError, match="currency precision"):
        match_exact_groups_v2((record("L", "1.231"),), (record("R", "1.231"),), policy)
    with pytest.raises(ExactGroupedMatchingError, match="currency precision"):
        match_exact_groups_v2((record("L", "1", fee="0.001"),), (record("R", "1"),), policy)
    valid = match_exact_groups_v2((record("L", "1.230"),), (record("R", "1.23"),), policy)
    assert valid.decision.status == "matched"


def test_tolerance_is_checked_for_every_currency() -> None:
    policy = GroupedMatchPolicy(mode="one-to-one", amount_tolerance=Decimal("0.001"))
    left = (record("L1", "1", currency="BHD"), record("L2", "1", currency="USD"))
    right = (record("R", "1", currency="BHD"),)
    with pytest.raises(ExactGroupedMatchingError, match="currency precision"):
        match_exact_groups_v2(left, right, policy)


def test_registry_identity_is_bound_to_input_and_artifact_digests() -> None:
    left, right = (record("L", "1"),), (record("R", "1"),)
    policy = GroupedMatchPolicy(mode="one-to-one")
    snapshot = REGISTRY.snapshot()
    snapshot.pop("digest")
    snapshot["registry_version"] = "review-other-version"
    other = CurrencyRegistryContext.from_snapshot(snapshot)
    a = _match_exact_groups_v2(left, right, policy, registry_context=REGISTRY)
    b = _match_exact_groups_v2(left, right, policy, registry_context=other)
    assert a.decision.status == b.decision.status == "matched"
    assert a.currency_registry_digest != b.currency_registry_digest
    assert a.input_digest != b.input_digest
    assert a.artifact_digest != b.artifact_digest


def test_partial_settlement_preserves_small_residual() -> None:
    policy = GroupedMatchPolicy(mode="partial-settlement")
    with localcontext() as context:
        context.prec = 3
        result = match_exact_groups_v2((record("L", "100000000.02"),), (record("R", "100000000.01"),), policy)
    assert result.decision.status == "matched"
    assert result.decision.left_residual == Decimal("0.01")


def test_netting_fees_remain_exact_under_hostile_context() -> None:
    left = (record("L", "123456789.01", "0.01"),)
    right = (record("R", "123456789.00"),)
    with localcontext() as context:
        context.prec = 3
        result = match_exact_groups_v2(left, right, GroupedMatchPolicy(mode="one-to-one", netting_mode="net"))
    assert result.decision.status == "matched"
    assert result.decision.left_fee_total == Decimal("0.01")
    assert result.decision.left_net_total == Decimal("123456789.00")


def test_portfolio_is_stable_under_context_and_record_permutation() -> None:
    left = (record("L1", "123456789.01"), record("L2", "987654321.02"))
    right = (record("R1", "123456789.01"), record("R2", "987654321.02"))
    policy = GroupedMatchPolicy(mode="portfolio", max_left_cardinality=1, max_right_cardinality=1)
    with localcontext() as context:
        context.prec = 2
        low = match_exact_groups_v2(left, right, policy)
    with localcontext() as context:
        context.prec = 36
        high = match_exact_groups_v2(left[::-1], right[::-1], policy)
    assert isinstance(low.decision, GroupedMatchPortfolioResult)
    assert low.decision.status == "matched"
    assert len(low.decision.decisions) == 2
    assert low.artifact_digest == high.artifact_digest


def test_ambiguous_portfolio_never_consumes_any_record() -> None:
    left = (record("L1", "1"), record("L2", "1"))
    right = (record("R1", "1"), record("R2", "1"))
    policy = GroupedMatchPolicy(mode="portfolio", max_left_cardinality=1, max_right_cardinality=1)
    result = match_exact_groups_v2(left, right, policy)
    assert isinstance(result.decision, GroupedMatchPortfolioResult)
    assert result.decision.status == "ambiguous"
    assert result.decision.unmatched_left_record_ids == ("L1", "L2")
    assert result.decision.unmatched_right_record_ids == ("R1", "R2")
    assert all(not decision.left_record_ids and not decision.right_record_ids for decision in result.decision.decisions)
    replay = match_exact_groups_v2(left[::-1], right[::-1], policy)
    assert result.artifact_digest == replay.artifact_digest


@settings(max_examples=120, deadline=None)
@given(base=st.integers(min_value=0, max_value=10**40), delta=st.integers(min_value=-10, max_value=10))
def test_matching_agrees_with_independent_scaled_integer_oracle(base: int, delta: int) -> None:
    # Construct decimal values without arithmetic under the ambient context.
    def scaled(value: int) -> Decimal:
        digits = tuple(int(char) for char in str(abs(value)))
        return Decimal((int(value < 0), digits, -3))

    left = (GroupedRecord("L", scaled(base), Decimal("0"), "BHD", date(2026, 10, 27), "partition"),)
    right = (GroupedRecord("R", scaled(base + delta), Decimal("0"), "BHD", date(2026, 10, 27), "partition"),)
    with localcontext() as context:
        context.prec = 2
        result = match_exact_groups_v2(left, right, GroupedMatchPolicy(mode="one-to-one"))
    assert result.decision.status == ("matched" if base == base + delta else "unmatched")
