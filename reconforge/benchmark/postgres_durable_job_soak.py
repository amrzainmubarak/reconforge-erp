"""Bounded repeated PostgreSQL durable-job soak profile.

The profile reuses the PostgreSQL multi-worker scale harness for several
isolated tenant lanes in one disposable database.  Job identifiers are kept
stable across iterations while tenant identifiers are unique, which makes the
effect-set digest a deterministic replay signal without violating the
tenant-scoped primary key.  Runtime is an observation only; this is not a
capacity, SLO, HA, or production-soak claim.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from reconforge.application.jobs import DurableJobApplicationService
from reconforge.benchmark.postgres_durable_job_scale import (
    PostgresDurableJobScaleProfile,
    PostgresDurableJobScaleResult,
    run_postgres_durable_job_scale_profile,
    verify_postgres_durable_job_scale_result,
)
from reconforge.benchmark.postgres_durable_job_scale import default_profile as default_scale_profile

POSTGRES_SOAK_SCHEMA_VERSION = 1
DEFAULT_POSTGRES_SOAK_PROFILE_ID = "postgres-durable-job-soak/repeated-small-tier-v1"
DEFAULT_POSTGRES_SOAK_ITERATIONS = 3


@dataclass(frozen=True)
class PostgresDurableJobSoakProfile:
    """Declared repeated PostgreSQL workload shape."""

    profile_id: str = DEFAULT_POSTGRES_SOAK_PROFILE_ID
    iterations: int = DEFAULT_POSTGRES_SOAK_ITERATIONS
    scale_profile: PostgresDurableJobScaleProfile | None = None

    def __post_init__(self) -> None:
        if not self.profile_id or len(self.profile_id) > 160:
            raise ValueError("profile_id must be a bounded non-empty value")
        if isinstance(self.iterations, bool) or self.iterations < 2 or self.iterations > 16:
            raise ValueError("iterations must be between 2 and 16")

    @property
    def declared_scale_profile(self) -> PostgresDurableJobScaleProfile:
        return self.scale_profile or default_scale_profile()


@dataclass(frozen=True)
class PostgresDurableJobSoakResult:
    """Closed structural result for a repeated PostgreSQL run."""

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
    "Each iteration uses unique synthetic PostgreSQL tenant lanes in one disposable database host; this does not prove distributed or multi-host soak.",
    "Observed runtime is hardware/load dependent and is not a throughput, capacity, SLO, RPO/RTO, or sizing claim.",
    "The repeated tier is bounded to the declared PostgreSQL scale profile; larger tiers, queue HA, automatic failover, host loss, and production workload diversity remain unverified.",
)


def _environment() -> dict[str, object]:
    import os

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": int(os.cpu_count() or 1),
        "database": "PostgreSQL",
    }


def _aggregate_digest(results: Sequence[PostgresDurableJobScaleResult]) -> str:
    payload = [
        {
            "effect_set_digest": result.effect_set_digest,
            "completed_jobs": result.completed_jobs,
            "committed_partition_effects": result.committed_partition_effects,
            "per_tenant_completions": result.per_tenant_completions,
        }
        for result in results
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def run_postgres_durable_job_soak_profile(
    connection_factory: Any,
    application: DurableJobApplicationService,
    tenant_ids_by_iteration: Sequence[Sequence[str]],
    *,
    profile: PostgresDurableJobSoakProfile | None = None,
    id_prefix: str = "PGSOAK",
) -> PostgresDurableJobSoakResult:
    """Run repeated isolated PostgreSQL tenant lanes with stable job IDs."""

    declared = profile or PostgresDurableJobSoakProfile()
    scale = declared.declared_scale_profile
    tenant_sets = tuple(tuple(str(value) for value in tenants) for tenants in tenant_ids_by_iteration)
    if len(tenant_sets) != declared.iterations:
        raise ValueError("tenant_ids_by_iteration must contain one lane set per iteration")
    flattened = [tenant for tenants in tenant_sets for tenant in tenants]
    if any(len(tenants) != scale.tenants or len(set(tenants)) != len(tenants) for tenants in tenant_sets):
        raise ValueError("each iteration must contain exactly the unique declared tenant lanes")
    if len(set(flattened)) != len(flattened):
        raise ValueError("tenant lanes must be unique across iterations")
    if not id_prefix or len(id_prefix) > 80:
        raise ValueError("id_prefix must be a bounded non-empty value")

    started = time.perf_counter()
    iteration_results: list[PostgresDurableJobScaleResult] = []
    for tenants in tenant_sets:
        result = run_postgres_durable_job_scale_profile(
            connection_factory,
            application,
            tenants,
            profile=scale,
            id_prefix=id_prefix,
        )
        verify_postgres_durable_job_scale_result(result, profile=scale)
        iteration_results.append(result)
    runtime = round(time.perf_counter() - started, 4)
    results = tuple(iteration_results)
    return PostgresDurableJobSoakResult(
        schema_version=POSTGRES_SOAK_SCHEMA_VERSION,
        profile_id=declared.profile_id,
        iterations=declared.iterations,
        jobs_per_iteration=scale.jobs,
        partitions_per_job=scale.partitions_per_job,
        total_jobs=sum(result.completed_jobs for result in results),
        total_partition_effects=sum(result.committed_partition_effects for result in results),
        duplicate_partition_effects=sum(result.duplicate_partition_effects for result in results),
        nonzero_queue_or_running_runs=sum(
            result.final_queue_depth != 0 or result.final_running_depth != 0 for result in results
        ),
        effect_digests=tuple(result.effect_set_digest for result in results),
        aggregate_effect_digest=_aggregate_digest(results),
        observed_runtime_seconds=runtime,
        environment=_environment(),
        limitations=LIMITATIONS,
    )


def verify_postgres_durable_job_soak_result(
    result: PostgresDurableJobSoakResult,
    *,
    profile: PostgresDurableJobSoakProfile,
) -> None:
    """Fail closed unless every repeated iteration preserves invariants."""

    scale = profile.declared_scale_profile
    if result.schema_version != POSTGRES_SOAK_SCHEMA_VERSION or result.profile_id != profile.profile_id:
        raise AssertionError("unsupported or misbound PostgreSQL soak manifest")
    if result.iterations != profile.iterations:
        raise AssertionError("PostgreSQL soak iteration count changed")
    if result.total_jobs != profile.iterations * scale.jobs:
        raise AssertionError("PostgreSQL soak jobs did not complete exactly once")
    if result.total_partition_effects != profile.iterations * scale.declared_partition_effects:
        raise AssertionError("PostgreSQL soak partition effects are incomplete")
    if result.duplicate_partition_effects != 0 or result.nonzero_queue_or_running_runs != 0:
        raise AssertionError("PostgreSQL soak left duplicate effects or active queue state")
    if len(result.effect_digests) != profile.iterations or len(set(result.effect_digests)) != 1:
        raise AssertionError("PostgreSQL soak effect digest changed across iterations")
    if len(result.aggregate_effect_digest) != 64:
        raise AssertionError("PostgreSQL soak aggregate digest is invalid")


__all__ = [
    "DEFAULT_POSTGRES_SOAK_ITERATIONS",
    "DEFAULT_POSTGRES_SOAK_PROFILE_ID",
    "LIMITATIONS",
    "POSTGRES_SOAK_SCHEMA_VERSION",
    "PostgresDurableJobSoakProfile",
    "PostgresDurableJobSoakResult",
    "run_postgres_durable_job_soak_profile",
    "verify_postgres_durable_job_soak_result",
]
