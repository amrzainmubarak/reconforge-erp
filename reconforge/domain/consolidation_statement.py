"""Deterministic, non-statutory management trial-balance projection."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext

from reconforge.domain.consolidation import ConsolidationAccountType, ConsolidationError
from reconforge.domain.consolidation_lifecycle import ConsolidationWorksheetResult
from reconforge.utils.money import Money

MANAGEMENT_TRIAL_BALANCE_SCHEMA_VERSION = 1
MANAGEMENT_TRIAL_BALANCE_ALGORITHM_VERSION = "consolidation-management-trial-balance-v1"


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def _sum(values: tuple[Decimal, ...]) -> Decimal:
    with localcontext() as context:
        context.prec = max(28, max((len(v.as_tuple().digits) for v in values), default=1) + 8)
        return sum(values, Decimal("0"))


@dataclass(frozen=True)
class ManagementTrialBalanceLine:
    group_account_code: str
    account_type: ConsolidationAccountType
    amount: Money
    source_references: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.group_account_code or not isinstance(self.group_account_code, str):
            raise ConsolidationError("Management statement account code is invalid.")
        if self.account_type not in {"Asset", "Liability", "Equity", "Income", "Expense"}:
            raise ConsolidationError("Management statement account type is invalid.")
        if not isinstance(self.amount, Money) or self.amount.amount.is_nan() or self.amount.amount.is_infinite():
            raise ConsolidationError("Management statement amount is invalid.")
        if not isinstance(self.source_references, tuple) or not self.source_references or any(
            not isinstance(item, str) or not item for item in self.source_references
        ):
            raise ConsolidationError("Management statement source lineage is required.")

    def to_dict(self) -> dict[str, object]:
        return {
            "account_type": self.account_type,
            "amount": self.amount.to_canonical_dict(),
            "group_account_code": self.group_account_code,
            "source_references": list(self.source_references),
        }


@dataclass(frozen=True)
class ManagementTrialBalance:
    worksheet_id: str
    worksheet_result_digest: str
    group_code: str
    period_id: str
    reporting_currency: str
    lines: tuple[ManagementTrialBalanceLine, ...]
    total_balance: Money
    artifact_digest: str
    schema_version: int = MANAGEMENT_TRIAL_BALANCE_SCHEMA_VERSION
    algorithm_version: str = MANAGEMENT_TRIAL_BALANCE_ALGORITHM_VERSION

    def _payload(self) -> dict[str, object]:
        return {
            "algorithm_version": self.algorithm_version,
            "group_code": self.group_code,
            "lines": [line.to_dict() for line in self.lines],
            "period_id": self.period_id,
            "reporting_currency": self.reporting_currency,
            "schema_version": self.schema_version,
            "total_balance": self.total_balance.to_canonical_dict(),
            "worksheet_id": self.worksheet_id,
            "worksheet_result_digest": self.worksheet_result_digest,
        }

    def to_dict(self) -> dict[str, object]:
        payload = self._payload()
        payload["artifact_digest"] = self.artifact_digest
        return payload


def build_management_trial_balance(worksheet: ConsolidationWorksheetResult) -> ManagementTrialBalance:
    """Project a balanced worksheet into an explainable management artifact.

    This is not a statutory financial statement and creates no posting effect.
    """
    if not isinstance(worksheet, ConsolidationWorksheetResult) or worksheet.posting_effect != "none":
        raise ConsolidationError("Only a verified non-posting consolidation worksheet is accepted.")
    currency = worksheet.reporting_currency
    lines = tuple(
        ManagementTrialBalanceLine(
            group_account_code=item.group_account_code,
            account_type=item.account_type,
            amount=item.amount,
            source_references=tuple(sorted(set(item.source_references))),
        )
        for item in sorted(worksheet.worksheet_accounts, key=lambda item: item.group_account_code)
    )
    if any(line.amount.currency != currency for line in lines):
        raise ConsolidationError("Management trial balance contains mixed currencies.")
    total = Money.from_exact(_sum(tuple(line.amount.amount for line in lines)), currency, strict_precision=True)
    if total.amount != 0:
        raise ConsolidationError("Management trial balance must remain balanced.")
    provisional = ManagementTrialBalance(
        worksheet_id=worksheet.worksheet_id,
        worksheet_result_digest=worksheet.result_digest,
        group_code=worksheet.group_code,
        period_id=worksheet.period_id,
        reporting_currency=currency,
        lines=lines,
        total_balance=total,
        artifact_digest="0" * 64,
    )
    return ManagementTrialBalance(**{**provisional.__dict__, "artifact_digest": _digest(provisional._payload())})


def verify_management_trial_balance(artifact: ManagementTrialBalance) -> ManagementTrialBalance:
    if not isinstance(artifact, ManagementTrialBalance):
        raise ConsolidationError("Management trial balance artifact is invalid.")
    if artifact.artifact_digest != _digest(artifact._payload()):
        raise ConsolidationError("Management trial balance digest verification failed.")
    if artifact.total_balance.amount != _sum(tuple(line.amount.amount for line in artifact.lines)):
        raise ConsolidationError("Management trial balance total is inconsistent.")
    if artifact.total_balance.amount != 0:
        raise ConsolidationError("Management trial balance is not balanced.")
    return artifact
