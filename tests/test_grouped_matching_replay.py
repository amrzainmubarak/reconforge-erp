from __future__ import annotations

from pathlib import Path

import pytest

from reconforge.benchmark.grouped_matching_replay import (
    GroupedMatchingReplayProfile,
    run_grouped_matching_replay_fault_matrix,
    run_grouped_matching_replay_profile,
    verify_grouped_matching_replay,
)


def test_grouped_matching_replay_resumes_without_duplicate_and_preserves_parity(tmp_path: Path) -> None:
    result = run_grouped_matching_replay_profile(tmp_path / "replay.db")

    verify_grouped_matching_replay(result)
    assert result.persisted_effect_digest == result.expected_effect_digest
    assert result.cross_engine_equal is True
    assert result.mutation_guard_passed is True


def test_grouped_matching_replay_digest_is_reproducible(tmp_path: Path) -> None:
    first = run_grouped_matching_replay_profile(tmp_path / "first.db")
    second = run_grouped_matching_replay_profile(tmp_path / "second.db")

    assert first.persisted_effect_digest == second.persisted_effect_digest
    assert first.expected_effect_digest == second.expected_effect_digest


def test_grouped_matching_replay_rejects_fault_after_final_partition() -> None:
    with pytest.raises(ValueError, match="leave at least one partition"):
        GroupedMatchingReplayProfile(fault_after_partition=4)


def test_grouped_matching_replay_requires_positive_retry_ceiling() -> None:
    with pytest.raises(ValueError, match="positive"):
        GroupedMatchingReplayProfile(retry_ceiling=0)


def test_grouped_matching_replay_documents_non_claim_boundary(tmp_path: Path) -> None:
    result = run_grouped_matching_replay_profile(tmp_path / "boundary.db")
    assert any("not a" in limitation or "not" in limitation for limitation in result.limitations)


def test_grouped_matching_replay_fault_matrix_covers_every_resumable_checkpoint(tmp_path: Path) -> None:
    results = run_grouped_matching_replay_fault_matrix(tmp_path / "matrix")

    assert [result.fault_after_partition for result in results] == [1, 2, 3]
    assert all(result.retry_count == 1 for result in results)
    assert all(result.duplicate_effects == 0 for result in results)
    assert all(result.cross_engine_equal and result.mutation_guard_passed for result in results)
    assert all(result.queue_depth == 0 and result.running_depth == 0 for result in results)
    assert len({result.persisted_effect_digest for result in results}) == 1
    assert len({result.expected_effect_digest for result in results}) == 1
