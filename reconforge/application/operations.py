"""Backend-neutral operational health and diagnostics use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

SchemaVersion = int | str


@dataclass(frozen=True)
class MigrationStatus:
    """Database migration state needed by the operational health use case."""

    current_version: SchemaVersion
    latest_version: SchemaVersion
    pending_versions: tuple[SchemaVersion, ...]


class OperationsRepositoryProtocol(Protocol):
    """Sanitized operational records exposed by a persistence adapter."""

    def audit_chain_ok(self) -> bool: ...

    def record_counts(self) -> tuple[int, int]: ...

    def list_jobs(self) -> list[dict[str, Any]]: ...

    def list_errors(self) -> list[dict[str, Any]]: ...

    def is_local_only(self) -> bool: ...


class MigrationStatusProvider(Protocol):
    """Resolve migration status without coupling application code to storage."""

    def __call__(self, database_locator: str) -> MigrationStatus: ...


class OperationsApplicationService:
    """Compose sanitized health output from explicit operational ports."""

    def __init__(
        self,
        repository: OperationsRepositoryProtocol,
        migration_status_provider: MigrationStatusProvider,
    ) -> None:
        self._repository = repository
        self._migration_status_provider = migration_status_provider

    def health(self, database_locator: str) -> dict[str, Any]:
        status = self._migration_status_provider(database_locator)
        job_records, error_records = self._repository.record_counts()
        return {
            "database_reachable": True,
            "schema_version": status.current_version,
            "latest_schema_version": status.latest_version,
            "pending_migrations": len(status.pending_versions),
            "audit_chain_ok": self._repository.audit_chain_ok(),
            "job_records": job_records,
            "error_records": error_records,
            "local_only": self._repository.is_local_only(),
        }

    def jobs(self) -> list[dict[str, Any]]:
        return self._repository.list_jobs()

    def errors(self) -> list[dict[str, Any]]:
        return self._repository.list_errors()
