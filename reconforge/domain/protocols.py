"""Formal Repository Protocols for Backend-Neutral Persistence.

These protocols establish explicit contracts for domain persistence operations,
enabling clean separation between domain logic and underlying database implementations
(SQLite, PostgreSQL, or mock test backends).
"""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from reconforge.domain.models import AuditEventReference, Period, Workspace

if TYPE_CHECKING:
    from reconforge.audit.events import AuditVerificationResult


@runtime_checkable
class WorkspaceRepositoryProtocol(Protocol):
    """Abstract contract for Workspace persistence."""

    def create(self, *, name: str, local_first_note: str | None = None) -> Workspace: ...

    def get(self, workspace_id: str) -> Workspace | None: ...

    def list(self) -> list[Workspace]: ...


@runtime_checkable
class PeriodRepositoryProtocol(Protocol):
    """Abstract contract for Period persistence."""

    def create(
        self,
        *,
        workspace_id: str,
        name: str,
        start_date: str,
        end_date: str,
        status: str = "Open",
    ) -> Period: ...

    def get(self, period_id: str) -> Period | None: ...

    def list(self, *, workspace_id: str | None = None) -> list[Period]: ...


@runtime_checkable
class AuditEventRepositoryProtocol(Protocol):
    """Abstract contract for Audit Event append-only persistence and verification."""

    def append(
        self,
        *,
        actor_label: str,
        object_type: str,
        object_id: str,
        action: str,
        actor_user_id: str | None = None,
        before_hash: str | None = None,
        after_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEventReference: ...

    def list(self, *, limit: int | None = None) -> list[AuditEventReference]: ...

    def verify(self) -> AuditVerificationResult: ...


@runtime_checkable
class DomainUnitOfWorkProtocol(Protocol):
    """Atomic application boundary for the local domain backbone.

    Implementations own the transaction and expose repositories without
    leaking a database connection into application services. Exiting without
    an explicit successful ``commit`` must roll back.
    """

    workspaces: WorkspaceRepositoryProtocol
    periods: PeriodRepositoryProtocol
    audit_events: AuditEventRepositoryProtocol

    def __enter__(self) -> DomainUnitOfWorkProtocol: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


DomainUnitOfWorkFactory = Callable[[], DomainUnitOfWorkProtocol]
