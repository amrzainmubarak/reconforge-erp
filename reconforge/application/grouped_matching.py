"""Backend-neutral application boundary for bounded grouped matching."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from reconforge.domain.grouped_matching import (
    GroupedMatchDecision,
    GroupedMatchingError,
    GroupedMatchPolicy,
    GroupedRecord,
    find_grouped_match,
)
from reconforge.utils.money import InvalidAmountError, parse_exact_amount


@dataclass(frozen=True)
class GroupedMatchRequest:
    left_records: tuple[Mapping[str, object], ...]
    right_records: tuple[Mapping[str, object], ...]
    policy: GroupedMatchPolicy
    left_id_field: str = "id"
    right_id_field: str = "id"
    amount_field: str = "amount"
    currency_field: str = "currency"
    date_field: str = "date"
    partition_field: str = "partition"


class GroupedMatchingApplicationService:
    """Translate canonical mappings into the pure grouped-match model."""

    def execute(self, request: GroupedMatchRequest) -> GroupedMatchDecision:
        fields = (
            request.left_id_field,
            request.right_id_field,
            request.amount_field,
            request.currency_field,
            request.date_field,
            request.partition_field,
        )
        if any(not field.strip() for field in fields):
            raise GroupedMatchingError("Grouped-match field names cannot be empty.")
        left = self._records(request.left_records, id_field=request.left_id_field, request=request)
        right = self._records(request.right_records, id_field=request.right_id_field, request=request)
        return find_grouped_match(left, right, request.policy)

    def _records(
        self,
        records: tuple[Mapping[str, object], ...],
        *,
        id_field: str,
        request: GroupedMatchRequest,
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
                converted.append(
                    GroupedRecord(
                        record_id=str(record[id_field]).strip(),
                        amount=parse_exact_amount(record[request.amount_field]),
                        currency=str(record[request.currency_field]).strip().upper(),
                        business_date=parsed_date,
                        partition_key=str(record[request.partition_field]).strip(),
                    )
                )
            except KeyError as exc:
                raise GroupedMatchingError(f"Grouped-match record is missing field: {exc.args[0]}") from exc
            except (InvalidAmountError, ValueError) as exc:
                if isinstance(exc, GroupedMatchingError):
                    raise
                raise GroupedMatchingError("Grouped-match record contains an invalid amount or date.") from exc
        return tuple(converted)
