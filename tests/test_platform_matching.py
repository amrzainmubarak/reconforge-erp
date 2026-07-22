from __future__ import annotations

from itertools import permutations
from pathlib import Path

from reconforge.db import connect, run_migrations
from reconforge.platform.matching import MatchingService


def _run_match(
    tmp_path: Path,
    left_rows: str,
    right_rows: str,
    *,
    allow_many_to_one: bool = False,
    run_name: str = "base",
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
            allow_many_to_one=allow_many_to_one,
        )
        matched = [record for record in service.results(result.job_id) if record["status"] == "Matched"]
    finally:
        connection.close()
    return result, matched


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
