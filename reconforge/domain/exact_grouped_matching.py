"""Experimental, versioned grouped matching with exact bounded Decimal arithmetic.

This entry point does not replace the existing persisted strategy or submit posts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, Inexact, InvalidOperation, Overflow, localcontext
from math import comb

from reconforge.domain.grouped_matching import (
    GroupedMatchDecision,
    GroupedMatchingError,
    GroupedMatchPolicy,
    GroupedMatchPortfolioResult,
    GroupedRecord,
    find_grouped_match,
    find_grouped_match_portfolio,
)
from reconforge.utils.money import CurrencyRegistryContext, InvalidAmountError

ALGORITHM_VERSION = "exact-bounded-grouped-matching-v2"
_MAX_RECORDS_PER_SIDE = 64
_MAX_DIGITS = 4096
_MAX_ABS_EXPONENT = 4096
_MAX_SEARCH = 25_000
_MAX_CARDINALITY = 4


class ExactGroupedMatchingError(ValueError):
    """A request cannot be evaluated safely within the exact arithmetic budget."""


@dataclass(frozen=True)
class ExactGroupedMatchingResult:
    algorithm_version: str
    input_digest: str
    artifact_digest: str
    total_search_limit: int
    phase_search_limit: int
    currency_registry_version: str
    currency_registry_digest: str
    decision: GroupedMatchDecision | GroupedMatchPortfolioResult


def _digest(payload: object) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(data).hexdigest()


def _record_payload(record: GroupedRecord) -> dict[str, str]:
    if not all(type(value) is str and value for value in (record.record_id, record.currency, record.partition_key)):
        raise ExactGroupedMatchingError("Records require text identity, currency, and partition.")
    if len(record.record_id) > 256 or len(record.partition_key) > 256:
        raise ExactGroupedMatchingError("Record identity or partition exceeds the supported budget.")
    if (
        len(record.currency) != 3
        or not record.currency.isascii()
        or not record.currency.isalpha()
        or not record.currency.isupper()
    ):
        raise ExactGroupedMatchingError("Records require a three-letter uppercase currency code.")
    if type(record.business_date) is not date:
        raise ExactGroupedMatchingError("Records require an explicit business date.")
    return {
        "id": record.record_id,
        "amount": format(record.amount, "f"),
        "fee": format(record.fee, "f"),
        "currency": record.currency,
        "date": record.business_date.isoformat(),
        "partition": record.partition_key,
    }


def _context_precision(values: tuple[Decimal, ...], record_count: int) -> int:
    if any(type(value) is not Decimal or not value.is_finite() for value in values):
        raise ExactGroupedMatchingError("Exact matching requires finite Decimal inputs.")
    parts = [value.as_tuple() for value in values]
    exponents = [int(part.exponent) for part in parts]
    high = max(value.adjusted() for value in values)
    low = min(exponents)
    if max(abs(high), abs(low)) > _MAX_ABS_EXPONENT:
        raise ExactGroupedMatchingError("Exact matching exponent exceeds the supported budget.")
    # Totals, differences and portfolio scores can add at most twice the records.
    carry = len(str(max(1, record_count * 2))) + 3
    precision = max(1, high - low + 1) + carry
    if precision > _MAX_DIGITS:
        raise ExactGroupedMatchingError("Exact matching precision exceeds the supported budget.")
    return precision


def _require_currency_precision(value: Decimal, precision: int) -> None:
    parts = value.as_tuple()
    excess = max(0, -int(parts.exponent) - precision)
    if excess and any(parts.digits[-min(excess, len(parts.digits)) :]):
        raise ExactGroupedMatchingError("Amount exceeds registered currency precision.")


def match_exact_groups_v2(
    left: tuple[GroupedRecord, ...],
    right: tuple[GroupedRecord, ...],
    policy: GroupedMatchPolicy,
    *,
    registry_context: CurrencyRegistryContext,
) -> ExactGroupedMatchingResult:
    """Evaluate non-posting groups with explicit limits and version-bound evidence.

    This is opt-in and is not the persisted v1 worker or a compatibility reader.
    """
    if type(left) is not tuple or type(right) is not tuple or type(policy) is not GroupedMatchPolicy:
        raise ExactGroupedMatchingError("Exact matching requires tuple records and a grouped policy.")
    if type(registry_context) is not CurrencyRegistryContext:
        raise ExactGroupedMatchingError("Exact matching requires an immutable currency registry context.")
    if len(left) > _MAX_RECORDS_PER_SIDE or len(right) > _MAX_RECORDS_PER_SIDE:
        raise ExactGroupedMatchingError("Exact matching record count exceeds the supported budget.")
    records = left + right
    if any(type(record) is not GroupedRecord for record in records):
        raise ExactGroupedMatchingError("Exact matching requires grouped records.")
    if type(policy.mode) is not str or type(policy.netting_mode) is not str:
        raise ExactGroupedMatchingError("Exact matching policy values must be plain text.")
    bounds = (
        policy.max_left_cardinality,
        policy.max_right_cardinality,
        policy.max_search_evaluations,
        policy.date_window_days,
    )
    if any(type(value) is not int for value in bounds):
        raise ExactGroupedMatchingError("Exact matching bounds must be integers.")
    if (
        policy.max_left_cardinality > _MAX_CARDINALITY
        or policy.max_right_cardinality > _MAX_CARDINALITY
        or policy.max_search_evaluations > _MAX_SEARCH
        or policy.date_window_days > 3660
    ):
        raise ExactGroupedMatchingError("Exact matching search exceeds the supported budget.")
    # The legacy portfolio algorithm has separate generation and selection
    # counters. Split the caller's total budget so both phases (and the
    # evaluator's one over-limit sentinel) cannot exceed it together.
    phase_limit = (
        (policy.max_search_evaluations - 1) // 2 if policy.mode == "portfolio" else policy.max_search_evaluations - 1
    )
    if phase_limit < 1:
        raise ExactGroupedMatchingError("Exact matching search budget is too small for safe evaluation.")
    search_policy = replace(policy, max_search_evaluations=phase_limit)
    # The older evaluator counts candidate pairs but not discarded left groups.
    left_ceiling = 1 if policy.mode in {"one-to-one", "one-to-many"} else policy.max_left_cardinality
    left_groups = sum(comb(len(left), size) for size in range(1, min(len(left), left_ceiling) + 1))
    if left_groups > phase_limit:
        raise ExactGroupedMatchingError("Exact matching left-group generation exceeds the search budget.")
    values = tuple(value for record in records for value in (record.amount, record.fee)) + (policy.amount_tolerance,)
    precision = _context_precision(values, len(records))
    left_payload = sorted((_record_payload(record) for record in left), key=lambda item: item["id"])
    right_payload = sorted((_record_payload(record) for record in right), key=lambda item: item["id"])
    try:
        for record in records:
            currency = registry_context.resolve(record.currency)
            _require_currency_precision(record.amount, currency.spec.minor_units)
            _require_currency_precision(record.fee, currency.spec.minor_units)
            _require_currency_precision(policy.amount_tolerance, currency.spec.minor_units)
    except InvalidAmountError as exc:
        raise ExactGroupedMatchingError("Currency is absent from the recorded registry.") from exc
    if len({item["id"] for item in left_payload}) != len(left_payload) or len(
        {item["id"] for item in right_payload}
    ) != len(right_payload):
        raise ExactGroupedMatchingError("Record identities must be unique on each side.")
    policy_payload = {
        "mode": policy.mode,
        "amount_tolerance": format(policy.amount_tolerance, "f"),
        "date_window_days": policy.date_window_days,
        "max_left_cardinality": policy.max_left_cardinality,
        "max_right_cardinality": policy.max_right_cardinality,
        "max_search_evaluations": policy.max_search_evaluations,
        "netting_mode": policy.netting_mode,
        "portfolio_allow_partial_settlement": policy.portfolio_allow_partial_settlement,
        "budget_model": "total-split-by-phase-v2",
        "effective_phase_limit": phase_limit,
    }
    input_digest = _digest(
        {
            "version": ALGORITHM_VERSION,
            "registry_version": registry_context.registry_manifest.registry_version,
            "registry_digest": registry_context.registry_manifest.digest,
            "left": left_payload,
            "right": right_payload,
            "policy": policy_payload,
        }
    )
    context = Context(
        prec=precision, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999, traps=[InvalidOperation, Overflow, Inexact]
    )
    try:
        with localcontext(context):
            decision = (
                find_grouped_match_portfolio(left, right, search_policy)
                if policy.mode == "portfolio"
                else find_grouped_match(left, right, search_policy)
            )
    except (ArithmeticError, GroupedMatchingError) as exc:
        raise ExactGroupedMatchingError("Exact grouped matching could not be completed safely.") from exc
    if isinstance(decision, GroupedMatchPortfolioResult) and decision.status == "ambiguous":
        # No portfolio was selected; every input record remains unresolved.
        if any(
            item.status == "matched" or item.left_record_ids or item.right_record_ids for item in decision.decisions
        ):
            raise ExactGroupedMatchingError("Ambiguous portfolio contains a selected group.")
        unmatched_left = tuple(sorted(record.record_id for record in left))
        unmatched_right = tuple(sorted(record.record_id for record in right))
        corrected_digest = _digest(
            {
                "candidate_count": decision.candidate_count,
                "decisions": [item.decision_digest for item in decision.decisions],
                "search_evaluations": decision.search_evaluations,
                "status": decision.status,
                "unmatched_left_record_ids": unmatched_left,
                "unmatched_right_record_ids": unmatched_right,
            }
        )
        decision = replace(
            decision,
            unmatched_left_record_ids=unmatched_left,
            unmatched_right_record_ids=unmatched_right,
            portfolio_digest=corrected_digest,
        )
    result_digest = (
        decision.portfolio_digest if isinstance(decision, GroupedMatchPortfolioResult) else decision.decision_digest
    )
    artifact_digest = _digest(
        {"version": ALGORITHM_VERSION, "input_digest": input_digest, "result_digest": result_digest}
    )
    if decision.search_evaluations > policy.max_search_evaluations:
        raise ExactGroupedMatchingError("Exact matching exceeded the total search budget.")
    return ExactGroupedMatchingResult(
        ALGORITHM_VERSION,
        input_digest,
        artifact_digest,
        policy.max_search_evaluations,
        phase_limit,
        registry_context.registry_manifest.registry_version,
        registry_context.registry_manifest.digest,
        decision,
    )
