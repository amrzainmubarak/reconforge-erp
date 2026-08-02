from __future__ import annotations

from pathlib import Path

import pytest

from reconforge.benchmark.grouped_matching_replay import (
    GroupedMatchingReplayProfile,
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
