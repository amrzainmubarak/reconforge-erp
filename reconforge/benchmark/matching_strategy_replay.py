"""Deterministic replay profile for every published matching strategy family.

This is a bounded synthetic correctness profile.  It deliberately exercises
the public registry and JSON result envelope, not a live provider or a
production-capacity claim.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from reconforge.application.matching_strategies import (
    MatchingStrategy,
    MatchingStrategyRequest,
    canonical_payload,
    replay_strategy_result,
)
from reconforge.infrastructure.carry_forward_strategy import CarryForwardFifoStrategy
from reconforge.infrastructure.grouped_matching_strategy import GroupedSubsetSumStrategy
from reconforge.infrastructure.matching_strategy_registry import build_matching_strategy_registry
from reconforge.infrastructure.reversal_matching_strategy import ReversalPairingStrategy
from reconforge.workers.postgres_grouped_matching import PostgresGroupedMatchingAdapter
from reconforge.workers.postgres_grouped_matching import _request as _grouped_request
from reconforge.workers.postgres_reconciliation import ReconciliationExecutionContext, ReconciliationInputPartition
from reconforge.workers.postgres_sequential_matching import PostgresSequentialMatchingAdapter
from reconforge.workers.postgres_sequential_matching import _request as _sequential_request

if TYPE_CHECKING:
    from reconforge.platform.matching import MatchingService


@dataclass(frozen=True)
class MatchingStrategyReplayObservation:
    strategy_id: str
    strategy_version: str
    manifest_digest: str
    input_digest: str
    decision_digest: str
    permutation_invariant: bool
    envelope_replay_verified: bool

    def to_payload(self) -> dict[str, object]:
        return {
            "decision_digest": self.decision_digest,
            "envelope_replay_verified": self.envelope_replay_verified,
            "input_digest": self.input_digest,
            "manifest_digest": self.manifest_digest,
            "permutation_invariant": self.permutation_invariant,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
        }


@dataclass(frozen=True)
class MatchingStrategyReplayProfile:
    profile_id: str
    observations: tuple[MatchingStrategyReplayObservation, ...]
    profile_digest: str

    @property
    def strategy_count(self) -> int:
        return len(self.observations)

    def to_payload(self) -> dict[str, object]:
        return {
            "observations": [item.to_payload() for item in self.observations],
            "profile_digest": self.profile_digest,
            "profile_id": self.profile_id,
            "strategy_count": self.strategy_count,
            "synthetic_only": True,
        }


@dataclass(frozen=True)
class WorkerParityObservation:
    adapter: str
    mode: str
    strategy_id: str
    direct_decision_digest: str
    projected_decision_digests: tuple[str, ...]
    permutation_invariant: bool

    @property
    def parity_verified(self) -> bool:
        return (
            bool(self.direct_decision_digest)
            and self.projected_decision_digests == (self.direct_decision_digest,)
            and self.permutation_invariant
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "adapter": self.adapter,
            "direct_decision_digest": self.direct_decision_digest,
            "mode": self.mode,
            "projected_decision_digests": list(self.projected_decision_digests),
            "permutation_invariant": self.permutation_invariant,
            "strategy_id": self.strategy_id,
            "parity_verified": self.parity_verified,
        }


@dataclass(frozen=True)
class WorkerParityProfile:
    profile_id: str
    observations: tuple[WorkerParityObservation, ...]
    profile_digest: str

    @property
    def parity_count(self) -> int:
        return sum(item.parity_verified for item in self.observations)

    def to_payload(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "observations": [
                item.to_payload()
                for item in self.observations
            ],
            "parity_count": self.parity_count,
            "synthetic_only": True,
            "profile_digest": self.profile_digest,
        }


def run_matching_strategy_replay_profile(service: MatchingService) -> MatchingStrategyReplayProfile:
    """Run every registered strategy against its bounded synthetic fixture.

    The profile compares original and record-permuted requests, then verifies
    both result envelopes through the shared replay verifier.  Any digest or
    payload drift raises immediately instead of producing a partial report.
    """

    registry = build_matching_strategy_registry(service)
    cases = _synthetic_cases()
    expected_ids = {manifest.id for manifest in registry.manifests}
    if expected_ids != set(cases):
        raise AssertionError("Replay profile fixture inventory does not cover the strategy registry.")
    observations: list[MatchingStrategyReplayObservation] = []
    for manifest in registry.manifests:
        strategy = registry.get(manifest.id, manifest.version)
        request = cases[manifest.id]
        permuted = _permute_request(request)
        result = strategy.execute(request)
        permuted_result = strategy.execute(permuted)
        replayed = replay_strategy_result(strategy, request, result)
        replayed_permuted = replay_strategy_result(strategy, permuted, permuted_result)
        if result.to_payload() != replayed.to_payload() or permuted_result.to_payload() != replayed_permuted.to_payload():
            raise AssertionError(f"Replay envelope changed for {manifest.id}.")
        if result.to_payload() != permuted_result.to_payload():
            raise AssertionError(f"Record permutation changed deterministic evidence for {manifest.id}.")
        observations.append(
            MatchingStrategyReplayObservation(
                strategy_id=manifest.id,
                strategy_version=manifest.version,
                manifest_digest=manifest.digest,
                input_digest=result.input_digest,
                decision_digest=result.decision_digest,
                permutation_invariant=True,
                envelope_replay_verified=True,
            )
        )
    payload = canonical_payload([item.to_payload() for item in observations])
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return MatchingStrategyReplayProfile(
        profile_id="matching-strategy-registry-replay-v1",
        observations=tuple(observations),
        profile_digest=hashlib.sha256(encoded.encode("ascii")).hexdigest(),
    )


def run_postgres_worker_matching_parity_profile() -> WorkerParityProfile:
    """Compare worker projections with direct strategy digests.

    This profile exercises the provider-neutral worker adapter contract in
    process. It intentionally does not connect to PostgreSQL; live database
    execution is a separate hosted/runtime gate.
    """

    observations: list[WorkerParityObservation] = []
    grouped_cases = {
        mode: (
            GroupedSubsetSumStrategy(),
            {"grouped_matching_mode": mode, "date_window_days": 0, "amount_tolerance": "0"},
        )
        for mode in ("one-to-many", "many-to-one", "many-to-many", "partial-settlement", "portfolio")
    }
    for mode, (grouped_strategy, rule) in grouped_cases.items():
        context = _worker_context(rule)
        permuted_context = _worker_context(rule, reverse=True)
        partition = ReconciliationInputPartition("replay-worker", context.left_inputs, context.right_inputs)
        request = _grouped_request(context, partition.partition_key, partition.left_inputs, partition.right_inputs)
        direct = grouped_strategy.execute(request)
        projected = PostgresGroupedMatchingAdapter().iter_partition_results(context)[0]
        permuted_partition = PostgresGroupedMatchingAdapter().iter_partition_results(permuted_context)[0]
        digests = _lineage_digests(projected.results)
        permuted_request = _grouped_request(
            permuted_context, "replay-worker", permuted_context.left_inputs, permuted_context.right_inputs
        )
        permuted_direct = grouped_strategy.execute(permuted_request)
        permutation_invariant = (
            direct.to_payload() == permuted_direct.to_payload()
            and digests == _lineage_digests(permuted_partition.results)
        )
        observation = WorkerParityObservation(
            "postgres-grouped", mode, grouped_strategy.manifest.id, direct.decision_digest, digests, permutation_invariant
        )
        if not observation.parity_verified:
            raise AssertionError(f"Grouped worker parity failed for {mode}.")
        observations.append(observation)

    sequential_cases: dict[str, MatchingStrategy] = {
        "carry-forward": CarryForwardFifoStrategy(),
        "sequence-window": CarryForwardFifoStrategy(),
        "reversal-pairing": ReversalPairingStrategy(),
    }
    for mode, sequential_strategy in sequential_cases.items():
        rule = {"matching_mode": mode, "date_window_days": 5, "amount_tolerance": "0"}
        context = _worker_context(rule)
        permuted_context = _worker_context(rule, reverse=True)
        partition = ReconciliationInputPartition("replay-worker", context.left_inputs, context.right_inputs)
        request = _sequential_request(context, partition.partition_key, partition.left_inputs, partition.right_inputs)
        direct = sequential_strategy.execute(request)
        projected = PostgresSequentialMatchingAdapter().iter_partition_results(context)[0]
        permuted_partition = PostgresSequentialMatchingAdapter().iter_partition_results(permuted_context)[0]
        digests = _lineage_digests(projected.results)
        permuted_request = _sequential_request(
            permuted_context, "replay-worker", permuted_context.left_inputs, permuted_context.right_inputs
        )
        permuted_direct = sequential_strategy.execute(permuted_request)
        permutation_invariant = (
            direct.to_payload() == permuted_direct.to_payload()
            and digests == _lineage_digests(permuted_partition.results)
        )
        observation = WorkerParityObservation(
            "postgres-sequential", mode, sequential_strategy.manifest.id, direct.decision_digest, digests, permutation_invariant
        )
        if not observation.parity_verified:
            raise AssertionError(f"Sequential worker parity failed for {mode}.")
        observations.append(observation)
    payload = canonical_payload([item.to_payload() for item in observations])
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return WorkerParityProfile(
        profile_id="postgres-worker-strategy-parity-v1",
        observations=tuple(observations),
        profile_digest=hashlib.sha256(encoded.encode("ascii")).hexdigest(),
    )


def run_postgres_domain_diverse_worker_parity_profile() -> WorkerParityProfile:
    """Compare grouped worker projections for six domain-diverse shapes.

    The profile is an in-process provider-neutral contract check.  It uses the
    same bounded cardinality, fee/netting, FX, and partial-settlement shapes as
    the PostgreSQL domain-diverse runtime profile, but deliberately does not
    connect to PostgreSQL or make a capacity claim.
    """

    observations: list[WorkerParityObservation] = []
    strategy = GroupedSubsetSumStrategy()
    adapter = PostgresGroupedMatchingAdapter()
    for mode in _DOMAIN_DIVERSE_PARITY_MODES:
        rule, left, right = _domain_worker_case(mode)
        context = _worker_context_from_records(rule, left, right)
        partition = ReconciliationInputPartition("replay-domain-diverse", context.left_inputs, context.right_inputs)
        request = _grouped_request(context, partition.partition_key, partition.left_inputs, partition.right_inputs)
        direct = strategy.execute(request)
        projected = adapter.iter_partition_results(context)[0]
        digests = _lineage_digests(projected.results)
        permutation_invariant = True
        for reverse_left, reverse_right in ((True, False), (False, True), (True, True)):
            permuted_context = _worker_context_from_records(
                rule,
                left,
                right,
                reverse_left=reverse_left,
                reverse_right=reverse_right,
            )
            permuted_partition = adapter.iter_partition_results(permuted_context)[0]
            permuted_request = _grouped_request(
                permuted_context,
                "replay-domain-diverse",
                permuted_context.left_inputs,
                permuted_context.right_inputs,
            )
            permuted_direct = strategy.execute(permuted_request)
            permutation_invariant = permutation_invariant and (
                direct.to_payload() == permuted_direct.to_payload()
                and digests == _lineage_digests(permuted_partition.results)
            )
        observation = WorkerParityObservation(
            "postgres-grouped",
            mode,
            strategy.manifest.id,
            direct.decision_digest,
            digests,
            permutation_invariant,
        )
        if not observation.parity_verified:
            raise AssertionError(f"Domain-diverse grouped worker parity failed for {mode}.")
        observations.append(observation)
    payload = canonical_payload([item.to_payload() for item in observations])
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return WorkerParityProfile(
        profile_id="postgres-worker-domain-diverse-parity-v1",
        observations=tuple(observations),
        profile_digest=hashlib.sha256(encoded.encode("ascii")).hexdigest(),
    )


_DOMAIN_DIVERSE_PARITY_MODES = (
    "domain-one-to-many",
    "domain-many-to-one",
    "domain-many-to-many",
    "domain-portfolio-net",
    "domain-fx-many-to-many",
    "domain-portfolio-partial",
)


def _domain_worker_case(
    mode: str,
) -> tuple[dict[str, object], tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    """Return one explicit synthetic domain-diverse worker fixture."""

    def record(side: str, record_id: str, amount: str, currency: str, fee: str = "0") -> Mapping[str, object]:
        return {
            "source_id": f"{mode}-{side.lower()}-{record_id}",
            "amount_decimal": amount,
            "date_value": "2026-08-01",
            "currency_code": currency,
            "attributes_json": {"fee": fee},
        }

    left: tuple[Mapping[str, object], ...]
    right: tuple[Mapping[str, object], ...]
    strategy_mode: str
    if mode == "domain-one-to-many":
        left = (record("Left", "l1", "100", "USD"),)
        right = (
            record("Right", "r1", "30", "USD"),
            record("Right", "r2", "30", "USD"),
            record("Right", "r3", "40", "USD"),
        )
        strategy_mode = "one-to-many"
    elif mode == "domain-many-to-one":
        left = (
            record("Left", "l1", "30", "USD"),
            record("Left", "l2", "30", "USD"),
            record("Left", "l3", "40", "USD"),
        )
        right = (record("Right", "r1", "100", "USD"),)
        strategy_mode = "many-to-one"
    elif mode == "domain-many-to-many":
        left = (record("Left", "l1", "30", "USD"), record("Left", "l2", "70", "USD"))
        right = (record("Right", "r1", "25", "USD"), record("Right", "r2", "75", "USD"))
        strategy_mode = "many-to-many"
    elif mode == "domain-portfolio-net":
        left = (record("Left", "l1", "60", "USD", "5"), record("Left", "l2", "40", "USD", "5"))
        right = (record("Right", "r1", "45", "USD"), record("Right", "r2", "45", "USD"))
        strategy_mode = "portfolio"
    elif mode == "domain-fx-many-to-many":
        left = (record("Left", "l1", "50", "EUR"), record("Left", "l2", "50", "EUR"))
        right = (record("Right", "r1", "100", "USD"), record("Right", "r2", "100", "USD"))
        strategy_mode = "many-to-many"
    elif mode == "domain-portfolio-partial":
        left = (record("Left", "l1", "70", "USD"), record("Left", "l2", "30", "USD"))
        right = (record("Right", "r1", "60", "USD"), record("Right", "r2", "20", "USD"))
        strategy_mode = "portfolio"
    else:
        raise ValueError(f"unsupported domain-diverse parity mode: {mode}")

    rule: dict[str, object] = {
        "grouped_matching_mode": strategy_mode,
        "date_window_days": 0,
        "amount_tolerance": "0",
    }
    if mode in {"domain-portfolio-net", "domain-portfolio-partial"}:
        rule.update(
            {
                "netting_mode": "net",
                "left_fee_field": "fee",
                "right_fee_field": "fee",
                "allow_partial_settlement": mode == "domain-portfolio-partial",
            }
        )
    if mode == "domain-fx-many-to-many":
        rule.update(
            {
                "target_currency": "USD",
                "fx_rates": (
                    {
                        "base_currency": "EUR",
                        "quote_currency": "USD",
                        "rate": "2",
                        "rate_type": "spot",
                        "source": "synthetic-domain-parity",
                        "effective_at": "2026-08-01",
                    },
                ),
            }
        )
    return rule, left, right


def _lineage_digests(rows: tuple[Mapping[str, object], ...]) -> tuple[str, ...]:
    values: set[str] = set()
    for row in rows:
        lineage = row.get("lineage")
        if isinstance(lineage, Mapping) and lineage.get("strategy_result_digest"):
            values.add(str(lineage["strategy_result_digest"]))
    return tuple(sorted(values))


def _worker_context(rule: Mapping[str, object], *, reverse: bool = False) -> ReconciliationExecutionContext:
    left: tuple[Mapping[str, object], ...] = (
        {"source_id": "L1", "amount_decimal": "100", "attributes_json": {"date": "2026-08-01", "currency": "USD"}},
    )
    right: tuple[Mapping[str, object], ...] = (
        {"source_id": "R1", "amount_decimal": "40", "attributes_json": {"date": "2026-08-01", "currency": "USD"}},
        {"source_id": "R2", "amount_decimal": "60", "attributes_json": {"date": "2026-08-01", "currency": "USD"}},
    )
    if reverse:
        left = tuple(reversed(left))
        right = tuple(reversed(right))
    return ReconciliationExecutionContext(
        run={"rule_json": dict(rule)},
        left_inputs=left,
        right_inputs=right,
        heartbeat=lambda _progress: {},
        cancellation_requested=lambda: False,
        partition_supplier=lambda: (ReconciliationInputPartition("replay-worker", left, right),),
    )


def _worker_context_from_records(
    rule: Mapping[str, object],
    left: tuple[Mapping[str, object], ...],
    right: tuple[Mapping[str, object], ...],
    *,
    reverse: bool = False,
    reverse_left: bool = False,
    reverse_right: bool = False,
) -> ReconciliationExecutionContext:
    """Build a worker context from explicit canonical synthetic records."""

    ordered_left = tuple(reversed(left)) if reverse or reverse_left else left
    ordered_right = tuple(reversed(right)) if reverse or reverse_right else right
    return ReconciliationExecutionContext(
        run={"rule_json": dict(rule)},
        left_inputs=ordered_left,
        right_inputs=ordered_right,
        heartbeat=lambda _progress: {},
        cancellation_requested=lambda: False,
        partition_supplier=lambda: (ReconciliationInputPartition("replay-domain-diverse", ordered_left, ordered_right),),
    )


def _permute_request(request: MatchingStrategyRequest) -> MatchingStrategyRequest:
    return replace(
        request,
        left_records=tuple(reversed(request.left_records)),
        right_records=tuple(reversed(request.right_records)),
        fx_rates=tuple(reversed(request.fx_rates)),
    )


def _synthetic_cases() -> dict[str, MatchingStrategyRequest]:
    partition = "replay-profile"
    return {
        "indexed-composite-one-to-one": MatchingStrategyRequest(
            left_records=(
                {"id": "L2", "reference": "INV-2", "amount": "20", "date": "2026-01-02"},
                {"id": "L1", "reference": "INV-1", "amount": "10", "date": "2026-01-01"},
            ),
            right_records=(
                {"id": "R1", "reference": "inv/1", "amount": "10", "date": "2026-01-01"},
                {"id": "R2", "reference": "INV-2", "amount": "20", "date": "2026-01-02"},
            ),
        ),
        "bounded-grouped-subset-sum": MatchingStrategyRequest(
            left_records=({"id": "L1", "amount": "10", "currency": "USD", "date": "2026-01-01", "partition": partition},),
            right_records=({"id": "R1", "amount": "10", "currency": "USD", "date": "2026-01-01", "partition": partition},),
            mode="many-to-many",
        ),
        "bounded-fee-aware-one-to-one": MatchingStrategyRequest(
            left_records=({"id": "L1", "amount": "100", "fee": "2", "currency": "USD", "date": "2026-01-01", "partition": partition},),
            right_records=({"id": "R1", "amount": "98", "fee": "0", "currency": "USD", "date": "2026-01-01", "partition": partition},),
            mode="fee-aware",
        ),
        "bounded-fx-aware-one-to-one": MatchingStrategyRequest(
            left_records=({"id": "L1", "amount": "100", "currency": "EUR", "date": "2026-01-01", "partition": partition},),
            right_records=({"id": "R1", "amount": "110", "currency": "USD", "date": "2026-01-01", "partition": partition},),
            mode="fx-aware",
            target_currency="USD",
            fx_rates=({"base_currency": "EUR", "quote_currency": "USD", "rate": "1.1", "source": "SYNTHETIC", "rate_type": "spot"},),
        ),
        "bounded-duplicate-detection": MatchingStrategyRequest(
            left_records=({"id": "L1", "amount": "10", "date": "2026-01-01", "reference": "INV-1", "currency": "USD", "partition": partition},),
            right_records=({"id": "R1", "amount": "10", "date": "2026-01-01", "reference": "INV-1", "currency": "USD", "partition": partition},),
            mode="duplicate-detection",
        ),
        "bounded-carry-forward-fifo": MatchingStrategyRequest(
            left_records=({"id": "O1", "amount": "10", "date": "2026-01-01", "currency": "USD", "partition": partition},),
            right_records=({"id": "S1", "amount": "10", "date": "2026-01-02", "currency": "USD", "partition": partition},),
            mode="carry-forward",
            date_window_days=5,
        ),
        "bounded-reversal-pairing": MatchingStrategyRequest(
            left_records=({"id": "J1", "amount": "10", "date": "2026-01-01", "currency": "USD", "partition": partition},),
            right_records=({"id": "R1", "amount": "-10", "date": "2026-01-02", "currency": "USD", "partition": partition, "reversal_of": "J1"},),
            mode="reversal-pairing",
            date_window_days=5,
        ),
    }
