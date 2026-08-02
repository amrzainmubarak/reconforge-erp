"""Declared 10K durable-job scale profile.

The profile reuses the existing generation-fenced SQLite durable-job worker
contract.  It is intentionally a partitioned workload (1,000 jobs x 10
partitions) so the 10K figure counts committed business effects, not rows
inserted into a synthetic table.  The result remains hardware-scoped evidence;
it does not imply PostgreSQL, soak, HA, or production capacity.
"""

from __future__ import annotations

from pathlib import Path

from reconforge.benchmark.durable_job_load import (
    DurableJobLoadProfile,
    DurableJobLoadResult,
    run_durable_job_load_profile,
    verify_load_manifest,
)

TEN_K_PROFILE_ID = "durable-job-load/10k-tier-v1"
TEN_K_WORKERS = 16
TEN_K_JOBS = 1000
TEN_K_PARTITIONS_PER_JOB = 10
TEN_K_TENANTS = 4
TEN_K_LEASE_SECONDS = 60
TEN_K_EFFECTS = TEN_K_JOBS * TEN_K_PARTITIONS_PER_JOB


def ten_k_profile() -> DurableJobLoadProfile:
    """Return the immutable declaration for the published 10K tier."""

    return DurableJobLoadProfile(
        profile_id=TEN_K_PROFILE_ID,
        workers=TEN_K_WORKERS,
        jobs=TEN_K_JOBS,
        partitions_per_job=TEN_K_PARTITIONS_PER_JOB,
        tenants=TEN_K_TENANTS,
        lease_seconds=TEN_K_LEASE_SECONDS,
    )


def run_ten_k_profile(database_path: Path) -> DurableJobLoadResult:
    """Run the declared 10K tier against a disposable SQLite database."""

    profile = ten_k_profile()
    result = run_durable_job_load_profile(database_path, profile=profile)
    verify_ten_k_result(result)
    return result


def verify_ten_k_result(result: DurableJobLoadResult) -> None:
    """Verify the structural invariants required for the 10K evidence."""

    profile = ten_k_profile()
    verify_load_manifest(result, profile=profile)
    if result.declared_partition_effects != TEN_K_EFFECTS:
        raise AssertionError("10K profile must declare exactly 10,000 partition effects.")
    if result.committed_partition_effects != TEN_K_EFFECTS:
        raise AssertionError("10K profile did not commit exactly 10,000 partition effects.")
    if result.completed_jobs != TEN_K_JOBS:
        raise AssertionError("10K profile did not complete all declared jobs.")

