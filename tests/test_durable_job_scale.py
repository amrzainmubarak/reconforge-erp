from __future__ import annotations

from reconforge.benchmark.durable_job_scale import (
    HUNDRED_K_BUSY_TIMEOUT_SECONDS,
    HUNDRED_K_EFFECTS,
    HUNDRED_K_JOBS,
    HUNDRED_K_PARTITIONS_PER_JOB,
    HUNDRED_K_PROFILE_ID,
    HUNDRED_K_TENANTS,
    HUNDRED_K_WORKERS,
    TEN_K_EFFECTS,
    TEN_K_JOBS,
    TEN_K_PARTITIONS_PER_JOB,
    TEN_K_PROFILE_ID,
    TEN_K_TENANTS,
    TEN_K_WORKERS,
    hundred_k_profile,
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


def test_hundred_k_profile_is_partitioned_and_fair() -> None:
    profile = hundred_k_profile()
    assert profile.profile_id == HUNDRED_K_PROFILE_ID
    assert profile.workers == HUNDRED_K_WORKERS == 16
    assert profile.jobs == HUNDRED_K_JOBS == 10_000
    assert profile.partitions_per_job == HUNDRED_K_PARTITIONS_PER_JOB == 10
    assert profile.tenants == HUNDRED_K_TENANTS == 4
    assert profile.lease_seconds == 600
    assert profile.busy_timeout_seconds == HUNDRED_K_BUSY_TIMEOUT_SECONDS == 300
    assert profile.declared_partition_effects == HUNDRED_K_EFFECTS == 100_000
    assert profile.workers % profile.tenants == 0


def test_hundred_k_profile_is_not_silently_a_different_scale() -> None:
    profile = hundred_k_profile()
    assert profile.declared_partition_effects == profile.jobs * profile.partitions_per_job
    assert profile.profile_id.endswith("100k-tier-v1")
