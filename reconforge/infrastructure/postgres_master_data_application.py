"""Complete tenant/workspace PostgreSQL adapter for the Master Data application port."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import date
from typing import Any, TypeVar

from reconforge.application.master_data import DEFAULT_LIST_LIMIT, MasterDataSummary
from reconforge.domain.models import utc_now_text
from reconforge.infrastructure.postgres import set_local_tenant_scope, validate_tenant_id
from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
from reconforge.infrastructure.postgres_master_data import (
    PostgresMasterDataError,
    PostgresMasterDataRepository,
    PostgresMasterDataValidationError,
)
from reconforge.io.persisted import encode_postgres_outbox_payload
from reconforge.platform.common import PlatformError
from reconforge.utils.currency_registry_governance import reconcile_currency_registry
from reconforge.utils.money import CurrencyRegistry, CurrencyRegistryContext

MAX_SNAPSHOT_RECORDS = 100_000
_T = TypeVar("_T")
_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,63}$")


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}_{digest}"


def _page(limit: int, offset: int) -> tuple[int, int]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_SNAPSHOT_RECORDS:
        raise PlatformError(f"List limit must be between 1 and {MAX_SNAPSHOT_RECORDS}.")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 10_000_000:
        raise PlatformError("List offset must be between 0 and 10000000.")
    return limit, offset


def _code(value: object, label: str) -> str:
    code = str(value or "").strip().upper()
    if not _CODE_PATTERN.fullmatch(code):
        raise PlatformError(f"{label} must use 1-64 uppercase letters, numbers, hyphens, or underscores.")
    return code


def _name(value: object, label: str) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text or len(text) > 255 or any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise PlatformError(f"{label} is invalid.")
    return text


def _iso_date(value: object, label: str) -> date:
    raw = str(value or "").strip()
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise PlatformError(f"{label} must use YYYY-MM-DD format.") from exc
    if parsed.isoformat() != raw:
        raise PlatformError(f"{label} must use YYYY-MM-DD format.")
    return parsed


class PostgresMasterDataApplicationRepository:
    """Adapt the complete application contract without duplicating master records."""

    def __init__(self, connection: Any, tenant_id: str) -> None:
        self.connection = connection
        self.tenant_id = validate_tenant_id(tenant_id)
        self._base = PostgresMasterDataRepository(connection)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        try:
            with self.connection.transaction():
                set_local_tenant_scope(self.connection, self.tenant_id)
                yield
        except PlatformError:
            raise
        except (PostgresMasterDataValidationError, PostgresMasterDataError) as exc:
            raise PlatformError(str(exc)) from exc
        except Exception as exc:
            raise PlatformError("PostgreSQL master-data operation failed.") from exc

    def _workspace_id(self, workspace: str, *, required: bool = True) -> str | None:
        name = " ".join(str(workspace).strip().split())
        if not name or len(name) > 160:
            raise PlatformError("Workspace name is invalid.")
        row = self.connection.execute(
            "SELECT id FROM reconforge.domain_workspaces WHERE tenant_id=%s AND name=%s",
            (self.tenant_id, name),
        ).fetchone()
        if row is None:
            if required:
                raise PlatformError("Workspace reference was not found.")
            return None
        return str(row["id"] if isinstance(row, Mapping) else row[0])

    def _run(self, operation: Callable[[], _T]) -> _T:
        try:
            return operation()
        except (PostgresMasterDataValidationError, PostgresMasterDataError) as exc:
            raise PlatformError(str(exc)) from exc

    def _event(
        self,
        *,
        actor_label: str,
        object_type: str,
        object_id: str,
        action: str,
        metadata: dict[str, Any],
        event_key: str | None = None,
    ) -> None:
        payload = encode_postgres_outbox_payload(metadata).text
        self.connection.execute(
            """INSERT INTO reconforge.outbox_events
               (tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
               VALUES (%s,%s,%s,%s,%s,CAST(%s AS jsonb)) ON CONFLICT (tenant_id,event_id) DO NOTHING""",
            (
                self.tenant_id,
                _stable_id("event", self.tenant_id, action, object_id, event_key or ""),
                action,
                object_type,
                object_id,
                payload,
            ),
        )
        PostgresAuditEventRepository(self.connection, self.tenant_id).append(
            actor_label=actor_label,
            object_type=object_type,
            object_id=object_id,
            action=action,
            metadata=metadata,
        )

    def _organization(self, workspace_id: str, organization_code: str) -> dict[str, Any]:
        row = self.connection.execute(
            """SELECT organizations.tenant_id,organizations.id,organizations.organization_code,
                      organizations.name,organizations.base_currency,organizations.active,
                      organizations.created_at,organizations.updated_at
               FROM reconforge.master_data_workspace_organizations links
               JOIN reconforge.organizations ON organizations.tenant_id=links.tenant_id
                AND organizations.id=links.organization_id
               WHERE links.tenant_id=%s AND links.workspace_id=%s AND organizations.organization_code=%s""",
            (self.tenant_id, workspace_id, str(organization_code).strip().upper()),
        ).fetchone()
        if row is None:
            raise PlatformError("Organization reference was not found in the selected workspace.")
        columns = (
            "tenant_id",
            "id",
            "organization_code",
            "name",
            "base_currency",
            "active",
            "created_at",
            "updated_at",
        )
        return dict(row) if isinstance(row, Mapping) else dict(zip(columns, row, strict=True))

    @staticmethod
    def _actor(actor_label: str) -> str:
        actor = " ".join(str(actor_label or "local-cli").strip().split())
        if not actor or len(actor) > 160:
            raise PlatformError("Actor label is invalid.")
        return actor

    def upsert_currency(
        self, *, code: str, name: str, minor_units: int = 2, active: bool = True, actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        with self._transaction():
            return self._run(
                lambda: self._base.upsert_currency(
                    tenant_id=self.tenant_id,
                    code=code,
                    name=name,
                    minor_units=minor_units,
                    active=active,
                    actor_id=self._actor(actor_label),
                )
            )

    def list_currencies(
        self,
        *,
        active_only: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        del actor_label
        page_limit, page_offset = _page(limit, offset)
        with self._transaction():
            return self._run(lambda: self._base.list_currencies(tenant_id=self.tenant_id, active_only=active_only))[
                page_offset : page_offset + page_limit
            ]

    def upsert_organization(
        self,
        *,
        organization_code: str,
        name: str,
        workspace: str = "default",
        active: bool = True,
        actor_label: str = "local-cli",
    ) -> dict[str, Any]:
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            if workspace_id is None:
                raise PlatformError("Workspace reference was not found.")
            existing = self.connection.execute(
                """SELECT organization_id,workspace_id FROM reconforge.master_data_workspace_organizations links
                   JOIN reconforge.organizations organizations ON organizations.tenant_id=links.tenant_id
                    AND organizations.id=links.organization_id WHERE links.tenant_id=%s
                    AND links.workspace_id=%s AND organizations.organization_code=%s""",
                (self.tenant_id, workspace_id, str(organization_code).strip().upper()),
            ).fetchone()
            organization_id = (
                str(existing["organization_id"] if isinstance(existing, Mapping) else existing[0])
                if existing
                else _stable_id("org", self.tenant_id, workspace_id, str(organization_code).upper())
            )
            code = _code(organization_code, "Organization code")
            row = self.connection.execute(
                """INSERT INTO reconforge.organizations
                   (tenant_id,id,organization_code,name,active,application_workspace_id)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (tenant_id,application_workspace_id,organization_code)
                    WHERE application_workspace_id IS NOT NULL AND organization_code IS NOT NULL
                   DO UPDATE SET name=excluded.name,active=excluded.active,updated_at=now()
                   RETURNING tenant_id,id,organization_code,name,base_currency,active,created_at,updated_at""",
                (self.tenant_id, organization_id, code, _name(name, "Organization name"), active, workspace_id),
            ).fetchone()
            if row is None:
                raise PlatformError("Unable to persist PostgreSQL organization reference.")
            columns = (
                "tenant_id",
                "id",
                "organization_code",
                "name",
                "base_currency",
                "active",
                "created_at",
                "updated_at",
            )
            record = dict(row) if isinstance(row, Mapping) else dict(zip(columns, row, strict=True))
            self.connection.execute(
                "INSERT INTO reconforge.master_data_workspace_organizations(tenant_id,workspace_id,organization_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (self.tenant_id, workspace_id, record["id"]),
            )
            self._event(
                actor_label=actor_label,
                object_type="organization",
                object_id=str(record["id"]),
                action="organization_upserted",
                metadata={"organization_code": code, "active": active, "workspace_id": workspace_id},
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
        del actor_label
        page_limit, page_offset = _page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace, required=False)
            if workspace_id is None:
                return []
            rows = self.connection.execute(
                """SELECT organizations.tenant_id,organizations.id,organizations.organization_code,
                          organizations.name,organizations.base_currency,organizations.active,
                          organizations.created_at,organizations.updated_at
                   FROM reconforge.master_data_workspace_organizations links JOIN reconforge.organizations
                    ON organizations.tenant_id=links.tenant_id AND organizations.id=links.organization_id
                   WHERE links.tenant_id=%s AND links.workspace_id=%s
                   ORDER BY organizations.organization_code LIMIT %s OFFSET %s""",
                (self.tenant_id, workspace_id, page_limit, page_offset),
            ).fetchall()
            columns = (
                "tenant_id",
                "id",
                "organization_code",
                "name",
                "base_currency",
                "active",
                "created_at",
                "updated_at",
            )
            return [dict(row) if isinstance(row, Mapping) else dict(zip(columns, row, strict=True)) for row in rows]

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
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            if workspace_id is None:
                raise PlatformError("Workspace reference was not found.")
            organization = self._organization(workspace_id, organization_code)
            entity_id = _stable_id("entity", self.tenant_id, str(organization["id"]), str(entity_code).upper())
            return self._run(
                lambda: self._base.upsert_legal_entity(
                    tenant_id=self.tenant_id,
                    organization_id=str(organization["id"]),
                    entity_id=entity_id,
                    entity_code=entity_code,
                    name=name,
                    currency_code=currency_code,
                    active=active,
                    actor_id=self._actor(actor_label),
                )
            )

    def list_legal_entities(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        del actor_label
        page_limit, page_offset = _page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace, required=False)
            if workspace_id is None:
                return []
            query = """SELECT entities.tenant_id,entities.id,entities.organization_id,entities.entity_code,
                       entities.name,entities.currency_code,entities.active,entities.created_at,entities.updated_at,
                       organizations.organization_code FROM reconforge.legal_entities entities
                       JOIN reconforge.master_data_workspace_organizations links ON links.tenant_id=entities.tenant_id
                        AND links.organization_id=entities.organization_id
                       JOIN reconforge.organizations organizations ON organizations.tenant_id=entities.tenant_id
                        AND organizations.id=entities.organization_id
                       WHERE entities.tenant_id=%s AND links.workspace_id=%s"""
            parameters: list[object] = [self.tenant_id, workspace_id]
            if organization_code:
                query += " AND organizations.organization_code=%s"
                parameters.append(str(organization_code).strip().upper())
            query += " ORDER BY organizations.organization_code,entities.entity_code LIMIT %s OFFSET %s"
            parameters.extend((page_limit, page_offset))
            columns = (
                "tenant_id",
                "id",
                "organization_id",
                "entity_code",
                "name",
                "currency_code",
                "active",
                "created_at",
                "updated_at",
                "organization_code",
            )
            rows = self.connection.execute(query, tuple(parameters)).fetchall()
            return [dict(row) if isinstance(row, Mapping) else dict(zip(columns, row, strict=True)) for row in rows]

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
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            if workspace_id is None:
                raise PlatformError("Workspace reference was not found.")
            organization = self._organization(workspace_id, organization_code)
            legal_entity_id: str | None = None
            if entity_code.strip():
                entity = self._run(
                    lambda: self._base.legal_entity_by_code(
                        tenant_id=self.tenant_id, organization_id=str(organization["id"]), entity_code=entity_code
                    )
                )
                legal_entity_id = str(entity["id"])
            branch_id = _stable_id("branch", self.tenant_id, str(organization["id"]), str(branch_code).upper())
            return self._run(
                lambda: self._base.upsert_branch(
                    tenant_id=self.tenant_id,
                    organization_id=str(organization["id"]),
                    branch_id=branch_id,
                    branch_code=branch_code,
                    name=name,
                    legal_entity_id=legal_entity_id,
                    active=active,
                    actor_id=self._actor(actor_label),
                )
            )

    def list_branches(
        self,
        *,
        workspace: str = "default",
        organization_code: str = "",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        del actor_label
        page_limit, page_offset = _page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace, required=False)
            if workspace_id is None:
                return []
            query = """SELECT branches.tenant_id,branches.id,branches.organization_id,branches.legal_entity_id,
                       branches.branch_code,branches.name,branches.active,branches.created_at,branches.updated_at,
                       organizations.organization_code,COALESCE(entities.entity_code,'') FROM reconforge.branches branches
                       JOIN reconforge.master_data_workspace_organizations links ON links.tenant_id=branches.tenant_id
                        AND links.organization_id=branches.organization_id
                       JOIN reconforge.organizations organizations ON organizations.tenant_id=branches.tenant_id
                        AND organizations.id=branches.organization_id LEFT JOIN reconforge.legal_entities entities
                        ON entities.tenant_id=branches.tenant_id AND entities.id=branches.legal_entity_id
                       WHERE branches.tenant_id=%s AND links.workspace_id=%s"""
            parameters: list[object] = [self.tenant_id, workspace_id]
            if organization_code:
                query += " AND organizations.organization_code=%s"
                parameters.append(str(organization_code).strip().upper())
            query += " ORDER BY organizations.organization_code,branches.branch_code LIMIT %s OFFSET %s"
            parameters.extend((page_limit, page_offset))
            columns = (
                "tenant_id",
                "id",
                "organization_id",
                "legal_entity_id",
                "branch_code",
                "name",
                "active",
                "created_at",
                "updated_at",
                "organization_code",
                "entity_code",
            )
            rows = self.connection.execute(query, tuple(parameters)).fetchall()
            return [dict(row) if isinstance(row, Mapping) else dict(zip(columns, row, strict=True)) for row in rows]

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
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            if workspace_id is None:
                raise PlatformError("Workspace reference was not found.")
            existing = self.connection.execute(
                """SELECT periods.id,links.workspace_id FROM reconforge.fiscal_periods periods
                   JOIN reconforge.master_data_workspace_periods links ON links.tenant_id=periods.tenant_id
                    AND links.period_id=periods.id WHERE periods.tenant_id=%s AND links.workspace_id=%s
                    AND periods.name=%s""",
                (self.tenant_id, workspace_id, str(name).strip()),
            ).fetchone()
            period_id = (
                str(existing["id"] if isinstance(existing, Mapping) else existing[0])
                if existing
                else _stable_id("period", self.tenant_id, workspace_id, str(name))
            )
            period_name = _name(name, "Period name")
            start, end = _iso_date(start_date, "Period start date"), _iso_date(end_date, "Period end date")
            if end < start:
                raise PlatformError("Period end date must be on or after the start date.")
            year = fiscal_year if fiscal_year is not None else start.year
            number = period_number if period_number is not None else start.month
            if not isinstance(year, int) or isinstance(year, bool) or not 1900 <= year <= 9999:
                raise PlatformError("Fiscal year must be between 1900 and 9999.")
            if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= 999:
                raise PlatformError("Period number must be between 1 and 999.")
            self.connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{self.tenant_id}:{workspace_id}",))
            if (
                self.connection.execute(
                    """SELECT 1 FROM reconforge.fiscal_periods WHERE tenant_id=%s AND id<>%s
                   AND application_workspace_id=%s AND start_date<=%s AND end_date>=%s LIMIT 1""",
                    (self.tenant_id, period_id, workspace_id, end.isoformat(), start.isoformat()),
                ).fetchone()
                is not None
            ):
                raise PlatformError("Fiscal periods in the same workspace must not overlap.")
            row = self.connection.execute(
                """INSERT INTO reconforge.fiscal_periods
                   (tenant_id,id,name,start_date,end_date,status,fiscal_year,period_number,status_reason,application_workspace_id)
                   VALUES (%s,%s,%s,%s,%s,'Open',%s,%s,'',%s)
                   ON CONFLICT (tenant_id,application_workspace_id,name) WHERE application_workspace_id IS NOT NULL
                   DO UPDATE SET start_date=excluded.start_date,end_date=excluded.end_date,
                    fiscal_year=excluded.fiscal_year,period_number=excluded.period_number,updated_at=now()
                   RETURNING tenant_id,id,name,start_date,end_date,status,created_at,fiscal_year,period_number,status_reason,updated_at""",
                (
                    self.tenant_id,
                    period_id,
                    period_name,
                    start.isoformat(),
                    end.isoformat(),
                    year,
                    number,
                    workspace_id,
                ),
            ).fetchone()
            if row is None:
                raise PlatformError("Unable to persist PostgreSQL fiscal-period reference.")
            columns = (
                "tenant_id",
                "id",
                "name",
                "start_date",
                "end_date",
                "status",
                "created_at",
                "fiscal_year",
                "period_number",
                "status_reason",
                "updated_at",
            )
            record = dict(row) if isinstance(row, Mapping) else dict(zip(columns, row, strict=True))
            self.connection.execute(
                "INSERT INTO reconforge.master_data_workspace_periods(tenant_id,workspace_id,period_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (self.tenant_id, workspace_id, record["id"]),
            )
            self._event(
                actor_label=actor_label,
                object_type="fiscal_period",
                object_id=str(record["id"]),
                action="fiscal_period_upserted",
                metadata={
                    "name": period_name,
                    "fiscal_year": year,
                    "period_number": number,
                    "workspace_id": workspace_id,
                },
            )
            return record

    def set_period_status(
        self, period_id: str, *, status: str, reason: str = "", actor_label: str = "local-cli"
    ) -> dict[str, Any]:
        with self._transaction():
            if (
                self.connection.execute(
                    "SELECT 1 FROM reconforge.master_data_workspace_periods WHERE tenant_id=%s AND period_id=%s",
                    (self.tenant_id, str(period_id)),
                ).fetchone()
                is None
            ):
                raise PlatformError("Fiscal-period reference was not found.")
            return self._run(
                lambda: self._base.set_period_status(
                    tenant_id=self.tenant_id,
                    period_id=period_id,
                    status=status,
                    reason=reason,
                    actor_id=self._actor(actor_label),
                )
            )

    def list_periods(
        self,
        *,
        workspace: str = "default",
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
        actor_label: str = "local-cli",
    ) -> list[dict[str, Any]]:
        del actor_label
        page_limit, page_offset = _page(limit, offset)
        with self._transaction():
            workspace_id = self._workspace_id(workspace, required=False)
            if workspace_id is None:
                return []
            rows = self.connection.execute(
                """SELECT periods.tenant_id,periods.id,periods.name,periods.start_date,periods.end_date,
                          periods.status,periods.created_at,periods.fiscal_year,periods.period_number,
                          periods.status_reason,periods.updated_at FROM reconforge.master_data_workspace_periods links
                   JOIN reconforge.fiscal_periods periods ON periods.tenant_id=links.tenant_id AND periods.id=links.period_id
                   WHERE links.tenant_id=%s AND links.workspace_id=%s
                   ORDER BY periods.start_date,periods.period_number,periods.id LIMIT %s OFFSET %s""",
                (self.tenant_id, workspace_id, page_limit, page_offset),
            ).fetchall()
            columns = (
                "tenant_id",
                "id",
                "name",
                "start_date",
                "end_date",
                "status",
                "created_at",
                "fiscal_year",
                "period_number",
                "status_reason",
                "updated_at",
            )
            return [dict(row) if isinstance(row, Mapping) else dict(zip(columns, row, strict=True)) for row in rows]

    def summary(self, *, workspace: str = "default", actor_label: str = "local-cli") -> MasterDataSummary:
        del actor_label
        workspace_name = " ".join(str(workspace).strip().split())
        with self._transaction():
            workspace_id = self._workspace_id(workspace_name, required=False)
            if workspace_id is None:
                active = len(self._run(lambda: self._base.list_currencies(tenant_id=self.tenant_id, active_only=True)))
                return MasterDataSummary(workspace_name, 0, 0, 0, 0, active)
            row = self.connection.execute(
                """SELECT
                   (SELECT COUNT(*) FROM reconforge.master_data_workspace_organizations WHERE tenant_id=%s AND workspace_id=%s),
                   (SELECT COUNT(*) FROM reconforge.legal_entities entities JOIN reconforge.master_data_workspace_organizations links ON links.tenant_id=entities.tenant_id AND links.organization_id=entities.organization_id WHERE links.tenant_id=%s AND links.workspace_id=%s),
                   (SELECT COUNT(*) FROM reconforge.branches branches JOIN reconforge.master_data_workspace_organizations links ON links.tenant_id=branches.tenant_id AND links.organization_id=branches.organization_id WHERE links.tenant_id=%s AND links.workspace_id=%s),
                   (SELECT COUNT(*) FROM reconforge.master_data_workspace_periods WHERE tenant_id=%s AND workspace_id=%s),
                   (SELECT COUNT(*) FROM reconforge.currencies WHERE tenant_id=%s AND active=TRUE)""",
                (self.tenant_id, workspace_id) * 4 + (self.tenant_id,),
            ).fetchone()
            if row is None:
                raise PlatformError("Unable to summarize PostgreSQL master data.")
            values = list(row.values()) if isinstance(row, Mapping) else list(row)
            return MasterDataSummary(workspace_name, *(int(value) for value in values))

    def snapshot(self, *, workspace: str = "default", actor_label: str = "local-cli") -> dict[str, object]:
        workspace_name = " ".join(str(workspace).strip().split())
        summary = self.summary(workspace=workspace_name, actor_label=actor_label)
        with self._transaction():
            row = self.connection.execute(
                "SELECT COUNT(*) FROM reconforge.currencies WHERE tenant_id=%s", (self.tenant_id,)
            ).fetchone()
            total_currencies = (
                0 if row is None else int(next(iter(row.values())) if isinstance(row, Mapping) else row[0])
            )
        if any(
            count > MAX_SNAPSHOT_RECORDS
            for count in (
                summary.organizations,
                summary.legal_entities,
                summary.branches,
                summary.periods,
                total_currencies,
            )
        ):
            raise PlatformError(f"Master-data snapshot is limited to {MAX_SNAPSHOT_RECORDS} records per collection.")
        return {
            "schema_version": 1,
            "generated_at": utc_now_text(),
            "source": {"kind": "postgres-master-data", "local_first": False, "external_calls": False},
            "workspace": workspace_name,
            "summary": summary.to_dict(),
            "currency_registry": self.currency_registry_reconciliation(
                workspace=workspace_name,
                actor_label=actor_label,
            ),
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

    def currency_registry_reconciliation(
        self,
        *,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, object]:
        """Reconcile this tenant's persisted currencies with the installed policy registry."""

        del actor_label
        workspace_name = " ".join(str(workspace).strip().split())
        if not workspace_name or len(workspace_name) > 160:
            raise PlatformError("Workspace name is invalid.")
        records = self.list_currencies(limit=MAX_SNAPSHOT_RECORDS, actor_label="local-cli")
        installed_context = CurrencyRegistry.context()
        operation_context = self.currency_registry_context(workspace=workspace_name, actor_label="local-cli")
        return reconcile_currency_registry(
            records,
            scope=f"tenant:{self.tenant_id}:workspace:{workspace_name}",
            binding=self.currency_registry_binding(workspace=workspace_name, actor_label="local-cli"),
            registry_context=operation_context or installed_context,
            installed_registry_context=installed_context,
        ).to_dict()

    def currency_registry_binding(
        self,
        *,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, object] | None:
        """Read the tenant/workspace registry snapshot binding."""

        del actor_label
        workspace_id = self._workspace_id(workspace, required=False)
        if workspace_id is None:
            return None
        with self._transaction():
            row = self.connection.execute(
                """SELECT registry_version, registry_digest, bound_at, bound_by
                   FROM reconforge.currency_registry_bindings
                   WHERE tenant_id=%s AND workspace_id=%s""",
                (self.tenant_id, workspace_id),
            ).fetchone()
            if row is None:
                return None
            columns = ("registry_version", "registry_digest", "bound_at", "bound_by")
            return dict(row) if isinstance(row, Mapping) else dict(zip(columns, row, strict=True))

    def currency_registry_context(
        self,
        *,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> CurrencyRegistryContext | None:
        """Load the immutable registry snapshot bound to one workspace."""

        del actor_label
        with self._transaction():
            return self._base.currency_registry_context(tenant_id=self.tenant_id, workspace=workspace)

    def bind_currency_registry(
        self,
        *,
        workspace: str = "default",
        actor_label: str = "local-cli",
    ) -> dict[str, object]:
        """Bind one tenant/workspace to the currently installed registry snapshot."""

        actor = self._actor(actor_label)
        manifest = CurrencyRegistry.manifest()
        snapshot_json = json.dumps(
            CurrencyRegistry.snapshot(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        with self._transaction():
            workspace_id = self._workspace_id(workspace)
            if workspace_id is None:
                raise PlatformError("Workspace reference was not found.")
            self.connection.execute(
                """INSERT INTO reconforge.currency_registry_snapshots
                   (tenant_id,registry_digest,registry_version,snapshot_json,captured_at,captured_by)
                   VALUES (%s,%s,%s,%s::jsonb,now(),%s)
                   ON CONFLICT (tenant_id,registry_digest) DO NOTHING""",
                (self.tenant_id, manifest.digest, manifest.registry_version, snapshot_json, actor),
            )
            row = self.connection.execute(
                """INSERT INTO reconforge.currency_registry_bindings
                   (tenant_id, workspace_id, registry_version, registry_digest, bound_at, bound_by)
                   VALUES (%s,%s,%s,%s,now(),%s)
                   ON CONFLICT (tenant_id, workspace_id) DO UPDATE SET
                     registry_version=EXCLUDED.registry_version,
                     registry_digest=EXCLUDED.registry_digest,
                     bound_at=EXCLUDED.bound_at,
                     bound_by=EXCLUDED.bound_by
                   RETURNING registry_version,registry_digest,bound_at,bound_by""",
                (self.tenant_id, workspace_id, manifest.registry_version, manifest.digest, actor),
            ).fetchone()
            self._event(
                actor_label=actor,
                object_type="currency_registry_binding",
                object_id=workspace_id,
                action="currency_registry_bound",
                event_key=manifest.digest,
                metadata={
                    "workspace_id": workspace_id,
                    "registry_version": manifest.registry_version,
                    "registry_digest": manifest.digest,
                },
            )
            if row is None:
                raise PlatformError("Currency registry binding was not persisted.")
            columns = ("registry_version", "registry_digest", "bound_at", "bound_by")
            return dict(row) if isinstance(row, Mapping) else dict(zip(columns, row, strict=True))


POSTGRES_MASTER_DATA_APPLICATION_SCHEMA_SQL = """
ALTER TABLE reconforge.organizations ADD COLUMN IF NOT EXISTS application_workspace_id TEXT;
ALTER TABLE reconforge.fiscal_periods ADD COLUMN IF NOT EXISTS application_workspace_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_workspace_code
 ON reconforge.organizations(tenant_id,application_workspace_id,organization_code)
 WHERE application_workspace_id IS NOT NULL AND organization_code IS NOT NULL;
ALTER TABLE reconforge.fiscal_periods DROP CONSTRAINT IF EXISTS fiscal_periods_tenant_id_name_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_fiscal_periods_legacy_name
 ON reconforge.fiscal_periods(tenant_id,name) WHERE application_workspace_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_fiscal_periods_workspace_name
 ON reconforge.fiscal_periods(tenant_id,application_workspace_id,name) WHERE application_workspace_id IS NOT NULL;
DO $reconforge$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='organizations_application_workspace_fk') THEN
  ALTER TABLE reconforge.organizations ADD CONSTRAINT organizations_application_workspace_fk
   FOREIGN KEY (tenant_id,application_workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE RESTRICT;
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fiscal_periods_application_workspace_fk') THEN
  ALTER TABLE reconforge.fiscal_periods ADD CONSTRAINT fiscal_periods_application_workspace_fk
   FOREIGN KEY (tenant_id,application_workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE RESTRICT;
 END IF;
END $reconforge$;
CREATE TABLE IF NOT EXISTS reconforge.master_data_workspace_organizations (
 tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL, organization_id TEXT NOT NULL,
 PRIMARY KEY (tenant_id,workspace_id,organization_id), UNIQUE (tenant_id,organization_id),
 FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY (tenant_id,organization_id) REFERENCES reconforge.organizations(tenant_id,id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reconforge.master_data_workspace_periods (
 tenant_id TEXT NOT NULL, workspace_id TEXT NOT NULL, period_id TEXT NOT NULL,
 PRIMARY KEY (tenant_id,workspace_id,period_id), UNIQUE (tenant_id,period_id),
 FOREIGN KEY (tenant_id,workspace_id) REFERENCES reconforge.domain_workspaces(tenant_id,id) ON DELETE CASCADE,
 FOREIGN KEY (tenant_id,period_id) REFERENCES reconforge.fiscal_periods(tenant_id,id) ON DELETE CASCADE
);
ALTER TABLE reconforge.master_data_workspace_organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.master_data_workspace_organizations FORCE ROW LEVEL SECURITY;
ALTER TABLE reconforge.master_data_workspace_periods ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.master_data_workspace_periods FORCE ROW LEVEL SECURITY;
DO $reconforge$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename='master_data_workspace_organizations' AND policyname='tenant_scope') THEN
  CREATE POLICY tenant_scope ON reconforge.master_data_workspace_organizations USING (tenant_id=current_setting('app.tenant_id',true)) WITH CHECK (tenant_id=current_setting('app.tenant_id',true));
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='reconforge' AND tablename='master_data_workspace_periods' AND policyname='tenant_scope') THEN
  CREATE POLICY tenant_scope ON reconforge.master_data_workspace_periods USING (tenant_id=current_setting('app.tenant_id',true)) WITH CHECK (tenant_id=current_setting('app.tenant_id',true));
 END IF;
END $reconforge$;
"""


POSTGRES_CURRENCY_REGISTRY_BINDING_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.currency_registry_bindings (
 tenant_id TEXT NOT NULL,
 workspace_id TEXT NOT NULL,
 registry_version TEXT NOT NULL CHECK (length(registry_version) BETWEEN 1 AND 128),
 registry_digest TEXT NOT NULL CHECK (registry_digest ~ '^[0-9a-f]{64}$'),
 bound_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 bound_by TEXT NOT NULL CHECK (length(bound_by) BETWEEN 1 AND 160),
 PRIMARY KEY (tenant_id, workspace_id),
 FOREIGN KEY (tenant_id, workspace_id)
   REFERENCES reconforge.domain_workspaces(tenant_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_currency_registry_bindings_digest
 ON reconforge.currency_registry_bindings(tenant_id, registry_version, registry_digest);
ALTER TABLE reconforge.currency_registry_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.currency_registry_bindings FORCE ROW LEVEL SECURITY;
DO $reconforge$ BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM pg_policies
   WHERE schemaname='reconforge' AND tablename='currency_registry_bindings' AND policyname='tenant_scope'
 ) THEN
   CREATE POLICY tenant_scope ON reconforge.currency_registry_bindings
    USING (tenant_id=current_setting('app.tenant_id',true))
    WITH CHECK (tenant_id=current_setting('app.tenant_id',true));
 END IF;
END $reconforge$;
"""


POSTGRES_CURRENCY_REGISTRY_SNAPSHOT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reconforge.currency_registry_snapshots (
 tenant_id TEXT NOT NULL,
 registry_digest TEXT NOT NULL CHECK (registry_digest ~ '^[0-9a-f]{64}$'),
 registry_version TEXT NOT NULL CHECK (length(registry_version) BETWEEN 1 AND 128),
 snapshot_json JSONB NOT NULL CHECK (jsonb_typeof(snapshot_json) = 'object')
     CHECK (octet_length(snapshot_json::text) BETWEEN 2 AND 1000000),
 captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 captured_by TEXT NOT NULL CHECK (length(captured_by) BETWEEN 1 AND 160),
 PRIMARY KEY (tenant_id, registry_digest)
);
CREATE INDEX IF NOT EXISTS idx_currency_registry_snapshots_version
 ON reconforge.currency_registry_snapshots(tenant_id, registry_version, captured_at, registry_digest);
ALTER TABLE reconforge.currency_registry_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconforge.currency_registry_snapshots FORCE ROW LEVEL SECURITY;
DO $reconforge$ BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM pg_policies
   WHERE schemaname='reconforge' AND tablename='currency_registry_snapshots' AND policyname='tenant_scope'
 ) THEN
   CREATE POLICY tenant_scope ON reconforge.currency_registry_snapshots
    USING (tenant_id=current_setting('app.tenant_id',true))
    WITH CHECK (tenant_id=current_setting('app.tenant_id',true));
 END IF;
END $reconforge$;
"""


def install_postgres_master_data_application_schema(connection: Any) -> None:
    connection.execute(POSTGRES_MASTER_DATA_APPLICATION_SCHEMA_SQL)
    connection.execute(POSTGRES_CURRENCY_REGISTRY_SNAPSHOT_SCHEMA_SQL)
    connection.execute(POSTGRES_CURRENCY_REGISTRY_BINDING_SCHEMA_SQL)
