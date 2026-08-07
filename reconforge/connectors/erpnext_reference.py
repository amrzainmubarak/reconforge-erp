"""Governed, read-only ERPNext GL Entry connector.

ERPNext is an open-source ERP with a stable REST resource surface.  This
adapter deliberately stops at a bounded, company-scoped read of ``GL Entry``;
posting, mutation, credential provisioning, and provider-specific operational
assurance remain outside the connector package.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from reconforge.connectors.manifest import (
    AuthenticationMethod,
    ConnectorCapability,
    ConnectorKind,
    ConnectorManifest,
    DataClassification,
    RetryPolicy,
    SupportLevel,
)
from reconforge.connectors.network import (
    ConnectorNetworkError,
    ConnectorReadResult,
    NetworkConnectorExecutor,
    NetworkConnectorRegistration,
)

ERP_NEXT_GL_ENTRY_PATH = "/api/resource/GL%20Entry"
ERP_NEXT_ENDPOINT = "https://erpnext.example.test" + ERP_NEXT_GL_ENTRY_PATH
ERP_NEXT_MANIFEST = ConnectorManifest(
    schema_version="connector-manifest-v1",
    connector_id="erpnext-gl-entry-readonly",
    display_name="ERPNext GL Entry read-only source",
    version="1.0.0",
    kind=ConnectorKind.NETWORK_SOURCE,
    capabilities=frozenset({ConnectorCapability.READ}),
    authentication=AuthenticationMethod.SECRET_REFERENCE,
    network_required=True,
    data_classification=DataClassification.RESTRICTED,
    rate_limit_per_minute=60,
    incremental_cursor=True,
    idempotent_reads=True,
    retry_policy=RetryPolicy(maximum_attempts=3, initial_delay_seconds=1, maximum_delay_seconds=8),
    schema_versions=("erpnext-gl-entry-page-v1",),
    synthetic_sandbox=True,
    threat_model=("ssrf", "credential-disclosure", "schema-confusion", "cross-company-leakage"),
    secret_handling="Resolve ERPNext API token at runtime; never persist, log, or return the secret.",  # nosec B106
    egress_destinations=(ERP_NEXT_ENDPOINT,),
    support_level=SupportLevel.COMMUNITY,
)


def _exact_non_negative_decimal(value: str, field_name: str) -> str:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be exact Decimal text") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field_name} must be finite non-negative Decimal text")
    return value


class ErpNextGlEntry(BaseModel):
    """Closed ERPNext ledger-line shape with both debit and credit preserved."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: str = Field(alias="name", min_length=1, max_length=256)
    company: str = Field(min_length=1, max_length=160)
    account: str = Field(min_length=1, max_length=256)
    debit: str = Field(min_length=1, max_length=128)
    credit: str = Field(min_length=1, max_length=128)
    currency: str = Field(alias="account_currency", min_length=3, max_length=12)
    posting_date: date = Field(alias="posting_date")
    document_reference: str = Field(default="", alias="voucher_no", max_length=512)

    @field_validator("debit", "credit")
    @classmethod
    def validate_amount(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "amount")
        return _exact_non_negative_decimal(value, str(field_name))

    @model_validator(mode="after")
    def validate_debit_credit(self) -> ErpNextGlEntry:
        if Decimal(self.debit) > 0 and Decimal(self.credit) > 0:
            raise ValueError("a GL Entry must not carry both debit and credit")
        return self

    @property
    def signed_amount(self) -> Decimal:
        """Return a derived amount without changing the source-line payload."""

        return Decimal(self.debit) - Decimal(self.credit)


class ErpNextGlEntryPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: tuple[ErpNextGlEntry, ...] = Field(alias="data", max_length=10_000)
    next_cursor: str | None = Field(default=None, min_length=1, max_length=4_096)

    @field_validator("entries")
    @classmethod
    def validate_unique_ids(cls, value: tuple[ErpNextGlEntry, ...]) -> tuple[ErpNextGlEntry, ...]:
        if len({entry.entry_id for entry in value}) != len(value):
            raise ValueError("entries must have unique names")
        if len({entry.company for entry in value}) > 1:
            raise ValueError("one page must not mix ERPNext companies")
        return value


@dataclass(frozen=True)
class ErpNextRead:
    page: ErpNextGlEntryPage
    request_digest: str
    response_digest: str
    attempts: int


def erpnext_registration(
    *, credential_reference: str, endpoint: str = ERP_NEXT_ENDPOINT
) -> NetworkConnectorRegistration:
    """Create an operator-bound ERPNext registration without widening egress."""

    parsed = urlsplit(endpoint)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != ERP_NEXT_GL_ENTRY_PATH
    ):
        raise ConnectorNetworkError("erpnext_endpoint_invalid")
    manifest = ERP_NEXT_MANIFEST.model_copy(update={"egress_destinations": (endpoint,)})
    return NetworkConnectorRegistration(
        registration_schema="network-connector-registration-v1",
        manifest=manifest,
        endpoint=endpoint,
        credential_reference=credential_reference,
        credential_auth_scheme="token",
        cursor_query_parameter="limit_start",
    )


@dataclass(frozen=True)
class ErpNextConnector:
    executor: NetworkConnectorExecutor
    registration: NetworkConnectorRegistration

    def read_gl_entries(
        self,
        *,
        idempotency_key: str,
        cursor: str | None = None,
        expected_company: str | None = None,
        page_length: int | None = None,
    ) -> ErpNextRead:
        if cursor is not None and (not cursor.isdecimal() or int(cursor) < 0 or len(cursor) > 12):
            raise ConnectorNetworkError("erpnext_cursor_invalid")
        if expected_company is not None:
            expected_company = expected_company.strip()
            if not expected_company or len(expected_company) > 160:
                raise ConnectorNetworkError("erpnext_company_scope_invalid")
        if page_length is not None and (isinstance(page_length, bool) or not 1 <= page_length <= 10_000):
            raise ConnectorNetworkError("erpnext_page_length_invalid")
        query_parameters: list[tuple[str, str]] = []
        if expected_company is not None:
            query_parameters.append(
                (
                    "filters",
                    json.dumps(
                        [["company", "=", expected_company]],
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ),
                )
            )
        if page_length is not None:
            query_parameters.append(("limit_page_length", str(page_length)))
        query_parameters.sort()
        result: ConnectorReadResult = self.executor.read(
            self.registration,
            idempotency_key=idempotency_key,
            cursor=cursor,
            query_parameters=tuple(query_parameters),
        )
        try:
            document = json.loads(result.response_body)
            if not isinstance(document, dict):
                raise ValueError("ERPNext response must be an object")
            document["next_cursor"] = result.next_cursor
            page = ErpNextGlEntryPage.model_validate(document)
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ConnectorNetworkError("erpnext_response_schema_invalid") from exc
        if expected_company is not None and any(entry.company != expected_company for entry in page.entries):
            raise ConnectorNetworkError("erpnext_company_scope_mismatch")
        if page.next_cursor is not None and (not page.next_cursor.isdecimal() or int(page.next_cursor) < 0):
            raise ConnectorNetworkError("erpnext_response_cursor_invalid")
        canonical_entries = tuple(
            sorted(
                (entry.model_dump(mode="json", by_alias=True) for entry in page.entries),
                key=lambda item: str(item["name"]),
            )
        )
        canonical_body = json.dumps(
            {"data": canonical_entries, "next_cursor": page.next_cursor},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return ErpNextRead(
            page=page,
            request_digest=result.request_digest,
            response_digest=hashlib.sha256(canonical_body).hexdigest(),
            attempts=result.attempts,
        )
