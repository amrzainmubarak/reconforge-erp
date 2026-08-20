"""Open, read-only REST reference connector over the governed network runtime."""

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

REFERENCE_REST_MANIFEST = ConnectorManifest(
    schema_version="connector-manifest-v1",
    connector_id="reference-rest-readonly",
    display_name="Reference REST read-only source",
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
    schema_versions=("reference-rest-record-v1",),
    synthetic_sandbox=True,
    threat_model=("ssrf", "credential-disclosure", "schema-confusion", "retry-amplification"),
    secret_handling="Resolve credential_reference at runtime; never persist, log, or return the secret.",  # nosec B106
    egress_destinations=("https://api.example.test/v1/records",),
    support_level=SupportLevel.COMMUNITY,
)


class ReferenceRestRecord(BaseModel):
    """Strict canonical record shape for the reference provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record_id: str = Field(alias="id", min_length=1, max_length=256)
    amount: str = Field(min_length=1, max_length=128)
    currency: str = Field(min_length=3, max_length=12)
    business_date: date = Field(alias="date")
    partition_key: str = Field(alias="partition", min_length=1, max_length=256)
    reference: str = Field(default="", max_length=512)

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: str) -> str:
        try:
            parsed = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("amount must be an exact Decimal text value") from exc
        if not parsed.is_finite():
            raise ValueError("amount must be finite")
        return value


class ReferenceRestPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    records: tuple[ReferenceRestRecord, ...] = Field(max_length=10_000)
    next_cursor: str | None = Field(default=None, min_length=1, max_length=4_096)

    @field_validator("records")
    @classmethod
    def validate_unique_ids(cls, value: tuple[ReferenceRestRecord, ...]) -> tuple[ReferenceRestRecord, ...]:
        if len({record.record_id for record in value}) != len(value):
            raise ValueError("records must have unique ids")
        return value


@dataclass(frozen=True)
class ReferenceRestRead:
    page: ReferenceRestPage
    request_digest: str
    response_digest: str
    attempts: int


def reference_rest_registration(
    *, credential_reference: str, endpoint: str = "https://api.example.test/v1/records"
) -> NetworkConnectorRegistration:
    """Build a registration constrained to the reference manifest's egress allowlist."""
    if endpoint != REFERENCE_REST_MANIFEST.egress_destinations[0]:
        raise ConnectorNetworkError("reference_rest_endpoint_not_allowlisted")
    return NetworkConnectorRegistration(
        registration_schema="network-connector-registration-v1",
        manifest=REFERENCE_REST_MANIFEST,
        endpoint=endpoint,
        credential_reference=credential_reference,
    )


@dataclass(frozen=True)
class ReferenceRestConnector:
    executor: NetworkConnectorExecutor
    registration: NetworkConnectorRegistration

    def read_page(self, *, idempotency_key: str, cursor: str | None = None) -> ReferenceRestRead:
        result: ConnectorReadResult = self.executor.read(
            self.registration,
            idempotency_key=idempotency_key,
            cursor=cursor,
        )
        try:
            page = ReferenceRestPage.model_validate_json(result.response_body)
        except (ValidationError, ValueError) as exc:
            raise ConnectorNetworkError("reference_rest_response_schema_invalid") from exc
        canonical_records = tuple(sorted((record.model_dump(mode="json", by_alias=True) for record in page.records), key=lambda item: str(item["id"])))
        canonical_body = json.dumps(
            {"records": canonical_records, "next_cursor": page.next_cursor},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        response_digest = hashlib.sha256(canonical_body).hexdigest()
        return ReferenceRestRead(page=page, request_digest=result.request_digest, response_digest=response_digest, attempts=result.attempts)
