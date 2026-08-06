"""Bounded repeated durable-job soak profile.

The profile reuses the public durable-job load harness for several isolated
iterations and verifies that structural effects remain identical, queues drain,
and no duplicate partition effects appear.  Runtime and memory are observations
only; this is a small one-host soak contract rather than a production SLO.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from reconforge.benchmark.durable_job_load import (
    DurableJobLoadProfile,
    DurableJobLoadResult,
    default_profile,
    run_durable_job_load_profile,
    verify_load_manifest,
)

SOAK_SCHEMA_VERSION = 1
DEFAULT_SOAK_PROFILE_ID = "durable-job-soak/repeated-small-tier-v1"
DEFAULT_ITERATIONS = 3


@dataclass(frozen=True)
class DurableJobSoakProfile:
    """Declared repeated-load shape."""

    profile_id: str = DEFAULT_SOAK_PROFILE_ID
    iterations: int = DEFAULT_ITERATIONS
    load_profile: DurableJobLoadProfile | None = None

    def __post_init__(self) -> None:
        if not self.profile_id or len(self.profile_id) > 160:
            raise ValueError("profile_id must be a bounded non-empty value.")
        if isinstance(self.iterations, bool) or self.iterations < 2 or self.iterations > 32:
            raise ValueError("iterations must be between 2 and 32.")

    @property
    def declared_load_profile(self) -> DurableJobLoadProfile:
        return self.load_profile or default_profile(profile_id=f"{self.profile_id}/load")


@dataclass(frozen=True)
class DurableJobSoakResult:
    """Closed structural result of a repeated-load run."""

    schema_version: int
    profile_id: str
    iterations: int
    jobs_per_iteration: int
    partitions_per_job: int
    total_jobs: int
    total_partition_effects: int
    duplicate_partition_effects: int
    nonzero_queue_or_running_runs: int
    effect_digests: tuple[str, ...]
    aggregate_effect_digest: str
    observed_runtime_seconds: float
    observed_peak_memory_mb: float
    environment: dict[str, object]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        document = asdict(self)
        document["effect_digests"] = list(self.effect_digests)
        document["limitations"] = list(self.limitations)
        return document

    def to_manifest_text(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


LIMITATIONS = (
    "Each iteration uses an isolated SQLite database; this does not prove PostgreSQL or distributed queue soak.",
    "Runtime and peak memory vary by hardware and are observations, not throughput, capacity, SLO, or sizing claims.",
    "The declared repeated tier is bounded and reuses the load profile's limits; larger tiers and production workload diversity remain unverified.",
)


def _environment() -> dict[str, object]:
    import os

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": int(os.cpu_count() or 1),
    }


def _aggregate_digest(results: tuple[DurableJobLoadResult, ...]) -> str:
    payload = [
        {
            "effect_set_digest": result.effect_set_digest,
            "completed_jobs": result.completed_jobs,
            "committed_partition_effects": result.committed_partition_effects,
            "per_tenant_completions": result.per_tenant_completions,
        }
        for result in results
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def run_durable_job_soak_profile(
    database_path: Path,
    *,
    profile: DurableJobSoakProfile | None = None,
) -> DurableJobSoakResult:
    """Run repeated isolated load iterations and return the soak manifest."""

    declared = profile or DurableJobSoakProfile()
    load_profile = declared.declared_load_profile
    started = time.perf_counter()
    iteration_results: list[DurableJobLoadResult] = []
    for iteration in range(declared.iterations):
        iteration_path = database_path.with_name(f"{database_path.stem}-iteration-{iteration + 1:02d}.db")
        result = run_durable_job_load_profile(iteration_path, profile=load_profile)
        verify_load_manifest(result, profile=load_profile)
        iteration_results.append(result)
    results = tuple(iteration_results)
    runtime = round(time.perf_counter() - started, 4)
    return DurableJobSoakResult(
        schema_version=SOAK_SCHEMA_VERSION,
        profile_id=declared.profile_id,
        iterations=declared.iterations,
        jobs_per_iteration=load_profile.jobs,
        partitions_per_job=load_profile.partitions_per_job,
        total_jobs=sum(result.completed_jobs for result in results),
        total_partition_effects=sum(result.committed_partition_effects for result in results),
        duplicate_partition_effects=sum(result.duplicate_partition_effects for result in results),
        nonzero_queue_or_running_runs=sum(
            result.final_queue_depth != 0 or result.final_running_depth != 0 for result in results
        ),
        effect_digests=tuple(result.effect_set_digest for result in results),
        aggregate_effect_digest=_aggregate_digest(results),
        observed_runtime_seconds=runtime,
        observed_peak_memory_mb=max(result.observed_peak_memory_mb for result in results),
        environment=_environment(),
        limitations=LIMITATIONS,
    )


def verify_soak_manifest(result: DurableJobSoakResult, *, profile: DurableJobSoakProfile) -> None:
    """Fail closed unless every repeated iteration preserves structural invariants."""

    load_profile = profile.declared_load_profile
    if result.schema_version != SOAK_SCHEMA_VERSION or result.profile_id != profile.profile_id:
        raise AssertionError("unsupported or misbound soak manifest")
    if result.iterations != profile.iterations:
        raise AssertionError("soak iteration count changed")
    if result.total_jobs != profile.iterations * load_profile.jobs:
        raise AssertionError("soak jobs did not complete exactly once")
    if result.total_partition_effects != profile.iterations * load_profile.declared_partition_effects:
        raise AssertionError("soak partition effects are incomplete")
    if result.duplicate_partition_effects != 0 or result.nonzero_queue_or_running_runs != 0:
        raise AssertionError("soak left duplicate effects or active queue state")
    if len(set(result.effect_digests)) != 1:
        raise AssertionError("soak effect digest changed across iterations")
    if len(result.aggregate_effect_digest) != 64:
        raise AssertionError("soak aggregate digest is invalid")


__all__ = [
    "DEFAULT_ITERATIONS",
    "DEFAULT_SOAK_PROFILE_ID",
    "LIMITATIONS",
    "SOAK_SCHEMA_VERSION",
    "DurableJobSoakProfile",
    "DurableJobSoakResult",
    "run_durable_job_soak_profile",
    "verify_soak_manifest",
]
