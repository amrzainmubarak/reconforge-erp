"""Captured monetary interpretation for integer-valued ledger entries."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from reconforge.utils.money import CurrencyRegistryContext, InvalidAmountError

POLICY_COLUMNS = (
    "currency_precision",
    "currency_rounding_policy",
    "currency_registry_version",
    "currency_registry_digest",
)


class FinancePolicyError(ValueError):
    """A monetary interpretation cannot be established from retained evidence."""


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("duplicate snapshot key")
        values[key] = value
    return values


def verified_registry_context(payload: object) -> CurrencyRegistryContext:
    """Validate a bounded persisted snapshot without installing global state."""

    try:
        if isinstance(payload, str):
            if len(payload.encode("utf-8")) > 1_000_000:
                raise ValueError("snapshot exceeds size limit")
            payload = json.loads(payload, object_pairs_hook=_unique_pairs)
        if not isinstance(payload, Mapping):
            raise ValueError("snapshot is missing")
        return CurrencyRegistryContext.from_snapshot(payload)
    except (InvalidAmountError, TypeError, ValueError) as exc:
        raise FinancePolicyError(
            "finance_currency_policy_invalid: retained currency snapshot is missing or invalid; "
            "restore and verify its original evidence."
        ) from exc


@dataclass(frozen=True)
class FinanceCurrencyPolicy:
    """One currency's immutable scale, rounding and registry provenance."""

    currency_code: str
    precision: int
    rounding_policy: str
    registry_version: str
    registry_digest: str

    @classmethod
    def capture(cls, currency_code: str, context: CurrencyRegistryContext) -> FinanceCurrencyPolicy:
        resolved = context.resolve(currency_code)
        return cls(
            resolved.spec.code,
            resolved.spec.minor_units,
            resolved.spec.rounding_policy,
            resolved.registry_version,
            resolved.registry_digest,
        )

    @classmethod
    def verify_record(
        cls, record: Mapping[str, object], context: CurrencyRegistryContext
    ) -> FinanceCurrencyPolicy:
        if any(record.get(column) is None for column in POLICY_COLUMNS):
            raise FinancePolicyError(
                "finance_currency_policy_unverified: legacy entry retains raw minor units but has no "
                "verified monetary policy; obtain independently reviewed historical policy evidence "
                "before interpreting or changing this entry."
            )
        policy = cls.capture(str(record["currency_code"]), context)
        if tuple(record[column] for column in POLICY_COLUMNS) != policy.values():
            raise FinancePolicyError(
                "finance_currency_policy_invalid: entry policy does not match its retained snapshot."
            )
        return policy

    def values(self) -> tuple[int, str, str, str]:
        return self.precision, self.rounding_policy, self.registry_version, self.registry_digest

    def metadata(self) -> dict[str, object]:
        return dict(zip(POLICY_COLUMNS, self.values(), strict=True))

    def require_compatible(self, other: FinanceCurrencyPolicy) -> None:
        if self != other:
            raise FinancePolicyError(
                "finance_currency_policy_mismatch: amounts have incompatible retained monetary "
                "policies; reconcile the policies explicitly before aggregation."
            )
