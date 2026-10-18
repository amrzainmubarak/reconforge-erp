"""Pure, exact invariants for governed operational budget utilization."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

MAX_MINOR = 9_000_000_000_000_000_000


class BudgetControlError(ValueError):
    """A safe, closed budget contract or invariant failure."""


def text(value: object, label: str, maximum: int = 160) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > maximum:
        raise BudgetControlError(f"{label} requires bounded, nonempty canonical text.")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise BudgetControlError(f"{label} contains control characters.")
    return value


def minor(value: object) -> int:
    """Reject implicit truncation, booleans, exponents, signs, and overflow."""
    if type(value) is int:
        result = value
    elif isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value):
        result = int(value)
    else:
        raise BudgetControlError("Amount requires a positive exact integer in minor units.")
    if not 1 <= result <= MAX_MINOR:
        raise BudgetControlError("Amount exceeds the supported minor-unit range.")
    return result


def digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class BudgetScope:
    workspace_id: str
    organization_id: str
    legal_entity_id: str

    def __post_init__(self) -> None:
        for label, value in vars(self).items():
            text(value, label)


@dataclass(frozen=True)
class BudgetDefinition:
    budget_code: str
    name: str
    period_id: str
    currency_code: str
    limit_minor: int

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{0,63}", self.budget_code):
            raise BudgetControlError("Budget code must be canonical uppercase text.")
        text(self.name, "Budget name", 200)
        text(self.period_id, "Fiscal period")
        if not re.fullmatch(r"[A-Z]{3}", self.currency_code):
            raise BudgetControlError("Currency requires an explicit uppercase three-letter code.")
        if type(self.limit_minor) is not int:
            raise BudgetControlError("Budget limit requires exact integer minor units.")
        minor(self.limit_minor)


@dataclass(frozen=True)
class CommitmentAction:
    operation: str
    amount_minor: int
    operation_date: str
    source_reference: str
    reason: str

    def __post_init__(self) -> None:
        if self.operation not in {"Reserve", "Release", "Consume"}:
            raise BudgetControlError("Unsupported commitment operation.")
        if type(self.amount_minor) is not int:
            raise BudgetControlError("Commitment amount requires exact integer minor units.")
        minor(self.amount_minor)
        try:
            if date.fromisoformat(self.operation_date).isoformat() != self.operation_date:
                raise ValueError("noncanonical date")
        except (TypeError, ValueError) as exc:
            raise BudgetControlError("Operation date requires YYYY-MM-DD.") from exc
        text(self.source_reference, "Source reference")
        text(self.reason, "Reason", 500)


def transition(status: str, action: str, *, preparer_id: str, submitter_id: str | None, actor_id: str) -> str:
    if action == "submit" and status == "Draft":
        return "Submitted"
    if action == "approve" and status == "Submitted":
        if actor_id in {preparer_id, submitter_id}:
            raise BudgetControlError("Independent approval requires a different persisted human identity.")
        return "Approved"
    raise BudgetControlError("Budget lifecycle transition is invalid.")


def conservation(limit: int, reserved: int, consumed: int) -> int:
    if any(type(value) is not int for value in (limit, reserved, consumed)) or limit < 1 or reserved < 0 or consumed < 0:
        raise BudgetControlError("Budget balance is malformed.")
    available = limit - reserved - consumed
    if available < 0:
        raise BudgetControlError("Budget capacity exceeded.")
    return available
