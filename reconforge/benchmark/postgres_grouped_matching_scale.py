"""Bounded PostgreSQL multi-worker scale profile for grouped matching.

The profile exercises the real PostgreSQL reconciliation worker, streamed
hard-key partitions, checkpoint commits, tenant RLS, and concurrent run
leases. It intentionally reports runtime as an observation rather than a
throughput or production-capacity claim.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

from reconforge.infrastructure.postgres import ConnectionFactory, PostgresTenantBoundary
from reconforge.infrastructure.postgres_reconciliation import PostgresReconciliationRepository
from reconforge.workers.postgres_grouped_matching import PostgresGroupedMatchingAdapter
from reconforge.workers.postgres_reconciliation import (
    PostgresReconciliationWorker,
    PostgresReconciliationWorkerSettings,
)

POSTGRES_GROUPED_SCALE_SCHEMA_VERSION = 1
_MODES = ("one-to-many", "many-to-one", "many-to-many", "portfolio", "fx-many-to-one")
_MODE_RESULT_ROWS = {
    "one-to-many": 2,
    "many-to-one": 2,
    "many-to-many": 4,
    "portfolio": 2,
    "fx-many-to-one": 2,
}


@dataclass(frozen=True)
class PostgresGroupedMatchingScaleProfile:
    """Declared shape for one bounded concurrent PostgreSQL run."""

    profile_id: str
    workers: int
    runs: int
    partitions_per_run: int = 2
    batch_size: int = 1
    lease_seconds: int = 60
    modes: tuple[str, ...] = _MODES

    def __post_init__(self) -> None:
        if not 1 <= self.workers <= 64:
            raise ValueError("workers must be between 1 and 64")
        if not 1 <= self.runs <= 1_000:
            raise ValueError("runs must be between 1 and 1000")
        if not 1 <= self.partitions_per_run <= 32:
            raise ValueError("partitions_per_run must be between 1 and 32")
        if not 1 <= self.batch_size <= 1_000 or self.lease_seconds < 1:
            raise ValueError("batch_size or lease_seconds is outside the supported range")
        if tuple(self.modes) != _MODES:
            raise ValueError("the bounded profile must retain all declared grouped modes")

    @property
    def declared_partitions(self) -> int:
        return self.runs * self.partitions_per_run

    @property
    def expected_result_rows(self) -> int:
        return sum(_MODE_RESULT_ROWS[mode] for mode in self.modes) * (
            self.runs // len(self.modes)
        ) * self.partitions_per_run + sum(
            _MODE_RESULT_ROWS[self.modes[index % len(self.modes)]]
            for index in range(self.runs % len(self.modes))
        ) * self.partitions_per_run


@dataclass(frozen=True)
class PostgresGroupedMatchingScaleResult:
    schema_version: int
    profile_id: str
    workers: int
    runs: int
    partitions_per_run: int
    declared_partitions: int
    completed_runs: int
    completed_partitions: int
    result_rows: int
    expected_result_rows: int
    duplicate_result_identities: int
    failed_runs: int
    final_active_runs: int
    per_mode_completed: dict[str, int]
    effect_set_digest: str
    observed_runtime_seconds: float
    environment: dict[str, object]
    manifest_digest: str
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        document = asdict(self)
        document["limitations"] = list(self.limitations)
        return document

    def to_manifest_text(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def default_profile() -> PostgresGroupedMatchingScaleProfile:
    """Return the hosted 64-partition, five-mode profile."""

    return PostgresGroupedMatchingScaleProfile(
        profile_id="postgres-grouped-matching/64-partitions-v1",
        workers=4,
        runs=32,
    )


def ten_k_profile() -> PostgresGroupedMatchingScaleProfile:
    """Return the bounded 10,000-partition, five-mode profile."""

    return PostgresGroupedMatchingScaleProfile(
        profile_id="postgres-grouped-matching/10k-partitions-v1",
        workers=16,
        runs=1_000,
        partitions_per_run=10,
        batch_size=32,
    )


LIMITATIONS = (
    "Synthetic one-tenant PostgreSQL 16 service with bounded independent worker connections.",
    "The workload uses bounded partitioned runs and synthetic USD/FX/fee inputs; no provider or statutory posting is exercised.",
    "Observed runtime is an environment observation, not a throughput, capacity, SLO, soak, or production-sizing claim.",
    "Cross-host scheduling, queue HA, automatic failover, large-domain diversity, and HA/DR remain unverified.",
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _environment() -> dict[str, object]:
    import os

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": int(os.cpu_count() or 1),
        "database": "PostgreSQL",
    }


def _manifest_digest(document: Mapping[str, object]) -> str:
    stable = {
        key: value
        for key, value in document.items()
        if key not in {"observed_runtime_seconds", "manifest_digest", "environment"}
    }
    return _digest(json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def _rule(mode: str) -> dict[str, object]:
    selected = "many-to-one" if mode == "fx-many-to-one" else mode
    rule: dict[str, object] = {
        "partition_fields": ["entity_id"],
        "partition_max_records": 10,
        "grouped_matching_mode": selected,
        "amount_tolerance": "0",
        "date_window_days": 0,
    }
    if mode == "portfolio":
        rule.update(
            {
                "netting_mode": "net",
                "left_fee_field": "fee",
                "right_fee_field": "fee",
                "allow_partial_settlement": True,
            }
        )
    if mode == "fx-many-to-one":
        rule.update(
            {
                "target_currency": "USD",
                "fx_rates": [
                    {
                        "base_currency": "EUR",
                        "quote_currency": "USD",
                        "rate": "0.5",
                        "rate_type": "spot",
                        "source": "synthetic-fx",
                        "effective_at": "2026-08-01",
                    }
                ],
            }
        )
    return rule


def _partition_records(mode: str, run_index: int, partition_index: int) -> tuple[tuple[str, str, str, str, str], ...]:
    prefix = f"{run_index:03d}-{partition_index:02d}"
    if mode == "one-to-many":
        return (
            ("Left", f"l-{prefix}", "100.00", "USD", "0.00"),
            ("Right", f"r1-{prefix}", "40.00", "USD", "0.00"),
            ("Right", f"r2-{prefix}", "60.00", "USD", "0.00"),
        )
    if mode in {"many-to-one", "fx-many-to-one"}:
        currency = "EUR" if mode == "fx-many-to-one" else "USD"
        right_amount = "200.00" if mode == "fx-many-to-one" else "100.00"
        return (
            ("Left", f"l1-{prefix}", "60.00", "USD", "0.00"),
            ("Left", f"l2-{prefix}", "40.00", "USD", "0.00"),
            ("Right", f"r-{prefix}", right_amount, currency, "0.00"),
        )
    if mode == "many-to-many":
        return (
            ("Left", f"l1-{prefix}", "30.00", "USD", "0.00"),
            ("Left", f"l2-{prefix}", "70.00", "USD", "0.00"),
            ("Right", f"r1-{prefix}", "25.00", "USD", "0.00"),
            ("Right", f"r2-{prefix}", "75.00", "USD", "0.00"),
        )
    if mode == "portfolio":
        return (
            ("Left", f"l1-{prefix}", "120.00", "USD", "20.00"),
            ("Left", f"l2-{prefix}", "50.00", "EUR", "0.00"),
            ("Right", f"r1-{prefix}", "80.00", "USD", "0.00"),
            ("Right", f"r2-{prefix}", "50.00", "EUR", "0.00"),
        )
    raise ValueError(f"unsupported profile mode: {mode}")


def _active_runs(connection_factory: ConnectionFactory, tenant_id: str) -> int:
    with PostgresTenantBoundary(connection_factory).transaction(tenant_id) as connection:
        return len(
            PostgresReconciliationRepository(connection).list_runs(
                tenant_id=tenant_id,
                execution_status="active",
                limit=1_000,
            )
        )


def run_postgres_grouped_matching_scale_profile(
    connection_factory: ConnectionFactory,
    tenant_id: str,
    *,
    profile: PostgresGroupedMatchingScaleProfile | None = None,
    id_prefix: str = "PG-GROUPED-SCALE",
) -> PostgresGroupedMatchingScaleResult:
    """Create and concurrently drain one bounded grouped-matching workload."""

    declared = profile or default_profile()
    tenant = str(tenant_id).strip().lower()
    prefix = str(id_prefix).strip().lower()
    run_modes: dict[str, str] = {}
    with PostgresTenantBoundary(connection_factory).transaction(tenant) as connection:
        repository = PostgresReconciliationRepository(connection)
        for run_index in range(declared.runs):
            mode = declared.modes[run_index % len(declared.modes)]
            run_id = f"{prefix}-run-{run_index:04d}"
            run_modes[run_id] = mode
            repository.create_run(
                tenant_id=tenant,
                run_id=run_id,
                name=f"PostgreSQL grouped scale {run_index:04d}",
                left_source=f"left-{run_index:04d}.csv",
                right_source=f"right-{run_index:04d}.csv",
                algorithm_version="bounded-grouped-subset-sum@1.0.0",
                rule=_rule(mode),
                input_hash=_digest(f"input:{run_id}"),
                actor_id="postgres-grouped-scale",
            )
            for partition_index in range(declared.partitions_per_run):
                entity = f"entity-{run_index:04d}-{partition_index:02d}"
                for side, source_id, amount, currency, fee in _partition_records(mode, run_index, partition_index):
                    repository.register_input(
                        tenant_id=tenant,
                        run_id=run_id,
                        side=side,
                        source_id=source_id,
                        record_hash=_digest(f"record:{run_id}:{source_id}"),
                        amount=amount,
                        currency_code=currency,
                        attributes={
                            "date": "2026-08-01",
                            "currency": currency,
                            "entity_id": entity,
                            "fee": fee,
                        },
                        allowed_uses=2,
                    )

    def worker_factory(worker_id: str) -> PostgresReconciliationWorker:
        return PostgresReconciliationWorker(
            connection_factory,
            tenant_supplier=lambda: (tenant,),
            matcher=PostgresGroupedMatchingAdapter(),
            settings=PostgresReconciliationWorkerSettings(
                worker_id=worker_id,
                actor_id=worker_id,
                batch_size=declared.batch_size,
                lease_seconds=declared.lease_seconds,
                poll_interval_seconds=0,
            ),
        )

    worker_ids = tuple(f"pg-grouped-scale-worker-{index:02d}" for index in range(declared.workers))
    started = time.perf_counter()
    cycles = 0
    with ThreadPoolExecutor(max_workers=declared.workers, thread_name_prefix="reconforge-pg-grouped") as pool:
        workers = tuple(
            worker_factory(worker_id)
            for worker_id in worker_ids
        )
        while cycles < 100:
            futures = [pool.submit(worker.process_once) for worker in workers]
            for future in futures:
                future.result()
            cycles += 1
            if _active_runs(connection_factory, tenant) == 0:
                break
    if _active_runs(connection_factory, tenant) != 0:
        raise TimeoutError("PostgreSQL grouped matching profile did not drain before 100 scheduler cycles")
    runtime = max(time.perf_counter() - started, 0.0)

    identities: list[tuple[str, str, str, str, str]] = []
    completed_runs = 0
    completed_partitions = 0
    result_rows = 0
    duplicate_result_identities = 0
    failed_runs = 0
    per_mode_completed = {mode: 0 for mode in declared.modes}
    with PostgresTenantBoundary(connection_factory).transaction(tenant) as connection:
        repository = PostgresReconciliationRepository(connection)
        for run_id, mode in sorted(run_modes.items()):
            metadata = repository.get_run_metadata(tenant_id=tenant, run_id=run_id)
            if str(metadata.get("execution_status")) == "Complete":
                completed_runs += 1
                per_mode_completed[mode] += 1
            if str(metadata.get("execution_status")) == "Failed":
                failed_runs += 1
            checkpoints = repository.list_checkpoints(tenant_id=tenant, run_id=run_id)
            completed_partitions += len(checkpoints)
            rows = repository.list_results(tenant_id=tenant, run_id=run_id)
            result_rows += len(rows)
            for row in rows:
                lineage = row.get("lineage_json", {})
                if not isinstance(lineage, Mapping):
                    raise AssertionError("grouped matching lineage is not an object")
                identities.append(
                    (
                        run_id,
                        str(lineage.get("partition_key", "")),
                        str(row.get("left_id", "")),
                        str(row.get("right_id", "")),
                        str(row.get("status", "")),
                    )
                )
    counts = {identity: identities.count(identity) for identity in set(identities)}
    duplicate_result_identities = sum(count - 1 for count in counts.values() if count > 1)
    serialized = json.dumps(sorted(identities), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    active = _active_runs(connection_factory, tenant)
    document: dict[str, object] = {
        "schema_version": POSTGRES_GROUPED_SCALE_SCHEMA_VERSION,
        "profile_id": declared.profile_id,
        "workers": declared.workers,
        "runs": declared.runs,
        "partitions_per_run": declared.partitions_per_run,
        "declared_partitions": declared.declared_partitions,
        "completed_runs": completed_runs,
        "completed_partitions": completed_partitions,
        "result_rows": result_rows,
        "expected_result_rows": declared.expected_result_rows,
        "duplicate_result_identities": duplicate_result_identities,
        "failed_runs": failed_runs,
        "final_active_runs": active,
        "per_mode_completed": dict(sorted(per_mode_completed.items())),
        "effect_set_digest": _digest(serialized),
        "limitations": list(LIMITATIONS),
    }
    return PostgresGroupedMatchingScaleResult(
        schema_version=POSTGRES_GROUPED_SCALE_SCHEMA_VERSION,
        profile_id=declared.profile_id,
        workers=declared.workers,
        runs=declared.runs,
        partitions_per_run=declared.partitions_per_run,
        declared_partitions=declared.declared_partitions,
        completed_runs=completed_runs,
        completed_partitions=completed_partitions,
        result_rows=result_rows,
        expected_result_rows=declared.expected_result_rows,
        duplicate_result_identities=duplicate_result_identities,
        failed_runs=failed_runs,
        final_active_runs=active,
        per_mode_completed=dict(sorted(per_mode_completed.items())),
        effect_set_digest=_digest(serialized),
        observed_runtime_seconds=round(runtime, 4),
        environment=_environment(),
        manifest_digest=_manifest_digest(document),
        limitations=LIMITATIONS,
    )


def verify_postgres_grouped_matching_scale_result(
    result: PostgresGroupedMatchingScaleResult,
    *,
    profile: PostgresGroupedMatchingScaleProfile | None = None,
) -> None:
    """Assert structural correctness of the bounded profile."""

    declared = profile or default_profile()
    if result.schema_version != POSTGRES_GROUPED_SCALE_SCHEMA_VERSION or result.profile_id != declared.profile_id:
        raise AssertionError("PostgreSQL grouped scale profile mismatch")
    if (result.workers, result.runs, result.partitions_per_run) != (
        declared.workers,
        declared.runs,
        declared.partitions_per_run,
    ):
        raise AssertionError("PostgreSQL grouped scale declared shape mismatch")
    if result.completed_runs != declared.runs or result.completed_partitions != declared.declared_partitions:
        raise AssertionError("PostgreSQL grouped scale did not drain every run and partition")
    if result.result_rows != result.expected_result_rows or result.duplicate_result_identities != 0:
        raise AssertionError("PostgreSQL grouped scale produced duplicate or unexpected result rows")
    if result.failed_runs != 0 or result.final_active_runs != 0:
        raise AssertionError("PostgreSQL grouped scale left failed or active runs")
    expected_modes = {mode: declared.runs // len(declared.modes) for mode in declared.modes}
    for index in range(declared.runs % len(declared.modes)):
        expected_modes[declared.modes[index]] += 1
    if result.per_mode_completed != dict(sorted(expected_modes.items())):
        raise AssertionError("PostgreSQL grouped scale did not complete every declared mode")
    if not result.effect_set_digest or not result.manifest_digest:
        raise AssertionError("PostgreSQL grouped scale is missing integrity digests")


__all__ = [
    "LIMITATIONS",
    "POSTGRES_GROUPED_SCALE_SCHEMA_VERSION",
    "PostgresGroupedMatchingScaleProfile",
    "PostgresGroupedMatchingScaleResult",
    "default_profile",
    "ten_k_profile",
    "run_postgres_grouped_matching_scale_profile",
    "verify_postgres_grouped_matching_scale_result",
]
