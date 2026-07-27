"""Governed organization, currency, branch, and fiscal-period master-data foundations."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from reconforge.domain.models import utc_now_text
from reconforge.platform.common import (
    PlatformError,
    commit_audited,
    ensure_platform_schema,
    ensure_workspace,
    platform_id,
    require_permission,
)

MASTER_DATA_READ_PERMISSION = "master_data.read"
MASTER_DATA_MANAGE_PERMISSION = "master_data.manage"
PERIOD_STATUSES = ("Open", "Soft Closed", "Closed")
DEFAULT_LIST_LIMIT = 500
MAX_SNAPSHOT_RECORDS = 100_000
_PERIOD_TRANSITIONS = {
    "Open": {"Soft Closed"},
    "Soft Closed": {"Open", "Closed"},
    "Closed": {"Open"},
}
_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,31}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class MasterDataSummary:
    """Counts for one local workspace's shared master-data references."""

    workspace: str
    organizations: int
    legal_entities: int
    branches: int
    periods: int
    active_currencies: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _clean_code(value: str, label: str) -> str:
    code = value.strip().upper()
    if not _CODE_PATTERN.fullmatch(code):
        raise PlatformError(f"{label} must use 1-32 uppercase letters, numbers, dots, underscores, or hyphens.")
    return code


def _currency_code(value: str) -> str:
    code = value.strip().upper()
    if not _CURRENCY_PATTERN.fullmatch(code):
        raise PlatformError("Currency code must contain exactly three uppercase letters.")
    return code


def _clean_name(value: str, label: str) -> str:
    raw = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise PlatformError(f"{label} must contain 1-160 printable characters.")
    name = " ".join(raw.split())
    if not name or len(name) > 160:
        raise PlatformError(f"{label} must contain 1-160 printable characters.")
    return name


def _workspace_name(value: str) -> str:
    return _clean_name(value, "Workspace name")


def _clean_reason(value: str) -> str:
    raw = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in raw):
        raise PlatformError("Period status reason must contain printable characters only.")
    reason = " ".join(raw.split())
    if len(reason) > 500:
        raise PlatformError("Period status reason must not exceed 500 characters.")
    return reason


def _iso_date(value: str, label: str) -> date:
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError as exc:
        raise PlatformError(f"{label} must be an ISO date in YYYY-MM-DD format.") from exc
    if parsed.isoformat() != value.strip():
        raise PlatformError(f"{label} must be an ISO date in YYYY-MM-DD format.")
    return parsed


def _public_record(row: sqlite3.Row) -> dict[str, Any]:
    record = dict(row)
    if "active" in record:
        record["active"] = bool(record["active"])
    return record


def _page(limit: int, offset: int) -> tuple[int, int]:
    if not 1 <= limit <= MAX_SNAPSHOT_RECORDS:
        raise PlatformError(f"List limit must be between 1 and {MAX_SNAPSHOT_RECORDS}.")
    if not 0 <= offset <= 10_000_000:
        raise PlatformError("List offset must be between 0 and 10000000.")
    return limit, offset


class MasterDataService:
    """Local service enforcing shared master-data invariants and audit events."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        ensure_platform_schema(connection)
        self.connection = connection
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        try:
            tables = {
                str(row["name"])
                for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('currencies', 'branches')"
                ).fetchall()
            }
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to inspect local master-data schema.") from exc
        if tables != {"currencies", "branches"}:
            raise PlatformError("Master-data schema is not initialized. Run 'reconforge db migrate' first.")

    def upsert_currency(
        self,
        *,
        code: str,
        name: str,
        minor_units: int = 2,
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create or update a local currency reference."""

        require_permission(self.connection, actor_label=actor_label, permission=MASTER_DATA_MANAGE_PERMISSION)
        currency = _currency_code(code)
        currency_name = _clean_name(name, "Currency name")
        if not 0 <= minor_units <= 6:
            raise PlatformError("Currency minor units must be between 0 and 6.")
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO currencies (code, name, minor_units, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    minor_units = excluded.minor_units,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (currency, currency_name, minor_units, int(active), now, now),
            )
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save local currency reference.") from exc
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="currency",
            object_id=currency,
            action="currency_upserted",
            metadata={"code": currency, "minor_units": minor_units, "active": active},
        )
        return self._currency(currency)

    def list_currencies(
        self,
        *,
        active_only: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        """List local currency references without exposing unrelated database state."""

        require_permission(self.connection, actor_label=actor_label, permission=MASTER_DATA_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        query = "SELECT * FROM currencies"
        parameters: tuple[object, ...] = ()
        if active_only:
            query += " WHERE active = ?"
            parameters = (1,)
        query += " ORDER BY code LIMIT ? OFFSET ?"
        parameters = (*parameters, page_limit, page_offset)
        try:
            return [_public_record(row) for row in self.connection.execute(query, parameters).fetchall()]
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local currency references.") from exc

    def upsert_organization(
        self,
        *,
        organization_code: str,
        name: str,
        workspace: str = "default",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Create or update one organization inside a local workspace."""

        require_permission(self.connection, actor_label=actor_label, permission=MASTER_DATA_MANAGE_PERMISSION)
        workspace_name = _workspace_name(workspace)
        workspace_id = ensure_workspace(self.connection, workspace_name)
        code = _clean_code(organization_code, "Organization code")
        organization_name = _clean_name(name, "Organization name")
        organization_id = platform_id("ORG", workspace_id, code)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO organizations (
                    id, workspace_id, name, created_at, organization_code, active, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, organization_code) DO UPDATE SET
                    name = excluded.name,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (organization_id, workspace_id, organization_name, now, code, int(active), now),
            )
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save local organization reference.") from exc
        record = self._organization(workspace_id, code)
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="organization",
            object_id=str(record["id"]),
            action="organization_upserted",
            metadata={"organization_code": code, "workspace": workspace_name, "active": active},
        )
        return record

    def list_organizations(
        self,
        *,
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        """List organizations for one local workspace."""

        require_permission(self.connection, actor_label=actor_label, permission=MASTER_DATA_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        try:
            rows = self.connection.execute(
                "SELECT * FROM organizations WHERE workspace_id = ? ORDER BY organization_code, id LIMIT ? OFFSET ?",
                (workspace_id, page_limit, page_offset),
            ).fetchall()
            return [_public_record(row) for row in rows]
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local organization references.") from exc

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
    ) -> dict[str, Any]:
        """Create or update a legal-entity reference after validating its active currency."""

        require_permission(self.connection, actor_label=actor_label, permission=MASTER_DATA_MANAGE_PERMISSION)
        workspace_id = ensure_workspace(self.connection, _workspace_name(workspace))
        organization = self._organization(workspace_id, _clean_code(organization_code, "Organization code"))
        code = _clean_code(entity_code, "Entity code")
        entity_name = _clean_name(name, "Entity name")
        currency = _currency_code(currency_code)
        currency_record = self._currency(currency)
        if not currency_record["active"]:
            raise PlatformError("Legal entities require an active currency reference.")
        entity_id = platform_id("LE", str(organization["id"]), code)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO legal_entities (
                    id, organization_id, entity_code, name, currency, created_at, active, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(organization_id, entity_code) DO UPDATE SET
                    name = excluded.name,
                    currency = excluded.currency,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (entity_id, organization["id"], code, entity_name, currency, now, int(active), now),
            )
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save local legal-entity reference.") from exc
        record = self._legal_entity(str(organization["id"]), code)
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="legal_entity",
            object_id=str(record["id"]),
            action="legal_entity_upserted",
            metadata={
                "entity_code": code,
                "organization_code": organization["organization_code"],
                "currency": currency,
            },
        )
        return record

    def list_legal_entities(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        """List legal entities with their organization code."""

        require_permission(self.connection, actor_label=actor_label, permission=MASTER_DATA_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        query = """
            SELECT legal_entities.*, organizations.organization_code
            FROM legal_entities
            JOIN organizations ON organizations.id = legal_entities.organization_id
            WHERE organizations.workspace_id = ?
        """
        parameters: list[object] = [workspace_id]
        if organization_code:
            query += " AND organizations.organization_code = ?"
            parameters.append(_clean_code(organization_code, "Organization code"))
        query += " ORDER BY organizations.organization_code, legal_entities.entity_code LIMIT ? OFFSET ?"
        parameters.extend((page_limit, page_offset))
        try:
            return [_public_record(row) for row in self.connection.execute(query, parameters).fetchall()]
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local legal-entity references.") from exc

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
    ) -> dict[str, Any]:
        """Create or update a branch and optionally bind it to an entity in the same organization."""

        require_permission(self.connection, actor_label=actor_label, permission=MASTER_DATA_MANAGE_PERMISSION)
        workspace_id = ensure_workspace(self.connection, _workspace_name(workspace))
        organization = self._organization(workspace_id, _clean_code(organization_code, "Organization code"))
        code = _clean_code(branch_code, "Branch code")
        branch_name = _clean_name(name, "Branch name")
        legal_entity_id: str | None = None
        normalized_entity_code = ""
        if entity_code.strip():
            normalized_entity_code = _clean_code(entity_code, "Entity code")
            legal_entity_id = str(self._legal_entity(str(organization["id"]), normalized_entity_code)["id"])
        branch_id = platform_id("BR", str(organization["id"]), code)
        now = utc_now_text()
        try:
            self.connection.execute(
                """
                INSERT INTO branches (
                    id, organization_id, legal_entity_id, branch_code, name, active, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(organization_id, branch_code) DO UPDATE SET
                    legal_entity_id = excluded.legal_entity_id,
                    name = excluded.name,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (branch_id, organization["id"], legal_entity_id, code, branch_name, int(active), now, now),
            )
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save local branch reference.") from exc
        record = self._branch(str(organization["id"]), code)
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="branch",
            object_id=str(record["id"]),
            action="branch_upserted",
            metadata={
                "branch_code": code,
                "organization_code": organization["organization_code"],
                "entity_code": normalized_entity_code,
            },
        )
        return record

    def list_branches(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        """List branches with bounded organization and entity references."""

        require_permission(self.connection, actor_label=actor_label, permission=MASTER_DATA_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        query = """
            SELECT branches.*, organizations.organization_code, legal_entities.entity_code
            FROM branches
            JOIN organizations ON organizations.id = branches.organization_id
            LEFT JOIN legal_entities ON legal_entities.id = branches.legal_entity_id
            WHERE organizations.workspace_id = ?
        """
        parameters: list[object] = [workspace_id]
        if organization_code:
            query += " AND organizations.organization_code = ?"
            parameters.append(_clean_code(organization_code, "Organization code"))
        query += " ORDER BY organizations.organization_code, branches.branch_code LIMIT ? OFFSET ?"
        parameters.extend((page_limit, page_offset))
        try:
            return [_public_record(row) for row in self.connection.execute(query, parameters).fetchall()]
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local branch references.") from exc

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
    ) -> dict[str, Any]:
        """Create or update a non-overlapping local fiscal-period reference."""

        require_permission(self.connection, actor_label=actor_label, permission=MASTER_DATA_MANAGE_PERMISSION)
        workspace_id = ensure_workspace(self.connection, _workspace_name(workspace))
        period_name = _clean_name(name, "Period name")
        start = _iso_date(start_date, "Period start date")
        end = _iso_date(end_date, "Period end date")
        if end < start:
            raise PlatformError("Period end date must be on or after the start date.")
        year = fiscal_year if fiscal_year is not None else start.year
        number = period_number if period_number is not None else start.month
        if not 1900 <= year <= 9999:
            raise PlatformError("Fiscal year must be between 1900 and 9999.")
        if not 1 <= number <= 999:
            raise PlatformError("Period number must be between 1 and 999.")
        now = utc_now_text()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.connection.execute(
                "SELECT * FROM periods WHERE workspace_id = ? AND name = ?",
                (workspace_id, period_name),
            ).fetchone()
            period_id = str(existing["id"]) if existing is not None else platform_id("PER", workspace_id, period_name)
            overlap = self.connection.execute(
                """
                SELECT id FROM periods
                WHERE workspace_id = ? AND id <> ? AND start_date <= ? AND end_date >= ?
                LIMIT 1
                """,
                (workspace_id, period_id, end.isoformat(), start.isoformat()),
            ).fetchone()
            if overlap is not None:
                raise PlatformError("Fiscal periods in the same workspace must not overlap.")
            self.connection.execute(
                """
                INSERT INTO periods (
                    id, workspace_id, name, start_date, end_date, status, created_at,
                    fiscal_year, period_number, status_reason, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'Open', ?, ?, ?, '', ?)
                ON CONFLICT(workspace_id, name) DO UPDATE SET
                    start_date = excluded.start_date,
                    end_date = excluded.end_date,
                    fiscal_year = excluded.fiscal_year,
                    period_number = excluded.period_number,
                    updated_at = excluded.updated_at
                """,
                (period_id, workspace_id, period_name, start.isoformat(), end.isoformat(), now, year, number, now),
            )
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to save local fiscal-period reference.") from exc
        record = self._period(period_id)
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="fiscal_period",
            object_id=period_id,
            action="fiscal_period_upserted",
            metadata={"name": period_name, "fiscal_year": year, "period_number": number},
        )
        return record

    def set_period_status(
        self,
        period_id: str,
        *,
        status: str,
        reason: str = "",
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        """Apply a controlled metadata transition; this does not post or lock ERP transactions."""

        require_permission(self.connection, actor_label=actor_label, permission=MASTER_DATA_MANAGE_PERMISSION)
        if (
            not period_id
            or len(period_id) > 160
            or any(ord(character) < 32 or ord(character) == 127 for character in period_id)
        ):
            raise PlatformError("Fiscal-period identifier is invalid.")
        record = self._period(period_id)
        target = " ".join(status.strip().title().split())
        if target not in PERIOD_STATUSES:
            raise PlatformError(f"Period status must be one of: {', '.join(PERIOD_STATUSES)}.")
        current = str(record["status"])
        if target == current:
            return record
        if target not in _PERIOD_TRANSITIONS.get(current, set()):
            raise PlatformError("Invalid fiscal-period status transition.")
        clean_reason = _clean_reason(reason)
        if target == "Open" and not clean_reason:
            raise PlatformError("Reopening a fiscal period requires a reason.")
        now = utc_now_text()
        try:
            cursor = self.connection.execute(
                "UPDATE periods SET status = ?, status_reason = ?, updated_at = ? WHERE id = ? AND status = ?",
                (target, clean_reason, now, period_id, current),
            )
            if cursor.rowcount != 1:
                raise PlatformError("Fiscal-period status changed concurrently; reload and retry.")
        except PlatformError:
            self.connection.rollback()
            raise
        except sqlite3.DatabaseError as exc:
            self.connection.rollback()
            raise PlatformError("Unable to update local fiscal-period status.") from exc
        commit_audited(
            self.connection,
            actor_label=actor_label,
            object_type="fiscal_period",
            object_id=period_id,
            action="fiscal_period_status_changed",
            metadata={"from_status": current, "to_status": target, "reason": clean_reason},
        )
        return self._period(period_id)

    def list_periods(
        self,
        *,
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        """List fiscal-period metadata for one workspace."""

        require_permission(self.connection, actor_label=actor_label, permission=MASTER_DATA_READ_PERMISSION)
        page_limit, page_offset = _page(limit, offset)
        workspace_id = self._workspace_id(workspace)
        if workspace_id is None:
            return []
        try:
            rows = self.connection.execute(
                "SELECT * FROM periods WHERE workspace_id = ? ORDER BY start_date, period_number, id LIMIT ? OFFSET ?",
                (workspace_id, page_limit, page_offset),
            ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to list local fiscal-period references.") from exc

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> MasterDataSummary:
        """Return bounded counts for the selected local workspace."""

        require_permission(self.connection, actor_label=actor_label, permission=MASTER_DATA_READ_PERMISSION)
        workspace_name = _workspace_name(workspace)
        workspace_id = self._workspace_id(workspace_name)
        if workspace_id is None:
            return MasterDataSummary(workspace_name, 0, 0, 0, 0, self._active_currency_count())
        try:
            row = self.connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM organizations WHERE workspace_id = ?) AS organizations,
                    (SELECT COUNT(*) FROM legal_entities le JOIN organizations org ON org.id = le.organization_id
                     WHERE org.workspace_id = ?) AS legal_entities,
                    (SELECT COUNT(*) FROM branches br JOIN organizations org ON org.id = br.organization_id
                     WHERE org.workspace_id = ?) AS branches,
                    (SELECT COUNT(*) FROM periods WHERE workspace_id = ?) AS periods
                """,
                (workspace_id, workspace_id, workspace_id, workspace_id),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to summarize local master data.") from exc
        if row is None:
            raise PlatformError("Unable to summarize local master data.")
        return MasterDataSummary(
            workspace_name,
            int(row["organizations"]),
            int(row["legal_entities"]),
            int(row["branches"]),
            int(row["periods"]),
            self._active_currency_count(),
        )

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]:
        """Return a versioned, path-free JSON-safe snapshot for local inspection and handoff."""

        workspace_name = _workspace_name(workspace)
        summary = self.summary(workspace=workspace_name, actor_label=actor_label)
        total_currencies = self._currency_count(active_only=False)
        scoped_counts = (
            summary.organizations,
            summary.legal_entities,
            summary.branches,
            summary.periods,
            total_currencies,
        )
        if any(count > MAX_SNAPSHOT_RECORDS for count in scoped_counts):
            raise PlatformError(f"Master-data snapshot is limited to {MAX_SNAPSHOT_RECORDS} records per collection.")
        return {
            "schema_version": 1,
            "generated_at": utc_now_text(),
            "source": {
                "kind": "local-sqlite-master-data",
                "local_first": True,
                "external_calls": False,
            },
            "workspace": workspace_name,
            "summary": summary.to_dict(),
            "currencies": self.list_currencies(limit=MAX_SNAPSHOT_RECORDS, actor_label=actor_label),
            "organizations": self.list_organizations(
                workspace=workspace_name, limit=MAX_SNAPSHOT_RECORDS, actor_label=actor_label
            ),
            "legal_entities": self.list_legal_entities(
                workspace=workspace_name, limit=MAX_SNAPSHOT_RECORDS, actor_label=actor_label
            ),
            "branches": self.list_branches(
                workspace=workspace_name, limit=MAX_SNAPSHOT_RECORDS, actor_label=actor_label
            ),
            "periods": self.list_periods(workspace=workspace_name, limit=MAX_SNAPSHOT_RECORDS, actor_label=actor_label),
        }

    def _workspace_id(self, workspace: str) -> str | None:
        name = _workspace_name(workspace)
        workspace_id = platform_id("WS", name)
        try:
            row = self.connection.execute("SELECT id FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read local workspace reference.") from exc
        return str(row["id"]) if row is not None else None

    def _organization(self, workspace_id: str, organization_code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                "SELECT * FROM organizations WHERE workspace_id = ? AND organization_code = ?",
                (workspace_id, organization_code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read local organization reference.") from exc
        if row is None:
            raise PlatformError("Organization reference was not found in the selected workspace.")
        return _public_record(row)

    def _currency(self, code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute("SELECT * FROM currencies WHERE code = ?", (code,)).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read local currency reference.") from exc
        if row is None:
            raise PlatformError("Currency reference was not found. Register it before assigning it to an entity.")
        return _public_record(row)

    def _legal_entity(self, organization_id: str, entity_code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                "SELECT * FROM legal_entities WHERE organization_id = ? AND entity_code = ?",
                (organization_id, entity_code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read local legal-entity reference.") from exc
        if row is None:
            raise PlatformError("Legal-entity reference was not found in the selected organization.")
        return _public_record(row)

    def _branch(self, organization_id: str, branch_code: str) -> dict[str, Any]:
        try:
            row = self.connection.execute(
                """
                SELECT branches.*, legal_entities.entity_code
                FROM branches
                LEFT JOIN legal_entities ON legal_entities.id = branches.legal_entity_id
                WHERE branches.organization_id = ? AND branches.branch_code = ?
                """,
                (organization_id, branch_code),
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read local branch reference.") from exc
        if row is None:
            raise PlatformError("Branch reference was not found in the selected organization.")
        return _public_record(row)

    def _period(self, period_id: str) -> dict[str, Any]:
        try:
            row = self.connection.execute("SELECT * FROM periods WHERE id = ?", (period_id,)).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to read local fiscal-period reference.") from exc
        if row is None:
            raise PlatformError("Fiscal-period reference was not found.")
        return dict(row)

    def _active_currency_count(self) -> int:
        return self._currency_count(active_only=True)

    def _currency_count(self, *, active_only: bool) -> int:
        try:
            query = "SELECT COUNT(*) AS count FROM currencies"
            if active_only:
                query += " WHERE active = 1"
            row = self.connection.execute(query).fetchone()
        except sqlite3.DatabaseError as exc:
            raise PlatformError("Unable to count local currency references.") from exc
        return int(row["count"]) if row is not None else 0
