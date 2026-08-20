"""Partitioned 10K/100K/1M benchmarks for sequential matching strategies.

Each partition is deliberately small and independent.  The profile measures
the public sequential strategy over synthetic USD records and samples the
PostgreSQL-worker projection plus permutation invariance at declared strides.
The results are algorithm observations, not distributed capacity or SLOs.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
import tracemalloc
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import date
from decimal import Decimal

from reconforge.application.matching_strategies import MatchingStrategyRequest
from reconforge.infrastructure.carry_forward_strategy import CarryForwardFifoStrategy
from reconforge.infrastructure.reversal_matching_strategy import ReversalPairingStrategy
from reconforge.workers.postgres_reconciliation import ReconciliationExecutionContext, ReconciliationInputPartition
from reconforge.workers.postgres_sequential_matching import PostgresSequentialMatchingAdapter

SEQUENTIAL_10K_PROFILE_ID = "sequential-matching/10k-record-partitioned-v1"
SEQUENTIAL_100K_PROFILE_ID = "sequential-matching/100k-record-partitioned-v1"
SEQUENTIAL_1M_PROFILE_ID = "sequential-matching/1m-record-partitioned-v1"
SEQUENTIAL_RECORDS_PER_PARTITION = 5
SEQUENTIAL_10K_PARTITIONS = 10_000 // SEQUENTIAL_RECORDS_PER_PARTITION
SEQUENTIAL_100K_PARTITIONS = 100_000 // SEQUENTIAL_RECORDS_PER_PARTITION
SEQUENTIAL_1M_PARTITIONS = 1_000_000 // SEQUENTIAL_RECORDS_PER_PARTITION
SEQUENTIAL_10K_RECORDS = SEQUENTIAL_10K_PARTITIONS * SEQUENTIAL_RECORDS_PER_PARTITION
SEQUENTIAL_100K_RECORDS = SEQUENTIAL_100K_PARTITIONS * SEQUENTIAL_RECORDS_PER_PARTITION
SEQUENTIAL_1M_RECORDS = SEQUENTIAL_1M_PARTITIONS * SEQUENTIAL_RECORDS_PER_PARTITION

LIMITATIONS_10K = (
    "One Windows host and one Python process; this is a partitioned algorithm observation, not distributed capacity or an SLO.",
    "Each partition cycles exact-USD carry-forward, contiguous sequence-window, and explicit reversal-pairing fixtures; live providers, FX, fees, and statutory posting are not represented.",
    "PostgreSQL-worker parity and permutation checks run at declared sample strides; this is not live PostgreSQL runtime or production sizing evidence.",
)
LIMITATIONS_100K = LIMITATIONS_10K + ("The 1M tier remains a separate declared profile and is not implied by this observation.",)
LIMITATIONS_1M = LIMITATIONS_10K + ("The 1M observation remains one-host synthetic evidence; soak, distributed capacity, and live PostgreSQL parity remain unverified.",)


@dataclass(frozen=True)
class SequentialMatchingScaleResult:
    schema_version: int
    profile_id: str
    partitions: int
    records: int
    matched_partitions: int
    ambiguous_partitions: int
    unmatched_partitions: int
    unmatched_records: int
    strategy_evaluations: int
    cross_engine_checks: int
    cross_engine_mismatches: int
    permutation_checks: int
    permutation_mismatches: int
    mutation_guard_passed: bool
    effect_digest: str
    observed_runtime_seconds: float
    observed_peak_memory_mb: float
    environment: dict[str, object]
    limitations: tuple[str, ...]
    manifest_digest: str

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["limitations"] = list(self.limitations)
        return result

    def to_manifest_text(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _environment() -> dict[str, object]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": __import__("os").cpu_count() or 1,
    }


def _request(index: int) -> MatchingStrategyRequest:
    partition = f"SEQ-{index:07d}"
    common = {"currency": "USD", "partition": partition}
    mode = index % 3
    if mode == 0:
        return MatchingStrategyRequest(
            left_records=(
                {**common, "id": f"O-{index}-01", "amount": "100", "date": "2026-08-01"},
                {**common, "id": f"O-{index}-02", "amount": "50", "date": "2026-08-02"},
                {**common, "id": f"O-{index}-03", "amount": "30", "date": "2026-08-03"},
            ),
            right_records=(
                {**common, "id": f"S-{index}-01", "amount": "100", "date": "2026-08-04"},
                {**common, "id": f"S-{index}-02", "amount": "50", "date": "2026-08-05"},
                {**common, "id": f"S-{index}-03", "amount": "10", "date": "2026-08-06"},
            ),
            amount_tolerance="0",
            date_window_days=30,
            mode="carry-forward",
        )
    if mode == 1:
        return MatchingStrategyRequest(
            left_records=(
                {**common, "id": f"O-{index}-01", "amount": "40", "date": "2026-08-01"},
                {**common, "id": f"O-{index}-02", "amount": "60", "date": "2026-08-02"},
                {**common, "id": f"O-{index}-03", "amount": "50", "date": "2026-08-03"},
            ),
            right_records=(
                {**common, "id": f"S-{index}-01", "amount": "100", "date": "2026-08-02"},
                {**common, "id": f"S-{index}-02", "amount": "50", "date": "2026-08-06"},
            ),
            amount_tolerance="0",
            date_window_days=30,
            mode="sequence-window",
        )
    return MatchingStrategyRequest(
        left_records=(
            {**common, "id": f"J-{index}-01", "amount": "100", "date": "2026-08-01"},
            {**common, "id": f"J-{index}-02", "amount": "50", "date": "2026-08-02"},
            {**common, "id": f"J-{index}-03", "amount": "25", "date": "2026-08-03"},
        ),
        right_records=(
            {**common, "id": f"R-{index}-01", "amount": "-100", "date": "2026-08-03", "reversal_of": f"J-{index}-01"},
            {**common, "id": f"R-{index}-02", "amount": "-50", "date": "2026-08-04", "reversal_of": f"J-{index}-02"},
        ),
        amount_tolerance="0",
        date_window_days=30,
        mode="reversal-pairing",
    )


def _record(value: dict[str, object]) -> dict[str, object]:
    return {
        "source_id": str(value["id"]),
        "amount_decimal": Decimal(str(value["amount"])),
        "date_value": date.fromisoformat(str(value["date"])),
        "currency_code": str(value["currency"]),
        "attributes_json": dict(value),
    }


def _adapter_digest(request: MatchingStrategyRequest) -> str:
    context = ReconciliationExecutionContext(
        run={"rule_json": {"matching_mode": request.mode, "amount_tolerance": request.amount_tolerance, "date_window_days": request.date_window_days}},
        left_inputs=tuple(_record(dict(item)) for item in request.left_records),
        right_inputs=tuple(_record(dict(item)) for item in request.right_records),
        heartbeat=lambda completed: {"completed": completed},
        cancellation_requested=lambda: False,
        partition_supplier=lambda: (
            ReconciliationInputPartition(
                partition_key=str(request.left_records[0].get(request.partition_field, "")),
                left_inputs=tuple(_record(dict(item)) for item in request.left_records),
                right_inputs=tuple(_record(dict(item)) for item in request.right_records),
            ),
        ),
    )
    projected = PostgresSequentialMatchingAdapter()(context)
    digests: set[str] = set()
    for row in projected.results:
        lineage = row.get("lineage")
        if isinstance(lineage, dict):
            digests.add(str(lineage.get("strategy_result_digest", "")))
    if len(digests) != 1:
        raise AssertionError("sequential worker must expose one digest per partition")
    return next(iter(digests))


def _execute(request: MatchingStrategyRequest) -> tuple[Mapping[str, object], str, int]:
    strategy = ReversalPairingStrategy() if request.mode == "reversal-pairing" else CarryForwardFifoStrategy()
    result = strategy.execute(request)
    decision = result.results[0]
    evaluations = decision.get("search_evaluations", 0)
    if not isinstance(evaluations, int):
        raise AssertionError("sequential search_evaluations must be an integer")
    return decision, result.decision_digest, evaluations


def _mutated(request: MatchingStrategyRequest) -> MatchingStrategyRequest:
    first = dict(request.left_records[0])
    first["amount"] = str((Decimal(str(first["amount"])) + Decimal("0.01")).quantize(Decimal("0.01")))
    return replace(request, left_records=(first,) + request.left_records[1:])


def _run(*, profile_id: str, partitions: int, parity_stride: int, permutation_stride: int) -> SequentialMatchingScaleResult:
    limitations: tuple[str, ...]
    if profile_id == SEQUENTIAL_1M_PROFILE_ID:
        limitations = LIMITATIONS_1M
    elif profile_id == SEQUENTIAL_100K_PROFILE_ID:
        limitations = LIMITATIONS_100K
    else:
        limitations = LIMITATIONS_10K
    strategy_evaluations = matched = ambiguous = unmatched = parity_checks = parity_mismatches = 0
    unmatched_records = 0
    permutation_checks = permutation_mismatches = 0
    decisions: list[dict[str, object]] = []
    mutation_guard = True
    tracemalloc.start()
    started = time.perf_counter()
    for index in range(partitions):
        request = _request(index)
        decision, decision_digest, evaluations = _execute(request)
        strategy_evaluations += evaluations
        status = str(decision.get("status", ""))
        if status in {"allocated", "matched"}:
            matched += 1
        elif status == "ambiguous":
            ambiguous += 1
        else:
            unmatched += 1
        for key in ("unmatched_obligation_ids", "unmatched_settlement_ids", "unmatched_original_ids", "unmatched_reversal_ids"):
            values = decision.get(key, ())
            if isinstance(values, (tuple, list)):
                unmatched_records += len(values)
        decisions.append({"partition": index, "mode": request.mode, "decision_digest": decision_digest, "status": status})
        if index == 0:
            _, mutated_digest, _ = _execute(_mutated(request))
            mutation_guard = mutated_digest != decision_digest
        if index % parity_stride == 0:
            parity_checks += 1
            if _adapter_digest(request) != decision_digest:
                parity_mismatches += 1
        if index % permutation_stride == 0:
            permutation_checks += 1
            permuted = replace(request, left_records=tuple(reversed(request.left_records)), right_records=tuple(reversed(request.right_records)))
            _, permuted_digest, _ = _execute(permuted)
            if permuted_digest != decision_digest:
                permutation_mismatches += 1
    runtime = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    effect_digest = _digest(decisions)
    structural = {
        "schema_version": 1,
        "profile_id": profile_id,
        "partitions": partitions,
        "records": partitions * SEQUENTIAL_RECORDS_PER_PARTITION,
        "matched_partitions": matched,
        "ambiguous_partitions": ambiguous,
        "unmatched_partitions": unmatched,
        "unmatched_records": unmatched_records,
        "strategy_evaluations": strategy_evaluations,
        "cross_engine_checks": parity_checks,
        "cross_engine_mismatches": parity_mismatches,
        "permutation_checks": permutation_checks,
        "permutation_mismatches": permutation_mismatches,
        "mutation_guard_passed": mutation_guard,
        "effect_digest": effect_digest,
        "environment": _environment(),
        "limitations": list(limitations),
    }
    return SequentialMatchingScaleResult(
        schema_version=1,
        profile_id=profile_id,
        partitions=partitions,
        records=partitions * SEQUENTIAL_RECORDS_PER_PARTITION,
        matched_partitions=matched,
        ambiguous_partitions=ambiguous,
        unmatched_partitions=unmatched,
        unmatched_records=unmatched_records,
        strategy_evaluations=strategy_evaluations,
        cross_engine_checks=parity_checks,
        cross_engine_mismatches=parity_mismatches,
        permutation_checks=permutation_checks,
        permutation_mismatches=permutation_mismatches,
        mutation_guard_passed=mutation_guard,
        effect_digest=effect_digest,
        observed_runtime_seconds=round(runtime, 4),
        observed_peak_memory_mb=round(peak / (1024 * 1024), 4),
        environment=_environment(),
        limitations=limitations,
        manifest_digest=_digest(structural),
    )


def run_sequential_matching_10k(*, parity_check: bool = True) -> SequentialMatchingScaleResult:
    return _run(
        profile_id=SEQUENTIAL_10K_PROFILE_ID,
        partitions=SEQUENTIAL_10K_PARTITIONS,
        parity_stride=1 if parity_check else SEQUENTIAL_10K_PARTITIONS,
        permutation_stride=100,
    )


def run_sequential_matching_100k(*, parity_check: bool = True) -> SequentialMatchingScaleResult:
    return _run(
        profile_id=SEQUENTIAL_100K_PROFILE_ID,
        partitions=SEQUENTIAL_100K_PARTITIONS,
        parity_stride=100 if parity_check else SEQUENTIAL_100K_PARTITIONS,
        permutation_stride=1_000,
    )


def run_sequential_matching_1m(*, parity_check: bool = True) -> SequentialMatchingScaleResult:
    return _run(
        profile_id=SEQUENTIAL_1M_PROFILE_ID,
        partitions=SEQUENTIAL_1M_PARTITIONS,
        parity_stride=1_000 if parity_check else SEQUENTIAL_1M_PARTITIONS,
        permutation_stride=10_000,
    )


def _verify(result: SequentialMatchingScaleResult, *, records: int, profile_id: str) -> None:
    if result.profile_id != profile_id or result.records != records:
        raise AssertionError("sequential profile shape does not match its declaration")
    if result.matched_partitions != result.partitions or result.ambiguous_partitions or result.unmatched_partitions:
        raise AssertionError("every synthetic sequential partition must match")
    if result.cross_engine_mismatches or result.permutation_mismatches or not result.mutation_guard_passed:
        raise AssertionError("sequential parity, permutation, or mutation guard failed")
    if not result.effect_digest or not result.manifest_digest:
        raise AssertionError("sequential benchmark digests are required")


def verify_sequential_matching_10k(result: SequentialMatchingScaleResult) -> None:
    _verify(result, records=SEQUENTIAL_10K_RECORDS, profile_id=SEQUENTIAL_10K_PROFILE_ID)


def verify_sequential_matching_100k(result: SequentialMatchingScaleResult) -> None:
    _verify(result, records=SEQUENTIAL_100K_RECORDS, profile_id=SEQUENTIAL_100K_PROFILE_ID)


def verify_sequential_matching_1m(result: SequentialMatchingScaleResult) -> None:
    _verify(result, records=SEQUENTIAL_1M_RECORDS, profile_id=SEQUENTIAL_1M_PROFILE_ID)


__all__ = [
    "SEQUENTIAL_10K_PARTITIONS",
    "SEQUENTIAL_10K_PROFILE_ID",
    "SEQUENTIAL_10K_RECORDS",
    "SEQUENTIAL_100K_PARTITIONS",
    "SEQUENTIAL_100K_PROFILE_ID",
    "SEQUENTIAL_100K_RECORDS",
    "SEQUENTIAL_1M_PARTITIONS",
    "SEQUENTIAL_1M_PROFILE_ID",
    "SEQUENTIAL_1M_RECORDS",
    "run_sequential_matching_10k",
    "run_sequential_matching_100k",
    "run_sequential_matching_1m",
    "verify_sequential_matching_10k",
    "verify_sequential_matching_100k",
    "verify_sequential_matching_1m",
]
