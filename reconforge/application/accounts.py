"""Backend-neutral account-reconciliation application boundary."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class ImportTrialBalanceResult:
    """Result from importing trial-balance rows without a database dependency."""

    source_path: Path
    imported_rows: int
    reconciliation_records: int


class AccountReconciliationRepositoryProtocol(Protocol):
    """Complete persistence and policy port for account reconciliation."""

    def import_trial_balance(
        self,
        input_path: Path | str,
        *,
        workspace: str = "default",
        default_period: str = "current",
        default_entity: str = "local",
        actor_label: str = "local-cli",
    ) -> ImportTrialBalanceResult: ...

    def create_template(
        self,
        *,
        account_code: str,
        name: str = "",
        workspace: str = "default",
        risk_rating: str = "medium",
        materiality_threshold: object = Decimal("0"),
        required_evidence: str = "",
        owner: str = "",
        reviewer: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def create_reconciliation(
        self,
        *,
        period_name: str,
        entity_code: str,
        account_code: str,
        account_name: str = "",
        workspace: str = "default",
        balance: object = Decimal("0"),
        owner: str = "",
        preparer: str = "",
        reviewer: str = "",
        risk_rating: str = "medium",
        materiality_threshold: object = Decimal("0"),
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def prepare(
        self,
        *,
        reconciliation_id: str | None = None,
        workspace: str = "default",
        period_name: str = "current",
        entity_code: str = "local",
        account_code: str = "",
        preparer: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def submit(self, reconciliation_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def review(
        self, reconciliation_id: str, *, reviewer: str = "", actor_label: str = "local-cli"
    ) -> dict[str, Any]: ...

    def complete(self, reconciliation_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def roll_forward(
        self,
        *,
        from_period: str,
        to_period: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> int: ...

    def list_reconciliations(
        self,
        *,
        status: str = "",
        owner: str = "",
        period_name: str = "",
        entity_code: str = "",
        risk_rating: str = "",
    ) -> list[dict[str, Any]]: ...

    def get_reconciliation(self, reconciliation_id: str) -> dict[str, Any]: ...

    def get_template(self, template_id: str) -> dict[str, Any]: ...


class AccountReconciliationApplicationService:
    """Coordinate account workflows without importing a database adapter."""

    def __init__(self, repository: AccountReconciliationRepositoryProtocol) -> None:
        self.repository = repository

    def import_trial_balance(
        self,
        input_path: Path | str,
        *,
        workspace: str = "default",
        default_period: str = "current",
        default_entity: str = "local",
        actor_label: str = "local-cli",
    ) -> ImportTrialBalanceResult:
        return self.repository.import_trial_balance(
            input_path,
            workspace=workspace,
            default_period=default_period,
            default_entity=default_entity,
            actor_label=actor_label,
        )

    def create_template(
        self,
        *,
        account_code: str,
        name: str = "",
        workspace: str = "default",
        risk_rating: str = "medium",
        materiality_threshold: object = Decimal("0"),
        required_evidence: str = "",
        owner: str = "",
        reviewer: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.create_template(
            account_code=account_code,
            name=name,
            workspace=workspace,
            risk_rating=risk_rating,
            materiality_threshold=materiality_threshold,
            required_evidence=required_evidence,
            owner=owner,
            reviewer=reviewer,
            actor_label=actor_label,
        )

    def create_reconciliation(
        self,
        *,
        period_name: str,
        entity_code: str,
        account_code: str,
        account_name: str = "",
        workspace: str = "default",
        balance: object = Decimal("0"),
        owner: str = "",
        preparer: str = "",
        reviewer: str = "",
        risk_rating: str = "medium",
        materiality_threshold: object = Decimal("0"),
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.create_reconciliation(
            period_name=period_name,
            entity_code=entity_code,
            account_code=account_code,
            account_name=account_name,
            workspace=workspace,
            balance=balance,
            owner=owner,
            preparer=preparer,
            reviewer=reviewer,
            risk_rating=risk_rating,
            materiality_threshold=materiality_threshold,
            actor_label=actor_label,
        )

    def prepare(
        self,
        *,
        reconciliation_id: str | None = None,
        workspace: str = "default",
        period_name: str = "current",
        entity_code: str = "local",
        account_code: str = "",
        preparer: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.prepare(
            reconciliation_id=reconciliation_id,
            workspace=workspace,
            period_name=period_name,
            entity_code=entity_code,
            account_code=account_code,
            preparer=preparer,
            actor_label=actor_label,
        )

    def submit(self, reconciliation_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.submit(reconciliation_id, actor_label=actor_label)

    def review(self, reconciliation_id: str, *, reviewer: str = "", actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.review(reconciliation_id, reviewer=reviewer, actor_label=actor_label)

    def complete(self, reconciliation_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.complete(reconciliation_id, actor_label=actor_label)

    def roll_forward(
        self,
        *,
        from_period: str,
        to_period: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> int:
        return self.repository.roll_forward(
            from_period=from_period,
            to_period=to_period,
            workspace=workspace,
            actor_label=actor_label,
        )

    def list_reconciliations(
        self,
        *,
        status: str = "",
        owner: str = "",
        period_name: str = "",
        entity_code: str = "",
        risk_rating: str = "",
    ) -> list[dict[str, Any]]:
        return self.repository.list_reconciliations(
            status=status,
            owner=owner,
            period_name=period_name,
            entity_code=entity_code,
            risk_rating=risk_rating,
        )

    def get_reconciliation(self, reconciliation_id: str) -> dict[str, Any]:
        return self.repository.get_reconciliation(reconciliation_id)

    def get_template(self, template_id: str) -> dict[str, Any]:
        return self.repository.get_template(template_id)
