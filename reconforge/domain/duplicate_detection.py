"""Deterministic, bounded duplicate detection for reconciliation inputs.

The detector deliberately treats duplicate detection as an evidence-producing
operation, not as a silent de-duplication step.  Every occurrence remains
visible and receives a stable ordinal within its canonical fingerprint group.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, cast

DuplicateSide = Literal["left", "right"]
DuplicateGroupStatus = Literal["unique", "duplicate"]
DuplicateDetectionStatus = Literal["unique", "duplicate", "ambiguous"]


class DuplicateDetectionError(ValueError):
    """Raised when duplicate detection input violates its contract."""


@dataclass(frozen=True)
class DuplicateDetectionPolicy:
    """Published ceilings for one bounded duplicate-detection execution."""

    max_records_per_side: int = 250_000
    max_total_evaluations: int = 500_000
    max_fingerprint_fields: int = 32

    def __post_init__(self) -> None:
        values = (self.max_records_per_side, self.max_total_evaluations, self.max_fingerprint_fields)
        if any(isinstance(value, bool) or value < 1 for value in values):
            raise DuplicateDetectionError("Duplicate-detection ceilings must be positive integers.")


@dataclass(frozen=True)
class DuplicateGroup:
    """One canonical fingerprint group and all of its visible occurrences."""

    side: DuplicateSide
    fingerprint: str
    record_ids: tuple[str, ...]
    occurrence_ids: tuple[str, ...]
    duplicate_count: int
    status: DuplicateGroupStatus
    reason_code: str


@dataclass(frozen=True)
class DuplicateDetectionResult:
    """Replayable duplicate evidence with an explicit fail-closed status."""

    status: DuplicateDetectionStatus
    groups: tuple[DuplicateGroup, ...]
    records_processed: int
    fingerprint_evaluations: int
    duplicate_group_count: int
    reason_code: str
    decision_digest: str


def detect_duplicates(
    left_records: tuple[Mapping[str, object], ...],
    right_records: tuple[Mapping[str, object], ...],
    *,
    fingerprint_fields: tuple[str, ...],
    amount_field: str,
    left_id_field: str = "id",
    right_id_field: str = "id",
    policy: DuplicateDetectionPolicy = DuplicateDetectionPolicy(),
) -> DuplicateDetectionResult:
    """Group exact canonical duplicates without deleting or rewriting records.

    Records are sorted by their stable business identity before occurrence
    ordinals are assigned.  The digest therefore remains unchanged when input
    rows are permuted, while duplicate row lineage remains explicit.
    """

    if not fingerprint_fields or len(fingerprint_fields) > policy.max_fingerprint_fields:
        raise DuplicateDetectionError("Duplicate-detection fingerprint fields are invalid.")
    if any(not field or not field.strip() for field in fingerprint_fields):
        raise DuplicateDetectionError("Duplicate-detection fingerprint fields cannot be empty.")
    if len(set(fingerprint_fields)) != len(fingerprint_fields):
        raise DuplicateDetectionError("Duplicate-detection fingerprint fields must be unique.")
    if len(left_records) > policy.max_records_per_side or len(right_records) > policy.max_records_per_side:
        raise DuplicateDetectionError("Duplicate-detection input record limit exceeded.")
    total = len(left_records) + len(right_records)
    if total > policy.max_total_evaluations:
        return _result(
            status="ambiguous",
            groups=(),
            records_processed=0,
            evaluations=total,
            duplicate_group_count=0,
            reason_code="DUPLICATE_DETECTION_BUDGET_EXCEEDED",
        )

    groups: list[DuplicateGroup] = []
    for side, records, id_field in (
        ("left", left_records, left_id_field),
        ("right", right_records, right_id_field),
    ):
        groups.extend(_groups_for_side(cast(DuplicateSide, side), records, fingerprint_fields, amount_field, id_field))
    duplicate_group_count = sum(1 for group in groups if group.status == "duplicate")
    status: DuplicateDetectionStatus = "duplicate" if duplicate_group_count else "unique"
    reason = "DUPLICATE_GROUPS_FOUND" if duplicate_group_count else "NO_DUPLICATE_GROUPS"
    return _result(
        status=status,
        groups=tuple(groups),
        records_processed=total,
        evaluations=total,
        duplicate_group_count=duplicate_group_count,
        reason_code=reason,
    )


def _groups_for_side(
    side: DuplicateSide,
    records: tuple[Mapping[str, object], ...],
    fingerprint_fields: tuple[str, ...],
    amount_field: str,
    id_field: str,
) -> list[DuplicateGroup]:
    identities: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    for record in records:
        raw_id = record.get(id_field)
        record_id = str(raw_id) if isinstance(raw_id, str | int) and not isinstance(raw_id, bool) else ""
        if not record_id.strip():
            raise DuplicateDetectionError("Duplicate-detection records require a non-empty string or integer id.")
        if record_id in seen_ids:
            raise DuplicateDetectionError("Duplicate-detection record identities must be unique per side.")
        seen_ids.add(record_id)
        projection = _projection(record, fingerprint_fields, amount_field)
        identities.append((record_id, _fingerprint(projection)))

    grouped: dict[str, list[str]] = {}
    for record_id, fingerprint in sorted(identities, key=lambda item: (item[1], item[0])):
        grouped.setdefault(fingerprint, []).append(record_id)
    result: list[DuplicateGroup] = []
    for fingerprint in sorted(grouped):
        record_ids = tuple(grouped[fingerprint])
        duplicate_count = len(record_ids)
        status: DuplicateGroupStatus = "duplicate" if duplicate_count > 1 else "unique"
        reason = "DUPLICATE_FINGERPRINT_GROUP" if duplicate_count > 1 else "UNIQUE_FINGERPRINT"
        occurrence_ids = tuple(
            record_id if duplicate_count == 1 else f"{record_id}#occurrence:{ordinal}"
            for ordinal, record_id in enumerate(record_ids, start=1)
        )
        result.append(
            DuplicateGroup(
                side=side,
                fingerprint=fingerprint,
                record_ids=record_ids,
                occurrence_ids=occurrence_ids,
                duplicate_count=duplicate_count,
                status=status,
                reason_code=reason,
            )
        )
    return result


def _projection(record: Mapping[str, object], fields: tuple[str, ...], amount_field: str) -> tuple[tuple[str, object], ...]:
    values: list[tuple[str, object]] = []
    for field in fields:
        if field not in record:
            values.append((field, ["missing"]))
            continue
        value = record[field]
        if field == amount_field:
            values.append((field, ["value", _canonical_amount(value)]))
        else:
            values.append((field, ["value", _canonical_value(value)]))
    return tuple(values)


def _canonical_amount(value: object) -> str:
    if isinstance(value, bool):
        raise DuplicateDetectionError("Duplicate-detection amounts cannot be boolean values.")
    if isinstance(value, float):
        raise DuplicateDetectionError("Duplicate-detection amounts cannot use binary floating point.")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DuplicateDetectionError("Duplicate-detection amounts must be finite exact values.") from exc
    if not isinstance(amount, Decimal) or not amount.is_finite():
        raise DuplicateDetectionError("Duplicate-detection amounts must be finite exact values.")
    normalized = Decimal("0") if amount == 0 else amount.normalize()
    return format(normalized, "f")


def _canonical_value(value: object) -> object:
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float):
        raise DuplicateDetectionError("Duplicate-detection payload cannot contain binary floating point.")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise DuplicateDetectionError("Duplicate-detection payload contains a non-finite Decimal.")
        normalized = Decimal("0") if value == 0 else value.normalize()
        return format(normalized, "f")
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        normalized_map: dict[str, object] = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            name = str(key)
            if name in normalized_map:
                raise DuplicateDetectionError("Duplicate-detection payload contains colliding field names.")
            normalized_map[name] = _canonical_value(item)
        return normalized_map
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_canonical_value(item) for item in value]
    raise DuplicateDetectionError("Duplicate-detection payload contains an unsupported value.")


def _fingerprint(projection: tuple[tuple[str, object], ...]) -> str:
    encoded = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _result(
    *,
    status: DuplicateDetectionStatus,
    groups: tuple[DuplicateGroup, ...],
    records_processed: int,
    evaluations: int,
    duplicate_group_count: int,
    reason_code: str,
) -> DuplicateDetectionResult:
    payload = {
        "status": status,
        "groups": [
            {
                "side": group.side,
                "fingerprint": group.fingerprint,
                "record_ids": group.record_ids,
                "occurrence_ids": group.occurrence_ids,
                "duplicate_count": group.duplicate_count,
                "status": group.status,
                "reason_code": group.reason_code,
            }
            for group in groups
        ],
        "records_processed": records_processed,
        "fingerprint_evaluations": evaluations,
        "duplicate_group_count": duplicate_group_count,
        "reason_code": reason_code,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(encoded.encode("ascii")).hexdigest()
    return DuplicateDetectionResult(
        status=status,
        groups=groups,
        records_processed=records_processed,
        fingerprint_evaluations=evaluations,
        duplicate_group_count=duplicate_group_count,
        reason_code=reason_code,
        decision_digest=digest,
    )
