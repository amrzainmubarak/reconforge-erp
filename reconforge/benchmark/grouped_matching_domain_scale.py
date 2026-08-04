"""Domain-diverse grouped-matching scale profile.

The existing 10K/100K/1M profiles intentionally use a homogeneous exact
many-to-many shape.  This profile keeps the same bounded partition discipline
but cycles through one-to-many, many-to-one, true many-to-many, fee-aware
portfolio, FX-aware many-to-many, and partial-settlement portfolio cases.  It
is an algorithm correctness and adapter-parity profile, not a capacity claim.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
import tracemalloc
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace

from reconforge.application.grouped_matching import (
    GroupedMatchingApplicationService,
    GroupedMatchRequest,
)
from reconforge.application.matching_strategies import MatchingStrategyRequest
from reconforge.domain.grouped_matching import GroupedMatchPolicy
from reconforge.infrastructure.grouped_matching_strategy import GroupedSubsetSumStrategy

DOMAIN_SCALE_SCHEMA_VERSION = 1
DOMAIN_SCALE_PROFILE_ID = "grouped-matching/10k-domain-diverse-v1"
DOMAIN_SCALE_PARTITIONS = 2_500
DOMAIN_SCALE_RECORDS_PER_PARTITION = 4
DOMAIN_SCALE_RECORDS = DOMAIN_SCALE_PARTITIONS * DOMAIN_SCALE_RECORDS_PER_PARTITION
DOMAIN_SCALE_MODES = (
    "one-to-many",
    "many-to-one",
    "many-to-many",
    "portfolio-net",
    "fx-many-to-many",
    "portfolio-partial",
)

LIMITATIONS = (
    "One host and one Python process; this is a partitioned algorithm correctness observation, not distributed capacity or an SLO.",
    "The declared 10K records cycle six synthetic grouped modes; carry-forward, sequence/window, reversal, PostgreSQL runtime, soak, and provider I/O are separate boundaries.",
    "Each partition stays inside the published grouped strategy cardinality and search-evaluation ceilings; this profile does not widen those limits or claim production sizing.",
)


@dataclass(frozen=True)
class GroupedMatchingDomainScaleResult:
    schema_version: int
    profile_id: str
    partitions: int
    records: int
    mode_counts: dict[str, int]
    matched_partitions: int
    ambiguous_partitions: int
    unmatched_partitions: int
    adapter_mismatches: int
    permutation_mismatches: int
    strategy_evaluations: int
    decision_digest: str
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


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _common(index: int) -> dict[str, str]:
    return {"date": "2026-08-01", "partition": f"DOMAIN-{index:05d}"}


def _request(index: int) -> tuple[str, MatchingStrategyRequest]:
    mode = DOMAIN_SCALE_MODES[index % len(DOMAIN_SCALE_MODES)]
    common = _common(index)
    left: tuple[Mapping[str, object], ...]
    right: tuple[Mapping[str, object], ...]
    request = MatchingStrategyRequest(left_records=(), right_records=())
    if mode == "one-to-many":
        left = ({**common, "id": f"L-{index:05d}-01", "amount": "100", "currency": "USD"},)
        right = tuple(
            {**common, "id": f"R-{index:05d}-0{ordinal}", "amount": amount, "currency": "USD"}
            for ordinal, amount in enumerate(("30", "30", "40"), start=1)
        )
        request = replace(request, left_records=left, right_records=right, mode="one-to-many")
    elif mode == "many-to-one":
        left = tuple(
            {**common, "id": f"L-{index:05d}-0{ordinal}", "amount": amount, "currency": "USD"}
            for ordinal, amount in enumerate(("30", "30", "40"), start=1)
        )
        right = ({**common, "id": f"R-{index:05d}-01", "amount": "100", "currency": "USD"},)
        request = replace(request, left_records=left, right_records=right, mode="many-to-one")
    elif mode == "many-to-many":
        left = tuple(
            {**common, "id": f"L-{index:05d}-0{ordinal}", "amount": amount, "currency": "USD"}
            for ordinal, amount in enumerate(("30", "70"), start=1)
        )
        right = tuple(
            {**common, "id": f"R-{index:05d}-0{ordinal}", "amount": amount, "currency": "USD"}
            for ordinal, amount in enumerate(("25", "75"), start=1)
        )
        request = replace(request, left_records=left, right_records=right, mode="many-to-many")
    elif mode == "portfolio-net":
        left = tuple(
            {**common, "id": f"L-{index:05d}-0{ordinal}", "amount": amount, "fee": fee, "currency": "USD"}
            for ordinal, (amount, fee) in enumerate((("60", "5"), ("40", "5")), start=1)
        )
        right = tuple(
            {**common, "id": f"R-{index:05d}-0{ordinal}", "amount": amount, "fee": "0", "currency": "USD"}
            for ordinal, amount in enumerate(("45", "45"), start=1)
        )
        request = replace(
            request,
            left_records=left,
            right_records=right,
            mode="portfolio",
            netting_mode="net",
            left_fee_field="fee",
            right_fee_field="fee",
        )
    elif mode == "fx-many-to-many":
        left = tuple(
            {**common, "id": f"L-{index:05d}-0{ordinal}", "amount": "50", "currency": "EUR"}
            for ordinal in range(1, 3)
        )
        right = tuple(
            {**common, "id": f"R-{index:05d}-0{ordinal}", "amount": "100", "currency": "USD"}
            for ordinal in range(1, 3)
        )
        request = replace(
            request,
            left_records=left,
            right_records=right,
            mode="many-to-many",
            target_currency="USD",
            fx_rates=(
                {
                    "base_currency": "EUR",
                    "quote_currency": "USD",
                    "rate": "2",
                    "rate_type": "spot",
                    "source": "synthetic-domain-scale",
                    "effective_at": "2026-08-01",
                },
            ),
        )
    else:
        left = tuple(
            {**common, "id": f"L-{index:05d}-0{ordinal}", "amount": amount, "currency": "USD"}
            for ordinal, amount in enumerate(("70", "30"), start=1)
        )
        right = tuple(
            {**common, "id": f"R-{index:05d}-0{ordinal}", "amount": amount, "currency": "USD"}
            for ordinal, amount in enumerate(("60", "20"), start=1)
        )
        request = replace(
            request,
            left_records=left,
            right_records=right,
            mode="portfolio",
            allow_partial_settlement=True,
        )
    return mode, replace(request, amount_tolerance="0")


def _environment() -> dict[str, object]:
    import os

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": int(os.cpu_count() or 1),
    }


def _direct_decision_digests(
    application: GroupedMatchingApplicationService,
    request: MatchingStrategyRequest,
) -> tuple[str, ...]:
    policy = GroupedMatchPolicy(
        mode=request.mode,  # type: ignore[arg-type]
        netting_mode=request.netting_mode,
        portfolio_allow_partial_settlement=request.allow_partial_settlement,
    )
    grouped_request = GroupedMatchRequest(
        left_records=request.left_records,
        right_records=request.right_records,
        policy=policy,
        left_fee_field=request.left_fee_field,
        right_fee_field=request.right_fee_field,
        target_currency=request.target_currency,
        fx_rates=request.fx_rates,
    )
    if request.mode == "portfolio":
        result = application.execute_portfolio(grouped_request)
        return tuple(decision.decision_digest for decision in result.decisions)
    return (application.execute(grouped_request).decision_digest,)


def run_grouped_matching_domain_scale(
    *, partitions: int = DOMAIN_SCALE_PARTITIONS, permutation_stride: int = 100
) -> GroupedMatchingDomainScaleResult:
    """Run the domain-diverse profile or a smaller deterministic test shape."""

    if not 1 <= partitions <= DOMAIN_SCALE_PARTITIONS or not 1 <= permutation_stride <= partitions:
        raise ValueError("partitions and permutation_stride are outside the declared profile bounds")
    strategy = GroupedSubsetSumStrategy()
    application = GroupedMatchingApplicationService()
    mode_counts: Counter[str] = Counter()
    matched = ambiguous = unmatched = adapter_mismatches = permutation_mismatches = evaluations = 0
    decisions: list[dict[str, object]] = []
    tracemalloc.start()
    started = time.perf_counter()
    for index in range(partitions):
        mode, request = _request(index)
        mode_counts[mode] += 1
        result = strategy.execute(request)
        direct_digests = _direct_decision_digests(application, request)
        strategy_digests = tuple(str(row.get("decision_digest", "")) for row in result.results)
        if strategy_digests != direct_digests:
            adapter_mismatches += 1
        statuses = tuple(str(row.get("status", "")) for row in result.results)
        if any(status == "ambiguous" for status in statuses):
            ambiguous += 1
        elif any(status == "matched" for status in statuses):
            matched += 1
        else:
            unmatched += 1
        evaluations += sum(int(str(row.get("search_evaluations", 0))) for row in result.results)
        decisions.append(
            {
                "index": index,
                "mode": mode,
                "status": statuses,
                "decision_digests": strategy_digests,
            }
        )
        if index % permutation_stride == 0:
            permuted = replace(
                request,
                left_records=tuple(reversed(request.left_records)),
                right_records=tuple(reversed(request.right_records)),
            )
            permuted_result = strategy.execute(permuted)
            permuted_digests = tuple(str(row.get("decision_digest", "")) for row in permuted_result.results)
            if permuted_digests != strategy_digests:
                permutation_mismatches += 1
    runtime = max(time.perf_counter() - started, 0.0)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    decision_digest = _digest(decisions)
    stable: dict[str, object] = {
        "schema_version": DOMAIN_SCALE_SCHEMA_VERSION,
        "profile_id": DOMAIN_SCALE_PROFILE_ID,
        "partitions": partitions,
        "records": partitions * DOMAIN_SCALE_RECORDS_PER_PARTITION,
        "mode_counts": dict(sorted(mode_counts.items())),
        "matched_partitions": matched,
        "ambiguous_partitions": ambiguous,
        "unmatched_partitions": unmatched,
        "adapter_mismatches": adapter_mismatches,
        "permutation_mismatches": permutation_mismatches,
        "strategy_evaluations": evaluations,
        "decision_digest": decision_digest,
        "limitations": list(LIMITATIONS),
    }
    return GroupedMatchingDomainScaleResult(
        schema_version=DOMAIN_SCALE_SCHEMA_VERSION,
        profile_id=DOMAIN_SCALE_PROFILE_ID,
        partitions=partitions,
        records=partitions * DOMAIN_SCALE_RECORDS_PER_PARTITION,
        mode_counts=dict(sorted(mode_counts.items())),
        matched_partitions=matched,
        ambiguous_partitions=ambiguous,
        unmatched_partitions=unmatched,
        adapter_mismatches=adapter_mismatches,
        permutation_mismatches=permutation_mismatches,
        strategy_evaluations=evaluations,
        decision_digest=decision_digest,
        limitations=LIMITATIONS,
        observed_runtime_seconds=round(runtime, 4),
        observed_peak_memory_mb=round(peak / (1024 * 1024), 4),
        environment=_environment(),
        manifest_digest=_digest(stable),
    )


def verify_grouped_matching_domain_scale(result: GroupedMatchingDomainScaleResult) -> None:
    """Verify the full declared 10K structural contract."""

    if result.schema_version != DOMAIN_SCALE_SCHEMA_VERSION or result.profile_id != DOMAIN_SCALE_PROFILE_ID:
        raise AssertionError("domain-diverse matching profile identity mismatch")
    if result.partitions != DOMAIN_SCALE_PARTITIONS or result.records != DOMAIN_SCALE_RECORDS:
        raise AssertionError("domain-diverse matching profile shape mismatch")
    base_count, remainder = divmod(DOMAIN_SCALE_PARTITIONS, len(DOMAIN_SCALE_MODES))
    expected_counts = {
        mode: base_count + int(index < remainder)
        for index, mode in enumerate(DOMAIN_SCALE_MODES)
    }
    if result.mode_counts != expected_counts:
        raise AssertionError("domain-diverse matching mode counts mismatch")
    expected_ambiguous = result.mode_counts["portfolio-partial"]
    expected_matched = result.partitions - expected_ambiguous
    if result.matched_partitions != expected_matched or result.ambiguous_partitions != expected_ambiguous:
        raise AssertionError("domain-diverse profile status counts drifted from its declared ambiguity cases")
    if result.unmatched_partitions:
        raise AssertionError("domain-diverse profile contains an unexpected unmatched partition")
    if result.adapter_mismatches or result.permutation_mismatches:
        raise AssertionError("domain-diverse adapter or permutation parity failed")
    if not result.decision_digest or not result.manifest_digest:
        raise AssertionError("domain-diverse profile is missing integrity digests")


__all__ = [
    "DOMAIN_SCALE_MODES",
    "DOMAIN_SCALE_PARTITIONS",
    "DOMAIN_SCALE_PROFILE_ID",
    "DOMAIN_SCALE_RECORDS",
    "GroupedMatchingDomainScaleResult",
    "LIMITATIONS",
    "run_grouped_matching_domain_scale",
    "verify_grouped_matching_domain_scale",
]
