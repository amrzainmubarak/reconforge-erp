from __future__ import annotations

from reconforge.benchmark.durable_job_scale import (
    TEN_K_EFFECTS,
    TEN_K_JOBS,
    TEN_K_PARTITIONS_PER_JOB,
    TEN_K_PROFILE_ID,
    TEN_K_TENANTS,
    TEN_K_WORKERS,
    ten_k_profile,
)


def test_ten_k_profile_is_partitioned_and_fair() -> None:
    profile = ten_k_profile()
    assert profile.profile_id == TEN_K_PROFILE_ID
    assert profile.workers == TEN_K_WORKERS == 16
    assert profile.jobs == TEN_K_JOBS == 1000
    assert profile.partitions_per_job == TEN_K_PARTITIONS_PER_JOB == 10
    assert profile.tenants == TEN_K_TENANTS == 4
    assert profile.declared_partition_effects == TEN_K_EFFECTS == 10_000
    assert profile.workers % profile.tenants == 0


def test_ten_k_profile_is_not_silently_a_different_scale() -> None:
    profile = ten_k_profile()
    assert profile.declared_partition_effects == profile.jobs * profile.partitions_per_job
    assert profile.profile_id.endswith("10k-tier-v1")

