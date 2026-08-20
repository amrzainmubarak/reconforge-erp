"""Read-only World Bank public REST reference connector.

The endpoint and query parameters are fixed in the manifest. The connector is
useful as an open-data interoperability reference, not as an ERP or banking
provider integration.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

WORLD_BANK_PUBLIC_ORIGIN = "https://datacatalogapi.worldbank.org"
WORLD_BANK_PUBLIC_PATH = "/dexapps/fone/api/apiservice"
WORLD_BANK_PUBLIC_DATASET = "DS01556"
WORLD_BANK_PUBLIC_RESOURCE = "RS00963"
WORLD_BANK_PUBLIC_PAGE_SIZE = 1_000
WORLD_BANK_PUBLIC_SKIPS = (0, 1_000, 2_000)


def world_bank_public_endpoint(skip: int) -> str:
    if skip not in WORLD_BANK_PUBLIC_SKIPS:
        raise ValueError("World Bank public connector only supports the declared page offsets")
    query = urlencode(
        {
            "datasetId": WORLD_BANK_PUBLIC_DATASET,
            "resourceId": WORLD_BANK_PUBLIC_RESOURCE,
            "top": WORLD_BANK_PUBLIC_PAGE_SIZE,
            "skip": skip,
            "type": "json",
        }
    )
    return f"{WORLD_BANK_PUBLIC_ORIGIN}{WORLD_BANK_PUBLIC_PATH}?{query}"


WORLD_BANK_PUBLIC_MANIFEST = ConnectorManifest(
    schema_version="connector-manifest-v1",
    connector_id="world-bank-public-readonly",
    display_name="World Bank public REST reference",
    version="1.0.0",
    kind=ConnectorKind.NETWORK_SOURCE,
    capabilities=frozenset({ConnectorCapability.READ}),
    authentication=AuthenticationMethod.NONE,
    network_required=True,
    data_classification=DataClassification.PUBLIC,
    rate_limit_per_minute=30,
    incremental_cursor=False,
    idempotent_reads=True,
    retry_policy=RetryPolicy(maximum_attempts=3, initial_delay_seconds=1, maximum_delay_seconds=8),
    schema_versions=("world-bank-public-record-v1",),
    synthetic_sandbox=True,
    threat_model=("ssrf", "schema-confusion", "response-amplification", "source-drift"),
    secret_handling="No secret is required; the exact public endpoint is read only.",  # nosec B106
    egress_destinations=tuple(world_bank_public_endpoint(skip) for skip in WORLD_BANK_PUBLIC_SKIPS),
    support_level=SupportLevel.COMMUNITY,
)


class WorldBankPublicRecord(BaseModel):
    """The closed row contract used by the pinned dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: str = Field(min_length=1, max_length=120)
    country: str = Field(min_length=1, max_length=160)
    development_policy: Decimal
    investment_lending: Decimal
    organization: str = Field(min_length=1, max_length=80)
    private_sector_window: Decimal
    program_for_results: Decimal
    region: str = Field(min_length=1, max_length=160)
    time_period: str = Field(min_length=1, max_length=40)
    total: Decimal

    @field_validator(
        "development_policy",
        "investment_lending",
        "private_sector_window",
        "program_for_results",
        "total",
    )
    @classmethod
    def validate_finite_amount(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("World Bank numeric fields must be finite")
        return value


class WorldBankPublicPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int = Field(ge=1, le=100_000)
    data: tuple[WorldBankPublicRecord, ...] = Field(min_length=1, max_length=WORLD_BANK_PUBLIC_PAGE_SIZE)


@dataclass(frozen=True)
class WorldBankPublicRead:
    page: WorldBankPublicPage
    request_digest: str
    response_digest: str
    attempts: int


def world_bank_public_registration(*, skip: int) -> NetworkConnectorRegistration:
    endpoint = world_bank_public_endpoint(skip)
    return NetworkConnectorRegistration(
        registration_schema="network-connector-registration-v1",
        manifest=WORLD_BANK_PUBLIC_MANIFEST,
        endpoint=endpoint,
    )


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"


def _canonical_record(record: WorldBankPublicRecord) -> dict[str, str]:
    values = record.model_dump()
    return {
        key: _decimal_text(value) if isinstance(value, Decimal) else str(value)
        for key, value in values.items()
    }


@dataclass(frozen=True)
class WorldBankPublicConnector:
    executor: NetworkConnectorExecutor
    registration: NetworkConnectorRegistration

    def read_page(self, *, idempotency_key: str) -> WorldBankPublicRead:
        if self.registration.manifest is not WORLD_BANK_PUBLIC_MANIFEST:
            raise ConnectorNetworkError("world_bank_public_manifest_mismatch")
        result: ConnectorReadResult = self.executor.read(
            self.registration,
            idempotency_key=idempotency_key,
        )
        try:
            payload: Any = json.loads(result.response_body, parse_float=Decimal, parse_int=int)
            page = WorldBankPublicPage.model_validate(payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ConnectorNetworkError("world_bank_public_response_schema_invalid") from exc
        canonical_records = tuple(sorted((_canonical_record(record) for record in page.data), key=lambda item: tuple(item.values())))
        canonical_body = json.dumps(
            {"count": page.count, "data": canonical_records},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return WorldBankPublicRead(
            page=page,
            request_digest=result.request_digest,
            response_digest=hashlib.sha256(canonical_body).hexdigest(),
            attempts=result.attempts,
        )
