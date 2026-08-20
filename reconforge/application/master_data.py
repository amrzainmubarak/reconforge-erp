"""Backend-neutral application contract for governed master data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from reconforge.utils.money import CurrencyRegistryContext

DEFAULT_LIST_LIMIT = 500


@dataclass(frozen=True)
class MasterDataSummary:
    """Counts for one workspace's shared master-data references."""

    workspace: str
    organizations: int
    legal_entities: int
    branches: int
    periods: int
    active_currencies: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class MasterDataRepository(Protocol):
    """Persistence port for the complete master-data use-case surface."""

    def upsert_currency(
        self, *, code: str, name: str, minor_units: int = 2, active: bool = True, actor_label: str = "local-cli"
    ) -> dict[str, Any]: ...
    def list_currencies(
        self,
        *,
        active_only: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...
    def upsert_organization(
        self,
        *,
        organization_code: str,
        name: str,
        workspace: str = "default",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...
    def list_organizations(
        self,
        *,
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...
    def upsert_legal_entity(
        self,
        *,
        organization_code: str,
        entity_code: str,
        name: str,
        currency_code: str,
        workspace: str = "default",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...
    def list_legal_entities(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...
    def upsert_branch(
        self,
        *,
        organization_code: str,
        branch_code: str,
        name: str,
        entity_code: str = "",
        workspace: str = "default",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...
    def list_branches(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...
    def upsert_period(
        self,
        *,
        name: str,
        start_date: str,
        end_date: str,
        workspace: str = "default",
        fiscal_year: int | None = None,
        period_number: int | None = None,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]: ...
    def set_period_status(
        self, period_id: str, *, status: str, reason: str = "", actor_label: str = "local-cli"
    ) -> dict[str, Any]: ...
    def list_periods(
        self,
        *,
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]: ...
    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> MasterDataSummary: ...
    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]: ...
    def currency_registry_reconciliation(
        self, *, workspace: str = "default", actor_label: str = "local-cli"
    ) -> dict[str, object]: ...
    def currency_registry_binding(
        self, *, workspace: str = "default", actor_label: str = "local-cli"
    ) -> dict[str, object] | None: ...
    def currency_registry_context(
        self, *, workspace: str = "default", actor_label: str = "local-cli"
    ) -> CurrencyRegistryContext | None: ...
    def bind_currency_registry(
        self, *, workspace: str = "default", actor_label: str = "local-cli"
    ) -> dict[str, object]: ...


class MasterDataApplicationService:
    """Coordinates master-data use cases independently of the storage backend."""

    def __init__(self, repository: MasterDataRepository) -> None:
        self._repository = repository

    def __getattr__(self, name: str) -> Any:
        """Delegate the stable use-case surface to the injected repository."""
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._repository, name)
