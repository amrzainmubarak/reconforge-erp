"""Provider-neutral, read-only ERP ledger-line reference connector.

The adapter is deliberately a data-only reference integration.  It exercises
the same governed HTTPS runtime as other network connectors while keeping ERP
provider credentials, endpoints, and write-back outside the package.
"""

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

ERP_REFERENCE_ENDPOINT = "https://erp.example.test/v1/ledger-lines"
ERP_REFERENCE_MANIFEST = ConnectorManifest(
    schema_version="connector-manifest-v1",
    connector_id="reference-erp-readonly",
    display_name="Reference ERP ledger-line read-only source",
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
    schema_versions=("reference-erp-ledger-page-v1",),
    synthetic_sandbox=True,
    threat_model=("ssrf", "credential-disclosure", "schema-confusion", "cross-entity-leakage"),
    secret_handling="Resolve credential_reference at runtime; never persist, log, or return the secret.",  # nosec B106
    egress_destinations=(ERP_REFERENCE_ENDPOINT,),
    support_level=SupportLevel.COMMUNITY,
)


class ReferenceErpLedgerLine(BaseModel):
    """Closed ERP ledger-line shape with exact financial text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    line_id: str = Field(alias="id", min_length=1, max_length=256)
    entity_code: str = Field(min_length=1, max_length=64)
    account_code: str = Field(min_length=1, max_length=128)
    amount: str = Field(min_length=1, max_length=128)
    currency: str = Field(min_length=3, max_length=12)
    posting_date: date = Field(alias="date")
    document_reference: str = Field(default="", alias="document", max_length=512)

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


class ReferenceErpLedgerPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lines: tuple[ReferenceErpLedgerLine, ...] = Field(max_length=10_000)
    next_cursor: str | None = Field(default=None, min_length=1, max_length=4_096)

    @field_validator("lines")
    @classmethod
    def validate_unique_ids(cls, value: tuple[ReferenceErpLedgerLine, ...]) -> tuple[ReferenceErpLedgerLine, ...]:
        if len({line.line_id for line in value}) != len(value):
            raise ValueError("lines must have unique ids")
        if len({line.entity_code for line in value}) > 1:
            raise ValueError("one page must not mix entity scopes")
        return value


@dataclass(frozen=True)
class ReferenceErpRead:
    page: ReferenceErpLedgerPage
    request_digest: str
    response_digest: str
    attempts: int


def erp_reference_registration(
    *, credential_reference: str, endpoint: str = ERP_REFERENCE_ENDPOINT
) -> NetworkConnectorRegistration:
    """Build a registration constrained to the reference ERP egress allowlist."""

    if endpoint != ERP_REFERENCE_ENDPOINT:
        raise ConnectorNetworkError("reference_erp_endpoint_not_allowlisted")
    return NetworkConnectorRegistration(
        registration_schema="network-connector-registration-v1",
        manifest=ERP_REFERENCE_MANIFEST,
        endpoint=endpoint,
        credential_reference=credential_reference,
    )


@dataclass(frozen=True)
class ReferenceErpConnector:
    executor: NetworkConnectorExecutor
    registration: NetworkConnectorRegistration

    def read_page(
        self,
        *,
        idempotency_key: str,
        cursor: str | None = None,
        expected_entity_code: str | None = None,
    ) -> ReferenceErpRead:
        if expected_entity_code is not None:
            expected_entity_code = expected_entity_code.strip()
            if not expected_entity_code or len(expected_entity_code) > 64:
                raise ConnectorNetworkError("reference_erp_entity_scope_invalid")
        result: ConnectorReadResult = self.executor.read(
            self.registration,
            idempotency_key=idempotency_key,
            cursor=cursor,
        )
        try:
            page = ReferenceErpLedgerPage.model_validate_json(result.response_body)
        except (ValidationError, ValueError) as exc:
            raise ConnectorNetworkError("reference_erp_response_schema_invalid") from exc
        if expected_entity_code is not None and any(
            line.entity_code != expected_entity_code for line in page.lines
        ):
            raise ConnectorNetworkError("reference_erp_entity_scope_mismatch")
        canonical_lines = tuple(
            sorted(
                (line.model_dump(mode="json", by_alias=True) for line in page.lines),
                key=lambda item: str(item["id"]),
            )
        )
        canonical_body = json.dumps(
            {"lines": canonical_lines, "next_cursor": page.next_cursor},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        response_digest = hashlib.sha256(canonical_body).hexdigest()
        return ReferenceErpRead(
            page=page,
            request_digest=result.request_digest,
            response_digest=response_digest,
            attempts=result.attempts,
        )
