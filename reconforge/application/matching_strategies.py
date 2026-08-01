"""Versioned, backend-neutral matching strategy execution contract."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Literal, Protocol

from reconforge.domain.grouped_matching import GroupedNettingMode

StrategyMaturity = Literal["experimental", "beta", "stable"]


class MatchingStrategyContractError(ValueError):
    """Raised when a strategy request or response violates its public contract."""


@dataclass(frozen=True)
class StrategyLimits:
    max_left_records: int
    max_right_records: int
    max_candidates_per_record: int
    max_total_candidate_evaluations: int
    max_date_window_days: int
    max_amount_text_characters: int = 128
    max_left_group_cardinality: int | None = None
    max_right_group_cardinality: int | None = None
    max_group_search_evaluations: int | None = None

    def __post_init__(self) -> None:
        values = (
            self.max_left_records,
            self.max_right_records,
            self.max_candidates_per_record,
            self.max_total_candidate_evaluations,
            self.max_date_window_days,
            self.max_amount_text_characters,
            self.max_left_group_cardinality,
            self.max_right_group_cardinality,
            self.max_group_search_evaluations,
        )
        if any(value is not None and (isinstance(value, bool) or value < 1) for value in values):
            raise MatchingStrategyContractError("Strategy limits must be positive integers.")

    @property
    def as_dict(self) -> dict[str, int]:
        return {key: value for key, value in self.__dict__.items() if value is not None}


@dataclass(frozen=True)
class MatchingStrategyManifest:
    id: str
    version: str
    maturity: StrategyMaturity
    algorithm: str
    supported_modes: tuple[str, ...]
    deterministic_tie_break: str
    explanation_schema: str
    limits: StrategyLimits

    def __post_init__(self) -> None:
        if not self.id or not self.version or not self.algorithm or not self.supported_modes:
            raise MatchingStrategyContractError("Strategy manifest is incomplete.")
        if tuple(sorted(set(self.supported_modes))) != self.supported_modes:
            raise MatchingStrategyContractError("Strategy modes must be unique and canonically sorted.")

    @property
    def digest(self) -> str:
        return _digest(
            {
                "algorithm": self.algorithm,
                "deterministic_tie_break": self.deterministic_tie_break,
                "explanation_schema": self.explanation_schema,
                "id": self.id,
                "limits": self.limits.as_dict,
                "maturity": self.maturity,
                "supported_modes": self.supported_modes,
                "version": self.version,
            }
        )


@dataclass(frozen=True)
class MatchingStrategyRequest:
    left_records: tuple[Mapping[str, object], ...]
    right_records: tuple[Mapping[str, object], ...]
    left_id_field: str = "id"
    right_id_field: str = "id"
    amount_field: str = "amount"
    date_field: str = "date"
    reference_field: str = "reference"
    exact_fields: str = ""
    amount_tolerance: str = "0"
    date_window_days: int = 0
    mode: str = "one-to-one"
    currency_field: str = "currency"
    partition_field: str = "partition"
    left_fee_field: str = "fee"
    right_fee_field: str = "fee"
    netting_mode: GroupedNettingMode = "gross"
    target_currency: str = ""
    fx_rates: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True)
class MatchingStrategyResult:
    manifest_digest: str
    input_digest: str
    decision_digest: str
    results: tuple[Mapping[str, object], ...]
    exceptions: tuple[Mapping[str, object], ...]
    explanation_schema: str


class MatchingStrategy(Protocol):
    @property
    def manifest(self) -> MatchingStrategyManifest: ...

    def execute(self, request: MatchingStrategyRequest) -> MatchingStrategyResult: ...


class MatchingStrategyRegistry:
    """Immutable registry that rejects ambiguous strategy identities."""

    def __init__(self, strategies: tuple[MatchingStrategy, ...]) -> None:
        entries: dict[str, MatchingStrategy] = {}
        for strategy in strategies:
            identity = f"{strategy.manifest.id}@{strategy.manifest.version}"
            if identity in entries:
                raise MatchingStrategyContractError("Duplicate matching strategy identity.")
            entries[identity] = strategy
        self._entries = MappingProxyType(entries)

    def get(self, strategy_id: str, version: str) -> MatchingStrategy:
        try:
            return self._entries[f"{strategy_id}@{version}"]
        except KeyError as exc:
            raise MatchingStrategyContractError("Matching strategy is not registered.") from exc

    @property
    def manifests(self) -> tuple[MatchingStrategyManifest, ...]:
        return tuple(self._entries[key].manifest for key in sorted(self._entries))


def canonical_payload(value: object) -> object:
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise MatchingStrategyContractError("Strategy payload contains a non-finite Decimal.")
        normalized = Decimal("0") if value == 0 else value.normalize()
        return format(normalized, "f")
    if isinstance(value, float):
        raise MatchingStrategyContractError("Strategy payload cannot contain binary floating point.")
    if isinstance(value, Mapping):
        normalized_map: dict[str, object] = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            name = str(key)
            if name in normalized_map:
                raise MatchingStrategyContractError("Strategy payload contains colliding field names.")
            normalized_map[name] = canonical_payload(item)
        return normalized_map
    if isinstance(value, list | tuple):
        return [canonical_payload(item) for item in value]
    raise MatchingStrategyContractError("Strategy payload contains an unsupported value.")


def _digest(value: object) -> str:
    encoded = json.dumps(canonical_payload(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def request_digest(request: MatchingStrategyRequest, manifest_digest: str) -> str:
    def canonical_records(records: tuple[Mapping[str, object], ...]) -> list[object]:
        normalized = [canonical_payload(record) for record in records]
        return sorted(
            normalized,
            key=lambda record: json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        )

    return _digest(
        {
            "amount_field": request.amount_field,
            "amount_tolerance": request.amount_tolerance,
            "date_field": request.date_field,
            "date_window_days": request.date_window_days,
            "currency_field": request.currency_field,
            "exact_fields": request.exact_fields,
            "left_id_field": request.left_id_field,
            "left_records": canonical_records(request.left_records),
            "manifest_digest": manifest_digest,
            "mode": request.mode,
            "partition_field": request.partition_field,
            "reference_field": request.reference_field,
            "right_id_field": request.right_id_field,
            "right_fee_field": request.right_fee_field,
            "right_records": canonical_records(request.right_records),
            "left_fee_field": request.left_fee_field,
            "netting_mode": request.netting_mode,
            "target_currency": request.target_currency,
            "fx_rates": list(canonical_records(request.fx_rates)),
        }
    )


def result_digest(*, manifest_digest: str, input_digest: str, results: object, exceptions: object) -> str:
    return _digest(
        {
            "exceptions": exceptions,
            "input_digest": input_digest,
            "manifest_digest": manifest_digest,
            "results": results,
        }
    )
