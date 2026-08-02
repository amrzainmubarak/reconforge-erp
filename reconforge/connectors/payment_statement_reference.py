"""Provider-neutral, read-only payment-statement reference connector."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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

PAYMENT_STATEMENT_ENDPOINT = "https://api.example.test/v1/payment-statements"
PAYMENT_STATEMENT_MANIFEST = ConnectorManifest(
    schema_version="connector-manifest-v1",
    connector_id="reference-payment-statement-readonly",
    display_name="Reference payment statement read-only source",
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
    schema_versions=("reference-payment-statement-v1",),
    synthetic_sandbox=True,
    threat_model=("ssrf", "credential-disclosure", "schema-confusion", "replay"),
    secret_handling="Resolve credential_reference at runtime; never persist or log the secret.",  # nosec B106
    egress_destinations=(PAYMENT_STATEMENT_ENDPOINT,),
    support_level=SupportLevel.COMMUNITY,
)


class PaymentStatementLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    line_id: str = Field(alias="id", min_length=1, max_length=256)
    account_id: str = Field(min_length=1, max_length=256)
    booking_date: date = Field(alias="bookingDate")
    value_date: date = Field(alias="valueDate")
    amount: str = Field(min_length=1, max_length=128)
    currency: str = Field(min_length=3, max_length=12)
    reference: str = Field(default="", max_length=512)

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: str) -> str:
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("amount must be exact Decimal text") from exc
        if not parsed.is_finite():
            raise ValueError("amount must be finite")
        return value

    @field_validator("value_date")
    @classmethod
    def validate_value_date(cls, value: date, info: object) -> date:
        booking = getattr(info, "data", {}).get("booking_date")
        if booking is not None and value < booking:
            raise ValueError("valueDate cannot precede bookingDate")
        return value


class PaymentStatementPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    records: tuple[PaymentStatementLine, ...] = Field(max_length=10_000)
    next_cursor: str | None = Field(default=None, min_length=1, max_length=4_096)

    @field_validator("records")
    @classmethod
    def validate_unique_ids(cls, value: tuple[PaymentStatementLine, ...]) -> tuple[PaymentStatementLine, ...]:
        if len({record.line_id for record in value}) != len(value):
            raise ValueError("records must have unique ids")
        return value


@dataclass(frozen=True)
class PaymentStatementRead:
    page: PaymentStatementPage
    request_digest: str
    response_digest: str
    attempts: int


def payment_statement_registration(
    *, credential_reference: str, endpoint: str = PAYMENT_STATEMENT_ENDPOINT
) -> NetworkConnectorRegistration:
    if endpoint != PAYMENT_STATEMENT_ENDPOINT:
        raise ConnectorNetworkError("payment_statement_endpoint_not_allowlisted")
    return NetworkConnectorRegistration(
        registration_schema="network-connector-registration-v1",
        manifest=PAYMENT_STATEMENT_MANIFEST,
        endpoint=endpoint,
        credential_reference=credential_reference,
    )


@dataclass(frozen=True)
class ReferencePaymentStatementConnector:
    executor: NetworkConnectorExecutor
    registration: NetworkConnectorRegistration

    def read_page(self, *, idempotency_key: str, cursor: str | None = None) -> PaymentStatementRead:
        result: ConnectorReadResult = self.executor.read(
            self.registration, idempotency_key=idempotency_key, cursor=cursor
        )
        try:
            page = PaymentStatementPage.model_validate_json(result.response_body)
        except (ValidationError, ValueError) as exc:
            raise ConnectorNetworkError("payment_statement_response_schema_invalid") from exc
        canonical_records = tuple(
            sorted(
                (record.model_dump(mode="json", by_alias=True) for record in page.records),
                key=lambda item: str(item["id"]),
            )
        )
        canonical_body = json.dumps(
            {"records": canonical_records, "next_cursor": page.next_cursor},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return PaymentStatementRead(
            page=page,
            request_digest=result.request_digest,
            response_digest=hashlib.sha256(canonical_body).hexdigest(),
            attempts=result.attempts,
        )
