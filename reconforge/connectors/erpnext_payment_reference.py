"""Governed, read-only ERPNext Payment Entry connector."""

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

ERP_NEXT_PAYMENT_ENTRY_PATH = "/api/resource/Payment%20Entry"
ERP_NEXT_PAYMENT_ENTRY_ENDPOINT = "https://erpnext.example.test" + ERP_NEXT_PAYMENT_ENTRY_PATH
ERP_NEXT_PAYMENT_ENTRY_MANIFEST = ConnectorManifest(
    schema_version="connector-manifest-v1",
    connector_id="erpnext-payment-entry-readonly",
    display_name="ERPNext Payment Entry read-only source",
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
    schema_versions=("erpnext-payment-entry-page-v1",),
    synthetic_sandbox=True,
    threat_model=("credential-disclosure", "cross-company-leakage", "replay", "schema-confusion"),
    secret_handling="Resolve ERPNext API token at runtime; never persist, log, or return the secret.",  # nosec B106
    egress_destinations=(ERP_NEXT_PAYMENT_ENTRY_ENDPOINT,),
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


class ErpNextPaymentEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: str = Field(alias="name", min_length=1, max_length=256)
    company: str = Field(min_length=1, max_length=160)
    posting_date: date = Field(alias="posting_date")
    paid_amount: str = Field(alias="paid_amount", min_length=1, max_length=128)
    received_amount: str = Field(alias="received_amount", min_length=1, max_length=128)
    paid_currency: str = Field(alias="paid_from_account_currency", min_length=3, max_length=12)
    received_currency: str = Field(alias="paid_to_account_currency", min_length=3, max_length=12)
    status: str = Field(min_length=1, max_length=64)
    party_type: str = Field(default="", alias="party_type", max_length=64)
    party: str = Field(default="", alias="party", max_length=256)
    reference_number: str = Field(default="", alias="reference_no", max_length=256)

    @field_validator("paid_amount", "received_amount")
    @classmethod
    def validate_amount(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "amount")
        return _exact_non_negative_decimal(value, str(field_name))

    @model_validator(mode="after")
    def validate_non_zero_payment(self) -> ErpNextPaymentEntry:
        if Decimal(self.paid_amount) == 0 and Decimal(self.received_amount) == 0:
            raise ValueError("a Payment Entry must carry a non-zero paid or received amount")
        return self


class ErpNextPaymentEntryPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: tuple[ErpNextPaymentEntry, ...] = Field(alias="data", max_length=10_000)
    next_cursor: str | None = Field(default=None, min_length=1, max_length=4_096)

    @field_validator("entries")
    @classmethod
    def validate_unique_ids(cls, value: tuple[ErpNextPaymentEntry, ...]) -> tuple[ErpNextPaymentEntry, ...]:
        if len({entry.entry_id for entry in value}) != len(value):
            raise ValueError("entries must have unique names")
        if len({entry.company for entry in value}) > 1:
            raise ValueError("one page must not mix ERPNext companies")
        return value


@dataclass(frozen=True)
class ErpNextPaymentEntryRead:
    page: ErpNextPaymentEntryPage
    request_digest: str
    response_digest: str
    attempts: int


def erpnext_payment_entry_registration(
    *, credential_reference: str, endpoint: str = ERP_NEXT_PAYMENT_ENTRY_ENDPOINT
) -> NetworkConnectorRegistration:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != ERP_NEXT_PAYMENT_ENTRY_PATH
    ):
        raise ConnectorNetworkError("erpnext_payment_entry_endpoint_invalid")
    manifest = ERP_NEXT_PAYMENT_ENTRY_MANIFEST.model_copy(update={"egress_destinations": (endpoint,)})
    return NetworkConnectorRegistration(
        registration_schema="network-connector-registration-v1",
        manifest=manifest,
        endpoint=endpoint,
        credential_reference=credential_reference,
        credential_auth_scheme="token",
        cursor_query_parameter="limit_start",
    )


@dataclass(frozen=True)
class ErpNextPaymentEntryConnector:
    executor: NetworkConnectorExecutor
    registration: NetworkConnectorRegistration

    def read_payment_entries(
        self,
        *,
        idempotency_key: str,
        cursor: str | None = None,
        expected_company: str | None = None,
        page_length: int | None = None,
    ) -> ErpNextPaymentEntryRead:
        if cursor is not None and (not cursor.isdecimal() or int(cursor) < 0 or len(cursor) > 12):
            raise ConnectorNetworkError("erpnext_payment_entry_cursor_invalid")
        if expected_company is not None:
            expected_company = expected_company.strip()
            if not expected_company or len(expected_company) > 160:
                raise ConnectorNetworkError("erpnext_payment_entry_company_scope_invalid")
        if page_length is not None and (isinstance(page_length, bool) or not 1 <= page_length <= 10_000):
            raise ConnectorNetworkError("erpnext_payment_entry_page_length_invalid")
        query_parameters: list[tuple[str, str]] = []
        if expected_company is not None:
            query_parameters.append(
                (
                    "filters",
                    json.dumps([["company", "=", expected_company]], ensure_ascii=True, separators=(",", ":")),
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
            page = ErpNextPaymentEntryPage.model_validate(document)
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ConnectorNetworkError("erpnext_payment_entry_response_schema_invalid") from exc
        if expected_company is not None and any(entry.company != expected_company for entry in page.entries):
            raise ConnectorNetworkError("erpnext_payment_entry_company_scope_mismatch")
        if page.next_cursor is not None and (not page.next_cursor.isdecimal() or int(page.next_cursor) < 0):
            raise ConnectorNetworkError("erpnext_payment_entry_response_cursor_invalid")
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
        return ErpNextPaymentEntryRead(
            page=page,
            request_digest=result.request_digest,
            response_digest=hashlib.sha256(canonical_body).hexdigest(),
            attempts=result.attempts,
        )


__all__ = [
    "ERP_NEXT_PAYMENT_ENTRY_ENDPOINT",
    "ERP_NEXT_PAYMENT_ENTRY_MANIFEST",
    "ERP_NEXT_PAYMENT_ENTRY_PATH",
    "ErpNextPaymentEntry",
    "ErpNextPaymentEntryConnector",
    "ErpNextPaymentEntryPage",
    "ErpNextPaymentEntryRead",
    "erpnext_payment_entry_registration",
]
