"""Tenant-isolated local database routing for optional hosted-style deployments.

This module implements the conservative database-per-tenant option. It does not
pretend to provide shared-schema PostgreSQL row-level security; callers must opt in
to the router and send an explicit tenant header for every database-backed request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from reconforge.db.connection import DatabaseError, resolve_db_path

_TENANT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class TenantRoutingError(DatabaseError):
    """Raised when a tenant database cannot be selected safely."""


class InvalidTenantIdError(TenantRoutingError):
    """Raised when a tenant identifier is missing or unsafe."""


class TenantDatabaseNotFoundError(TenantRoutingError):
    """Raised when a valid tenant has no initialized database."""


def resolve_tenant_root(root: Path | str) -> Path:
    """Resolve and validate a tenant database directory without creating it."""

    raw = str(root)
    if not raw.strip():
        raise TenantRoutingError("Tenant database root must be a directory.")
    path = Path(root).expanduser()
    if path.exists() and path.is_symlink():
        raise TenantRoutingError("Tenant database root must not be a symlink.")
    resolved = path.resolve(strict=False)
    if resolved.exists() and not resolved.is_dir():
        raise TenantRoutingError("Tenant database root must be a directory.")
    return resolved


@dataclass(frozen=True)
class TenantDatabaseRouter:
    """Resolve one immutable SQLite database path per validated tenant ID."""

    root: Path

    @classmethod
    def from_root(cls, root: Path | str) -> TenantDatabaseRouter:
        return cls(root=resolve_tenant_root(root))

    def path_for(self, tenant_id: str, *, require_exists: bool = True) -> Path:
        """Return the tenant database path while preventing traversal or symlink escape."""

        normalized = str(tenant_id or "").strip().lower()
        if not _TENANT_ID_PATTERN.fullmatch(normalized):
            raise InvalidTenantIdError(
                "Tenant identifier must use 1-64 lowercase letters, numbers, hyphens, or underscores."
            )
        candidate = (self.root / f"{normalized}.db").resolve(strict=False)
        if candidate.parent != self.root:
            raise InvalidTenantIdError("Tenant identifier resolved outside the tenant database root.")
        try:
            resolved = resolve_db_path(candidate)
        except DatabaseError as exc:
            raise TenantRoutingError("Tenant database path is not safe.") from exc
        if require_exists and not resolved.exists():
            raise TenantDatabaseNotFoundError("Tenant database is not initialized.")
        return resolved
