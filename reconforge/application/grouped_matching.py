"""Backend-neutral application boundary for bounded grouped matching."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from reconforge.domain.grouped_matching import (
    GroupedMatchDecision,
    GroupedMatchingError,
    GroupedMatchPolicy,
    GroupedMatchPortfolioResult,
    GroupedRecord,
    find_grouped_match,
    find_grouped_match_portfolio,
)
from reconforge.utils.money import ExchangeRate, InvalidAmountError, Money, parse_exact_amount

GroupedFxRateType = Literal["inverted", "direct"]


@dataclass(frozen=True)
class _FxRateProfile:
    base_currency: str
    quote_currency: str
    rate: Decimal
    source: str
    rate_type: str
    effective_at: date | None
    conversion: GroupedFxRateType


def _parse_fx_rate_fields(raw_rate: Mapping[str, object]) -> _FxRateProfile:
    base = str(raw_rate.get("base_currency") or raw_rate.get("from_currency", "")).strip().upper()
    quote = str(raw_rate.get("quote_currency") or raw_rate.get("to_currency", "")).strip().upper()
    if not base or not quote:
        raise GroupedMatchingError("Grouped-match FX rate must include base/from and quote/to currencies.")
    try:
        raw_rate_value = raw_rate["rate"]
    except KeyError as exc:
        raise GroupedMatchingError("Grouped-match FX rate is missing the 'rate' field.") from exc
    rate = parse_exact_amount(raw_rate_value)
    if rate <= Decimal("0"):
        raise GroupedMatchingError("Grouped-match FX rate must be positive.")
    source = str(raw_rate.get("source", "MANUAL")).strip()
    if not source:
        raise GroupedMatchingError("Grouped-match FX rate source cannot be empty.")
    rate_type = str(raw_rate.get("rate_type", "manual")).strip()
    if not rate_type:
        raise GroupedMatchingError("Grouped-match FX rate_type cannot be empty.")
    raw_effective_at = str(raw_rate.get("effective_at", "")).strip()
    effective_at = date.fromisoformat(raw_effective_at) if raw_effective_at else None
    if raw_effective_at and effective_at is not None and effective_at.isoformat() != raw_effective_at:
        raise GroupedMatchingError("Grouped-match FX effective_at must be canonical YYYY-MM-DD text.")
    return _FxRateProfile(
        base_currency=base,
        quote_currency=quote,
        rate=rate,
        source=source,
        rate_type=rate_type,
        effective_at=effective_at,
        conversion="direct",
    )


def _fx_rates_by_pair(
    raw_rates: Iterable[Mapping[str, object]],
) -> tuple[_FxRateProfile, ...]:
    parsed_rates = tuple(_parse_fx_rate_fields(rate) for rate in raw_rates)
    by_pair = []
    seen: set[tuple[str, str, str, str, object]] = set()
    for profile in parsed_rates:
        effective_at_key: str | None = None
        if profile.effective_at:
            effective_at_key = profile.effective_at.isoformat()
        key = (
            profile.base_currency,
            profile.quote_currency,
            profile.source,
            profile.rate_type,
            effective_at_key,
        )
        if key in seen:
            raise GroupedMatchingError("Grouped-match FX profile contains duplicate rate definitions.")
        seen.add(key)
        by_pair.append(profile)
    return tuple(
        sorted(
            by_pair,
            key=lambda item: (
                item.base_currency,
                item.quote_currency,
                item.effective_at or date.min,
                item.source,
                item.rate_type,
                str(item.rate),
            ),
        )
    )


def _select_fx_profile(
    *,
    pair_profiles: tuple[_FxRateProfile, ...],
    from_currency: str,
    to_currency: str,
    business_date: date,
) -> _FxRateProfile:
    candidates: list[_FxRateProfile] = []
    for profile in pair_profiles:
        if (
            profile.base_currency == from_currency
            and profile.quote_currency == to_currency
            and (profile.effective_at is None or profile.effective_at <= business_date)
        ):
            candidates.append(profile)
        elif (
            profile.base_currency == to_currency
            and profile.quote_currency == from_currency
            and (profile.effective_at is None or profile.effective_at <= business_date)
        ):
            inverse_profile = _FxRateProfile(
                base_currency=from_currency,
                quote_currency=to_currency,
                rate=Decimal("1") / profile.rate,
                source=profile.source,
                rate_type=f"inverted:{profile.rate_type}",
                effective_at=profile.effective_at,
                conversion="inverted",
            )
            candidates.append(inverse_profile)
    if not candidates:
        raise GroupedMatchingError(
            f"Grouped-match missing FX rate for conversion {from_currency}->{to_currency} as of {business_date.isoformat()}."
        )
    return max(
        candidates,
        key=lambda profile: (
            profile.effective_at or date.min,
            profile.source,
            profile.rate_type,
            str(profile.rate),
        ),
    )


def _convert_with_fx(
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    *,
    business_date: date,
    fx_rates: tuple[_FxRateProfile, ...],
) -> tuple[Decimal, str]:
    if from_currency == to_currency:
        return amount, ""
    if not fx_rates:
        raise GroupedMatchingError(
            f"Grouped-match requires FX rate data for conversion from {from_currency} to {to_currency}."
        )
    selected = _select_fx_profile(
        pair_profiles=fx_rates,
        from_currency=from_currency,
        to_currency=to_currency,
        business_date=business_date,
    )
    converted = ExchangeRate(
        base_currency=selected.base_currency,
        quote_currency=selected.quote_currency,
        rate=selected.rate,
        source=f"{selected.rate_type}:{selected.source}",
        effective_at=selected.effective_at.isoformat() if selected.effective_at else "",
    ).convert(Money.from_exact(amount, currency=from_currency, strict_precision=True))
    return converted.amount, selected.conversion


@dataclass(frozen=True)
class GroupedMatchRequest:
    left_records: tuple[Mapping[str, object], ...]
    right_records: tuple[Mapping[str, object], ...]
    policy: GroupedMatchPolicy
    left_id_field: str = "id"
    right_id_field: str = "id"
    amount_field: str = "amount"
    left_fee_field: str = "fee"
    right_fee_field: str = "fee"
    currency_field: str = "currency"
    date_field: str = "date"
    partition_field: str = "partition"
    target_currency: str = ""
    fx_rates: tuple[Mapping[str, object], ...] = ()


class GroupedMatchingApplicationService:
    """Translate canonical mappings into the pure grouped-match model."""

    def execute(self, request: GroupedMatchRequest) -> GroupedMatchDecision:
        fields = (
            request.left_id_field,
            request.right_id_field,
            request.amount_field,
            request.left_fee_field,
            request.right_fee_field,
            request.currency_field,
            request.date_field,
            request.partition_field,
        )
        if any(not isinstance(field, str) or not field.strip() for field in fields):
            raise GroupedMatchingError("Grouped-match field names cannot be empty.")
        target_currency = request.target_currency.strip().upper() if isinstance(request.target_currency, str) else ""
        if request.target_currency is not None and target_currency == "":
            target_currency = ""
        fx_rates = _fx_rates_by_pair(request.fx_rates) if request.fx_rates else ()
        left = self._records(
            request.left_records,
            id_field=request.left_id_field,
            fee_field=request.left_fee_field,
            policy=request.policy,
            request=request,
            target_currency=target_currency,
            fx_rates=fx_rates,
        )
        right = self._records(
            request.right_records,
            id_field=request.right_id_field,
            fee_field=request.right_fee_field,
            policy=request.policy,
            request=request,
            target_currency=target_currency,
            fx_rates=fx_rates,
        )
        return find_grouped_match(left, right, request.policy)

    def execute_portfolio(self, request: GroupedMatchRequest) -> GroupedMatchPortfolioResult:
        """Execute bounded non-overlapping portfolio matching through the same ports."""

        if request.policy.mode != "portfolio":
            raise GroupedMatchingError("Grouped portfolio execution requires portfolio mode.")
        fields = (
            request.left_id_field,
            request.right_id_field,
            request.amount_field,
            request.left_fee_field,
            request.right_fee_field,
            request.currency_field,
            request.date_field,
            request.partition_field,
        )
        if any(not isinstance(field, str) or not field.strip() for field in fields):
            raise GroupedMatchingError("Grouped-match field names cannot be empty.")
        target_currency = request.target_currency.strip().upper() if isinstance(request.target_currency, str) else ""
        fx_rates = _fx_rates_by_pair(request.fx_rates) if request.fx_rates else ()
        left = self._records(
            request.left_records,
            id_field=request.left_id_field,
            fee_field=request.left_fee_field,
            policy=request.policy,
            request=request,
            target_currency=target_currency,
            fx_rates=fx_rates,
        )
        right = self._records(
            request.right_records,
            id_field=request.right_id_field,
            fee_field=request.right_fee_field,
            policy=request.policy,
            request=request,
            target_currency=target_currency,
            fx_rates=fx_rates,
        )
        return find_grouped_match_portfolio(left, right, request.policy)

    def _records(
        self,
        records: tuple[Mapping[str, object], ...],
        *,
        id_field: str,
        fee_field: str,
        policy: GroupedMatchPolicy,
        request: GroupedMatchRequest,
        target_currency: str,
        fx_rates: tuple[_FxRateProfile, ...],
    ) -> tuple[GroupedRecord, ...]:
        converted: list[GroupedRecord] = []
        for record in records:
            try:
                raw_date = record[request.date_field]
                if not isinstance(raw_date, str):
                    raise GroupedMatchingError("Grouped-match dates must use canonical YYYY-MM-DD text.")
                parsed_date = date.fromisoformat(raw_date)
                if parsed_date.isoformat() != raw_date:
                    raise GroupedMatchingError("Grouped-match dates must use canonical YYYY-MM-DD text.")
                record_currency = str(record[request.currency_field]).strip().upper()
                target = target_currency or record_currency
                amount, conversion = _convert_with_fx(
                    parse_exact_amount(record[request.amount_field]),
                    record_currency,
                    target,
                    business_date=parsed_date,
                    fx_rates=fx_rates,
                )
                fee_value = self._parse_fee(record, fee_field, policy=policy)
                fee, fee_conversion = _convert_with_fx(
                    fee_value,
                    record_currency,
                    target,
                    business_date=parsed_date,
                    fx_rates=fx_rates,
                )
                converted.append(
                    GroupedRecord(
                        record_id=str(record[id_field]).strip(),
                        amount=amount,
                        fee=fee,
                        currency=target,
                        business_date=parsed_date,
                        partition_key=str(record[request.partition_field]).strip(),
                    )
                )
                if conversion != fee_conversion:
                    raise GroupedMatchingError("Grouped-match fee and principal conversion paths diverged.")
            except KeyError as exc:
                raise GroupedMatchingError(f"Grouped-match record is missing field: {exc.args[0]}") from exc
            except (InvalidAmountError, ValueError) as exc:
                if isinstance(exc, GroupedMatchingError):
                    raise
                raise GroupedMatchingError("Grouped-match record contains an invalid amount or date.") from exc
        return tuple(converted)

    @staticmethod
    def _parse_fee(
        record: Mapping[str, object],
        fee_field: str,
        *,
        policy: GroupedMatchPolicy,
    ) -> Decimal:
        if policy.netting_mode == "gross":
            return Decimal("0")
        if fee_field not in record:
            return Decimal("0")
        return parse_exact_amount(record[fee_field])
