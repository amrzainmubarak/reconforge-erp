from pathlib import Path

from reconforge.benchmark.durable_job_backpressure import (
    BACKPRESSURE_PROFILE_ID,
    run_backpressure_profile,
    verify_backpressure_result,
)


def test_backpressure_caps_queue_and_preserves_effects(tmp_path: Path) -> None:
    result = run_backpressure_profile(tmp_path / "backpressure.db", max_queued_jobs=8)
    verify_backpressure_result(result)
    assert result.profile_id == BACKPRESSURE_PROFILE_ID
    assert result.observed_max_queue_depth <= 8
    assert result.completed_jobs == 64
    assert result.committed_partition_effects == 256
    assert result.duplicate_partition_effects == 0


def test_backpressure_manifest_is_deterministic_in_structural_fields(tmp_path: Path) -> None:
    first = run_backpressure_profile(tmp_path / "first.db", jobs=24, max_queued_jobs=4)
    second = run_backpressure_profile(tmp_path / "second.db", jobs=24, max_queued_jobs=4)
    verify_backpressure_result(first)
    verify_backpressure_result(second)
    assert first.effect_set_digest == second.effect_set_digest
    assert first.manifest_digest == second.manifest_digest

