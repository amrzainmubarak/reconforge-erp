"""Restore validation uses an explicit historical watermark, never inferred history."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from reconforge.domain.outbox_fencing import OutboxEvidenceIntegrityError, validate_outbox_delivery_evidence


def _claim(generation: int) -> dict[str, object]:
    return dict(event_id="event", lease_generation=generation, action="claimed", worker_id="worker", attempts=1)


@given(st.integers(min_value=0, max_value=30), st.sampled_from([0, 2]), st.randoms())
def test_claim_continuity_is_independent_of_evidence_order(count: int, floor: int, random: object) -> None:
    rows = [_claim(floor + index + 1) for index in range(count)]
    random.shuffle(rows)  # type: ignore[attr-defined]
    validate_outbox_delivery_evidence(event_id="event", lease_generation=floor + count, lease_generation_floor=floor, evidence=rows)


@pytest.mark.parametrize("rows", [[], [_claim(1), _claim(1)], [_claim(2)], [_claim(1), _claim(3)]])
def test_missing_duplicate_or_gapped_claims_are_rejected(rows: list[dict[str, object]]) -> None:
    with pytest.raises(OutboxEvidenceIntegrityError):
        validate_outbox_delivery_evidence(event_id="event", lease_generation=2, lease_generation_floor=0, evidence=rows)


def test_preupgrade_watermark_is_explicit_and_not_invented() -> None:
    validate_outbox_delivery_evidence(event_id="legacy", lease_generation=2, lease_generation_floor=2, evidence=[])
    with pytest.raises(OutboxEvidenceIntegrityError, match="Historical"):
        validate_outbox_delivery_evidence(event_id="event", lease_generation=2, lease_generation_floor=2, evidence=[_claim(2)])


def test_huge_corrupt_generation_does_not_allocate_or_iterate_history() -> None:
    with pytest.raises(OutboxEvidenceIntegrityError):
        validate_outbox_delivery_evidence(event_id="event", lease_generation=2**63 - 1, lease_generation_floor=0, evidence=[])


@pytest.mark.parametrize("field,value", [("event_id", "other"), ("worker_id", ""), ("attempts", -1), ("lease_generation", True), ("action", "forged")])
def test_malformed_or_unbound_evidence_is_rejected(field: str, value: object) -> None:
    row = _claim(1)
    row[field] = value
    with pytest.raises(OutboxEvidenceIntegrityError):
        validate_outbox_delivery_evidence(event_id="event", lease_generation=1, lease_generation_floor=0, evidence=[row])
