"""Finite public evidence validators for versioned monetary source adapters.

These checks verify transport and source affinity. Native owners retain financial
authorization, allocation, posting and historical evidence responsibility.
"""

from collections.abc import Mapping
from datetime import date
from typing import Any

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.operational_fx_tax import HistoricalRate

MAX_MINOR = 9_000_000_000_000_000_000
SCOPE = frozenset({"workspace_id", "organization_id", "legal_entity_id"})
POLICY = frozenset({"currency_code", "currency_precision", "currency_rounding_policy", "currency_registry_version", "currency_registry_digest"})
RATE = frozenset({"rate", "source", "effective_at"})
BALANCE = frozenset({
    "schema_version", "history_version", "history_fingerprint", "transaction_original_gross_minor", "functional_original_gross_minor",
    "transaction_collected_minor", "transaction_credited_minor", "transaction_outstanding_minor", "functional_outstanding_minor",
    "transaction_refund_entitlement_minor", "functional_refund_entitlement_minor", "transaction_refunded_minor",
    "functional_refund_released_minor", "transaction_refund_due_minor", "functional_refund_due_minor", "active_plan_id", "active_revaluation_plan_id",
})


class MonetaryResponseError(ValueError):
    """A malformed native acknowledgement cannot be published as success."""


def require(condition: bool) -> None:
    if not condition:
        raise MonetaryResponseError("The monetary source response could not be verified.")


def closed(value: Any, fields: frozenset[str]) -> dict[str, Any]:
    require(type(value) is dict and set(value) == fields)
    return dict(value)


def text(value: Any, *, maximum: int = 160, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    require(type(value) is str and 0 < len(value) <= maximum and value == value.strip()
            and all(ord(character) >= 32 and ord(character) != 127 for character in value))


def integer(value: Any, *, maximum: int, minimum: int = 0) -> None:
    require(type(value) is int and minimum <= value <= maximum)


def minor(value: Any, *, positive: bool = False) -> int:
    require(type(value) is str and 0 < len(value) <= 19 and value.isascii() and value.isdecimal()
            and (value == "0" or value[0] != "0"))
    number = int(value)
    require((1 if positive else 0) <= number <= MAX_MINOR)
    return number


def digest(value: Any, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    require(type(value) is str and len(value) == 64 and all(character in "0123456789abcdef" for character in value))


def calendar(value: Any) -> None:
    try:
        require(type(value) is str and date.fromisoformat(value).isoformat() == value)
    except (TypeError, ValueError) as exc:
        raise MonetaryResponseError("The monetary source date could not be verified.") from exc


def scope_of(row: Mapping[str, Any], scope: Mapping[str, Any]) -> None:
    for key in SCOPE:
        text(row[key])
        require(row[key] == scope[key])


def policy(value: Any) -> dict[str, Any]:
    row = closed(value, POLICY)
    code = row["currency_code"]
    require(type(code) is str and len(code) == 3 and all("A" <= character <= "Z" for character in code))
    integer(row["currency_precision"], maximum=8)
    require(row["currency_rounding_policy"] == "ROUND_HALF_UP")
    text(row["currency_registry_version"])
    digest(row["currency_registry_digest"])
    return row


def rate(value: Any, *, day: str, identity: bool) -> dict[str, Any] | None:
    if identity:
        require(value is None)
        return None
    row = closed(value, RATE)
    try:
        require(HistoricalRate(**row).payload(day) == row)
    except (FinancePostingError, TypeError, ValueError) as exc:
        raise MonetaryResponseError("The monetary source rate provenance could not be verified.") from exc
    return row


def balance_fields(row: Mapping[str, Any]) -> None:
    integer(row["history_version"], maximum=256)
    digest(row["history_fingerprint"])
    amounts = {name: minor(value) for name, value in row.items() if name.endswith("_minor")}
    for key in ("active_plan_id", "active_revaluation_plan_id"):
        text(row[key], nullable=True)
    require(amounts["transaction_original_gross_minor"] > 0 and amounts["functional_original_gross_minor"] > 0)
    require(amounts["transaction_credited_minor"] <= amounts["transaction_original_gross_minor"])
    require(amounts["transaction_refunded_minor"] <= amounts["transaction_refund_entitlement_minor"]
            and amounts["functional_refund_released_minor"] <= amounts["functional_refund_entitlement_minor"])
    require(amounts["transaction_refund_due_minor"] == amounts["transaction_refund_entitlement_minor"] - amounts["transaction_refunded_minor"]
            and amounts["functional_refund_due_minor"] == amounts["functional_refund_entitlement_minor"] - amounts["functional_refund_released_minor"])
    # Collection admission is prefix-time and native-owned. Do not impose the
    # incorrect final-state C <= G predicate after governed credit/refund history.
