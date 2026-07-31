"""Backend-neutral governed finance-core application boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Protocol

DEFAULT_LIST_LIMIT = 500
MAX_LIST_LIMIT = 100_000


@dataclass(frozen=True)
class FinanceCoreSummary:
    """Counts for one workspace without a persistence dependency."""

    workspace: str
    charts: int
    accounts: int
    dimensions: int
    dimension_values: int
    journals: int
    draft_entries: int
    validated_entries: int
    voided_entries: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class FinanceCoreRepositoryProtocol(Protocol):
    """Complete persistence and policy port for the governed finance core."""

    def upsert_chart(
        self,
        *,
        chart_code: str,
        name: str,
        workspace: str = "default",
        organization_code: str = "",
        description: str = "",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def list_charts(
        self,
        *,
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...

    def upsert_account(
        self,
        *,
        account_code: str,
        name: str,
        workspace: str = "default",
        chart_code: str = "DEFAULT",
        parent_account_code: str = "",
        account_type: str = "Asset",
        normal_balance: str = "Debit",
        allow_posting: bool = True,
        allow_manual_posting: bool = True,
        reconciliation_required: bool = False,
        active: bool = True,
        description: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def list_accounts(
        self,
        *,
        workspace: str = "default",
        chart_code: str = "",
        active_only: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...

    def upsert_dimension(
        self,
        *,
        dimension_code: str,
        name: str,
        workspace: str = "default",
        organization_code: str = "",
        dimension_type: str = "Custom",
        required_on_entries: bool = False,
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def upsert_dimension_value(
        self,
        *,
        dimension_code: str,
        value_code: str,
        name: str,
        workspace: str = "default",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def list_dimensions(
        self,
        *,
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...

    def list_dimension_values(
        self,
        *,
        dimension_code: str = "",
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...

    def upsert_journal(
        self,
        *,
        journal_code: str,
        name: str,
        organization_code: str,
        currency_code: str,
        workspace: str = "default",
        chart_code: str = "DEFAULT",
        journal_type: str = "General",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def list_journals(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...

    def create_entry(
        self,
        *,
        entry_number: str,
        organization_code: str,
        entity_code: str,
        period_id: str,
        journal_code: str,
        posting_date: str,
        description: str,
        lines: Sequence[Mapping[str, object]],
        workspace: str = "default",
        external_reference: str = "",
        source_type: str = "Manual",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...

    def validate_entry(self, entry_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def void_entry(self, entry_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def get_entry(self, entry_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]: ...

    def list_entries(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        period_id: str = "",
        status: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...

    def trial_balance(
        self,
        *,
        period_id: str,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, object]: ...

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> FinanceCoreSummary: ...

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]: ...


class FinanceCoreApplicationService:
    """Coordinate finance-core use cases without importing a database adapter."""

    def __init__(self, repository: FinanceCoreRepositoryProtocol) -> None:
        self.repository = repository

    def upsert_chart(
        self,
        *,
        chart_code: str,
        name: str,
        workspace: str = "default",
        organization_code: str = "",
        description: str = "",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.upsert_chart(
            chart_code=chart_code,
            name=name,
            workspace=workspace,
            organization_code=organization_code,
            description=description,
            active=active,
            actor_label=actor_label,
        )

    def list_charts(
        self,
        *,
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        return self.repository.list_charts(workspace=workspace, limit=limit, offset=offset, actor_label=actor_label)

    def upsert_account(
        self,
        *,
        account_code: str,
        name: str,
        workspace: str = "default",
        chart_code: str = "DEFAULT",
        parent_account_code: str = "",
        account_type: str = "Asset",
        normal_balance: str = "Debit",
        allow_posting: bool = True,
        allow_manual_posting: bool = True,
        reconciliation_required: bool = False,
        active: bool = True,
        description: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.upsert_account(
            account_code=account_code,
            name=name,
            workspace=workspace,
            chart_code=chart_code,
            parent_account_code=parent_account_code,
            account_type=account_type,
            normal_balance=normal_balance,
            allow_posting=allow_posting,
            allow_manual_posting=allow_manual_posting,
            reconciliation_required=reconciliation_required,
            active=active,
            description=description,
            actor_label=actor_label,
        )

    def list_accounts(
        self,
        *,
        workspace: str = "default",
        chart_code: str = "",
        active_only: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        return self.repository.list_accounts(
            workspace=workspace,
            chart_code=chart_code,
            active_only=active_only,
            limit=limit,
            offset=offset,
            actor_label=actor_label,
        )

    def upsert_dimension(
        self,
        *,
        dimension_code: str,
        name: str,
        workspace: str = "default",
        organization_code: str = "",
        dimension_type: str = "Custom",
        required_on_entries: bool = False,
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.upsert_dimension(
            dimension_code=dimension_code,
            name=name,
            workspace=workspace,
            organization_code=organization_code,
            dimension_type=dimension_type,
            required_on_entries=required_on_entries,
            active=active,
            actor_label=actor_label,
        )

    def upsert_dimension_value(
        self,
        *,
        dimension_code: str,
        value_code: str,
        name: str,
        workspace: str = "default",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.upsert_dimension_value(
            dimension_code=dimension_code,
            value_code=value_code,
            name=name,
            workspace=workspace,
            active=active,
            actor_label=actor_label,
        )

    def list_dimensions(
        self,
        *,
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        return self.repository.list_dimensions(workspace=workspace, limit=limit, offset=offset, actor_label=actor_label)

    def list_dimension_values(
        self,
        *,
        dimension_code: str = "",
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        return self.repository.list_dimension_values(
            dimension_code=dimension_code,
            workspace=workspace,
            limit=limit,
            offset=offset,
            actor_label=actor_label,
        )

    def upsert_journal(
        self,
        *,
        journal_code: str,
        name: str,
        organization_code: str,
        currency_code: str,
        workspace: str = "default",
        chart_code: str = "DEFAULT",
        journal_type: str = "General",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.upsert_journal(
            journal_code=journal_code,
            name=name,
            organization_code=organization_code,
            currency_code=currency_code,
            workspace=workspace,
            chart_code=chart_code,
            journal_type=journal_type,
            active=active,
            actor_label=actor_label,
        )

    def list_journals(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        return self.repository.list_journals(
            workspace=workspace,
            organization_code=organization_code,
            limit=limit,
            offset=offset,
            actor_label=actor_label,
        )

    def create_entry(
        self,
        *,
        entry_number: str,
        organization_code: str,
        entity_code: str,
        period_id: str,
        journal_code: str,
        posting_date: str,
        description: str,
        lines: Sequence[Mapping[str, object]],
        workspace: str = "default",
        external_reference: str = "",
        source_type: str = "Manual",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        return self.repository.create_entry(
            entry_number=entry_number,
            organization_code=organization_code,
            entity_code=entity_code,
            period_id=period_id,
            journal_code=journal_code,
            posting_date=posting_date,
            description=description,
            lines=lines,
            workspace=workspace,
            external_reference=external_reference,
            source_type=source_type,
            actor_label=actor_label,
        )

    def validate_entry(self, entry_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.validate_entry(entry_id, reason=reason, actor_label=actor_label)

    def void_entry(self, entry_id: str, *, reason: str, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.void_entry(entry_id, reason=reason, actor_label=actor_label)

    def get_entry(self, entry_id: str, *, actor_label: str = "local-cli") -> dict[str, Any]:
        return self.repository.get_entry(entry_id, actor_label=actor_label)

    def list_entries(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        entity_code: str = "",
        period_id: str = "",
        status: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        return self.repository.list_entries(
            workspace=workspace,
            organization_code=organization_code,
            entity_code=entity_code,
            period_id=period_id,
            status=status,
            limit=limit,
            offset=offset,
            actor_label=actor_label,
        )

    def trial_balance(
        self,
        *,
        period_id: str,
        organization_code: str,
        entity_code: str,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, object]:
        return self.repository.trial_balance(
            period_id=period_id,
            organization_code=organization_code,
            entity_code=entity_code,
            workspace=workspace,
            actor_label=actor_label,
        )

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> FinanceCoreSummary:
        return self.repository.summary(workspace=workspace, actor_label=actor_label)

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]:
        return self.repository.snapshot(workspace=workspace, actor_label=actor_label)
