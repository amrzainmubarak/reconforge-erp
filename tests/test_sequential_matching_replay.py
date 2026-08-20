from __future__ import annotations

from pathlib import Path

import pytest

from reconforge.benchmark.sequential_matching_replay import (
    SequentialMatchingReplayProfile,
    run_sequential_matching_replay_fault_matrix,
    run_sequential_matching_replay_profile,
    verify_sequential_matching_replay,
)


def test_sequential_matching_replay_resumes_without_duplicates_and_preserves_adapter_parity(tmp_path: Path) -> None:
    result = run_sequential_matching_replay_profile(tmp_path / "replay.db")

    verify_sequential_matching_replay(result)
    assert result.persisted_effect_digest == result.expected_effect_digest
    assert result.adapter_parity is True
    assert result.mutation_guard_passed is True


def test_sequential_matching_replay_digest_is_reproducible(tmp_path: Path) -> None:
    first = run_sequential_matching_replay_profile(tmp_path / "first.db")
    second = run_sequential_matching_replay_profile(tmp_path / "second.db")

    assert first.persisted_effect_digest == second.persisted_effect_digest
    assert first.expected_effect_digest == second.expected_effect_digest


def test_sequential_matching_replay_fault_matrix_covers_each_resumable_partition(tmp_path: Path) -> None:
    results = run_sequential_matching_replay_fault_matrix(tmp_path / "matrix")

    assert [result.fault_after_partition for result in results] == [1, 2]
    assert all(result.retry_count == 1 for result in results)
    assert all(result.duplicate_effects == 0 for result in results)
    assert all(result.adapter_parity and result.mutation_guard_passed for result in results)
    assert all(result.queue_depth == 0 and result.running_depth == 0 for result in results)
    assert len({result.persisted_effect_digest for result in results}) == 1
    assert len({result.expected_effect_digest for result in results}) == 1


def test_sequential_matching_replay_rejects_fault_after_final_partition() -> None:
    with pytest.raises(ValueError, match="leave at least one partition"):
        SequentialMatchingReplayProfile(fault_after_partition=3)


def test_sequential_matching_replay_requires_positive_retry_ceiling() -> None:
    with pytest.raises(ValueError, match="positive"):
        SequentialMatchingReplayProfile(retry_ceiling=0)


def test_sequential_matching_replay_documents_non_claim_boundary(tmp_path: Path) -> None:
    result = run_sequential_matching_replay_profile(tmp_path / "boundary.db")
    assert any("not" in limitation for limitation in result.limitations)
