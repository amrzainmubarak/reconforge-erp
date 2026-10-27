"""Experimental, versioned grouped matching with exact bounded Decimal arithmetic.

This entry point does not replace the existing persisted strategy or submit posts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal, Inexact, InvalidOperation, Overflow, localcontext
from fractions import Fraction
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
from reconforge.utils.money import CurrencyRegistryContext, InvalidAmountError, ResolvedCurrencyPolicy

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


@dataclass(frozen=True)
class GroupedFxRateV2:
    """Original observed rate; quote units per base unit on its effective date."""

    base_currency: str
    quote_currency: str
    rate: Decimal
    source: str
    rate_type: str
    effective_at: date
    valid_until: date


@dataclass(frozen=True)
class GroupedFxConversionV2:
    side: str
    record_id: str
    source_currency: str
    target_currency: str
    direction: str
    source_rate: GroupedFxRateV2 | None
    converted_amount: Decimal
    converted_fee: Decimal


@dataclass(frozen=True)
class GroupedFxSourceRecordV2:
    side: str
    record: GroupedRecord


@dataclass(frozen=True)
class GroupedFxDecisionV2:
    """One FX-bound decision with the inputs required to inspect its lineage."""

    algorithm_version: str
    status: str
    group_id: str
    decision_digest: str
    reason_code: str
    explanation: str
    left_record_ids: tuple[str, ...]
    right_record_ids: tuple[str, ...]
    currency: str
    left_total: Decimal
    right_total: Decimal
    left_fee_total: Decimal
    right_fee_total: Decimal
    left_net_total: Decimal
    right_net_total: Decimal
    amount_difference: Decimal
    candidate_count: int
    search_evaluations: int
    verification_evaluations: int
    tie_break: str
    ambiguous_candidate_sets: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]
    policy: GroupedMatchPolicy
    target_currency: str
    rounding_scope: str
    registry_context: CurrencyRegistryContext
    source_records: tuple[GroupedFxSourceRecordV2, ...]
    rates: tuple[GroupedFxRateV2, ...]
    conversions: tuple[GroupedFxConversionV2, ...]
    exact_difference_numerator: int | None
    exact_difference_denominator: int | None


@dataclass(frozen=True)
class ExactGroupedFxResultV2:
    algorithm_version: str
    registry_version: str
    registry_digest: str
    conversions: tuple[GroupedFxConversionV2, ...]
    decision: GroupedFxDecisionV2
    verification_evaluations: int
    exact_difference_numerator: int | None
    exact_difference_denominator: int | None
    artifact_digest: str


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


def _fx_bounded_decimal(value: Decimal) -> None:
    if type(value) is not Decimal or not value.is_finite():
        raise ExactGroupedMatchingError("FX values must be finite exact decimals.")
    parts = value.as_tuple()
    if len(parts.digits) > 200 or abs(int(parts.exponent)) > 200:
        raise ExactGroupedMatchingError("FX value exceeds the supported arithmetic budget.")


def _fx_currency(code: str, registry: CurrencyRegistryContext) -> ResolvedCurrencyPolicy:
    if type(code) is not str or len(code) != 3 or not code.isascii() or not code.isalpha() or not code.isupper():
        raise ExactGroupedMatchingError("FX currency must be a three-letter uppercase code.")
    try:
        return registry.resolve(code)
    except InvalidAmountError as exc:
        raise ExactGroupedMatchingError("FX currency is absent from the recorded registry.") from exc


def _fx_amount(value: Decimal, rate: Decimal, *, inverse: bool, precision: int, rounding: str) -> Decimal:
    """Round the exact rational once; never construct a rounded reciprocal."""
    if rounding != "ROUND_HALF_UP":
        raise ExactGroupedMatchingError("FX rounding policy is not supported.")
    amount_numerator, amount_denominator = value.as_integer_ratio()
    rate_numerator, rate_denominator = rate.as_integer_ratio()
    if inverse:
        numerator = amount_numerator * rate_denominator
        denominator = amount_denominator * rate_numerator
    else:
        numerator = amount_numerator * rate_numerator
        denominator = amount_denominator * rate_denominator
    units, remainder = divmod(abs(numerator) * 10**precision, denominator)
    if remainder * 2 >= denominator:
        units += 1
    digits = tuple(int(digit) for digit in str(units))
    return Decimal((int(numerator < 0 and units != 0), digits, -precision))


def _verify_fx_candidates(
    left: tuple[GroupedRecord, ...], right: tuple[GroupedRecord, ...],
    exact: dict[tuple[str, str], tuple[Fraction, Fraction]], policy: GroupedMatchPolicy,
    decision: GroupedMatchDecision,
) -> int:
    """Check all bounded pairs before and after currency rounding, independently."""
    pairs = len(left) * len(right)
    if pairs > min(4096, policy.max_search_evaluations):
        raise ExactGroupedMatchingError("FX candidate verification exceeds its independent search budget.")
    threshold = Fraction(policy.amount_tolerance)
    original_scores: dict[tuple[str, str], tuple[Fraction, int]] = {}
    rounded_scores: dict[tuple[str, str], tuple[Fraction, int]] = {}
    for lhs in left:
        for rhs in right:
            span = abs((lhs.business_date - rhs.business_date).days)
            if lhs.partition_key != rhs.partition_key or span > policy.date_window_days:
                continue
            left_amount, left_fee = exact[("left", lhs.record_id)]
            right_amount, right_fee = exact[("right", rhs.record_id)]
            left_rounded, right_rounded = Fraction(lhs.amount), Fraction(rhs.amount)
            if policy.netting_mode == "net":
                left_amount -= left_fee
                right_amount -= right_fee
                left_rounded -= Fraction(lhs.fee)
                right_rounded -= Fraction(rhs.fee)
            original_difference = abs(left_amount - right_amount)
            rounded_difference = abs(left_rounded - right_rounded)
            key = (lhs.record_id, rhs.record_id)
            if original_difference <= threshold:
                original_scores[key] = (original_difference, span)
            if rounded_difference <= threshold:
                rounded_scores[key] = (rounded_difference, span)
    if original_scores.keys() != rounded_scores.keys():
        raise ExactGroupedMatchingError("FX candidate set differs before and after rounding.")
    if original_scores:
        original_best = min(original_scores.values())
        rounded_best = min(rounded_scores.values())
        exact_winners = {key for key, score in original_scores.items() if score == original_best}
        rounded_winners = {key for key, score in rounded_scores.items() if score == rounded_best}
        if exact_winners != rounded_winners:
            raise ExactGroupedMatchingError("FX candidate ranking differs before and after rounding.")
    else:
        exact_winners = set()
    if decision.reason_code == "GROUP_SEARCH_BUDGET_EXCEEDED":
        return pairs
    if not exact_winners and decision.status != "unmatched":
        raise ExactGroupedMatchingError("FX decision does not match verified candidates.")
    if len(exact_winners) == 1:
        selected = next(iter(exact_winners))
        if decision.status != "matched" or (decision.left_record_ids, decision.right_record_ids) != ((selected[0],), (selected[1],)):
            raise ExactGroupedMatchingError("FX selected decision differs from verified candidates.")
    if len(exact_winners) > 1:
        ambiguous = {((left_id,), (right_id,)) for left_id, right_id in exact_winners}
        if decision.status != "ambiguous" or set(decision.ambiguous_candidate_sets) != ambiguous:
            raise ExactGroupedMatchingError("FX ambiguous decision differs from verified candidates.")
    return pairs


def match_exact_groups_fx_v2(
    left: tuple[GroupedRecord, ...],
    right: tuple[GroupedRecord, ...],
    policy: GroupedMatchPolicy,
    *,
    target_currency: str,
    rates: tuple[GroupedFxRateV2, ...],
    registry_context: CurrencyRegistryContext,
    rounding_scope: str,
) -> ExactGroupedFxResultV2:
    """Opt-in one-to-one FX proposal; round each record's amount and fee separately.

    No posting, persistence, live rate selection or replay migration is provided.
    The caller must explicitly choose the only supported rounding scope. Rates
    are original quote-per-base observations, not pre-rounded reciprocals.
    A separate bounded verification checks the candidate set and best ranking
    before and after rounding; it examines at most 4096 pairs and at most the
    requested search budget in addition to the grouped kernel's own search.
    """
    if type(registry_context) is not CurrencyRegistryContext:
        raise ExactGroupedMatchingError("FX matching requires an immutable registry context.")
    if type(left) is not tuple or type(right) is not tuple or type(rates) is not tuple:
        raise ExactGroupedMatchingError("FX records and rates must be tuples.")
    if type(policy) is not GroupedMatchPolicy or policy.mode != "one-to-one":
        raise ExactGroupedMatchingError("FX matching supports one-to-one mode only.")
    _fx_bounded_decimal(policy.amount_tolerance)
    if rounding_scope != "per-record-per-component":
        raise ExactGroupedMatchingError("FX matching requires explicit per-record-per-component rounding.")
    if len(left) > 64 or len(right) > 64 or len(rates) > 128:
        raise ExactGroupedMatchingError("FX matching request exceeds its bounded size.")
    target = _fx_currency(target_currency, registry_context)
    rate_payload = []
    for rate in rates:
        if type(rate) is not GroupedFxRateV2:
            raise ExactGroupedMatchingError("FX rate profile is invalid.")
        _fx_currency(rate.base_currency, registry_context)
        _fx_currency(rate.quote_currency, registry_context)
        _fx_bounded_decimal(rate.rate)
        if rate.base_currency == rate.quote_currency or rate.rate <= 0:
            raise ExactGroupedMatchingError("FX rate must describe distinct currencies and a positive rate.")
        if type(rate.effective_at) is not date or type(rate.valid_until) is not date or rate.valid_until < rate.effective_at or any(
            type(value) is not str or not value or value != value.strip() or len(value) > 128
            for value in (rate.source, rate.rate_type)
        ):
            raise ExactGroupedMatchingError("FX rate source, type and effective date are required.")
        rate_payload.append({"base": rate.base_currency, "quote": rate.quote_currency,
                             "rate": format(rate.rate, "f"), "source": rate.source,
                             "rate_type": rate.rate_type, "effective_at": rate.effective_at.isoformat(),
                             "valid_until": rate.valid_until.isoformat()})
    conversions: list[GroupedFxConversionV2] = []
    exact_components: dict[tuple[str, str], tuple[Fraction, Fraction]] = {}
    source_records: list[dict[str, str]] = []
    converted_sides: list[tuple[GroupedRecord, ...]] = []
    for side, records in (("left", left), ("right", right)):
        converted: list[GroupedRecord] = []
        for record in records:
            if type(record) is not GroupedRecord:
                raise ExactGroupedMatchingError("FX matching requires grouped records.")
            _fx_bounded_decimal(record.amount)
            _fx_bounded_decimal(record.fee)
            source_policy = _fx_currency(record.currency, registry_context)
            _require_currency_precision(record.amount, source_policy.spec.minor_units)
            _require_currency_precision(record.fee, source_policy.spec.minor_units)
            payload = _record_payload(record)
            payload.update({"side": side, "amount": "0" if record.amount == 0 else payload["amount"],
                            "fee": "0" if record.fee == 0 else payload["fee"]})
            source_records.append(payload)
            direction = "identity"
            selected = None
            amount, fee = record.amount, record.fee
            exact_amount, exact_fee = Fraction(record.amount), Fraction(record.fee)
            if record.currency != target_currency:
                candidates = [rate for rate in rates if rate.effective_at <= record.business_date <= rate.valid_until and
                              ((rate.base_currency == record.currency and rate.quote_currency == target_currency) or
                               (rate.quote_currency == record.currency and rate.base_currency == target_currency))]
                if len(candidates) != 1:
                    raise ExactGroupedMatchingError("FX matching requires exactly one applicable original rate.")
                selected = candidates[0]
                inverse = selected.quote_currency == record.currency
                direction = "inverse" if inverse else "direct"
                exact_rate = Fraction(selected.rate)
                exact_amount = exact_amount / exact_rate if inverse else exact_amount * exact_rate
                exact_fee = exact_fee / exact_rate if inverse else exact_fee * exact_rate
                amount = _fx_amount(record.amount, selected.rate, inverse=inverse,
                                    precision=target.spec.minor_units, rounding=target.spec.rounding_policy)
                fee = _fx_amount(record.fee, selected.rate, inverse=inverse,
                                 precision=target.spec.minor_units, rounding=target.spec.rounding_policy)
            amount = Decimal("0") if amount == 0 else amount
            fee = Decimal("0") if fee == 0 else fee
            conversions.append(GroupedFxConversionV2(side, record.record_id, record.currency, target_currency,
                                                     direction, selected, amount, fee))
            exact_components[(side, record.record_id)] = (exact_amount, exact_fee)
            converted.append(replace(record, amount=amount, fee=fee, currency=target_currency))
        converted_sides.append(tuple(converted))
    match = match_exact_groups_v2(converted_sides[0], converted_sides[1], policy, registry_context=registry_context)
    if not isinstance(match.decision, GroupedMatchDecision):
        raise ExactGroupedMatchingError("FX one-to-one matching returned an unexpected portfolio.")
    difference: Fraction | None = None
    if match.decision.status == "matched":
        if len(match.decision.left_record_ids) != 1 or len(match.decision.right_record_ids) != 1:
            raise ExactGroupedMatchingError("FX one-to-one match has an invalid record selection.")
        left_amount, left_fee = exact_components[("left", match.decision.left_record_ids[0])]
        right_amount, right_fee = exact_components[("right", match.decision.right_record_ids[0])]
        if policy.netting_mode == "net":
            left_amount -= left_fee
            right_amount -= right_fee
        difference = abs(left_amount - right_amount)
        if difference > Fraction(policy.amount_tolerance):
            raise ExactGroupedMatchingError("FX candidate differs beyond the declared tolerance before rounding.")
    verification_evaluations = _verify_fx_candidates(
        converted_sides[0], converted_sides[1], exact_components, policy, match.decision,
    )
    source_records.sort(key=lambda item: (item["side"], item["id"]))
    rate_payload.sort(key=lambda item: (item["base"], item["quote"], item["effective_at"], item["valid_until"], item["source"], item["rate_type"], item["rate"]))
    conversions.sort(key=lambda item: (item.side, item.record_id))
    version = "exact-bounded-grouped-fx-per-component-v1"
    artifact = _digest({"version": version, "registry_version": registry_context.registry_manifest.registry_version,
                        "registry_digest": registry_context.registry_manifest.digest, "target_currency": target_currency,
                        "target_precision": target.spec.minor_units, "target_rounding": target.spec.rounding_policy,
                        "rounding_scope": rounding_scope, "source_records": source_records, "rates": rate_payload,
                        "verification_evaluations": verification_evaluations,
                        "conversions": [{"side": item.side, "id": item.record_id, "direction": item.direction,
                                         "amount": format(item.converted_amount, "f"),
                                         "fee": format(item.converted_fee, "f"),
                                         "source": item.source_rate.source if item.source_rate else "",
                                         "rate_type": item.source_rate.rate_type if item.source_rate else "",
                                         "effective_at": item.source_rate.effective_at.isoformat() if item.source_rate else "",
                                         "valid_until": item.source_rate.valid_until.isoformat() if item.source_rate else ""}
                                        for item in conversions],
                        "exact_difference": None if difference is None else {
                            "numerator": str(difference.numerator), "denominator": str(difference.denominator)},
                        "match_artifact_digest": match.artifact_digest})
    bound_sources = tuple(sorted(
        (GroupedFxSourceRecordV2(side, record) for side, records in (("left", left), ("right", right))
         for record in records), key=lambda item: (item.side, item.record.record_id),
    ))
    bound_rates = tuple(sorted(rates, key=lambda item: (
        item.base_currency, item.quote_currency, item.effective_at, item.valid_until,
        item.source, item.rate_type, format(item.rate, "f"),
    )))
    decision = GroupedFxDecisionV2(
        algorithm_version=version, status=match.decision.status,
        group_id=f"MG-{artifact[:20].upper()}" if match.decision.group_id else "",
        decision_digest=artifact, reason_code=match.decision.reason_code,
        explanation=match.decision.explanation, left_record_ids=match.decision.left_record_ids,
        right_record_ids=match.decision.right_record_ids, currency=match.decision.currency,
        left_total=match.decision.left_total, right_total=match.decision.right_total,
        left_fee_total=match.decision.left_fee_total, right_fee_total=match.decision.right_fee_total,
        left_net_total=match.decision.left_net_total, right_net_total=match.decision.right_net_total,
        amount_difference=match.decision.amount_difference, candidate_count=match.decision.candidate_count,
        search_evaluations=match.decision.search_evaluations, verification_evaluations=verification_evaluations,
        tie_break=match.decision.tie_break,
        ambiguous_candidate_sets=match.decision.ambiguous_candidate_sets, policy=policy, target_currency=target_currency,
        rounding_scope=rounding_scope, registry_context=registry_context, source_records=bound_sources,
        rates=bound_rates, conversions=tuple(conversions),
        exact_difference_numerator=difference.numerator if difference is not None else None,
        exact_difference_denominator=difference.denominator if difference is not None else None,
    )
    return ExactGroupedFxResultV2(version, registry_context.registry_manifest.registry_version,
                                  registry_context.registry_manifest.digest, tuple(conversions), decision,
                                  verification_evaluations,
                                  difference.numerator if difference is not None else None,
                                  difference.denominator if difference is not None else None, artifact)
