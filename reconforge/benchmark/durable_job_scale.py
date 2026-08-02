"""Declared 10K and 100K durable-job scale profiles.

The profile reuses the existing generation-fenced SQLite durable-job worker
contract.  It is intentionally a partitioned workload (1,000 jobs x 10
partitions) so the declared figures count committed business effects, not rows
inserted into a synthetic table. Results remain hardware-scoped evidence; they
do not imply PostgreSQL, soak, HA, or production capacity.
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

HUNDRED_K_PROFILE_ID = "durable-job-load/100k-tier-v1"
# Keep the writer contention at the proven 10K worker width; increasing it to
# 32 caused a reproducible SQLite database-lock failure in the first 100K run.
HUNDRED_K_WORKERS = 16
HUNDRED_K_JOBS = 10_000
HUNDRED_K_PARTITIONS_PER_JOB = 10
HUNDRED_K_TENANTS = 4
# The 100K SQLite contention profile needs a bounded lease longer than the
# observed single-job critical section; this is a test declaration, not an
# operational default or an SLO.
HUNDRED_K_LEASE_SECONDS = 600
HUNDRED_K_BUSY_TIMEOUT_SECONDS = 300
HUNDRED_K_EFFECTS = HUNDRED_K_JOBS * HUNDRED_K_PARTITIONS_PER_JOB


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


def hundred_k_profile() -> DurableJobLoadProfile:
    """Return the immutable declaration for the 100K effect tier."""

    return DurableJobLoadProfile(
        profile_id=HUNDRED_K_PROFILE_ID,
        workers=HUNDRED_K_WORKERS,
        jobs=HUNDRED_K_JOBS,
        partitions_per_job=HUNDRED_K_PARTITIONS_PER_JOB,
        tenants=HUNDRED_K_TENANTS,
        lease_seconds=HUNDRED_K_LEASE_SECONDS,
        busy_timeout_seconds=HUNDRED_K_BUSY_TIMEOUT_SECONDS,
    )


def run_hundred_k_profile(database_path: Path) -> DurableJobLoadResult:
    """Run the declared 100K effect tier against a disposable SQLite database."""

    profile = hundred_k_profile()
    result = run_durable_job_load_profile(database_path, profile=profile)
    verify_hundred_k_result(result)
    return result


def verify_hundred_k_result(result: DurableJobLoadResult) -> None:
    """Verify the structural invariants required for the 100K evidence."""

    profile = hundred_k_profile()
    verify_load_manifest(result, profile=profile)
    if result.declared_partition_effects != HUNDRED_K_EFFECTS:
        raise AssertionError("100K profile must declare exactly 100,000 partition effects.")
    if result.committed_partition_effects != HUNDRED_K_EFFECTS:
        raise AssertionError("100K profile did not commit exactly 100,000 partition effects.")
    if result.completed_jobs != HUNDRED_K_JOBS:
        raise AssertionError("100K profile did not complete all declared jobs.")
