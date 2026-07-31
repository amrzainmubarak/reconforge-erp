"""Authenticated routes for governed local organization master data."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from reconforge.api.dependencies import get_local_db, require_any_permission, require_permission
from reconforge.api.errors import APIError
from reconforge.api.server_master_data import execute_postgres_master_data, server_master_data_enabled
from reconforge.auth.models import LocalUser
from reconforge.db import DatabaseError
from reconforge.infrastructure.postgres_master_data import (
    PostgresMasterDataRepository,
    PostgresMasterDataValidationError,
)
from reconforge.platform.common import PlatformError
from reconforge.platform.master_data import DEFAULT_LIST_LIMIT, MasterDataService
from reconforge.utils.time import utc_now_text

router = APIRouter(prefix="/master-data", tags=["master-data"])
MAX_API_LIST_LIMIT = 1_000

MasterDataRead = Annotated[
    LocalUser,
    Depends(require_any_permission({"master_data.read", "master_data.manage"})),
]
MasterDataManage = Annotated[LocalUser, Depends(require_permission("master_data.manage"))]
PageLimit = Annotated[int, Query(ge=1, le=MAX_API_LIST_LIMIT)]
PageOffset = Annotated[int, Query(ge=0, le=10_000_000)]


class CurrencyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=200)
    minor_units: int = Field(default=2, ge=0, le=6)
    active: bool = True


class OrganizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    base_currency: str = Field(default="", max_length=16)
    active: bool = True


class LegalEntityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_code: str = Field(min_length=1, max_length=64)
    entity_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    currency_code: str = Field(min_length=1, max_length=16)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    active: bool = True


class BranchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_code: str = Field(min_length=1, max_length=64)
    branch_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    entity_code: str = Field(default="", max_length=64)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    active: bool = True


class PeriodRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    start_date: str = Field(min_length=10, max_length=10)
    end_date: str = Field(min_length=10, max_length=10)
    workspace: str = Field(default="default", min_length=1, max_length=160)
    fiscal_year: int | None = Field(default=None, ge=1900, le=9999)
    period_number: int | None = Field(default=None, ge=1, le=999)


class PeriodStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(min_length=1, max_length=32)
    reason: str = Field(default="", max_length=500)


def _api_error(code: str, exc: Exception) -> APIError:
    return APIError(status_code=400, code=code, message=str(exc))


def _list_response(
    key: str,
    records: list[dict[str, object]],
    *,
    limit: int,
    offset: int,
) -> dict[str, object]:
    return {
        key: records,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(records),
        },
    }


def _local_connection(connection: sqlite3.Connection | None) -> sqlite3.Connection:
    if connection is None:
        raise APIError(
            status_code=500,
            code="local_database_not_configured",
            message="The local master-data database is not configured for this request.",
        )
    return connection


def _server_workspace(workspace: str) -> None:
    if workspace.strip().casefold() not in {"", "default"}:
        raise APIError(
            status_code=400,
            code="server_workspace_unsupported",
            message="The PostgreSQL server master-data boundary is tenant-scoped and does not support workspaces yet.",
        )


def _server_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("|".join(str(part).strip().casefold() for part in parts).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:48]}"


def _server_page(records: list[dict[str, object]], *, limit: int, offset: int) -> list[dict[str, object]]:
    return records[offset : offset + limit]


def _server_currency(record: dict[str, object]) -> dict[str, object]:
    return {**record, "source_backend": "postgresql-master-data"}


def _server_organization(record: dict[str, object]) -> dict[str, object]:
    return {**record, "workspace": None, "workspace_id": None, "source_backend": "postgresql-master-data"}


def _server_entity(record: dict[str, object]) -> dict[str, object]:
    return {
        **record,
        "currency": record.get("currency_code"),
        "workspace": None,
        "workspace_id": None,
        "source_backend": "postgresql-master-data",
    }


def _server_branch(record: dict[str, object]) -> dict[str, object]:
    return {
        **record,
        "entity_code": None,
        "workspace": None,
        "workspace_id": None,
        "source_backend": "postgresql-master-data",
    }


def _server_period(record: dict[str, object]) -> dict[str, object]:
    return {**record, "workspace": None, "workspace_id": None, "source_backend": "postgresql-master-data"}


@router.get("/summary")
def summary(
    request: Request,
    current_user: MasterDataRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
) -> dict[str, object]:
    """Return bounded master-data counts for one workspace."""

    if server_master_data_enabled(request):
        _server_workspace(workspace)
        server_result = execute_postgres_master_data(
            request, lambda repository, tenant: repository.summary(tenant_id=tenant)
        )
        return {
            "summary": {
                "workspace": None,
                "organizations": server_result["organizations"],
                "legal_entities": server_result["legal_entities"],
                "branches": server_result["branches"],
                "periods": server_result["periods"],
                "active_currencies": server_result["active_currencies"],
                "source": server_result["source"],
                "unsupported_collections": server_result["unsupported_collections"],
            }
        }
    try:
        local_result = MasterDataService(_local_connection(connection)).summary(
            workspace=workspace, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("master_data_summary_failed", exc) from exc
    return {"summary": local_result.to_dict()}


@router.get("/snapshot")
def snapshot(
    request: Request,
    current_user: MasterDataRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
) -> dict[str, object]:
    """Return the versioned, path-free organization master-data contract."""

    if server_master_data_enabled(request):
        _server_workspace(workspace)

        def operation(repository: PostgresMasterDataRepository, tenant: str) -> dict[str, object]:
            summary_record = repository.summary(tenant_id=tenant)
            return {
                "schema_version": 1,
                "generated_at": utc_now_text(),
                "source": summary_record["source"],
                "workspace": None,
                "summary": {
                    "workspace": None,
                    "organizations": summary_record["organizations"],
                    "legal_entities": summary_record["legal_entities"],
                    "branches": summary_record["branches"],
                    "periods": 0,
                    "active_currencies": summary_record["active_currencies"],
                    "source": summary_record["source"],
                    "unsupported_collections": summary_record["unsupported_collections"],
                },
                "currencies": [_server_currency(record) for record in repository.list_currencies(tenant_id=tenant)],
                "organizations": [
                    _server_organization(record) for record in repository.list_organizations(tenant_id=tenant)
                ],
                "legal_entities": [
                    _server_entity(record) for record in repository.list_legal_entities(tenant_id=tenant)
                ],
                "branches": [_server_branch(record) for record in repository.list_branches(tenant_id=tenant)],
                "periods": [_server_period(record) for record in repository.list_periods(tenant_id=tenant)],
                "unsupported_collections": [],
            }

        return execute_postgres_master_data(request, operation)
    try:
        return MasterDataService(_local_connection(connection)).snapshot(
            workspace=workspace, actor_label=current_user.username
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("master_data_snapshot_failed", exc) from exc


@router.get("/currencies")
def list_currencies(
    request: Request,
    current_user: MasterDataRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    active_only: bool = False,
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    """List governed currency references; no exchange-rate feed is implied."""

    if server_master_data_enabled(request):

        def operation(repository: PostgresMasterDataRepository, tenant: str) -> list[dict[str, object]]:
            records = repository.list_currencies(tenant_id=tenant, active_only=active_only)
            return [_server_currency(record) for record in records]

        records = execute_postgres_master_data(request, operation)
        return _list_response(
            "currencies", _server_page(records, limit=limit, offset=offset), limit=limit, offset=offset
        )
    try:
        records = MasterDataService(_local_connection(connection)).list_currencies(
            active_only=active_only,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("currencies_list_failed", exc) from exc
    return _list_response("currencies", records, limit=limit, offset=offset)


@router.post("/currencies")
def upsert_currency(
    request: Request,
    payload: CurrencyRequest,
    current_user: MasterDataManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Create or update one local currency reference."""

    if server_master_data_enabled(request):
        record = execute_postgres_master_data(
            request,
            lambda repository, tenant: repository.upsert_currency(
                tenant_id=tenant,
                code=payload.code,
                name=payload.name,
                minor_units=payload.minor_units,
                active=payload.active,
                actor_id=current_user.id,
                request_id=str(getattr(request.state, "request_id", "")),
                metadata={"source": "api"},
            ),
        )
        return {"currency": _server_currency(record)}
    try:
        record = MasterDataService(_local_connection(connection)).upsert_currency(
            code=payload.code,
            name=payload.name,
            minor_units=payload.minor_units,
            active=payload.active,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("currency_save_failed", exc) from exc
    return {"currency": record}


@router.get("/organizations")
def list_organizations(
    request: Request,
    current_user: MasterDataRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    """List organizations in one workspace."""

    if server_master_data_enabled(request):
        _server_workspace(workspace)

        def operation(repository: PostgresMasterDataRepository, tenant: str) -> list[dict[str, object]]:
            return [_server_organization(record) for record in repository.list_organizations(tenant_id=tenant)]

        records = execute_postgres_master_data(request, operation)
        return _list_response(
            "organizations", _server_page(records, limit=limit, offset=offset), limit=limit, offset=offset
        )
    try:
        records = MasterDataService(_local_connection(connection)).list_organizations(
            workspace=workspace,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("organizations_list_failed", exc) from exc
    return _list_response("organizations", records, limit=limit, offset=offset)


@router.post("/organizations")
def upsert_organization(
    request: Request,
    payload: OrganizationRequest,
    current_user: MasterDataManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Create or update one local organization reference."""

    if server_master_data_enabled(request):
        _server_workspace(payload.workspace)

        def operation(repository: PostgresMasterDataRepository, tenant: str) -> dict[str, object]:
            base_currency = payload.base_currency.strip().upper() or None
            if base_currency is not None:
                active_currencies = repository.list_currencies(tenant_id=tenant, active_only=True)
                if not any(str(currency["code"]) == base_currency for currency in active_currencies):
                    raise PostgresMasterDataValidationError("Organizations require an active base-currency reference.")
            return repository.upsert_organization(
                tenant_id=tenant,
                organization_id=_server_id("org", tenant, payload.organization_code),
                organization_code=payload.organization_code,
                name=payload.name,
                base_currency=base_currency,
                active=payload.active,
                actor_id=current_user.id,
                request_id=str(getattr(request.state, "request_id", "")),
                metadata={"source": "api"},
            )

        record = execute_postgres_master_data(
            request,
            operation,
        )
        return {"organization": _server_organization(record)}
    try:
        values = payload.model_dump()
        values.pop("base_currency", None)
        record = MasterDataService(_local_connection(connection)).upsert_organization(
            **values,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("organization_save_failed", exc) from exc
    return {"organization": record}


@router.get("/entities")
def list_legal_entities(
    request: Request,
    current_user: MasterDataRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    organization: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    """List legal-entity references in one workspace."""

    if server_master_data_enabled(request):
        _server_workspace(workspace)

        def operation(repository: PostgresMasterDataRepository, tenant: str) -> list[dict[str, object]]:
            organization_id: str | None = None
            if organization.strip():
                organization_id = str(
                    repository.organization_by_code(
                        tenant_id=tenant,
                        organization_code=organization,
                    )["id"]
                )
            return [
                _server_entity(record)
                for record in repository.list_legal_entities(
                    tenant_id=tenant,
                    organization_id=organization_id,
                )
            ]

        records = execute_postgres_master_data(request, operation)
        return _list_response("entities", _server_page(records, limit=limit, offset=offset), limit=limit, offset=offset)
    try:
        records = MasterDataService(_local_connection(connection)).list_legal_entities(
            workspace=workspace,
            organization_code=organization,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("entities_list_failed", exc) from exc
    return _list_response("entities", records, limit=limit, offset=offset)


@router.post("/entities")
def upsert_legal_entity(
    request: Request,
    payload: LegalEntityRequest,
    current_user: MasterDataManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Create or update one local legal-entity reference."""

    if server_master_data_enabled(request):
        _server_workspace(payload.workspace)

        def operation(repository: PostgresMasterDataRepository, tenant: str) -> dict[str, object]:
            organization = repository.organization_by_code(
                tenant_id=tenant,
                organization_code=payload.organization_code,
            )
            if not bool(organization["active"]):
                raise PostgresMasterDataValidationError("Legal entities require an active organization reference.")
            currency_code = payload.currency_code.strip().upper()
            active_currencies = repository.list_currencies(tenant_id=tenant, active_only=True)
            if not any(str(currency["code"]) == currency_code for currency in active_currencies):
                raise PostgresMasterDataValidationError("Legal entities require an active currency reference.")
            record = repository.upsert_legal_entity(
                tenant_id=tenant,
                organization_id=str(organization["id"]),
                entity_id=_server_id("entity", tenant, organization["id"], payload.entity_code),
                entity_code=payload.entity_code,
                name=payload.name,
                currency_code=currency_code,
                active=payload.active,
                actor_id=current_user.id,
                request_id=str(getattr(request.state, "request_id", "")),
                metadata={"source": "api"},
            )
            return record

        return {"entity": _server_entity(execute_postgres_master_data(request, operation))}
    try:
        record = MasterDataService(_local_connection(connection)).upsert_legal_entity(
            organization_code=payload.organization_code,
            entity_code=payload.entity_code,
            name=payload.name,
            currency_code=payload.currency_code,
            workspace=payload.workspace,
            active=payload.active,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("entity_save_failed", exc) from exc
    return {"entity": record}


@router.get("/branches")
def list_branches(
    request: Request,
    current_user: MasterDataRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    organization: str = "",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    """List branch references in one workspace."""

    if server_master_data_enabled(request):
        _server_workspace(workspace)

        def operation(repository: PostgresMasterDataRepository, tenant: str) -> list[dict[str, object]]:
            organization_id: str | None = None
            if organization.strip():
                organization_id = str(
                    repository.organization_by_code(
                        tenant_id=tenant,
                        organization_code=organization,
                    )["id"]
                )
            return [
                _server_branch(record)
                for record in repository.list_branches(
                    tenant_id=tenant,
                    organization_id=organization_id,
                )
            ]

        records = execute_postgres_master_data(request, operation)
        return _list_response("branches", _server_page(records, limit=limit, offset=offset), limit=limit, offset=offset)
    try:
        records = MasterDataService(_local_connection(connection)).list_branches(
            workspace=workspace,
            organization_code=organization,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("branches_list_failed", exc) from exc
    return _list_response("branches", records, limit=limit, offset=offset)


@router.post("/branches")
def upsert_branch(
    request: Request,
    payload: BranchRequest,
    current_user: MasterDataManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Create or update one local branch reference."""

    if server_master_data_enabled(request):
        _server_workspace(payload.workspace)

        def operation(repository: PostgresMasterDataRepository, tenant: str) -> dict[str, object]:
            organization = repository.organization_by_code(
                tenant_id=tenant,
                organization_code=payload.organization_code,
            )
            if not bool(organization["active"]):
                raise PostgresMasterDataValidationError("Branches require an active organization reference.")
            legal_entity_id: str | None = None
            if payload.entity_code.strip():
                legal_entity = repository.legal_entity_by_code(
                    tenant_id=tenant,
                    organization_id=str(organization["id"]),
                    entity_code=payload.entity_code,
                )
                if not bool(legal_entity["active"]):
                    raise PostgresMasterDataValidationError("Branches require an active legal-entity reference.")
                legal_entity_id = str(legal_entity["id"])
            return repository.upsert_branch(
                tenant_id=tenant,
                organization_id=str(organization["id"]),
                branch_id=_server_id("branch", tenant, organization["id"], payload.branch_code),
                branch_code=payload.branch_code,
                name=payload.name,
                legal_entity_id=legal_entity_id,
                active=payload.active,
                actor_id=current_user.id,
                request_id=str(getattr(request.state, "request_id", "")),
                metadata={"source": "api"},
            )

        return {"branch": _server_branch(execute_postgres_master_data(request, operation))}
    try:
        record = MasterDataService(_local_connection(connection)).upsert_branch(
            organization_code=payload.organization_code,
            branch_code=payload.branch_code,
            name=payload.name,
            entity_code=payload.entity_code,
            workspace=payload.workspace,
            active=payload.active,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("branch_save_failed", exc) from exc
    return {"branch": record}


@router.get("/periods")
def list_periods(
    request: Request,
    current_user: MasterDataRead,
    connection: sqlite3.Connection | None = Depends(get_local_db),
    workspace: str = "default",
    limit: PageLimit = DEFAULT_LIST_LIMIT,
    offset: PageOffset = 0,
) -> dict[str, object]:
    """List local fiscal-period metadata."""

    if server_master_data_enabled(request):
        _server_workspace(workspace)
        records = execute_postgres_master_data(
            request,
            lambda repository, tenant: [_server_period(record) for record in repository.list_periods(tenant_id=tenant)],
        )
        return _list_response("periods", _server_page(records, limit=limit, offset=offset), limit=limit, offset=offset)
    try:
        records = MasterDataService(_local_connection(connection)).list_periods(
            workspace=workspace,
            limit=limit,
            offset=offset,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("periods_list_failed", exc) from exc
    return _list_response("periods", records, limit=limit, offset=offset)


@router.post("/periods")
def upsert_period(
    request: Request,
    payload: PeriodRequest,
    current_user: MasterDataManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Create or update one non-overlapping local fiscal period."""

    if server_master_data_enabled(request):
        _server_workspace(payload.workspace)
        record = execute_postgres_master_data(
            request,
            lambda repository, tenant: repository.upsert_period(
                tenant_id=tenant,
                period_id=_server_id("period", tenant, payload.name),
                name=payload.name,
                start_date=payload.start_date,
                end_date=payload.end_date,
                fiscal_year=payload.fiscal_year,
                period_number=payload.period_number,
                actor_id=current_user.id,
                request_id=str(getattr(request.state, "request_id", "")),
                metadata={"source": "api"},
            ),
        )
        return {"period": _server_period(record)}
    try:
        record = MasterDataService(_local_connection(connection)).upsert_period(
            name=payload.name,
            start_date=payload.start_date,
            end_date=payload.end_date,
            workspace=payload.workspace,
            fiscal_year=payload.fiscal_year,
            period_number=payload.period_number,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("period_save_failed", exc) from exc
    return {"period": record}


@router.post("/periods/{period_id}/status")
def set_period_status(
    request: Request,
    period_id: str,
    payload: PeriodStatusRequest,
    current_user: MasterDataManage,
    connection: sqlite3.Connection | None = Depends(get_local_db),
) -> dict[str, object]:
    """Transition fiscal-period metadata; this does not post or lock ERP transactions."""

    if server_master_data_enabled(request):
        record = execute_postgres_master_data(
            request,
            lambda repository, tenant: repository.set_period_status(
                tenant_id=tenant,
                period_id=period_id,
                status=payload.status,
                reason=payload.reason,
                actor_id=current_user.id,
                request_id=str(getattr(request.state, "request_id", "")),
                metadata={"source": "api"},
            ),
        )
        return {"period": _server_period(record)}
    try:
        record = MasterDataService(_local_connection(connection)).set_period_status(
            period_id,
            status=payload.status,
            reason=payload.reason,
            actor_label=current_user.username,
        )
    except (DatabaseError, PlatformError) as exc:
        raise _api_error("period_status_failed", exc) from exc
    return {"period": record}
