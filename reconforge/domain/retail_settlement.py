"""Deterministic, non-posting retail POS to processor settlement control.

This slice intentionally reconciles exported POS batches with exported
processor settlements.  It does not post journals, contact a processor, or
claim completeness for retail operations.  Every monetary operation stays in
the installed ``Money``/currency policy and every decision carries a digest.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal

from reconforge.utils.money import Money

RETAIL_SETTLEMENT_SCHEMA_VERSION = 1
RETAIL_SETTLEMENT_ALGORITHM_VERSION = "retail-pos-settlement-v1"
RetailSettlementStatus = Literal[
    "matched",
    "exception",
    "unmatched_pos",
    "unmatched_settlement",
    "ambiguous",
]
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")


class RetailSettlementError(ValueError):
    """Raised when a retail settlement input violates the closed contract."""


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.strip()):
        raise RetailSettlementError(f"{field} is invalid.")
    return value.strip()


def _iso_date(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise RetailSettlementError(f"{field} must be an ISO-8601 date.")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise RetailSettlementError(f"{field} must be an ISO-8601 date.") from exc


def _money(value: object, currency: str, field: str) -> Money:
    if isinstance(value, (bool, float)):
        raise RetailSettlementError(f"{field} must use an exact decimal amount.")
    try:
        result = Money.from_exact(value, currency)
    except Exception as exc:  # Money exposes several precise policy errors.
        raise RetailSettlementError(f"{field} is not a valid {currency} amount.") from exc
    if not result.amount.is_finite() or result.amount < 0:
        raise RetailSettlementError(f"{field} must be finite and non-negative.")
    return result


def _same_currency(values: tuple[Money, ...], currency: str, field: str) -> None:
    if any(value.currency != currency for value in values):
        raise RetailSettlementError(f"{field} currency does not match the batch currency.")


def _amount_text(value: Money) -> str:
    normalized = value.amount.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _money_dict(value: Money) -> dict[str, object]:
    return value.to_canonical_dict()


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _decision_sort_key(item: Mapping[str, object]) -> tuple[str, str, str, tuple[str, ...]]:
    """Return the stable ordering key used by every settlement artifact."""

    store_id = item.get("store_id")
    batch_id = item.get("batch_id")
    status = item.get("status")
    settlement_ids = item.get("settlement_ids")
    if not isinstance(store_id, str) or not isinstance(batch_id, str) or not isinstance(status, str):
        raise RetailSettlementError("settlement decision identity is invalid.")
    if not isinstance(settlement_ids, list) or any(not isinstance(value, str) for value in settlement_ids):
        raise RetailSettlementError("settlement decision references are invalid.")
    return store_id, batch_id, status, tuple(settlement_ids)


def retail_settlement_decision_digest(
    *,
    algorithm_version: object,
    schema_version: object,
    tolerance: object,
    input_digests: object,
    decisions: object,
) -> str:
    """Rebuild the canonical decision digest from a serialized run payload.

    This deliberately accepts serialized values so report readers can verify the
    exact bytes that were persisted without silently normalizing a mutated
    decision back into a valid in-memory object.
    """

    if not isinstance(input_digests, list) or any(not isinstance(value, str) for value in input_digests):
        raise RetailSettlementError("settlement input digests are invalid.")
    if not isinstance(decisions, list) or any(not isinstance(value, dict) for value in decisions):
        raise RetailSettlementError("settlement decisions are invalid.")
    return _digest(
        {
            "algorithm_version": algorithm_version,
            "decisions": decisions,
            "input_digests": sorted(input_digests),
            "schema_version": schema_version,
            "tolerance": tolerance,
        }
    )


def verify_retail_settlement_payload(payload: Mapping[str, object]) -> None:
    """Verify canonical ordering, status counts, and the nested decision digest."""

    if payload.get("schema_version") != RETAIL_SETTLEMENT_SCHEMA_VERSION:
        raise RetailSettlementError("retail settlement schema version is unsupported.")
    if payload.get("algorithm_version") != RETAIL_SETTLEMENT_ALGORITHM_VERSION:
        raise RetailSettlementError("retail settlement algorithm version is unsupported.")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or any(not isinstance(value, dict) for value in decisions):
        raise RetailSettlementError("retail settlement decisions are invalid.")
    if decisions != sorted(decisions, key=_decision_sort_key):
        raise RetailSettlementError("retail settlement decisions are not canonical.")
    statuses = {"matched", "exception", "unmatched_pos", "unmatched_settlement", "ambiguous"}
    counts: dict[str, int] = {}
    for decision in decisions:
        status = decision.get("status")
        if status not in statuses:
            raise RetailSettlementError("retail settlement decision status is invalid.")
        counts[status] = counts.get(status, 0) + 1
    if payload.get("status_counts") != dict(sorted(counts.items())):
        raise RetailSettlementError("retail settlement status counts are inconsistent.")
    expected = retail_settlement_decision_digest(
        algorithm_version=payload.get("algorithm_version"),
        schema_version=payload.get("schema_version"),
        tolerance=payload.get("tolerance"),
        input_digests=payload.get("input_digests"),
        decisions=decisions,
    )
    if payload.get("decision_digest") != expected:
        raise RetailSettlementError("retail settlement decision digest verification failed.")


@dataclass(frozen=True)
class RetailPosBatch:
    """One immutable POS close batch exported by a store."""

    batch_id: str
    store_id: str
    business_date: str
    currency: str
    card_sales: Money
    card_refunds: Money
    cash_sales: Money
    cash_refunds: Money
    gift_sales: Money
    gift_refunds: Money
    transaction_count: int
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "batch_id", _identifier(self.batch_id, "POS batch ID"))
        object.__setattr__(self, "store_id", _identifier(self.store_id, "POS store ID"))
        object.__setattr__(self, "business_date", _iso_date(self.business_date, "POS business date"))
        currency = self.currency.strip().upper() if isinstance(self.currency, str) else ""
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise RetailSettlementError("POS batch currency is invalid.")
        object.__setattr__(self, "currency", currency)
        amounts = (
            self.card_sales,
            self.card_refunds,
            self.cash_sales,
            self.cash_refunds,
            self.gift_sales,
            self.gift_refunds,
        )
        if not all(isinstance(value, Money) for value in amounts):
            raise RetailSettlementError("POS batch amounts must use Money.")
        _same_currency(amounts, currency, "POS batch")
        if isinstance(self.transaction_count, bool) or not isinstance(self.transaction_count, int) or self.transaction_count < 1:
            raise RetailSettlementError("POS transaction count must be a positive integer.")
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "POS source reference"))

    @property
    def card_net(self) -> Money:
        return self.card_sales - self.card_refunds

    @property
    def total_net_sales(self) -> Money:
        return self.card_sales + self.cash_sales + self.gift_sales - self.card_refunds - self.cash_refunds - self.gift_refunds

    def to_dict(self) -> dict[str, object]:
        return {
            "batch_id": self.batch_id,
            "business_date": self.business_date,
            "card_refunds": _money_dict(self.card_refunds),
            "card_sales": _money_dict(self.card_sales),
            "cash_refunds": _money_dict(self.cash_refunds),
            "cash_sales": _money_dict(self.cash_sales),
            "currency": self.currency,
            "gift_refunds": _money_dict(self.gift_refunds),
            "gift_sales": _money_dict(self.gift_sales),
            "source_reference": self.source_reference,
            "store_id": self.store_id,
            "total_net_sales": _money_dict(self.total_net_sales),
            "transaction_count": self.transaction_count,
        }


@dataclass(frozen=True)
class RetailProcessorSettlement:
    """One immutable processor settlement exported by a payment provider."""

    settlement_id: str
    batch_id: str
    store_id: str
    settlement_date: str
    currency: str
    card_gross: Money
    refunds: Money
    fees: Money
    chargebacks: Money
    net_settlement: Money
    provider_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "settlement_id", _identifier(self.settlement_id, "settlement ID"))
        object.__setattr__(self, "batch_id", _identifier(self.batch_id, "settlement batch ID"))
        object.__setattr__(self, "store_id", _identifier(self.store_id, "settlement store ID"))
        object.__setattr__(self, "settlement_date", _iso_date(self.settlement_date, "settlement date"))
        currency = self.currency.strip().upper() if isinstance(self.currency, str) else ""
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise RetailSettlementError("settlement currency is invalid.")
        object.__setattr__(self, "currency", currency)
        amounts = (self.card_gross, self.refunds, self.fees, self.chargebacks, self.net_settlement)
        if not all(isinstance(value, Money) for value in amounts):
            raise RetailSettlementError("settlement amounts must use Money.")
        _same_currency(amounts, currency, "settlement")
        object.__setattr__(self, "provider_reference", _identifier(self.provider_reference, "provider reference"))

    def to_dict(self) -> dict[str, object]:
        return {
            "batch_id": self.batch_id,
            "card_gross": _money_dict(self.card_gross),
            "chargebacks": _money_dict(self.chargebacks),
            "currency": self.currency,
            "fees": _money_dict(self.fees),
            "net_settlement": _money_dict(self.net_settlement),
            "provider_reference": self.provider_reference,
            "refunds": _money_dict(self.refunds),
            "settlement_date": self.settlement_date,
            "settlement_id": self.settlement_id,
            "store_id": self.store_id,
        }


@dataclass(frozen=True)
class RetailSettlementDecision:
    """One explainable result, including every material variance."""

    batch_id: str
    store_id: str
    status: RetailSettlementStatus
    pos_total_net_sales: Money | None
    expected_card_net: Money | None
    settlement_net: Money | None
    card_gross_variance: Money | None
    refund_variance: Money | None
    net_variance: Money | None
    settlement_ids: tuple[str, ...]
    reason_code: str

    def to_dict(self) -> dict[str, object]:
        return {
            "batch_id": self.batch_id,
            "card_gross_variance": _money_dict(self.card_gross_variance) if self.card_gross_variance else None,
            "expected_card_net": _money_dict(self.expected_card_net) if self.expected_card_net else None,
            "net_variance": _money_dict(self.net_variance) if self.net_variance else None,
            "pos_total_net_sales": _money_dict(self.pos_total_net_sales) if self.pos_total_net_sales else None,
            "reason_code": self.reason_code,
            "refund_variance": _money_dict(self.refund_variance) if self.refund_variance else None,
            "settlement_ids": list(self.settlement_ids),
            "settlement_net": _money_dict(self.settlement_net) if self.settlement_net else None,
            "status": self.status,
            "store_id": self.store_id,
        }


@dataclass(frozen=True)
class RetailSettlementRun:
    """Replay-verifiable output of one POS settlement control run."""

    schema_version: int
    algorithm_version: str
    tolerance: Money
    input_digests: tuple[str, ...]
    decisions: tuple[RetailSettlementDecision, ...]
    decision_digest: str

    @property
    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for decision in self.decisions:
            counts[decision.status] = counts.get(decision.status, 0) + 1
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "decision_digest": self.decision_digest,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "input_digests": list(self.input_digests),
            "schema_version": self.schema_version,
            "status_counts": self.status_counts,
            "tolerance": _money_dict(self.tolerance),
        }


def run_retail_settlement(
    pos_batches: tuple[RetailPosBatch, ...],
    settlements: tuple[RetailProcessorSettlement, ...],
    *,
    tolerance: Money,
    input_digests: tuple[str, ...] = (),
) -> RetailSettlementRun:
    """Reconcile exported POS batches with processor settlements fail-closed."""

    if not isinstance(tolerance, Money) or tolerance.amount < 0 or not tolerance.amount.is_finite():
        raise RetailSettlementError("settlement tolerance must be finite non-negative Money.")
    if not pos_batches and not settlements:
        raise RetailSettlementError("settlement run requires at least one input record.")
    pos_ids = [batch.batch_id for batch in pos_batches]
    if len(pos_ids) != len(set(pos_ids)):
        raise RetailSettlementError("POS batch IDs must be unique.")
    settlement_ids = [item.settlement_id for item in settlements]
    if len(settlement_ids) != len(set(settlement_ids)):
        raise RetailSettlementError("settlement IDs must be unique.")
    record_currencies = [batch.currency for batch in pos_batches] + [item.currency for item in settlements]
    if any(currency != tolerance.currency for currency in record_currencies):
        raise RetailSettlementError("all records and tolerance must use one currency.")
    grouped: dict[str, list[RetailProcessorSettlement]] = {}
    for settlement in settlements:
        grouped.setdefault(settlement.batch_id, []).append(settlement)
    decisions: list[RetailSettlementDecision] = []
    pos_by_id = {batch.batch_id: batch for batch in pos_batches}
    for batch in sorted(pos_batches, key=lambda item: (item.store_id, item.business_date, item.batch_id)):
        matches = sorted(grouped.get(batch.batch_id, []), key=lambda item: item.settlement_id)
        if not matches:
            decisions.append(
                RetailSettlementDecision(
                    batch.batch_id,
                    batch.store_id,
                    "unmatched_pos",
                    batch.total_net_sales,
                    batch.card_net,
                    None,
                    None,
                    None,
                    None,
                    (),
                    "POS_BATCH_HAS_NO_SETTLEMENT",
                )
            )
            continue
        if len(matches) > 1:
            decisions.append(
                RetailSettlementDecision(
                    batch.batch_id,
                    batch.store_id,
                    "ambiguous",
                    batch.total_net_sales,
                    batch.card_net,
                    None,
                    None,
                    None,
                    None,
                    tuple(item.settlement_id for item in matches),
                    "MULTIPLE_SETTLEMENTS_FOR_POS_BATCH",
                )
            )
            continue
        settlement = matches[0]
        if settlement.store_id != batch.store_id or settlement.currency != batch.currency:
            decisions.append(
                RetailSettlementDecision(
                    batch.batch_id,
                    batch.store_id,
                    "exception",
                    batch.total_net_sales,
                    batch.card_net,
                    settlement.net_settlement,
                    settlement.card_gross - batch.card_sales,
                    settlement.refunds - batch.card_refunds,
                    settlement.net_settlement - (batch.card_net - settlement.fees - settlement.chargebacks),
                    (settlement.settlement_id,),
                    "SETTLEMENT_SCOPE_OR_CURRENCY_MISMATCH",
                )
            )
            continue
        expected = batch.card_net - settlement.fees - settlement.chargebacks
        card_variance = settlement.card_gross - batch.card_sales
        refund_variance = settlement.refunds - batch.card_refunds
        net_variance = settlement.net_settlement - expected
        matched = all(abs(value.amount) <= tolerance.amount for value in (card_variance, refund_variance, net_variance))
        decisions.append(
            RetailSettlementDecision(
                batch.batch_id,
                batch.store_id,
                "matched" if matched else "exception",
                batch.total_net_sales,
                expected,
                settlement.net_settlement,
                card_variance,
                refund_variance,
                net_variance,
                (settlement.settlement_id,),
                "POS_SETTLEMENT_RECONCILED" if matched else "POS_SETTLEMENT_VARIANCE_ABOVE_TOLERANCE",
            )
        )
    for settlement in sorted(settlements, key=lambda item: (item.store_id, item.settlement_date, item.settlement_id)):
        if settlement.batch_id not in pos_by_id:
            decisions.append(
                RetailSettlementDecision(
                    settlement.batch_id,
                    settlement.store_id,
                    "unmatched_settlement",
                    None,
                    None,
                    settlement.net_settlement,
                    None,
                    None,
                    None,
                    (settlement.settlement_id,),
                    "SETTLEMENT_HAS_NO_POS_BATCH",
                )
            )
    ordered = tuple(sorted(decisions, key=lambda item: (item.store_id, item.batch_id, item.status, item.settlement_ids)))
    payload = {
        "algorithm_version": RETAIL_SETTLEMENT_ALGORITHM_VERSION,
        "decisions": [item.to_dict() for item in ordered],
        "input_digests": sorted(input_digests),
        "schema_version": RETAIL_SETTLEMENT_SCHEMA_VERSION,
        "tolerance": _money_dict(tolerance),
    }
    return RetailSettlementRun(
        RETAIL_SETTLEMENT_SCHEMA_VERSION,
        RETAIL_SETTLEMENT_ALGORITHM_VERSION,
        tolerance,
        tuple(sorted(input_digests)),
        ordered,
        retail_settlement_decision_digest(
            algorithm_version=payload["algorithm_version"],
            schema_version=payload["schema_version"],
            tolerance=payload["tolerance"],
            input_digests=payload["input_digests"],
            decisions=payload["decisions"],
        ),
    )


__all__ = [
    "RETAIL_SETTLEMENT_ALGORITHM_VERSION",
    "RETAIL_SETTLEMENT_SCHEMA_VERSION",
    "RetailPosBatch",
    "RetailProcessorSettlement",
    "RetailSettlementDecision",
    "RetailSettlementError",
    "RetailSettlementRun",
    "retail_settlement_decision_digest",
    "run_retail_settlement",
    "verify_retail_settlement_payload",
]
