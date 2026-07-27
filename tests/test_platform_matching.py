from __future__ import annotations

import json
import random
import sqlite3
from decimal import Decimal
from itertools import permutations
from pathlib import Path
from typing import Any

import pytest

from reconforge.db import connect, run_migrations
from reconforge.domain.models import utc_now_text
from reconforge.platform.common import PlatformError
from reconforge.platform.matching import MatchingService
from reconforge.reconciliation.matching import RECORD_IDENTITY_POLICY


def _assert_data_quality_exception_shape(exception: object) -> None:
    assert isinstance(exception, dict), exception
    assert exception["exception_type"] == "data_quality"
    for key in (
        "exception_id",
        "source_side",
        "source_id",
        "title",
        "explanation",
        "severity",
        "risk_score",
        "reason_code",
        "evidence",
    ):
        assert key in exception

    assert str(exception["exception_id"]).startswith("EXC-")


def _run_match(
    tmp_path: Path,
    left_rows: str,
    right_rows: str,
    *,
    allow_many_to_one: bool = False,
    allow_one_to_many: bool = False,
    allow_many_to_many: bool = False,
    left_id_field: str = "id",
    right_id_field: str = "id",
    run_name: str = "base",
):
    db_path = tmp_path / f"{run_name}_operations.db"
    run_migrations(db_path)

    left = tmp_path / f"{run_name}_left.csv"
    right = tmp_path / f"{run_name}_right.csv"
    left.write_text(left_rows, encoding="utf-8")
    right.write_text(right_rows, encoding="utf-8")

    return _run_match_internal(
        tmp_path=tmp_path,
        left_rows=left_rows,
        right_rows=right_rows,
        left_id_field=left_id_field,
        right_id_field=right_id_field,
        allow_many_to_one=allow_many_to_one,
        allow_one_to_many=allow_one_to_many,
        allow_many_to_many=allow_many_to_many,
        run_name=run_name,
        include_rows=False,
    )


def _run_match_internal(
    *,
    tmp_path: Path,
    left_rows: str,
    right_rows: str,
    left_id_field: str,
    right_id_field: str,
    allow_many_to_one: bool,
    allow_one_to_many: bool,
    allow_many_to_many: bool,
    run_name: str,
    include_rows: bool,
):
    db_path = tmp_path / f"{run_name}_operations.db"
    run_migrations(db_path)

    left = tmp_path / f"{run_name}_left.csv"
    right = tmp_path / f"{run_name}_right.csv"
    left.write_text(left_rows, encoding="utf-8")
    right.write_text(right_rows, encoding="utf-8")

    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        result = service.run(
            left_path=left,
            right_path=right,
            left_id_field=left_id_field,
            right_id_field=right_id_field,
            allow_many_to_one=allow_many_to_one,
            allow_one_to_many=allow_one_to_many,
            allow_many_to_many=allow_many_to_many,
        )
        all_rows = service.results(result.job_id)
        matched = [record for record in all_rows if record["status"] == "Matched"]
    finally:
        connection.close()
    if include_rows:
        return result, matched, all_rows
    return result, matched


def _result_exceptions(result_rows: list[dict[str, object]]) -> tuple[tuple[str, ...], ...]:
    exceptions = [
        (
            str(item.get("match_type", "")),
            str(item.get("left_id", "")) or str(item.get("right_id", "")),
            str(item.get("reason_code", "")),
        )
        for item in result_rows
        if str(item.get("status")) == "Invalid"
    ]
    return tuple(sorted(exceptions))


def test_matching_is_deterministic_after_shuffling_left_rows(tmp_path: Path) -> None:
    left_rows = [
        "id,reference,amount,date",
        "L-A,REF-INV,100.00,2026-01-10",
        "L-B,REF-INV,100.00,2026-01-10",
    ]
    left_records = [
        "L-A,REF-INV,100.00,2026-01-10",
        "L-B,REF-INV,100.00,2026-01-10",
    ]
    left = "\n".join(left_rows) + "\n"
    left_shuffled = left_rows[0] + "\n" + "\n".join(reversed(left_records)) + "\n"
    right = (
        "id,reference,amount,date\n"
        "R-B,REF-INV,100.00,2026-01-10\n"
        "R-A,REF-INV,100.00,2026-01-10\n"
    )
    _, matched_a = _run_match(tmp_path, left, right, allow_many_to_one=False, run_name="base")
    _, matched_b = _run_match(tmp_path, left_shuffled, right, allow_many_to_one=False, run_name="shuffled")

    matched_pairs_a = {(row["left_id"], row["right_id"]) for row in matched_a}
    matched_pairs_b = {(row["left_id"], row["right_id"]) for row in matched_b}
    assert matched_pairs_a == matched_pairs_b
    assert len(matched_a) == 2


def test_matching_is_deterministic_after_shuffling_right_rows(tmp_path: Path) -> None:
    left = (
        "id,reference,amount,date\n"
        "L-A,REF-INV,100.00,2026-01-10\n"
        "L-B,REF-INV,100.00,2026-01-10\n"
    )
    right_records = [
        "id,reference,amount,date",
        "R-A,REF-INV,100.00,2026-01-10",
        "R-B,REF-INV,100.00,2026-01-10",
    ]
    right = "\n".join(right_records) + "\n"
    right_shuffled = right_records[0] + "\n" + "\n".join(reversed(right_records[1:])) + "\n"

    _, matched_a = _run_match(tmp_path, left, right, allow_many_to_one=False, run_name="base_right")
    _, matched_b = _run_match(tmp_path, left, right_shuffled, allow_many_to_one=False, run_name="shuffled_right")

    matched_pairs_a = {(row["left_id"], row["right_id"]) for row in matched_a}
    matched_pairs_b = {(row["left_id"], row["right_id"]) for row in matched_b}
    assert matched_pairs_a == matched_pairs_b
    assert len(matched_a) == 2


def _exception_signature(exceptions: tuple[dict[str, object], ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(
        sorted(
            (
                str(item.get("exception_type", "")),
                str(item.get("source_side", "")),
                str(item.get("source_id", "")),
                str(item.get("reason_code", "")),
            )
            for item in exceptions
        )
    )


def _exception_id_signature(exceptions: tuple[dict[str, object], ...]) -> tuple[str, ...]:
    return tuple(
        sorted(str(item.get("exception_id", "")) for item in exceptions),
    )


def test_matching_data_quality_exceptions_are_order_invariant(tmp_path: Path) -> None:
    left_payload = (
        "id,reference,amount,date\n"
        "L-1,REF-001,abc,2026-01-10\n"
        "L-2,REF-002,200.00,2026-13-01\n"
    )
    right_payload = (
        "id,reference,amount,date\n"
        "R-1,REF-003,100.00,2026-01-10\n"
        "R-2,REF-004,200.00,2026-01-10\n"
    )

    _, _, first_rows = _run_match_internal(
        tmp_path=tmp_path,
        left_rows=left_payload,
        right_rows=right_payload,
        left_id_field="id",
        right_id_field="id",
        allow_many_to_one=False,
        allow_one_to_many=False,
        allow_many_to_many=False,
        run_name="dq_order_a",
        include_rows=True,
    )
    _, _, second_rows = _run_match_internal(
        tmp_path=tmp_path,
        left_rows=(
            "id,reference,amount,date\n"
            "L-2,REF-002,200.00,2026-13-01\n"
            "L-1,REF-001,abc,2026-01-10\n"
        ),
        right_rows=(
            "id,reference,amount,date\n"
            "R-2,REF-004,200.00,2026-01-10\n"
            "R-1,REF-003,100.00,2026-01-10\n"
        ),
        left_id_field="id",
        right_id_field="id",
        allow_many_to_one=False,
        allow_one_to_many=False,
        allow_many_to_many=False,
        run_name="dq_order_b",
        include_rows=True,
    )

    assert _result_exceptions(first_rows) == _result_exceptions(second_rows)
    assert len([row for row in first_rows if row["status"] == "Invalid"]) == len(
        [row for row in second_rows if row["status"] == "Invalid"]
    ) == 2


def test_matching_data_quality_exception_ids_are_stable_under_row_shuffles(tmp_path: Path) -> None:
    db_path = tmp_path / "matching_exception_ids.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        base_left = [
            {"id": "L-1", "reference": "REF-001", "amount": "abc", "date": "2026-01-10"},
            {"id": "L-2", "reference": "REF-002", "amount": "200.00", "date": "2026-13-01"},
            {"id": "L-3", "reference": "REF-003", "amount": "100.00", "date": "2026-01-10"},
        ]
        base_right = [
            {"id": "R-1", "reference": "REF-004", "amount": "100.00", "date": "2026-01-10"},
            {"id": "R-2", "reference": "REF-005", "amount": "N/A", "date": "2026-01-11"},
            {"id": "R-3", "reference": "REF-006", "amount": "300.00", "date": "2026-13-01"},
        ]
        baseline = service.match_records(
            left_records=base_left,
            right_records=base_right,
            allow_many_to_many=False,
        )

        shuffled_left = [
            {"id": "L-2", "reference": "REF-002", "amount": "200.00", "date": "2026-13-01"},
            {"id": "L-3", "reference": "REF-003", "amount": "100.00", "date": "2026-01-10"},
            {"id": "L-1", "reference": "REF-001", "amount": "abc", "date": "2026-01-10"},
        ]
        shuffled_right = [
            {"id": "R-3", "reference": "REF-006", "amount": "300.00", "date": "2026-13-01"},
            {"id": "R-1", "reference": "REF-004", "amount": "100.00", "date": "2026-01-10"},
            {"id": "R-2", "reference": "REF-005", "amount": "N/A", "date": "2026-01-11"},
        ]
        shuffled = service.match_records(
            left_records=shuffled_left,
            right_records=shuffled_right,
            allow_many_to_many=False,
        )
    finally:
        connection.close()

    assert _exception_id_signature(baseline.exceptions) == _exception_id_signature(shuffled.exceptions)
    assert len(baseline.exceptions) == len(shuffled.exceptions) == 4
    for entry in baseline.exceptions:
        _assert_data_quality_exception_shape(entry)


def _signature(results: list[dict[str, object]]) -> tuple[tuple[str, ...], ...]:
    relevant = []
    for row in results:
        left_id = str(row.get("left_id", ""))
        right_id = str(row.get("right_id", ""))
        relevant.append(
            (
                str(row.get("match_type", "")),
                str(row.get("status", "")),
                left_id,
                right_id,
                str(row.get("reason_code", "")),
            ),
        )
    return tuple(sorted(relevant))


def test_matching_order_invariance_across_many_random_permutations(tmp_path: Path) -> None:
    left_rows = [
        "L-1,REF-INV,100.00,2026-01-10",
        "L-2,REF-INV,100.00,2026-01-10",
        "L-3,REF-INV,100.00,2026-01-10",
        "L-4,REF-INV,100.00,2026-01-10",
    ]
    right_rows = [
        "R-4,REF-INV,100.00,2026-01-10",
        "R-3,REF-INV,100.00,2026-01-10",
        "R-2,REF-INV,100.00,2026-01-10",
        "R-1,REF-INV,100.00,2026-01-10",
    ]
    base_left = "id,reference,amount,date\n" + "\n".join(left_rows) + "\n"
    base_right = "id,reference,amount,date\n" + "\n".join(right_rows) + "\n"
    _, baseline_matched = _run_match(
        tmp_path,
        base_left,
        base_right,
        allow_many_to_one=False,
        run_name="random_perm_base",
    )
    baseline_signature = _signature(baseline_matched)
    assert len(baseline_signature) == 4

    rng = random.Random(2026)
    for run in range(12):
        shuffled_left_rows = left_rows[:]
        shuffled_right_rows = right_rows[:]
        rng.shuffle(shuffled_left_rows)
        rng.shuffle(shuffled_right_rows)
        _, signature_candidates = _run_match(
            tmp_path,
            "id,reference,amount,date\n" + "\n".join(shuffled_left_rows) + "\n",
            "id,reference,amount,date\n" + "\n".join(shuffled_right_rows) + "\n",
            allow_many_to_one=False,
            run_name=f"random_perm_{run}",
        )
        assert _signature(signature_candidates) == baseline_signature


def test_match_records_order_invariance_for_equivalent_shuffles(tmp_path: Path) -> None:
    records_left = [
        {"id": "L-1", "reference": "REF-INV", "amount": "100.00", "date": "2026-01-10"},
        {"id": "L-2", "reference": "REF-INV", "amount": "75.00", "date": "2026-01-10"},
        {"id": "L-3", "reference": "REF-INV", "amount": "25.00", "date": "2026-01-10"},
    ]
    records_right = [
        {"id": "R-1", "reference": "REF-INV", "amount": "75.00", "date": "2026-01-10"},
        {"id": "R-2", "reference": "REF-INV", "amount": "25.00", "date": "2026-01-10"},
        {"id": "R-3", "reference": "REF-INV", "amount": "100.00", "date": "2026-01-10"},
    ]

    db_path = tmp_path / "order_invariance_records.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        baseline = service.match_records(
            left_records=records_left,
            right_records=records_right,
        )
        baseline_signature = _signature(baseline.results)

        rng = random.Random(2027)
        for _ in range(8):
            left_values = records_left[:]
            right_values = records_right[:]
            rng.shuffle(left_values)
            rng.shuffle(right_values)
            output = service.match_records(
                left_records=left_values,
                right_records=right_values,
            )
            assert _signature(output.results) == baseline_signature
            assert len(output.results) == len(baseline.results)
    finally:
        connection.close()


def test_matching_results_are_order_invariant_across_all_permutations(tmp_path: Path) -> None:
    left_rows = [
        "L-A,REF-INV,100.00,2026-01-10",
        "L-B,REF-INV,100.00,2026-01-10",
        "L-C,REF-INV,100.00,2026-01-10",
    ]
    right_rows = [
        "R-3,REF-INV,100.00,2026-01-10",
        "R-1,REF-INV,100.00,2026-01-10",
        "R-2,REF-INV,100.00,2026-01-10",
    ]
    left_payload = "id,reference,amount,date\n" + "\n".join(left_rows) + "\n"
    right_payload = "id,reference,amount,date\n" + "\n".join(right_rows) + "\n"

    expected_pairs: set[tuple[str, str]] | None = None
    run = 0
    for left_order in permutations(left_rows):
        for right_order in permutations(right_rows):
            left_data = "id,reference,amount,date\n" + "\n".join(left_order) + "\n"
            right_data = "id,reference,amount,date\n" + "\n".join(right_order) + "\n"
            _, matched = _run_match(
                tmp_path,
                left_data,
                right_data,
                allow_many_to_one=True,
                run_name=f"perm_{run}",
            )
            current_pairs = {(row["left_id"], row["right_id"]) for row in matched}
            if expected_pairs is None:
                expected_pairs = current_pairs
            else:
                assert current_pairs == expected_pairs
            run += 1

    # Keep deterministic baseline parity assertion for at least one non-identity path.
    _, expected_matched = _run_match(tmp_path, left_payload, right_payload, allow_many_to_one=True, run_name="baseline")
    assert {(row["left_id"], row["right_id"]) for row in expected_matched} == set(expected_pairs or set())


def test_matching_allows_many_to_one_when_enabled(tmp_path: Path) -> None:
    left = (
        "id,reference,amount,date\n"
        "L-1,REF-INV,100.00,2026-01-10\n"
        "L-2,REF-INV,100.00,2026-01-10\n"
    )
    right = "id,reference,amount,date\nR-1,REF-INV,100.00,2026-01-10\n"

    one_to_one_result, one_to_one_matched = _run_match(tmp_path, left, right, allow_many_to_one=False, run_name="one_to_one")
    many_to_one_result, many_to_one_matched = _run_match(tmp_path, left, right, allow_many_to_one=True, run_name="many_to_one")

    assert one_to_one_result.matched_count == 1
    assert len(one_to_one_matched) == 1
    assert many_to_one_result.matched_count == 2
    assert len(many_to_one_matched) == 2
    assert len({row["right_id"] for row in many_to_one_matched}) == 1


def test_matching_allows_one_to_many_when_enabled(tmp_path: Path) -> None:
    left = "id,reference,amount,date\nL-1,REF-INV,100.00,2026-01-10\n"
    right = (
        "id,reference,amount,date\n"
        "R-1,REF-INV,100.00,2026-01-10\n"
        "R-2,REF-INV,100.00,2026-01-10\n"
    )

    one_to_one_result, one_to_one_matched = _run_match(
        tmp_path,
        left,
        right,
        allow_many_to_one=False,
        run_name="one_to_one_for_left_only",
    )
    one_to_many_result, one_to_many_matched = _run_match(
        tmp_path,
        left,
        right,
        allow_many_to_one=False,
        allow_one_to_many=True,
        run_name="one_to_many",
    )

    assert one_to_one_result.matched_count == 1
    assert len(one_to_one_matched) == 1
    assert one_to_many_result.matched_count == 2
    assert len(one_to_many_matched) == 2
    assert {row["left_id"] for row in one_to_many_matched} == {"L-1"}


def test_matching_allows_many_to_many_when_enabled(tmp_path: Path) -> None:
    left = "id,reference,amount,date\nL-INV-1,INV-1,100.00,2026-01-10\nL-INV-2,INV-1,100.00,2026-01-10\n"
    right = "id,reference,amount,date\nR-A,INV-1,100.00,2026-01-10\nR-B,INV-1,100.00,2026-01-10\n"

    _, matched = _run_match(
        tmp_path,
        left,
        right,
        allow_many_to_many=True,
        run_name="many_to_many",
    )

    assert len(matched) == 4
    assert len({row["left_id"] for row in matched}) == 2
    assert len({row["right_id"] for row in matched}) == 2


def test_matching_returns_empty_exception_payload_when_inputs_are_fully_valid(tmp_path: Path) -> None:
    db_path = tmp_path / "empty_exceptions_match.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        output = service.match_records(
            left_records=[
                {"id": "L-1", "reference": "REF-100", "amount": "50.00", "date": "2026-01-01"},
            ],
            right_records=[
                {"id": "R-1", "reference": "REF-100", "amount": "50.00", "date": "2026-01-01"},
            ],
        )
    finally:
        connection.close()

    assert output.exceptions == ()
    assert len(output.results) == 1
    assert output.results[0]["status"] == "Matched"


def _upsert_currency(
    connection,
    code: str,
    *,
    minor_units: int = 2,
    active: bool = True,
) -> None:
    now = utc_now_text()
    connection.execute(
        """
        INSERT INTO currencies (code, name, minor_units, active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            name = excluded.name,
            minor_units = excluded.minor_units,
            active = excluded.active,
            updated_at = excluded.updated_at
        """,
        (code.upper(), code.upper(), minor_units, 1 if active else 0, now, now),
    )
    connection.commit()


def test_matching_unknown_currency_is_emitted_as_data_quality_exception(tmp_path: Path) -> None:
    db_path = tmp_path / "unknown_currency_exception.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        output = service.match_records(
            left_records=[
                {"id": "L-1", "reference": "REF-100", "amount": "50.00", "date": "2026-01-01", "currency_code": "ZZZ"},
            ],
            right_records=[
                {"id": "R-1", "reference": "REF-100", "amount": "50.00", "date": "2026-01-01", "currency_code": "ZZZ"},
            ],
        )
    finally:
        connection.close()

    assert output.results[0]["status"] == "Invalid"
    assert output.results[1]["match_type"] == "invalid_right"
    assert all(item["reason_code"] == "UNKNOWN_CURRENCY" for item in output.exceptions)


def test_matching_inactive_currency_is_emitted_as_data_quality_exception(tmp_path: Path) -> None:
    db_path = tmp_path / "inactive_currency_exception.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        _upsert_currency(connection, "JPY", minor_units=0, active=False)
        service = MatchingService(connection)
        output = service.match_records(
            left_records=[
                {"id": "L-1", "reference": "REF-100", "amount": "10", "currency_code": "JPY", "date": "2026-01-01"},
            ],
            right_records=[
                {"id": "R-1", "reference": "REF-100", "amount": "10", "currency_code": "JPY", "date": "2026-01-01"},
            ],
        )
    finally:
        connection.close()

    assert output.results[0]["status"] == "Invalid"
    assert output.results[1]["match_type"] == "invalid_right"
    assert all(item["reason_code"] == "INACTIVE_CURRENCY" for item in output.exceptions)


def test_matching_precision_violation_is_blocked_for_zero_minor_unit_currency(tmp_path: Path) -> None:
    db_path = tmp_path / "precision_violation_match.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        _upsert_currency(connection, "JPY", minor_units=0, active=True)
        service = MatchingService(connection)
        output = service.match_records(
            left_records=[
                {"id": "L-1", "reference": "REF-100", "amount": "10.50", "currency_code": "JPY", "date": "2026-01-01"},
            ],
            right_records=[
                {"id": "R-1", "reference": "REF-100", "amount": "10.50", "currency_code": "JPY", "date": "2026-01-01"},
            ],
        )
    finally:
        connection.close()

    assert output.results[0]["status"] == "Invalid"
    assert output.results[1]["match_type"] == "invalid_right"
    assert all(item["reason_code"] == "INVALID_AMOUNT" for item in output.exceptions)


def test_matching_without_currency_precision_uses_exact_amount_bucketing_for_candidate_indexing(tmp_path: Path) -> None:
    db_path = tmp_path / "precision_bucket_no_currency.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        output = service.match_records(
            left_records=[
                {
                    "id": "L-1",
                    "reference": "L-REF",
                    "amount": "1000.004",
                    "date": "2026-01-10",
                }
            ],
            right_records=[
                {
                    "id": "R-1",
                    "reference": "R-REF",
                    "amount": "1000.0049",
                    "date": "2026-01-10",
                },
            ],
        )
    finally:
        connection.close()

    left_result = next(item for item in output.results if item["left_id"] == "L-1")
    assert left_result["status"] == "Unmatched"
    assert left_result["lineage"]["candidate_count"] == 0


def test_matching_unknown_currency_precision_works_identically_in_memory_and_run(tmp_path: Path) -> None:
    db_path = tmp_path / "precision_bucket_run_parity.db"
    run_migrations(db_path)

    base_left_records = [
        {"id": "L-1", "reference": "INV-A", "amount": "1000.004", "date": "2026-01-10"},
        {"id": "L-2", "reference": "INV-B", "amount": "250.001", "date": "2026-01-10"},
    ]
    base_right_records = [
        {"id": "R-1", "reference": "R-INV-A", "amount": "1000.0049", "date": "2026-01-10"},
        {"id": "R-2", "reference": "R-INV-B", "amount": "250.0019", "date": "2026-01-10"},
    ]

    left_path = tmp_path / "left.csv"
    right_path = tmp_path / "right.csv"
    left_path.write_text(
        "id,reference,amount,date\n"
        "L-1,INV-A,1000.004,2026-01-10\n"
        "L-2,INV-B,250.001,2026-01-10\n",
        encoding="utf-8",
    )
    right_path.write_text(
        "id,reference,amount,date\n"
        "R-1,R-INV-A,1000.0049,2026-01-10\n"
        "R-2,R-INV-B,250.0019,2026-01-10\n",
        encoding="utf-8",
    )

    left_shuffled_path = tmp_path / "left_shuffled.csv"
    right_shuffled_path = tmp_path / "right_shuffled.csv"
    left_shuffled_path.write_text(
        "id,reference,amount,date\n"
        "L-2,INV-B,250.001,2026-01-10\n"
        "L-1,INV-A,1000.004,2026-01-10\n",
        encoding="utf-8",
    )
    right_shuffled_path.write_text(
        "id,reference,amount,date\n"
        "R-2,R-INV-B,250.0019,2026-01-10\n"
        "R-1,R-INV-A,1000.0049,2026-01-10\n",
        encoding="utf-8",
    )

    def decision_lineage(value: object) -> object:
        if isinstance(value, dict):
            return {
                str(key): decision_lineage(item)
                for key, item in value.items()
                if key != "source_location"
            }
        if isinstance(value, list):
            return [decision_lineage(item) for item in value]
        return value

    def stable_signature(values: list[dict[str, Any]]) -> tuple[tuple[str, ...], ...]:
        return tuple(
            sorted(
                (
                    str(row.get("left_id", "")),
                    str(row.get("right_id", "")),
                    str(row.get("status", "")),
                    str(row.get("reason_code", "")),
                    str(row.get("match_type", "")),
                    json.dumps(
                        decision_lineage(row.get("lineage", {})),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
                for row in values
            )
        )

    def stable_signature_rows(rows: list[sqlite3.Row]) -> tuple[tuple[str, ...], ...]:
        return tuple(
            sorted(
                (
                    str(row["left_id"] or ""),
                    str(row["right_id"] or ""),
                    str(row["status"] or ""),
                    str(row["reason_code"] or ""),
                    str(row["match_type"] or ""),
                    json.dumps(
                        decision_lineage(json.loads(row["lineage_json"] or "{}")),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
                for row in rows
            )
        )

    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        in_memory_base = service.match_records(
            left_records=base_left_records,
            right_records=base_right_records,
            allow_many_to_many=False,
        )
        in_memory_shuffled = service.match_records(
            left_records=list(reversed(base_left_records)),
            right_records=list(reversed(base_right_records)),
            allow_many_to_many=False,
        )
        assert stable_signature(list(in_memory_base.results)) == stable_signature(list(in_memory_shuffled.results))

        run_result = service.run(
            left_path=left_path,
            right_path=right_path,
            allow_many_to_one=False,
            allow_one_to_many=False,
            allow_many_to_many=False,
        )
        run_rows = connection.execute(
            """
            SELECT left_id, right_id, status, reason_code, match_type, lineage_json
            FROM match_results
            WHERE job_id = ?
            ORDER BY COALESCE(left_id, ''), COALESCE(right_id, '')
            """,
            (run_result.job_id,),
        ).fetchall()
        run_signature = stable_signature_rows(run_rows)

        run_shuffled = service.run(
            left_path=left_shuffled_path,
            right_path=right_shuffled_path,
            allow_many_to_one=False,
            allow_one_to_many=False,
            allow_many_to_many=False,
        )
        run_shuffled_rows = connection.execute(
            """
            SELECT left_id, right_id, status, reason_code, match_type, lineage_json
            FROM match_results
            WHERE job_id = ?
            ORDER BY COALESCE(left_id, ''), COALESCE(right_id, '')
            """,
            (run_shuffled.job_id,),
        ).fetchall()
    finally:
        connection.close()

    assert run_signature == stable_signature_rows(run_shuffled_rows)
    assert run_signature == stable_signature(list(in_memory_base.results))
    assert all(
        row["left_id"] in {"L-1", "L-2"} and row["status"] == "Unmatched" and json.loads(row["lineage_json"])["candidate_count"] == 0
        for row in run_rows
        if row["left_id"]
    )
    assert all(
        row["right_id"] in {"R-1", "R-2"}
        and row["status"] == "Unmatched"
        and row["reason_code"] == "MISSING_LEFT"
        and json.loads(row["lineage_json"])["candidate_count"] == 0
        for row in run_rows
        if not row["left_id"]
    )


def test_matching_invalid_amount_emits_invalid_amount_exception(tmp_path: Path) -> None:
    db_path = tmp_path / "invalid_amount_exception.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        output = service.match_records(
            left_records=[
                {"id": "L-1", "reference": "REF-100", "amount": "N/A", "date": "2026-01-01"},
            ],
            right_records=[
                {"id": "R-1", "reference": "REF-100", "amount": "50.00", "date": "2026-01-01"},
            ],
        )
    finally:
        connection.close()

    assert output.results[0]["status"] == "Invalid"
    assert any(item["reason_code"] == "INVALID_AMOUNT" for item in output.exceptions)
    assert all(row["status"] != "Matched" for row in output.results)
    for exception in output.exceptions:
        _assert_data_quality_exception_shape(exception)


def test_matching_missing_date_records_emit_invalid_date_exception(tmp_path: Path) -> None:
    db_path = tmp_path / "missing_date_exception.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        output = service.match_records(
            left_records=[
                {"id": "L-1", "reference": "REF-100", "amount": "50.00", "date": ""},
            ],
            right_records=[
                {"id": "R-1", "reference": "REF-100", "amount": "50.00", "date": "2026-01-01"},
            ],
        )
    finally:
        connection.close()

    assert output.results[0]["status"] == "Invalid"
    assert output.results[0]["reason_code"] == "MISSING_DATE"
    assert any(item["reason_code"] == "MISSING_DATE" for item in output.exceptions)
    for exception in output.exceptions:
        _assert_data_quality_exception_shape(exception)


def test_matching_invalid_record_flagged_when_explicit_record_invalid(tmp_path: Path) -> None:
    db_path = tmp_path / "invalid_record_exception.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        output = service.match_records(
            left_records=[
                {"id": "L-1", "reference": "REF-100", "amount": "50.00", "date": "2026-01-01", "valid": False},
            ],
            right_records=[
                {"id": "R-1", "reference": "REF-100", "amount": "50.00", "date": "2026-01-01"},
            ],
        )
    finally:
        connection.close()

    assert output.results[0]["status"] == "Invalid"
    assert output.results[0]["reason_code"] == "INVALID_RECORD"
    assert any(item["reason_code"] == "INVALID_RECORD" for item in output.exceptions)
    for exception in output.exceptions:
        _assert_data_quality_exception_shape(exception)


def test_matching_reference_mismatch_is_exposed_as_unmatched_without_exception(tmp_path: Path) -> None:
    db_path = tmp_path / "reference_mismatch_unmatched.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        output = service.match_records(
            left_records=[
                {"id": "L-1", "reference": "INV-001", "amount": "100.00", "date": "2026-01-01"},
                {"id": "L-2", "reference": "INV-002", "amount": "200.00", "date": "2026-01-01"},
            ],
            right_records=[
                {"id": "R-1", "reference": "INV-001", "amount": "100.00", "date": "2026-01-01"},
                {"id": "R-2", "reference": "INV-XXX", "amount": "200.00", "date": "2026-01-01"},
            ],
        )
    finally:
        connection.close()

    assert len(output.results) == 3
    unmatched = next(item for item in output.results if item["left_id"] == "L-2")
    assert unmatched["status"] == "Unmatched"
    assert unmatched["match_type"] == "unmatched"
    assert unmatched["reason_code"] == "MISSING_RIGHT"
    unmatched_right = next(item for item in output.results if item.get("right_id") == "R-2")
    assert unmatched_right["status"] == "Unmatched"
    assert unmatched_right["match_type"] == "unmatched_right"
    assert unmatched_right["reason_code"] == "MISSING_LEFT"
    assert output.exceptions == ()


def test_reference_normalization_enables_cross_format_matching(tmp_path: Path) -> None:
    left = "id,reference,amount,date\nL-1,INV-0001,100.00,2026-01-10\n"
    right = "id,reference,amount,date\nR-1,inv001,100.00,2026-01-10\n"

    _, matched = _run_match(tmp_path, left, right, run_name="normalize_ref")

    assert len(matched) == 1
    assert "normalization" in matched[0]["explanation"].lower()
    assert matched[0]["left_id"] == "L-1"
    assert matched[0]["right_id"] == "R-1"


def test_reference_normalization_rules_reject_invalid_configuration(tmp_path: Path) -> None:
    db_path = tmp_path / "invalid_ref_rules.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)

        with pytest.raises(
            PlatformError,
            match="reference_normalization_rules.case must be one of: upper, lower, none.",
        ):
            service.match_records(
                left_records=[{"id": "L-1", "reference": "REF-1", "amount": "1.00", "date": "2026-01-10"}],
                right_records=[{"id": "R-1", "reference": "REF-1", "amount": "1.00", "date": "2026-01-10"}],
                reference_normalization_rules={"case": "title"},
            )

        with pytest.raises(
            PlatformError,
            match="reference_normalization_rules.separator_normalizations must be a list of two-value string pairs.",
        ):
            service.match_records(
                left_records=[{"id": "L-2", "reference": "REF-2", "amount": "1.00", "date": "2026-01-10"}],
                right_records=[{"id": "R-2", "reference": "REF-2", "amount": "1.00", "date": "2026-01-10"}],
                reference_normalization_rules={"separator_normalizations": "BAD"},
            )
    finally:
        connection.close()


def test_reference_normalization_rules_reject_invalid_regex_normalization_pattern(tmp_path: Path) -> None:
    db_path = tmp_path / "invalid_ref_regex_rule.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)

        with pytest.raises(
            PlatformError,
            match="reference_normalization_rules.regex_normalizations\\[0\\] must be a valid regular expression",
        ):
            service.match_records(
                left_records=[{"id": "L-1", "reference": "REF-1", "amount": "1.00", "date": "2026-01-10"}],
                right_records=[{"id": "R-1", "reference": "REF-1", "amount": "1.00", "date": "2026-01-10"}],
                reference_normalization_rules={"regex_normalizations": [["[", "X"]]},
            )
    finally:
        connection.close()


def test_stable_ids_without_explicit_id_fields_are_deterministic(tmp_path: Path) -> None:
    left = "reference,amount,date\nINV 001,100.00,2026-01-10\nINV 002,200.00,2026-01-10\n"
    right = "reference,amount,date\ninv001,100.00,2026-01-10\ninv002,200.00,2026-01-10\n"
    _, matched_a = _run_match(
        tmp_path,
        left,
        right,
        left_id_field="__missing__",
        right_id_field="__missing__",
        run_name="stable_ids_a",
    )
    _, matched_b = _run_match(
        tmp_path,
        left,
        right,
        left_id_field="__missing__",
        right_id_field="__missing__",
        run_name="stable_ids_b",
    )

    assert all(record["left_id"] for record in matched_a)
    assert all(record["right_id"] for record in matched_b)
    assert {
        (record["left_id"], record["right_id"]) for record in matched_a
    } == {(record["left_id"], record["right_id"]) for record in matched_b}


def test_invalid_amount_rows_do_not_match_when_amount_is_not_numeric(tmp_path: Path) -> None:
    left = "id,reference,amount,date\nL-BAD,REF-INV,N/A?,2026-01-10\n"
    right = "id,reference,amount,date\nR-1,REF-INV,0.00,2026-01-10\n"

    result, matched = _run_match(tmp_path, left, right, run_name="invalid_amount")

    assert result.result_count == 1
    assert result.matched_count == 0
    assert not matched


def test_matching_persists_exact_decimal_difference_and_rejects_invalid_tolerance(tmp_path: Path) -> None:
    db_path = tmp_path / "decimal_difference.db"
    run_migrations(db_path)
    left = tmp_path / "decimal_left.csv"
    right = tmp_path / "decimal_right.csv"
    left.write_text(
        "id,reference,amount,date\nL-1,INV-DECIMAL,100.000000001,2026-01-10\n",
        encoding="utf-8",
    )
    right.write_text(
        "id,reference,amount,date\nR-1,INV-DECIMAL,100.000000000,2026-01-10\n",
        encoding="utf-8",
    )
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        result = service.run(left_path=left, right_path=right, amount_tolerance="0.000000001")
        row = connection.execute(
            "SELECT amount_difference_decimal, amount_difference FROM match_results WHERE job_id = ? AND status = 'Matched'",
            (result.job_id,),
        ).fetchone()
        assert row is not None
        assert row["amount_difference_decimal"] == "0.000000001"
        assert row["amount_difference"] == pytest.approx(0.000000001)
        rule = connection.execute("SELECT rule_json FROM match_rules WHERE job_id = ?", (result.job_id,)).fetchone()
        assert rule is not None
        assert '"amount_tolerance": "0.000000001"' in rule["rule_json"]
        with pytest.raises(PlatformError, match="Invalid financial amount"):
            service.run(left_path=left, right_path=right, amount_tolerance="not-a-number")
        with pytest.raises(PlatformError, match="non-negative"):
            service.run(left_path=left, right_path=right, amount_tolerance="-0.01")
    finally:
        connection.close()


def test_invalid_date_records_are_flagged_as_data_quality(tmp_path: Path) -> None:
    db_path = tmp_path / "invalid_dates.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    service = MatchingService(connection)
    try:
        output = service.match_records(
            left_records=[
                {"id": "L-INV", "reference": "INV-1", "amount": "100.00", "date": "2026-13-01"},
            ],
            right_records=[
                {"id": "R-INV", "reference": "INV-1", "amount": "100.00", "date": "2026-01-10"},
            ],
        )
    finally:
        connection.close()

    assert len(output.results) == 2
    invalid_left = next(result for result in output.results if result["left_id"] == "L-INV")
    assert invalid_left["status"] == "Invalid"
    assert invalid_left["match_type"] == "invalid"
    assert invalid_left["reason_code"] == "INVALID_DATE"
    assert any(item["reason_code"] == "INVALID_DATE" for item in output.exceptions)
    assert all(result["status"] != "Matched" for result in output.results)


def test_run_path_persists_invalid_left_and_unmatched_right_records(tmp_path: Path) -> None:
    db_path = tmp_path / "run_matching_invalid_and_unmatched_right.db"
    run_migrations(db_path)
    left = tmp_path / "left.csv"
    right = tmp_path / "right.csv"
    left.write_text(
        "id,reference,amount,date\n"
        "L-BAD,INV-001,100.00,2026-13-01\n"
        "L-OK,INV-OK,50.00,2026-01-10\n",
        encoding="utf-8",
    )
    right.write_text(
        "id,reference,amount,date\n"
        "R-BAD,INV-001,100.00,2026-01-10\n"
        "R-OK,INV-OK,50.00,2026-01-10\n",
        encoding="utf-8",
    )
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        result = service.run(left_path=left, right_path=right)
        rows = service.results(result.job_id)
    finally:
        connection.close()

    invalid_left = next(row for row in rows if row["left_id"] == "L-BAD")
    orphan_right = next(row for row in rows if row["right_id"] == "R-BAD")
    matched = next(row for row in rows if row["status"] == "Matched")

    assert invalid_left["match_type"] == "invalid"
    assert invalid_left["status"] == "Invalid"
    assert orphan_right["match_type"] == "unmatched_right"
    assert orphan_right["status"] == "Unmatched"
    assert matched["match_type"] == "deterministic"
    assert result.result_count == 2
    assert result.matched_count == 1


def test_matching_records_use_quantized_decimal_confidence(tmp_path: Path) -> None:
    db_path = tmp_path / "decimal_confidence.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        output = service.match_records(
            left_records=[
                {"id": "L-1", "reference": "INV-001", "amount": "100.00", "date": "2026-01-10"},
            ],
            right_records=[
                {"id": "R-1", "reference": "INV-001", "amount": "100.00", "date": "2026-01-10"},
            ],
        )
    finally:
        connection.close()

    matched = next(row for row in output.results if row["status"] == "Matched")
    confidence = Decimal(str(matched["confidence"])).quantize(Decimal("0.00"))
    assert confidence == Decimal("0.90")


def test_matching_explainability_payload_includes_alternatives_and_stable_selection_reason(tmp_path: Path) -> None:
    db_path = tmp_path / "match_explainability.db"
    run_migrations(db_path)
    left_records = [
        {"id": "L-MAIN", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
        {"id": "L-SECOND", "reference": "INV-200", "amount": "50.00", "date": "2026-01-10"},
    ]
    right_records = [
        {"id": "R-DRIFT", "reference": "INV-100", "amount": "100.01", "date": "2026-01-11"},
        {"id": "R-ON-TIME", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
        {"id": "R-2", "reference": "INV-200", "amount": "50.00", "date": "2026-01-10"},
    ]

    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        baseline = service.match_records(
            left_records=left_records,
            right_records=right_records,
            amount_tolerance=Decimal("0.05"),
        )
    finally:
        connection.close()

    baseline_main = next(row for row in baseline.results if row["left_id"] == "L-MAIN")
    baseline_lineage = baseline_main["lineage"]

    assert baseline_main["status"] == "Matched"
    assert baseline_main["right_id"] == "R-ON-TIME"
    assert baseline_lineage["candidate_count"] == 2
    assert baseline_lineage["selected_rank"] == 1
    assert baseline_main["confidence"] == baseline_lineage["selected_score"]
    assert isinstance(baseline_lineage["alternatives"], list)
    assert len(baseline_lineage["alternatives"]) == 1

    alternative = baseline_lineage["alternatives"][0]
    assert alternative["right_id"] == "R-DRIFT"
    for key in ("right_id", "score", "amount_difference", "date_difference_days", "explanation"):
        assert key in alternative

    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        shuffled = service.match_records(
            left_records=list(reversed(left_records)),
            right_records=list(reversed(right_records)),
            amount_tolerance=Decimal("0.05"),
        )
    finally:
        connection.close()

    shuffled_main = next(row for row in shuffled.results if row["left_id"] == "L-MAIN")
    shuffled_lineage = shuffled_main["lineage"]

    assert shuffled_main["right_id"] == baseline_main["right_id"]
    assert shuffled_main["status"] == "Matched"
    assert shuffled_main["confidence"] == baseline_main["confidence"]
    assert shuffled_lineage["candidate_count"] == baseline_lineage["candidate_count"]
    assert shuffled_lineage["selected_rank"] == baseline_lineage["selected_rank"]
    assert shuffled_lineage["selected_score"] == baseline_lineage["selected_score"]
    assert shuffled_lineage["alternatives"] == baseline_lineage["alternatives"]


def test_matching_in_memory_unmatched_right_explainability_includes_rejection_reason(tmp_path: Path) -> None:
    db_path = tmp_path / "match_unmatched_right_explainability.db"
    run_migrations(db_path)
    left_records = [
        {"id": "L-1", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
        {"id": "L-2", "reference": "INV-200", "amount": "50.00", "date": "2026-01-10"},
    ]
    right_records = [
        {"id": "R-1", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
        {"id": "R-UNMATCHED", "reference": "INV-300", "amount": "25.00", "date": "2026-01-11"},
    ]

    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        output = service.match_records(
            left_records=left_records,
            right_records=right_records,
            amount_tolerance=Decimal("0.05"),
        )
    finally:
        connection.close()

    unmatched_right = next(row for row in output.results if row.get("right_id") == "R-UNMATCHED")
    lineage = unmatched_right["lineage"]

    assert unmatched_right["status"] == "Unmatched"
    assert unmatched_right["match_type"] == "unmatched_right"
    assert unmatched_right["reason_code"] == "MISSING_LEFT"
    assert lineage["candidate_count"] == 0
    assert "rejection_reasons" in lineage
    assert lineage["rejection_reasons"] == ["No left-side candidate matched this right-side record."]


def test_matching_in_memory_unmatched_left_explainability_includes_rejection_reason(tmp_path: Path) -> None:
    db_path = tmp_path / "match_unmatched_left_explainability.db"
    run_migrations(db_path)
    left_records = [
        {"id": "L-1", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
        {"id": "L-UNMATCHED", "reference": "INV-300", "amount": "25.00", "date": "2026-01-11"},
    ]
    right_records = [
        {"id": "R-1", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
    ]

    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        output = service.match_records(
            left_records=left_records,
            right_records=right_records,
            amount_tolerance=Decimal("0.05"),
        )
    finally:
        connection.close()

    unmatched_left = next(row for row in output.results if row["left_id"] == "L-UNMATCHED")
    lineage = unmatched_left["lineage"]

    assert unmatched_left["status"] == "Unmatched"
    assert unmatched_left["match_type"] == "unmatched"
    assert unmatched_left["reason_code"] == "MISSING_RIGHT"
    assert lineage["candidate_count"] == 0
    assert "rejection_reasons" in lineage
    assert lineage["rejection_reasons"] == ["No indexed candidate met the configured rules."]


def test_matching_tie_breaking_is_deterministic_when_confidence_is_tied(tmp_path: Path) -> None:
    db_path = tmp_path / "match_tie_breaking.db"
    run_migrations(db_path)
    left_records = [
        {"id": "L-1", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
    ]
    right_records = [
        {"id": "R-B", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
        {"id": "R-A", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
    ]
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        baseline = service.match_records(
            left_records=left_records,
            right_records=right_records,
            amount_tolerance=Decimal("0"),
        )
        baseline_matched = next(row for row in baseline.results if row["status"] == "Matched")
        baseline_alternatives = baseline_matched["lineage"]["alternatives"]
    finally:
        connection.close()

    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        shuffled = service.match_records(
            left_records=left_records,
            right_records=list(reversed(right_records)),
            amount_tolerance=Decimal("0"),
        )
    finally:
        connection.close()

    shuffled_matched = next(row for row in shuffled.results if row["status"] == "Matched")

    assert shuffled_matched["right_id"] == baseline_matched["right_id"]
    assert shuffled_matched["confidence"] == baseline_matched["confidence"]
    assert shuffled_matched["lineage"]["selected_rank"] == baseline_matched["lineage"]["selected_rank"]
    assert shuffled_matched["lineage"]["selected_score"] == baseline_matched["lineage"]["selected_score"]
    assert len(shuffled_matched["lineage"]["alternatives"]) == len(baseline_alternatives)
    assert baseline_alternatives == shuffled_matched["lineage"]["alternatives"]


def test_matching_db_tie_breaking_is_deterministic_when_confidence_is_tied(tmp_path: Path) -> None:
    left_rows = "id,reference,amount,date\nL-1,INV-100,100.00,2026-01-10\n"
    right_rows = (
        "id,reference,amount,date\n"
        "R-B,INV-100,100.00,2026-01-10\n"
        "R-A,INV-100,100.00,2026-01-10\n"
    )
    baseline_db = tmp_path / "db_tie_a.db"
    run_migrations(baseline_db)
    left_file = tmp_path / "db_tie_left.csv"
    right_file = tmp_path / "db_tie_right.csv"
    left_file.write_text(left_rows, encoding="utf-8")
    right_file.write_text(right_rows, encoding="utf-8")
    db_connection = connect(baseline_db, require_exists=True)
    try:
        service = MatchingService(db_connection)
        baseline_result = service.run(
            left_path=left_file,
            right_path=right_file,
            allow_many_to_one=False,
            allow_one_to_many=False,
            allow_many_to_many=False,
        )
        baseline_rows = service.connection.execute(
            "SELECT left_id, right_id, status, lineage_json FROM match_results WHERE job_id = ? ORDER BY left_id, right_id",
            (baseline_result.job_id,),
        ).fetchall()
    finally:
        db_connection.close()

    right_rows_shuffled = (
        "id,reference,amount,date\n"
        "R-A,INV-100,100.00,2026-01-10\n"
        "R-B,INV-100,100.00,2026-01-10\n"
    )
    shuffled_db = tmp_path / "db_tie_b.db"
    run_migrations(shuffled_db)
    right_file_shuffled = tmp_path / "db_tie_right_shuffled.csv"
    right_file_shuffled.write_text(right_rows_shuffled, encoding="utf-8")
    shuffled_connection = connect(shuffled_db, require_exists=True)
    try:
        service = MatchingService(shuffled_connection)
        shuffled_result = service.run(
            left_path=left_file,
            right_path=right_file_shuffled,
            allow_many_to_one=False,
            allow_one_to_many=False,
            allow_many_to_many=False,
        )
        shuffled_rows = service.connection.execute(
            "SELECT left_id, right_id, status, lineage_json FROM match_results WHERE job_id = ? ORDER BY left_id, right_id",
            (shuffled_result.job_id,),
        ).fetchall()
    finally:
        shuffled_connection.close()

    baseline_matched = next(row for row in baseline_rows if row["status"] == "Matched")
    shuffled_matched = next(row for row in shuffled_rows if row["status"] == "Matched")
    baseline_lineage = json.loads(baseline_matched["lineage_json"])
    shuffled_lineage = json.loads(shuffled_matched["lineage_json"])

    assert baseline_matched["right_id"] == shuffled_matched["right_id"]
    assert baseline_lineage["selected_rank"] == shuffled_lineage["selected_rank"]
    assert baseline_lineage["selected_score"] == shuffled_lineage["selected_score"]
    assert baseline_lineage["alternatives"] == shuffled_lineage["alternatives"]


def test_matching_many_to_many_explainability_stability(tmp_path: Path) -> None:
    db_path = tmp_path / "many_to_many_explainability.db"
    run_migrations(db_path)
    left_records = [
        {"id": "L-1", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
        {"id": "L-2", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
    ]
    right_records = [
        {"id": "R-A", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
        {"id": "R-B", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
    ]

    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        baseline = service.match_records(
            left_records=left_records,
            right_records=right_records,
            allow_many_to_one=True,
            allow_one_to_many=True,
            allow_many_to_many=True,
        )
        baseline_rows = [row for row in baseline.results if row["status"] == "Matched"]
        baseline_signature = sorted(
            (
                row["left_id"],
                row["right_id"],
                row["match_type"],
                row["status"],
                row["lineage"]["selected_rank"],
            )
            for row in baseline_rows
        )
    finally:
        connection.close()

    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        shuffled = service.match_records(
            left_records=list(reversed(left_records)),
            right_records=list(reversed(right_records)),
            allow_many_to_one=True,
            allow_one_to_many=True,
            allow_many_to_many=True,
        )
        shuffled_rows = [row for row in shuffled.results if row["status"] == "Matched"]
        shuffled_signature = sorted(
            (
                row["left_id"],
                row["right_id"],
                row["match_type"],
                row["status"],
                row["lineage"]["selected_rank"],
            )
            for row in shuffled_rows
        )
    finally:
        connection.close()

    assert len([row for row in baseline.results if row["status"] == "Matched"]) == 4
    assert baseline_signature == shuffled_signature

    for row in baseline_rows:
        lineage = row["lineage"]
        assert lineage["candidate_count"] == 2
        assert lineage["selected_rank"] in {1, 2}
        assert isinstance(lineage["alternatives"], list)
        assert len(lineage["alternatives"]) >= 1

    assert len(set((row["left_id"], row["right_id"]) for row in baseline_rows)) == 4


def test_matching_many_to_many_disabled_rejects_competing_candidates_with_expected_rejection_narrative(tmp_path: Path) -> None:
    db_path = tmp_path / "many_to_many_disabled_rejection.db"
    run_migrations(db_path)
    left_records = [
        {"id": "L-1", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
        {"id": "L-2", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
    ]
    right_records = [
        {"id": "R-1", "reference": "INV-100", "amount": "100.00", "date": "2026-01-10"},
    ]

    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        output = service.match_records(
            left_records=left_records,
            right_records=right_records,
            allow_many_to_one=False,
            allow_one_to_many=False,
            allow_many_to_many=False,
        )
    finally:
        connection.close()

    matched = [row for row in output.results if row["status"] == "Matched"]
    unmatched_left = next(row for row in output.results if row["status"] == "Unmatched")
    matched_row = next(row for row in output.results if row["status"] == "Matched")

    assert len(matched) == 1
    assert unmatched_left["reason_code"] == "MISSING_RIGHT"
    assert unmatched_left["lineage"]["candidate_count"] == 1
    assert unmatched_left["lineage"]["rejection_reasons"] == ["No indexed candidate met the configured rules."]
    assert matched_row["match_type"] == "deterministic"
    assert matched_row["lineage"]["candidate_count"] == 1
    assert all(
        row["match_type"] != "unmatched_right" or row["status"] == "Unmatched"
        for row in output.results
    )


def test_matching_persists_reason_and_lineage_metadata_for_db_results(tmp_path: Path) -> None:
    db_path = tmp_path / "persisted_lineage.db"
    run_migrations(db_path)
    left = tmp_path / "left.csv"
    right = tmp_path / "right.csv"
    left.write_text(
        "id,reference,amount,date\n"
        "L-MATCH,INV-100,120.00,2026-01-10\n"
        "L-MISSING,INV-200,75.00,2026-01-10\n",
        encoding="utf-8",
    )
    right.write_text(
        "id,reference,amount,date\n"
        "R-MATCH,INV-100,120.00,2026-01-10\n"
        "R-UNMATCHED,INV-300,80.00,2026-01-11\n",
        encoding="utf-8",
    )

    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        result = service.run(
            left_path=left,
            right_path=right,
            allow_many_to_one=False,
            allow_one_to_many=False,
            allow_many_to_many=False,
        )
    finally:
        connection.close()

    connection = connect(db_path, require_exists=True)
    try:
        rows = connection.execute(
            """
            SELECT left_id, right_id, reason_code, match_type, status, lineage_json
            FROM match_results
            WHERE job_id = ?
            ORDER BY COALESCE(left_id, ''), COALESCE(right_id, '')
            """,
            (result.job_id,),
        ).fetchall()
    finally:
        connection.close()

    match_row = next(
        row
        for row in rows
        if str(row["left_id"]) == "L-MATCH" and str(row["right_id"]) == "R-MATCH"
    )
    unmatched_left = next(
        row
        for row in rows
        if str(row["left_id"]) == "L-MISSING" and (row["right_id"] == "" or row["right_id"] is None)
    )
    unmatched_right = next(row for row in rows if str(row["right_id"]) == "R-UNMATCHED")

    match_lineage = json.loads(match_row["lineage_json"])
    unmatched_left_lineage = json.loads(unmatched_left["lineage_json"])
    unmatched_right_lineage = json.loads(unmatched_right["lineage_json"])

    assert match_row["reason_code"] == ""
    assert match_row["status"] == "Matched"
    assert match_row["match_type"] == "deterministic"
    assert match_lineage["candidate_count"] >= 1
    assert match_lineage["selected_rank"] == 1
    assert "selected_score" in match_lineage
    assert "alternatives" in match_lineage

    assert unmatched_left["status"] == "Unmatched"
    assert unmatched_left["reason_code"] == "MISSING_RIGHT"
    assert unmatched_left_lineage["candidate_count"] >= 0
    assert unmatched_left_lineage["rejection_reasons"] == ["No indexed candidate met the configured rules."]

    assert unmatched_right["status"] == "Unmatched"
    assert unmatched_right["reason_code"] == "MISSING_LEFT"
    assert unmatched_right_lineage["candidate_count"] >= 0
    assert unmatched_right_lineage["rejection_reasons"] == ["No left-side candidate matched this right-side record."]


def test_matching_reference_normalization_rules_apply_and_persisted(tmp_path: Path) -> None:
    db_path = tmp_path / "reference_normalization_run.db"
    run_migrations(db_path)
    left = tmp_path / "left.csv"
    right = tmp_path / "right.csv"
    left.write_text(
        "id,reference,amount,date\n"
        "L-1,inv 001,120.00,2026-01-10\n",
        encoding="utf-8",
    )
    right.write_text(
        "id,reference,amount,date\n"
        "R-1,INV 1,120.00,2026-01-10\n",
        encoding="utf-8",
    )
    reference_normalization_rules = {
        "trim_whitespace": True,
        "remove_whitespace": True,
        "case": "upper",
    }

    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        result = service.run(
            left_path=left,
            right_path=right,
            reference_normalization_rules=reference_normalization_rules,
            amount_tolerance=Decimal("0"),
        )
    finally:
        connection.close()

    connection = connect(db_path, require_exists=True)
    try:
        job_rule = connection.execute(
            "SELECT rule_json FROM match_rules WHERE job_id = ?",
            (result.job_id,),
        ).fetchone()
        rows = connection.execute(
            "SELECT lineage_json, status FROM match_results WHERE job_id = ? ORDER BY left_id, right_id",
            (result.job_id,),
        ).fetchall()
    finally:
        connection.close()

    assert job_rule is not None
    job_rule_json = json.loads(str(job_rule["rule_json"] or "{}"))
    assert job_rule_json["reference_normalization_rules"]["trim_whitespace"] is True
    assert job_rule_json["reference_normalization_rules"]["remove_whitespace"] is True
    assert job_rule_json["reference_normalization_rules"]["case"] == "upper"

    matched = [row for row in rows if row["status"] == "Matched"]
    assert len(matched) == 1
    lineage = json.loads(matched[0]["lineage_json"] or "{}")
    assert lineage["selected_match"]["left_reference_original"] == "inv 001"
    assert lineage["selected_match"]["left_reference_normalized"] == "INV1"
    assert lineage["selected_match"]["right_reference_original"] == "INV 1"
    assert lineage["selected_match"]["right_reference_normalized"] == "INV1"


def test_platform_duplicate_identity_is_multiset_stable_and_source_location_is_unavailable(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "duplicate-identity.db"
    run_migrations(db_path)
    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        left = [
            {"id": "LEFT-DUP", "reference": "INV-DUP", "amount": "10.00", "date": "2026-07-25"},
            {"id": "LEFT-DUP", "reference": "INV-DUP", "amount": "10.00", "date": "2026-07-25"},
        ]
        right = [
            {"id": "RIGHT-DUP", "reference": "INV-DUP", "amount": "10.00", "date": "2026-07-25"},
            {"id": "RIGHT-DUP", "reference": "INV-DUP", "amount": "10.00", "date": "2026-07-25"},
        ]
        first = service.match_records(
            left_records=left,
            right_records=right,
            record_identity_policy=RECORD_IDENTITY_POLICY,
        )
        shuffled = service.match_records(
            left_records=list(reversed(left)),
            right_records=list(reversed(right)),
            record_identity_policy=RECORD_IDENTITY_POLICY,
        )
    finally:
        connection.close()

    assert first.results == shuffled.results
    assert first.record_identity_policy == RECORD_IDENTITY_POLICY
    matched = [item for item in first.results if item["status"] == "Matched"]
    assert len(matched) == 2
    left_lineages = [item["lineage"]["left_record"] for item in matched]
    right_lineages = [item["lineage"]["right_record"] for item in matched]
    assert len({item["record_instance_id"] for item in left_lineages}) == 2
    assert len({item["record_instance_id"] for item in right_lineages}) == 2
    assert {item["duplicate_ordinal"] for item in left_lineages} == {1, 2}
    assert {item["duplicate_count"] for item in left_lineages} == {2}
    assert {
        item["source_location"]["basis"]
        for item in left_lineages + right_lineages
    } == {"source-location-unavailable-v1"}
    assert all(item["source_location"]["position"] is None for item in left_lineages + right_lineages)


def test_local_csv_run_persists_current_identity_policy_and_physical_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "identity-policy.db"
    run_migrations(db_path)
    left_path = tmp_path / "identity-left.csv"
    right_path = tmp_path / "identity-right.csv"
    left_path.write_text(
        "id,reference,amount,date\n"
        "LEFT-DUP,INV-DUP,10.00,2026-07-25\n"
        "LEFT-DUP,INV-DUP,10.00,2026-07-25\n",
        encoding="utf-8",
    )
    right_path.write_text(
        "id,reference,amount,date\n"
        "RIGHT-DUP,INV-DUP,10.00,2026-07-25\n"
        "RIGHT-DUP,INV-DUP,10.00,2026-07-25\n",
        encoding="utf-8",
    )

    connection = connect(db_path, require_exists=True)
    try:
        service = MatchingService(connection)
        run = service.run(
            left_path=left_path,
            right_path=right_path,
            record_identity_policy=RECORD_IDENTITY_POLICY,
            idempotency_key="identity-policy-1",
        )
        with pytest.raises(PlatformError, match="different record identity policy"):
            service.run(
                left_path=left_path,
                right_path=right_path,
                record_identity_policy="row-order-occurrence-legacy-v0",
                idempotency_key="identity-policy-1",
            )
        rule_row = connection.execute(
            "SELECT rule_json FROM match_jobs WHERE id = ?",
            (run.job_id,),
        ).fetchone()
        result_rows = connection.execute(
            "SELECT lineage_json FROM match_results WHERE job_id = ? AND status = 'Matched'",
            (run.job_id,),
        ).fetchall()
        audit_metadata = json.loads(
            str(
                connection.execute(
                    "SELECT metadata_json FROM audit_events WHERE object_id = ? AND action = 'match_job_completed'",
                    (run.job_id,),
                ).fetchone()["metadata_json"]
            )
        )
        outbox_payload = json.loads(
            str(
                connection.execute(
                    "SELECT payload_json FROM outbox_events WHERE aggregate_id = ? AND event_type = 'match_job.completed'",
                    (run.job_id,),
                ).fetchone()["payload_json"]
            )
        )
    finally:
        connection.close()

    assert run.record_identity_policy == RECORD_IDENTITY_POLICY
    assert json.loads(str(rule_row["rule_json"]))["record_identity_policy"] == RECORD_IDENTITY_POLICY
    assert audit_metadata["record_identity_policy"] == RECORD_IDENTITY_POLICY
    assert outbox_payload["record_identity_policy"] == RECORD_IDENTITY_POLICY
    lineages = [json.loads(str(row["lineage_json"])) for row in result_rows]
    left_records = [lineage["left_record"] for lineage in lineages]
    right_records = [lineage["right_record"] for lineage in lineages]
    assert {item["source_location"]["row"] for item in left_records} == {2, 3}
    assert {item["source_location"]["row"] for item in right_records} == {2, 3}
    assert {
        item["source_location"]["basis"]
        for item in left_records + right_records
    } == {"tabular-header-offset-v1"}
