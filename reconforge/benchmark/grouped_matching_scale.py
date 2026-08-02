"""Reproducible partitioned grouped-matching scale benchmarks.

Each declared tier is intentionally partitioned into independent true
many-to-many groups (four records per partition). Every group is executed
through the public strategy adapter and backend-neutral application service,
so the measurement covers the explainable grouped contract without creating
an unbounded cross-partition search.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass

from reconforge.application.grouped_matching import (
    GroupedMatchingApplicationService,
    GroupedMatchRequest,
)
from reconforge.application.matching_strategies import MatchingStrategyRequest
from reconforge.domain.grouped_matching import GroupedMatchPolicy
from reconforge.infrastructure.grouped_matching_strategy import GroupedSubsetSumStrategy

GROUPED_10K_PROFILE_ID = "grouped-matching/10k-record-true-many-to-many-v1"
GROUPED_10K_PARTITIONS = 2_500
GROUPED_10K_RECORDS_PER_PARTITION = 4
GROUPED_10K_RECORDS = GROUPED_10K_PARTITIONS * GROUPED_10K_RECORDS_PER_PARTITION
GROUPED_100K_PROFILE_ID = "grouped-matching/100k-record-true-many-to-many-v1"
GROUPED_100K_PARTITIONS = 25_000
GROUPED_100K_RECORDS = GROUPED_100K_PARTITIONS * GROUPED_10K_RECORDS_PER_PARTITION
GROUPED_1M_PROFILE_ID = "grouped-matching/1m-record-true-many-to-many-v1"
GROUPED_1M_PARTITIONS = 250_000
GROUPED_1M_RECORDS = GROUPED_1M_PARTITIONS * GROUPED_10K_RECORDS_PER_PARTITION


@dataclass(frozen=True)
class GroupedMatchingScaleResult:
    schema_version: int
    profile_id: str
    partitions: int
    records: int
    matched_partitions: int
    ambiguous_partitions: int
    unmatched_partitions: int
    strategy_evaluations: int
    cross_engine_mismatches: int
    permutation_mismatches: int
    effect_digest: str
    observed_runtime_seconds: float
    observed_peak_memory_mb: float
    environment: dict[str, object]
    limitations: tuple[str, ...]
    manifest_digest: str

    def to_dict(self) -> dict[str, object]:
        document = asdict(self)
        document["limitations"] = list(self.limitations)
        return document

    def to_manifest_text(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


LIMITATIONS = (
    "One Windows host and one Python process; this is a partitioned algorithm observation, not a distributed capacity or SLO claim.",
    "The workload uses exact USD true-many-to-many groups with four records per partition; FX, fee, partial-settlement, ambiguity density, and provider I/O are not represented in this tier.",
    "The grouped strategy remains bounded by its published per-partition record and search-evaluation ceilings; 100K/1M records and PostgreSQL runtime parity remain unverified.",
)

LIMITATIONS_100K = (
    "One Windows host and one Python process; this is a partitioned algorithm observation, not a distributed capacity or SLO claim.",
    "The workload uses exact USD true-many-to-many groups with four records per partition; FX, fee, partial-settlement, ambiguity density, and provider I/O are not represented in this tier.",
    "The grouped strategy remains bounded by its published per-partition record and search-evaluation ceilings; 1M records and PostgreSQL runtime parity remain unverified.",
)

LIMITATIONS_1M = (
    "One Windows host and one Python process; this is a partitioned algorithm observation, not a distributed capacity or SLO claim.",
    "The workload uses exact USD true-many-to-many groups with four records per partition; FX, fee, partial-settlement, ambiguity density, and provider I/O are not represented in this tier.",
    "The grouped strategy remains bounded by its published per-partition record and search-evaluation ceilings; PostgreSQL runtime parity, soak, and distributed 1M capacity remain unverified.",
)


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _request(index: int) -> MatchingStrategyRequest:
    partition = f"M2M-{index:05d}"
    common = {"currency": "USD", "date": "2026-08-01", "partition": partition}
    return MatchingStrategyRequest(
        left_records=(
            {**common, "id": f"L-{index:05d}-01", "amount": "30"},
            {**common, "id": f"L-{index:05d}-02", "amount": "70"},
        ),
        right_records=(
            {**common, "id": f"R-{index:05d}-01", "amount": "25"},
            {**common, "id": f"R-{index:05d}-02", "amount": "75"},
        ),
        mode="many-to-many",
        amount_tolerance="0",
    )


def _environment() -> dict[str, object]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": int(__import__("os").cpu_count() or 1),
    }


def _run_grouped_matching_scale(
    *, profile_id: str, partitions: int, permutation_stride: int, permutation_check: bool
) -> GroupedMatchingScaleResult:
    """Run one declared partitioned grouped-matching profile."""

    strategy = GroupedSubsetSumStrategy()
    application = GroupedMatchingApplicationService()
    policy = GroupedMatchPolicy(mode="many-to-many")
    tracemalloc.start()
    started = time.perf_counter()
    matched = ambiguous = unmatched = evaluations = mismatches = permutation_mismatches = 0
    decisions: list[dict[str, object]] = []
    for index in range(partitions):
        request = _request(index)
        strategy_result = strategy.execute(request)
        direct = application.execute(
            GroupedMatchRequest(
                left_records=request.left_records,
                right_records=request.right_records,
                policy=policy,
            )
        )
        strategy_decision = strategy_result.results[0]
        if strategy_decision.get("decision_digest") != direct.decision_digest:
            mismatches += 1
        status = str(strategy_decision.get("status", ""))
        if status == "matched":
            matched += 1
        elif status == "ambiguous":
            ambiguous += 1
        else:
            unmatched += 1
        raw_evaluations = strategy_decision.get("search_evaluations", 0)
        if not isinstance(raw_evaluations, int):
            raise AssertionError("Grouped strategy search_evaluations must be an integer.")
        evaluations += raw_evaluations
        decisions.append(
            {
                "partition": index,
                "decision_digest": strategy_decision.get("decision_digest", ""),
                "status": status,
            }
        )
        if permutation_check and index % permutation_stride == 0:
            permuted = MatchingStrategyRequest(
                left_records=tuple(reversed(request.left_records)),
                right_records=tuple(reversed(request.right_records)),
                mode=request.mode,
            )
            permuted_result = strategy.execute(permuted)
            if permuted_result.results[0].get("decision_digest") != strategy_decision.get("decision_digest"):
                permutation_mismatches += 1
    runtime = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    effect_digest = _digest(decisions)
    if profile_id == GROUPED_1M_PROFILE_ID:
        limitations = LIMITATIONS_1M
    elif profile_id == GROUPED_100K_PROFILE_ID:
        limitations = LIMITATIONS_100K
    else:
        limitations = LIMITATIONS
    document: dict[str, object] = {
        "schema_version": 1,
        "profile_id": profile_id,
        "partitions": partitions,
        "records": partitions * GROUPED_10K_RECORDS_PER_PARTITION,
        "matched_partitions": matched,
        "ambiguous_partitions": ambiguous,
        "unmatched_partitions": unmatched,
        "strategy_evaluations": evaluations,
        "cross_engine_mismatches": mismatches,
        "permutation_mismatches": permutation_mismatches,
        "effect_digest": effect_digest,
        "environment": _environment(),
        "limitations": list(limitations),
    }
    manifest_digest = _digest(document)
    return GroupedMatchingScaleResult(
        schema_version=1,
        profile_id=profile_id,
        partitions=partitions,
        records=partitions * GROUPED_10K_RECORDS_PER_PARTITION,
        matched_partitions=matched,
        ambiguous_partitions=ambiguous,
        unmatched_partitions=unmatched,
        strategy_evaluations=evaluations,
        cross_engine_mismatches=mismatches,
        permutation_mismatches=permutation_mismatches,
        effect_digest=effect_digest,
        observed_runtime_seconds=round(runtime, 4),
        observed_peak_memory_mb=round(peak / (1024 * 1024), 4),
        environment=_environment(),
        limitations=limitations,
        manifest_digest=manifest_digest,
    )


def run_grouped_matching_10k(*, permutation_check: bool = True) -> GroupedMatchingScaleResult:
    """Run the declared 10K-record partitioned matching profile."""

    return _run_grouped_matching_scale(
        profile_id=GROUPED_10K_PROFILE_ID,
        partitions=GROUPED_10K_PARTITIONS,
        permutation_stride=100,
        permutation_check=permutation_check,
    )


def run_grouped_matching_100k(*, permutation_check: bool = True) -> GroupedMatchingScaleResult:
    """Run the declared 100K-record partitioned matching profile."""

    return _run_grouped_matching_scale(
        profile_id=GROUPED_100K_PROFILE_ID,
        partitions=GROUPED_100K_PARTITIONS,
        permutation_stride=1_000,
        permutation_check=permutation_check,
    )


def run_grouped_matching_1m(*, permutation_check: bool = True) -> GroupedMatchingScaleResult:
    """Run the declared 1M-record partitioned matching profile."""

    return _run_grouped_matching_scale(
        profile_id=GROUPED_1M_PROFILE_ID,
        partitions=GROUPED_1M_PARTITIONS,
        permutation_stride=10_000,
        permutation_check=permutation_check,
    )


def verify_grouped_matching_10k(result: GroupedMatchingScaleResult) -> None:
    """Verify the correctness and parity invariants of the 10K result."""

    if result.profile_id != GROUPED_10K_PROFILE_ID or result.records != GROUPED_10K_RECORDS:
        raise AssertionError("Grouped 10K result does not match the declared profile.")
    if result.matched_partitions != GROUPED_10K_PARTITIONS:
        raise AssertionError("Every declared partition must match in the synthetic tier.")
    if result.ambiguous_partitions or result.unmatched_partitions:
        raise AssertionError("The synthetic 10K tier contains an unresolved partition.")
    if result.strategy_evaluations != GROUPED_10K_PARTITIONS:
        raise AssertionError("Unexpected bounded search-evaluation count.")
    if result.cross_engine_mismatches or result.permutation_mismatches:
        raise AssertionError("Grouped strategy parity or permutation invariance failed.")
    if not result.effect_digest or not result.manifest_digest:
        raise AssertionError("Grouped 10K digests are required.")


def verify_grouped_matching_100k(result: GroupedMatchingScaleResult) -> None:
    """Verify the correctness and parity invariants of the 100K result."""

    if result.profile_id != GROUPED_100K_PROFILE_ID or result.records != GROUPED_100K_RECORDS:
        raise AssertionError("Grouped 100K result does not match the declared profile.")
    if result.matched_partitions != GROUPED_100K_PARTITIONS:
        raise AssertionError("Every declared 100K partition must match.")
    if result.ambiguous_partitions or result.unmatched_partitions:
        raise AssertionError("The synthetic 100K tier contains an unresolved partition.")
    if result.strategy_evaluations != GROUPED_100K_PARTITIONS:
        raise AssertionError("Unexpected 100K bounded search-evaluation count.")
    if result.cross_engine_mismatches or result.permutation_mismatches:
        raise AssertionError("Grouped 100K parity or permutation invariance failed.")
    if not result.effect_digest or not result.manifest_digest:
        raise AssertionError("Grouped 100K digests are required.")


def verify_grouped_matching_1m(result: GroupedMatchingScaleResult) -> None:
    """Verify the correctness and parity invariants of the 1M result."""

    if result.profile_id != GROUPED_1M_PROFILE_ID or result.records != GROUPED_1M_RECORDS:
        raise AssertionError("Grouped 1M result does not match the declared profile.")
    if result.matched_partitions != GROUPED_1M_PARTITIONS:
        raise AssertionError("Every declared 1M partition must match.")
    if result.ambiguous_partitions or result.unmatched_partitions:
        raise AssertionError("The synthetic 1M tier contains an unresolved partition.")
    if result.strategy_evaluations != GROUPED_1M_PARTITIONS:
        raise AssertionError("Unexpected 1M bounded search-evaluation count.")
    if result.cross_engine_mismatches or result.permutation_mismatches:
        raise AssertionError("Grouped 1M parity or permutation invariance failed.")
    if not result.effect_digest or not result.manifest_digest:
        raise AssertionError("Grouped 1M digests are required.")
