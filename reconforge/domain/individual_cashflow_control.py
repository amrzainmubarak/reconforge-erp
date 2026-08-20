"""Deterministic, non-posting cashflow control for individuals and freelancers.

The control compares local income/expense transactions with an optional
category budget.  It is intentionally provider-neutral: it does not connect
to a bank, move money, post a journal, or infer tax/legal conclusions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal, cast

from reconforge.domain.decision_artifact import canonical_decision_digest, verify_canonical_decision_payload
from reconforge.utils.money import Money

INDIVIDUAL_CASHFLOW_CONTROL_SCHEMA_VERSION = 1
INDIVIDUAL_CASHFLOW_CONTROL_ALGORITHM_VERSION = "individual-cashflow-control-v1"
CashflowType = Literal["income", "expense"]
CashflowStatus = Literal["within_budget", "over_budget", "unbudgeted", "no_activity"]
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_CATEGORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/&+\-]{0,119}$")
_PERIOD = re.compile(r"^\d{4}-\d{2}$")


class IndividualCashflowControlError(ValueError):
    """Raised when the individual cashflow contract is violated."""


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.strip()):
        raise IndividualCashflowControlError(f"{field} is invalid.")
    return value.strip()


def _category(value: object) -> str:
    if not isinstance(value, str) or not _CATEGORY.fullmatch(value.strip()):
        raise IndividualCashflowControlError("cashflow category is invalid.")
    return " ".join(value.strip().split()).casefold()


def _cashflow_type(value: object) -> CashflowType:
    if value not in {"income", "expense"}:
        raise IndividualCashflowControlError("cashflow type must be income or expense.")
    return cast(CashflowType, value)


def _iso_date(value: object) -> str:
    if not isinstance(value, str):
        raise IndividualCashflowControlError("transaction date must be an ISO-8601 date.")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise IndividualCashflowControlError("transaction date must be an ISO-8601 date.") from exc


def _period(value: object) -> str:
    if not isinstance(value, str) or not _PERIOD.fullmatch(value.strip()):
        raise IndividualCashflowControlError("budget period must use YYYY-MM.")
    try:
        year, month = (int(part) for part in value.strip().split("-"))
        date(year, month, 1)
    except (ValueError, TypeError) as exc:
        raise IndividualCashflowControlError("budget period must use a valid YYYY-MM.") from exc
    return value.strip()


@dataclass(frozen=True)
class CashTransaction:
    transaction_id: str
    transaction_date: str
    flow_type: CashflowType
    category: str
    amount: Money
    reference: str
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "transaction_id", _identifier(self.transaction_id, "transaction ID"))
        object.__setattr__(self, "transaction_date", _iso_date(self.transaction_date))
        object.__setattr__(self, "flow_type", _cashflow_type(self.flow_type))
        object.__setattr__(self, "category", _category(self.category))
        if not isinstance(self.amount, Money) or not self.amount.amount.is_finite() or self.amount.amount < 0:
            raise IndividualCashflowControlError("transaction amount must be finite non-negative Money.")
        object.__setattr__(self, "reference", _identifier(self.reference, "transaction reference"))
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "transaction source reference"))

    @property
    def period(self) -> str:
        return self.transaction_date[:7]


@dataclass(frozen=True)
class CashBudgetLine:
    budget_id: str
    period: str
    flow_type: CashflowType
    category: str
    limit: Money
    source_reference: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "budget_id", _identifier(self.budget_id, "budget ID"))
        object.__setattr__(self, "period", _period(self.period))
        object.__setattr__(self, "flow_type", _cashflow_type(self.flow_type))
        object.__setattr__(self, "category", _category(self.category))
        if not isinstance(self.limit, Money) or not self.limit.amount.is_finite() or self.limit.amount < 0:
            raise IndividualCashflowControlError("budget limit must be finite non-negative Money.")
        object.__setattr__(self, "source_reference", _identifier(self.source_reference, "budget source reference"))


@dataclass(frozen=True)
class CashflowDecision:
    period: str
    flow_type: CashflowType
    category: str
    status: CashflowStatus
    actual: Money
    budget: Money | None
    variance: Money | None
    transaction_ids: tuple[str, ...]
    budget_id: str | None
    reason_code: str

    def to_dict(self) -> dict[str, object]:
        return {
            "actual": self.actual.to_canonical_dict(),
            "budget": self.budget.to_canonical_dict() if self.budget is not None else None,
            "budget_id": self.budget_id,
            "category": self.category,
            "flow_type": self.flow_type,
            "period": self.period,
            "reason_code": self.reason_code,
            "status": self.status,
            "transaction_ids": list(self.transaction_ids),
            "variance": self.variance.to_canonical_dict() if self.variance is not None else None,
        }


@dataclass(frozen=True)
class IndividualCashflowControlRun:
    schema_version: int
    algorithm_version: str
    input_digests: tuple[str, ...]
    decisions: tuple[CashflowDecision, ...]
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
        }


def run_individual_cashflow_control(
    transactions: tuple[CashTransaction, ...],
    budgets: tuple[CashBudgetLine, ...] = (),
    *,
    input_digests: tuple[str, ...] = (),
) -> IndividualCashflowControlRun:
    """Aggregate exact local transactions into explainable budget decisions."""

    if not transactions and not budgets:
        raise IndividualCashflowControlError("individual cashflow control requires at least one record.")
    transaction_ids = [item.transaction_id for item in transactions]
    budget_ids = [item.budget_id for item in budgets]
    if len(transaction_ids) != len(set(transaction_ids)):
        raise IndividualCashflowControlError("transaction IDs must be unique.")
    if len(budget_ids) != len(set(budget_ids)):
        raise IndividualCashflowControlError("budget IDs must be unique.")
    currencies = [item.amount.currency for item in transactions] + [item.limit.currency for item in budgets]
    if currencies and len(set(currencies)) != 1:
        raise IndividualCashflowControlError("all transactions and budgets must use one currency.")
    actuals: dict[tuple[str, CashflowType, str], Money] = {}
    transaction_groups: dict[tuple[str, CashflowType, str], list[str]] = {}
    for transaction in transactions:
        key = (transaction.period, transaction.flow_type, transaction.category)
        actuals[key] = actuals.get(key, Money.from_exact("0", transaction.amount.currency)) + transaction.amount
        transaction_groups.setdefault(key, []).append(transaction.transaction_id)
    budget_groups: dict[tuple[str, CashflowType, str], CashBudgetLine] = {}
    for budget in budgets:
        key = (budget.period, budget.flow_type, budget.category)
        if key in budget_groups:
            raise IndividualCashflowControlError("only one budget line is allowed per period, type, and category.")
        budget_groups[key] = budget
    keys = sorted(set(actuals) | set(budget_groups))
    decisions: list[CashflowDecision] = []
    for period, flow_type, category in keys:
        key = (period, flow_type, category)
        budget_line = budget_groups.get(key)
        if budget_line is not None:
            zero = Money.from_exact("0", budget_line.limit.currency)
        else:
            zero = Money.from_exact("0", currencies[0])
        actual = actuals.get(key, zero)
        ids = tuple(sorted(transaction_groups.get(key, [])))
        if budget_line is None:
            status: CashflowStatus = "unbudgeted"
            variance = actual
            reason = "CASHFLOW_ACTIVITY_HAS_NO_BUDGET"
        elif not ids:
            status = "no_activity"
            variance = zero - budget_line.limit
            reason = "CASHFLOW_BUDGET_HAS_NO_ACTIVITY"
        else:
            variance = actual - budget_line.limit
            if actual.amount > budget_line.limit.amount:
                status = "over_budget"
                reason = "CASHFLOW_ACTIVITY_EXCEEDS_BUDGET"
            else:
                status = "within_budget"
                reason = "CASHFLOW_ACTIVITY_WITHIN_BUDGET"
        decisions.append(
            CashflowDecision(
                period,
                flow_type,
                category,
                status,
                actual,
                budget_line.limit if budget_line is not None else None,
                variance,
                ids,
                budget_line.budget_id if budget_line is not None else None,
                reason,
            )
        )
    ordered = tuple(sorted(decisions, key=lambda item: (item.period, item.flow_type, item.category, item.status)))
    payload = {
        "algorithm_version": INDIVIDUAL_CASHFLOW_CONTROL_ALGORITHM_VERSION,
        "decisions": [item.to_dict() for item in ordered],
        "input_digests": sorted(set(input_digests)),
        "schema_version": INDIVIDUAL_CASHFLOW_CONTROL_SCHEMA_VERSION,
    }
    return IndividualCashflowControlRun(
        INDIVIDUAL_CASHFLOW_CONTROL_SCHEMA_VERSION,
        INDIVIDUAL_CASHFLOW_CONTROL_ALGORITHM_VERSION,
        tuple(sorted(set(input_digests))),
        ordered,
        canonical_decision_digest(payload),
    )


def verify_individual_cashflow_payload(payload: dict[str, object]) -> None:
    try:
        verify_canonical_decision_payload(
            payload,
            expected_schema_version=INDIVIDUAL_CASHFLOW_CONTROL_SCHEMA_VERSION,
            expected_algorithm_version=INDIVIDUAL_CASHFLOW_CONTROL_ALGORITHM_VERSION,
            digest_fields=("algorithm_version", "decisions", "input_digests", "schema_version"),
            decision_sort_key=lambda item: (
                str(item.get("period")),
                str(item.get("flow_type")),
                str(item.get("category")),
                str(item.get("status")),
            ),
            allowed_statuses=frozenset({"within_budget", "over_budget", "unbudgeted", "no_activity"}),
        )
    except ValueError as exc:
        raise IndividualCashflowControlError("individual cashflow report replay verification failed.") from exc


__all__ = [
    "CashBudgetLine",
    "CashTransaction",
    "CashflowDecision",
    "CashflowStatus",
    "CashflowType",
    "INDIVIDUAL_CASHFLOW_CONTROL_ALGORITHM_VERSION",
    "INDIVIDUAL_CASHFLOW_CONTROL_SCHEMA_VERSION",
    "IndividualCashflowControlError",
    "IndividualCashflowControlRun",
    "run_individual_cashflow_control",
    "verify_individual_cashflow_payload",
]
