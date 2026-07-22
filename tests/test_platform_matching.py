from __future__ import annotations

from pathlib import Path

from reconforge.db import connect, run_migrations
from reconforge.platform.matching import MatchingService


def _run_match(tmp_path: Path, left_rows: str, right_rows: str, *, allow_many_to_one: bool = False):
    db_path = tmp_path / "operations.db"
    run_migrations(db_path)

    left = tmp_path / "left.csv"
    right = tmp_path / "right.csv"
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
    left = "\n".join(left_rows) + "\n"
    left_shuffled = "\n".join(reversed(left_rows)) + "\n"
    right = (
        "id,reference,amount,date\n"
        "R-B,REF-INV,100.00,2026-01-10\n"
        "R-A,REF-INV,100.00,2026-01-10\n"
    )
    _, matched_a = _run_match(tmp_path, left, right, allow_many_to_one=False)
    _, matched_b = _run_match(tmp_path / "shuffled", left_shuffled, right, allow_many_to_one=False)

    matched_pairs_a = {(row["left_id"], row["right_id"]) for row in matched_a}
    matched_pairs_b = {(row["left_id"], row["right_id"]) for row in matched_b}
    assert matched_pairs_a == matched_pairs_b
    assert len(matched_a) == 2


def test_matching_allows_many_to_one_when_enabled(tmp_path: Path) -> None:
    left = (
        "id,reference,amount,date\n"
        "L-1,REF-INV,100.00,2026-01-10\n"
        "L-2,REF-INV,100.00,2026-01-10\n"
    )
    right = "id,reference,amount,date\nR-1,REF-INV,100.00,2026-01-10\n"

    one_to_one_result, one_to_one_matched = _run_match(tmp_path / "one_to_one", left, right, allow_many_to_one=False)
    many_to_one_result, many_to_one_matched = _run_match(tmp_path / "many_to_one", left, right, allow_many_to_one=True)

    assert one_to_one_result.matched_count == 1
    assert len(one_to_one_matched) == 1
    assert many_to_one_result.matched_count == 2
    assert len(many_to_one_matched) == 2
    assert len({row["right_id"] for row in many_to_one_matched}) == 1
