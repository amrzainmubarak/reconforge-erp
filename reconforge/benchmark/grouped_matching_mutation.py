"""Bounded mutation campaign for critical grouped-matching decisions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from reconforge.application.matching_strategies import MatchingStrategyRequest
from reconforge.benchmark.grouped_matching_replay import (
    _execute_partition,
    _partition_requests,
)


@dataclass(frozen=True)
class MatchingMutationResult:
    campaign_id: str
    mutants: int
    killed: int
    survivors: tuple[str, ...]
    baseline_digest: str

    @property
    def kill_ratio(self) -> Decimal:
        return Decimal(self.killed) / Decimal(self.mutants) if self.mutants else Decimal("0")

    def to_dict(self) -> dict[str, object]:
        return {
            "campaign_id": self.campaign_id,
            "mutants": self.mutants,
            "killed": self.killed,
            "survivors": list(self.survivors),
            "kill_ratio": str(self.kill_ratio),
            "baseline_digest": self.baseline_digest,
            "limitations": [
                "Bounded request-level mutants only; no source-code mutation engine score is claimed.",
                "Synthetic grouped matching inputs; PostgreSQL runtime, fuzzing, and domain-wide mutation remain unverified.",
            ],
        }


def _with_amount(request: MatchingStrategyRequest, amount: str) -> MatchingStrategyRequest:
    first = dict(request.left_records[0])
    first["amount"] = amount
    return MatchingStrategyRequest(
        left_records=(first,) + request.left_records[1:],
        right_records=request.right_records,
        mode=request.mode,
        amount_tolerance=request.amount_tolerance,
        date_window_days=request.date_window_days,
        allow_partial_settlement=request.allow_partial_settlement,
    )


def run_grouped_matching_mutation_campaign() -> MatchingMutationResult:
    requests = _partition_requests()
    baseline, _ = _execute_partition(requests[0])
    mutants = (
        ("amount_plus_one_cent", requests[0], _with_amount(requests[0], "100.01")),
        ("amount_minus_one_cent", requests[0], _with_amount(requests[0], "99.99")),
        (
            "partial_settlement_disabled",
            requests[3],
            MatchingStrategyRequest(
                left_records=requests[3].left_records,
                right_records=requests[3].right_records,
                mode=requests[3].mode,
                amount_tolerance=requests[3].amount_tolerance,
                date_window_days=requests[3].date_window_days,
                allow_partial_settlement=False,
            ),
        ),
    )
    survivors: list[str] = []
    for name, original, mutant in mutants:
        original_digest, _ = _execute_partition(original)
        digest, _ = _execute_partition(mutant)
        if digest == original_digest:
            survivors.append(name)
    return MatchingMutationResult(
        campaign_id="grouped-matching-mutation/synthetic-v1",
        mutants=len(mutants),
        killed=len(mutants) - len(survivors),
        survivors=tuple(survivors),
        baseline_digest=baseline,
    )


def verify_mutation_campaign(result: MatchingMutationResult) -> None:
    if result.mutants != 3:
        raise AssertionError("unexpected mutation campaign size")
    if result.killed != result.mutants or result.survivors:
        raise AssertionError("critical grouped-matching mutant survived")
