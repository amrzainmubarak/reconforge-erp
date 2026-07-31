"""Bounded SCIM 2.0 discovery, User, and Group resources."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from reconforge.api.scim_security import SCIMHTTPError, SCIMRequestContext, get_scim_context
from reconforge.auth.scim import (
    SCIM_GROUP_SCHEMA,
    SCIM_PATCH_SCHEMA,
    SCIM_USER_SCHEMA,
    SCIMError,
    SCIMGroup,
    SCIMGroupWrite,
    SCIMMember,
    SCIMService,
    SCIMUser,
    SCIMUserWrite,
    scim_timestamp,
)
from reconforge.infrastructure.postgres_scim import scim_resource_etag


class SCIMJSONResponse(JSONResponse):
    media_type = "application/scim+json"


router = APIRouter(prefix="/scim/v2", tags=["scim"], default_response_class=SCIMJSONResponse)
SCIMContext = Annotated[SCIMRequestContext, Depends(get_scim_context)]
LIST_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SERVICE_PROVIDER_CONFIG_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
RESOURCE_TYPE_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
SCHEMA_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Schema"
_FILTER = re.compile(r'^\s*(userName|externalId|displayName)\s+eq\s+"([^"\\]{1,255})"\s*$', re.IGNORECASE)
_MEMBER_REMOVE = re.compile(r'^members\[value\s+eq\s+"(scu-[0-9a-f]{32})"\]$', re.IGNORECASE)


class PatchOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    op: Literal["add", "remove", "replace"]
    path: str = Field(min_length=1, max_length=512)
    value: Any = None

    @field_validator("op", mode="before")
    @classmethod
    def normalize_operation(cls, value: Any) -> Any:
        return value.casefold() if isinstance(value, str) else value


class PatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schemas: tuple[str, ...]
    Operations: tuple[PatchOperation, ...] = Field(min_length=1, max_length=100)

    @field_validator("schemas", "Operations", mode="before")
    @classmethod
    def accept_arrays(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("SCIM multi-valued attributes must be arrays.")
        return tuple(value)

    @field_validator("schemas")
    @classmethod
    def require_patch_schema(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != (SCIM_PATCH_SCHEMA,):
            raise ValueError("PATCH requires the SCIM PatchOp schema.")
        return value


def _execute(operation: Any) -> Any:
    try:
        return operation()
    except ValidationError as exc:
        raise SCIMHTTPError(400, "SCIM request validation failed.", scim_type="invalidValue") from exc
    except SCIMError as exc:
        status = 404 if "not found" in str(exc).casefold() else 412 if exc.scim_type == "invalidVers" else 409
        if exc.scim_type in {"invalidFilter", "invalidPath", "invalidValue"} and status != 404:
            status = 400
        raise SCIMHTTPError(status, str(exc), scim_type=exc.scim_type) from exc


def _filter(value: str | None, resource: Literal["User", "Group"]) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    match = _FILTER.fullmatch(value)
    if match is None:
        raise SCIMHTTPError(400, "SCIM filter is not supported.", scim_type="invalidFilter")
    attribute, expected = match.group(1).casefold(), match.group(2)
    allowed = {"username", "externalid"} if resource == "User" else {"displayname", "externalid"}
    if attribute not in allowed:
        raise SCIMHTTPError(400, "SCIM filter is not supported.", scim_type="invalidFilter")
    return attribute, expected.casefold() if attribute == "username" else expected


def _location(request: Request, resource_type: str, resource_id: str) -> str:
    return str(request.base_url).rstrip("/") + f"/scim/v2/{resource_type}/{resource_id}"


def _user_payload(request: Request, resource: SCIMUser) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemas": [SCIM_USER_SCHEMA],
        "id": resource.id,
        "externalId": resource.external_id,
        "userName": resource.username,
        "displayName": resource.display_name,
        "active": resource.active,
        "meta": {
            "resourceType": "User",
            "created": scim_timestamp(resource.created_at),
            "lastModified": scim_timestamp(resource.updated_at),
            "version": scim_resource_etag(resource),
            "location": _location(request, "Users", resource.id),
        },
    }
    if resource.email is not None:
        payload["emails"] = [{"value": resource.email, "type": "work", "primary": True}]
    return payload


def _group_payload(request: Request, resource: SCIMGroup) -> dict[str, Any]:
    return {
        "schemas": [SCIM_GROUP_SCHEMA],
        "id": resource.id,
        "externalId": resource.external_id,
        "displayName": resource.display_name,
        "members": [
            {"value": member, "$ref": _location(request, "Users", member), "type": "User"}
            for member in resource.member_ids
        ],
        "meta": {
            "resourceType": "Group",
            "created": scim_timestamp(resource.created_at),
            "lastModified": scim_timestamp(resource.updated_at),
            "version": scim_resource_etag(resource),
            "location": _location(request, "Groups", resource.id),
        },
    }


def _require_match(if_match: str | None, resource: SCIMUser | SCIMGroup) -> int:
    if if_match is None or if_match.strip() != scim_resource_etag(resource):
        raise SCIMHTTPError(412, "SCIM resource version does not match.", scim_type="invalidVers")
    return resource.version


@router.get("/ServiceProviderConfig")
def service_provider_config(context: SCIMContext) -> dict[str, Any]:
    del context
    return {
        "schemas": [SERVICE_PROVIDER_CONFIG_SCHEMA],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": True},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "Opaque Bearer Token",
                "description": "Operator-issued, revocable, tenant-scoped bearer credential.",
                "primary": True,
            }
        ],
    }


@router.get("/ResourceTypes")
def resource_types(context: SCIMContext) -> dict[str, Any]:
    del context
    resources = [
        {
            "schemas": [RESOURCE_TYPE_SCHEMA],
            "id": "User",
            "name": "User",
            "endpoint": "/Users",
            "schema": SCIM_USER_SCHEMA,
        },
        {
            "schemas": [RESOURCE_TYPE_SCHEMA],
            "id": "Group",
            "name": "Group",
            "endpoint": "/Groups",
            "schema": SCIM_GROUP_SCHEMA,
        },
    ]
    return {"schemas": [LIST_SCHEMA], "totalResults": 2, "Resources": resources}


@router.get("/Schemas")
def schemas(context: SCIMContext) -> dict[str, Any]:
    del context
    resources = [
        {
            "schemas": [SCHEMA_SCHEMA],
            "id": SCIM_USER_SCHEMA,
            "name": "User",
            "description": "ReconForge supported SCIM User subset.",
            "attributes": [
                {
                    "name": "userName",
                    "type": "string",
                    "multiValued": False,
                    "required": True,
                    "caseExact": False,
                    "mutability": "readWrite",
                    "returned": "default",
                    "uniqueness": "server",
                },
                {
                    "name": "displayName",
                    "type": "string",
                    "multiValued": False,
                    "required": False,
                    "caseExact": False,
                    "mutability": "readWrite",
                    "returned": "default",
                    "uniqueness": "none",
                },
                {
                    "name": "active",
                    "type": "boolean",
                    "multiValued": False,
                    "required": False,
                    "mutability": "readWrite",
                    "returned": "default",
                    "uniqueness": "none",
                },
            ],
        },
        {
            "schemas": [SCHEMA_SCHEMA],
            "id": SCIM_GROUP_SCHEMA,
            "name": "Group",
            "description": "ReconForge supported role-free SCIM Group subset.",
            "attributes": [
                {
                    "name": "displayName",
                    "type": "string",
                    "multiValued": False,
                    "required": True,
                    "caseExact": False,
                    "mutability": "readWrite",
                    "returned": "default",
                    "uniqueness": "none",
                },
                {
                    "name": "members",
                    "type": "complex",
                    "multiValued": True,
                    "required": False,
                    "mutability": "readWrite",
                    "returned": "default",
                    "uniqueness": "none",
                },
            ],
        },
    ]
    return {"schemas": [LIST_SCHEMA], "totalResults": 2, "Resources": resources}


@router.post("/Users", status_code=201)
def create_user(payload: SCIMUserWrite, request: Request, context: SCIMContext) -> JSONResponse:
    user, created = _execute(
        lambda: SCIMService(context.repository, context.audit).provision_user(
            tenant_id=context.principal.tenant_id,
            provisioning_domain=context.principal.provisioning_domain,
            actor_id=context.principal.client_id,
            resource=payload,
        )
    )
    body = _user_payload(request, user)
    return SCIMJSONResponse(
        status_code=201 if created else 200,
        content=body,
        headers={"Location": body["meta"]["location"], "ETag": scim_resource_etag(user)},
    )


@router.get("/Users")
def list_users(
    request: Request,
    context: SCIMContext,
    filter: str | None = Query(default=None, max_length=512),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=0, le=200),
) -> dict[str, Any]:
    attribute, expected = _filter(filter, "User")
    total, resources = _execute(
        lambda: context.repository.list_users(
            tenant_id=context.principal.tenant_id,
            domain=context.principal.provisioning_domain,
            filter_attribute=attribute,
            filter_value=expected,
            offset=startIndex - 1,
            limit=count,
        )
    )
    return {
        "schemas": [LIST_SCHEMA],
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": len(resources),
        "Resources": [_user_payload(request, item) for item in resources],
    }


@router.get("/Users/{resource_id}")
def get_user(resource_id: str, request: Request, response: Response, context: SCIMContext) -> dict[str, Any]:
    user = _execute(
        lambda: context.repository.get_user(
            tenant_id=context.principal.tenant_id, domain=context.principal.provisioning_domain, resource_id=resource_id
        )
    )
    response.headers["ETag"] = scim_resource_etag(user)
    return _user_payload(request, user)


@router.put("/Users/{resource_id}")
def replace_user(
    resource_id: str,
    payload: SCIMUserWrite,
    request: Request,
    context: SCIMContext,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> JSONResponse:
    current = _execute(
        lambda: context.repository.get_user(
            tenant_id=context.principal.tenant_id, domain=context.principal.provisioning_domain, resource_id=resource_id
        )
    )
    version = _require_match(if_match, current)
    user = _execute(
        lambda: context.repository.replace_user(
            tenant_id=context.principal.tenant_id,
            domain=context.principal.provisioning_domain,
            resource_id=resource_id,
            expected_version=version,
            resource=payload,
        )
    )
    context.audit.record(
        tenant_id=context.principal.tenant_id,
        domain=context.principal.provisioning_domain,
        actor_id=context.principal.client_id,
        resource_type="User",
        resource_id=user.id,
        action="REPLACE",
        outcome="ALLOWED",
        reason_code=None,
    )
    body = _user_payload(request, user)
    return SCIMJSONResponse(
        content=body, headers={"ETag": scim_resource_etag(user), "Location": body["meta"]["location"]}
    )


@router.patch("/Users/{resource_id}")
def patch_user(
    resource_id: str,
    payload: PatchRequest,
    request: Request,
    context: SCIMContext,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> JSONResponse:
    current = _execute(
        lambda: context.repository.get_user(
            tenant_id=context.principal.tenant_id, domain=context.principal.provisioning_domain, resource_id=resource_id
        )
    )
    version = _require_match(if_match, current)
    values: dict[str, Any] = {
        "schemas": [SCIM_USER_SCHEMA],
        "externalId": current.external_id,
        "userName": current.username,
        "displayName": current.display_name,
        "active": current.active,
        "emails": ([{"value": current.email, "primary": True}] if current.email else []),
    }
    for operation in payload.Operations:
        path = operation.path.casefold()
        if operation.op != "replace" or path not in {"active", "displayname"}:
            raise SCIMHTTPError(400, "SCIM PATCH path is not supported.", scim_type="invalidPath")
        values["active" if path == "active" else "displayName"] = operation.value
    write = _execute(lambda: SCIMUserWrite.model_validate(values))
    user = _execute(
        lambda: context.repository.replace_user(
            tenant_id=context.principal.tenant_id,
            domain=context.principal.provisioning_domain,
            resource_id=resource_id,
            expected_version=version,
            resource=write,
        )
    )
    context.audit.record(
        tenant_id=context.principal.tenant_id,
        domain=context.principal.provisioning_domain,
        actor_id=context.principal.client_id,
        resource_type="User",
        resource_id=user.id,
        action="REPLACE",
        outcome="ALLOWED",
        reason_code=None,
    )
    return SCIMJSONResponse(content=_user_payload(request, user), headers={"ETag": scim_resource_etag(user)})


@router.delete("/Users/{resource_id}", status_code=204)
def delete_user(
    resource_id: str, context: SCIMContext, if_match: str | None = Header(default=None, alias="If-Match")
) -> Response:
    current = _execute(
        lambda: context.repository.get_user(
            tenant_id=context.principal.tenant_id, domain=context.principal.provisioning_domain, resource_id=resource_id
        )
    )
    _require_match(if_match, current)
    _execute(
        lambda: SCIMService(context.repository, context.audit).deactivate_user(
            tenant_id=context.principal.tenant_id,
            provisioning_domain=context.principal.provisioning_domain,
            actor_id=context.principal.client_id,
            resource_id=resource_id,
        )
    )
    return Response(status_code=204)


@router.post("/Groups", status_code=201)
def create_group(payload: SCIMGroupWrite, request: Request, context: SCIMContext) -> JSONResponse:
    group, created = _execute(
        lambda: SCIMService(context.repository, context.audit).provision_group(
            tenant_id=context.principal.tenant_id,
            provisioning_domain=context.principal.provisioning_domain,
            actor_id=context.principal.client_id,
            resource=payload,
        )
    )
    body = _group_payload(request, group)
    return SCIMJSONResponse(
        status_code=201 if created else 200,
        content=body,
        headers={"Location": body["meta"]["location"], "ETag": scim_resource_etag(group)},
    )


@router.get("/Groups")
def list_groups(
    request: Request,
    context: SCIMContext,
    filter: str | None = Query(default=None, max_length=512),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=0, le=200),
) -> dict[str, Any]:
    attribute, expected = _filter(filter, "Group")
    total, resources = _execute(
        lambda: context.repository.list_groups(
            tenant_id=context.principal.tenant_id,
            domain=context.principal.provisioning_domain,
            filter_attribute=attribute,
            filter_value=expected,
            offset=startIndex - 1,
            limit=count,
        )
    )
    return {
        "schemas": [LIST_SCHEMA],
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": len(resources),
        "Resources": [_group_payload(request, item) for item in resources],
    }


@router.get("/Groups/{resource_id}")
def get_group(resource_id: str, request: Request, response: Response, context: SCIMContext) -> dict[str, Any]:
    group = _execute(
        lambda: context.repository.get_group(
            tenant_id=context.principal.tenant_id, domain=context.principal.provisioning_domain, resource_id=resource_id
        )
    )
    response.headers["ETag"] = scim_resource_etag(group)
    return _group_payload(request, group)


def _group_write_from_patch(current: SCIMGroup, payload: PatchRequest) -> SCIMGroupWrite:
    display, members = current.display_name, set(current.member_ids)
    for operation in payload.Operations:
        path = operation.path
        folded = path.casefold()
        if folded == "displayname" and operation.op == "replace":
            display = operation.value
        elif folded == "members" and operation.op in {"add", "replace"}:
            raw = operation.value if isinstance(operation.value, list) else [operation.value]
            parsed = tuple(SCIMMember.model_validate(item) for item in raw)
            members = (
                set(item.value for item in parsed)
                if operation.op == "replace"
                else members | {item.value for item in parsed}
            )
        elif operation.op == "remove" and (match := _MEMBER_REMOVE.fullmatch(path)) is not None:
            members.discard(match.group(1).casefold())
        else:
            raise SCIMHTTPError(400, "SCIM PATCH path is not supported.", scim_type="invalidPath")
    return SCIMGroupWrite.model_validate(
        {
            "schemas": [SCIM_GROUP_SCHEMA],
            "externalId": current.external_id,
            "displayName": display,
            "members": [{"value": item} for item in sorted(members)],
        }
    )


@router.put("/Groups/{resource_id}")
def replace_group(
    resource_id: str,
    payload: SCIMGroupWrite,
    request: Request,
    context: SCIMContext,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> JSONResponse:
    current = _execute(
        lambda: context.repository.get_group(
            tenant_id=context.principal.tenant_id, domain=context.principal.provisioning_domain, resource_id=resource_id
        )
    )
    version = _require_match(if_match, current)
    group = _execute(
        lambda: context.repository.replace_group(
            tenant_id=context.principal.tenant_id,
            domain=context.principal.provisioning_domain,
            resource_id=resource_id,
            expected_version=version,
            resource=payload,
        )
    )
    context.audit.record(
        tenant_id=context.principal.tenant_id,
        domain=context.principal.provisioning_domain,
        actor_id=context.principal.client_id,
        resource_type="Group",
        resource_id=group.id,
        action="REPLACE",
        outcome="ALLOWED",
        reason_code=None,
    )
    return SCIMJSONResponse(content=_group_payload(request, group), headers={"ETag": scim_resource_etag(group)})


@router.patch("/Groups/{resource_id}")
def patch_group(
    resource_id: str,
    payload: PatchRequest,
    request: Request,
    context: SCIMContext,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> JSONResponse:
    current = _execute(
        lambda: context.repository.get_group(
            tenant_id=context.principal.tenant_id, domain=context.principal.provisioning_domain, resource_id=resource_id
        )
    )
    version = _require_match(if_match, current)
    write = _execute(lambda: _group_write_from_patch(current, payload))
    group = _execute(
        lambda: context.repository.replace_group(
            tenant_id=context.principal.tenant_id,
            domain=context.principal.provisioning_domain,
            resource_id=resource_id,
            expected_version=version,
            resource=write,
        )
    )
    context.audit.record(
        tenant_id=context.principal.tenant_id,
        domain=context.principal.provisioning_domain,
        actor_id=context.principal.client_id,
        resource_type="Group",
        resource_id=group.id,
        action="REPLACE",
        outcome="ALLOWED",
        reason_code=None,
    )
    return SCIMJSONResponse(content=_group_payload(request, group), headers={"ETag": scim_resource_etag(group)})


@router.delete("/Groups/{resource_id}", status_code=204)
def delete_group(
    resource_id: str, context: SCIMContext, if_match: str | None = Header(default=None, alias="If-Match")
) -> Response:
    current = _execute(
        lambda: context.repository.get_group(
            tenant_id=context.principal.tenant_id, domain=context.principal.provisioning_domain, resource_id=resource_id
        )
    )
    version = _require_match(if_match, current)
    deleted = _execute(
        lambda: context.repository.delete_group(
            tenant_id=context.principal.tenant_id,
            domain=context.principal.provisioning_domain,
            resource_id=resource_id,
            expected_version=version,
        )
    )
    context.audit.record(
        tenant_id=context.principal.tenant_id,
        domain=context.principal.provisioning_domain,
        actor_id=context.principal.client_id,
        resource_type="Group",
        resource_id=deleted.id,
        action="DELETE",
        outcome="ALLOWED",
        reason_code=None,
    )
    return Response(status_code=204)
