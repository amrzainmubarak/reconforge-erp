from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from reconforge.domain.grouped_matching import (
    GroupedMatchPolicy,
    GroupedRecord,
    find_grouped_match,
    find_grouped_match_portfolio,
)


@st.composite
def _records(draw: st.DrawFn, prefix: str, *, minimum: int = 1, maximum: int = 4) -> tuple[GroupedRecord, ...]:
    indexes = draw(st.lists(st.integers(min_value=0, max_value=32), min_size=minimum, max_size=maximum, unique=True))
    records: list[GroupedRecord] = []
    for index in indexes:
        records.append(
            GroupedRecord(
                record_id=f"{prefix}{index}",
                amount=Decimal(draw(st.integers(min_value=1, max_value=150))),
                fee=Decimal(draw(st.integers(min_value=0, max_value=8))),
                currency=draw(st.sampled_from(("USD", "EUR"))),
                business_date=date(2026, 8, 1) + timedelta(days=draw(st.integers(min_value=0, max_value=2))),
                partition_key=draw(st.sampled_from(("SETTLEMENT", "OTHER"))),
            )
        )
    return tuple(records)


@settings(max_examples=80, deadline=None, derandomize=True)
@given(left=_records("L"), right=_records("R"))
def test_grouped_match_fuzz_is_permutation_invariant_and_closed(
    left: tuple[GroupedRecord, ...], right: tuple[GroupedRecord, ...]
) -> None:
    policy = GroupedMatchPolicy(
        mode="many-to-many",
        max_left_cardinality=3,
        max_right_cardinality=3,
        max_search_evaluations=5_000,
    )

    first = find_grouped_match(left, right, policy)
    reordered = find_grouped_match(tuple(reversed(left)), tuple(reversed(right)), policy)

    assert first.decision_digest == reordered.decision_digest
    assert first.status == reordered.status
    assert first.search_evaluations == reordered.search_evaluations
    assert first.left_record_ids == reordered.left_record_ids
    assert first.right_record_ids == reordered.right_record_ids
    if first.status == "matched":
        selected = tuple(left_record for left_record in left if left_record.record_id in first.left_record_ids) + tuple(
            right_record for right_record in right if right_record.record_id in first.right_record_ids
        )
        assert len({record.currency for record in selected}) == 1
        assert len({record.partition_key for record in selected}) == 1
        assert max(record.business_date for record in selected) - min(record.business_date for record in selected) == timedelta(0)
        assert first.amount_difference == Decimal("0")


@settings(max_examples=60, deadline=None, derandomize=True)
@given(left=_records("L", minimum=2), right=_records("R", minimum=2))
def test_grouped_match_fuzz_budget_refusal_never_selects_partial_identity(
    left: tuple[GroupedRecord, ...], right: tuple[GroupedRecord, ...]
) -> None:
    policy = GroupedMatchPolicy(
        mode="many-to-many",
        max_left_cardinality=3,
        max_right_cardinality=3,
        max_search_evaluations=1,
    )
    result = find_grouped_match(left, right, policy)

    if result.search_evaluations > policy.max_search_evaluations:
        assert result.status == "ambiguous"
        assert result.reason_code == "GROUP_SEARCH_BUDGET_EXCEEDED"
        assert result.left_record_ids == result.right_record_ids == ()


@settings(max_examples=60, deadline=None, derandomize=True)
@given(left=_records("L", minimum=1, maximum=3), right=_records("R", minimum=1, maximum=3))
def test_grouped_portfolio_fuzz_preserves_non_overlap_and_replay_digest(
    left: tuple[GroupedRecord, ...], right: tuple[GroupedRecord, ...]
) -> None:
    policy = GroupedMatchPolicy(
        mode="portfolio",
        max_left_cardinality=2,
        max_right_cardinality=2,
        max_search_evaluations=2_000,
    )
    first = find_grouped_match_portfolio(left, right, policy)
    reordered = find_grouped_match_portfolio(tuple(reversed(left)), tuple(reversed(right)), policy)

    assert first.portfolio_digest == reordered.portfolio_digest
    assert first.status == reordered.status
    if first.status == "matched":
        left_ids = [record_id for decision in first.decisions for record_id in decision.left_record_ids]
        right_ids = [record_id for decision in first.decisions for record_id in decision.right_record_ids]
        assert len(left_ids) == len(set(left_ids))
        assert len(right_ids) == len(set(right_ids))
        assert not set(left_ids).intersection(first.unmatched_left_record_ids)
        assert not set(right_ids).intersection(first.unmatched_right_record_ids)
