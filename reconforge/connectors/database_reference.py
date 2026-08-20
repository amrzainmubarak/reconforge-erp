"""Synthetic tenant-scoped database reference connector.

Only named query profiles may cross this boundary.  The transport is injected
so tests can prove tenant, schema, cursor, and digest behavior without a live
database or accepting arbitrary SQL.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    MAX_CURSOR_BYTES,
    MAX_IDEMPOTENCY_KEY_BYTES,
    ConnectorNetworkError,
    ConnectorSecretResolver,
)

DATABASE_REFERENCE_ENDPOINT = "https://db-gateway.example.test/reconforge"


class DatabaseQueryProfile(StrEnum):
    STATEMENT_LINES_V1 = "statement_lines_v1"
    TRIAL_BALANCE_V1 = "trial_balance_v1"


DATABASE_REFERENCE_MANIFEST = ConnectorManifest(
    schema_version="connector-manifest-v1",
    connector_id="reference-database-readonly",
    display_name="Reference database read-only source",
    version="1.0.0",
    kind=ConnectorKind.NETWORK_SOURCE,
    capabilities=frozenset({ConnectorCapability.READ}),
    authentication=AuthenticationMethod.SECRET_REFERENCE,
    network_required=True,
    data_classification=DataClassification.RESTRICTED,
    rate_limit_per_minute=120,
    incremental_cursor=True,
    idempotent_reads=True,
    retry_policy=RetryPolicy(maximum_attempts=3, initial_delay_seconds=1, maximum_delay_seconds=8),
    schema_versions=("reference-database-row-v1",),
    synthetic_sandbox=True,
    threat_model=("sql-injection", "tenant-crossing", "schema-confusion", "response-amplification"),
    secret_handling="Resolve database credential_reference at runtime; never persist, log, or return it.",  # nosec B106
    egress_destinations=(DATABASE_REFERENCE_ENDPOINT,),
    support_level=SupportLevel.COMMUNITY,
)


class DatabaseConnectorRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    registration_schema: str = Field(pattern=r"^database-connector-registration-v1$")
    manifest: ConnectorManifest
    endpoint: str = Field(min_length=1, max_length=2_048)
    credential_reference: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,255}$")
    tenant_id: str = Field(min_length=1, max_length=256)
    query_profile: DatabaseQueryProfile
    maximum_rows: int = Field(default=1_000, ge=1, le=100_000)
    maximum_cell_characters: int = Field(default=16_384, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def validate_boundary(self) -> DatabaseConnectorRegistration:
        parsed = urlsplit(self.endpoint)
        if self.manifest.kind is not ConnectorKind.NETWORK_SOURCE or not self.manifest.network_required:
            raise ValueError("database registration requires a network-source manifest")
        if self.manifest.authentication is not AuthenticationMethod.SECRET_REFERENCE:
            raise ValueError("database registration requires secret-reference authentication")
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("database endpoint must be a credential-free exact HTTPS URL")
        if self.endpoint not in self.manifest.egress_destinations:
            raise ValueError("endpoint must exactly match one declared database egress destination")
        return self

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json", exclude_none=False), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


class DatabaseRecordRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1, max_length=256)
    record_id: str = Field(min_length=1, max_length=256)
    amount: str = Field(min_length=1, max_length=128)
    currency: str = Field(min_length=3, max_length=12)
    business_date: date
    reference: str = Field(default="", max_length=512)

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: str) -> str:
        try:
            amount = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("amount must be exact Decimal text") from exc
        if not amount.is_finite():
            raise ValueError("amount must be finite")
        return value


class DatabaseTransport(Protocol):
    def fetch_named(
        self,
        endpoint: str,
        *,
        tenant_id: str,
        query_profile: DatabaseQueryProfile,
        cursor: str | None,
        credential: bytes,
        maximum_rows: int,
        maximum_cell_characters: int,
    ) -> tuple[DatabaseRecordRow, ...]: ...


class DatabaseRegistration(Protocol):
    """Minimal immutable registration surface shared by database adapters."""

    manifest: ConnectorManifest
    endpoint: str
    credential_reference: str
    tenant_id: str
    query_profile: DatabaseQueryProfile
    maximum_rows: int
    maximum_cell_characters: int

    @property
    def digest(self) -> str: ...


@dataclass(frozen=True)
class DatabaseRead:
    rows: tuple[DatabaseRecordRow, ...]
    query_profile: DatabaseQueryProfile
    request_digest: str
    response_digest: str
    next_cursor: str | None


def database_reference_registration(
    *, credential_reference: str, tenant_id: str, query_profile: DatabaseQueryProfile = DatabaseQueryProfile.STATEMENT_LINES_V1
) -> DatabaseConnectorRegistration:
    return DatabaseConnectorRegistration(
        registration_schema="database-connector-registration-v1",
        manifest=DATABASE_REFERENCE_MANIFEST,
        endpoint=DATABASE_REFERENCE_ENDPOINT,
        credential_reference=credential_reference,
        tenant_id=tenant_id,
        query_profile=query_profile,
    )


@dataclass(frozen=True)
class ReferenceDatabaseConnector:
    transport: DatabaseTransport
    secret_resolver: ConnectorSecretResolver
    registration: DatabaseRegistration

    def read_rows(self, *, idempotency_key: str, cursor: str | None = None) -> DatabaseRead:
        key_bytes = idempotency_key.encode("utf-8")
        if not key_bytes or len(key_bytes) > MAX_IDEMPOTENCY_KEY_BYTES or any(ord(c) < 33 for c in idempotency_key):
            raise ConnectorNetworkError("database_idempotency_key_invalid")
        if cursor is not None and (not cursor or len(cursor.encode("utf-8")) > MAX_CURSOR_BYTES):
            raise ConnectorNetworkError("database_cursor_invalid")
        credential = self.secret_resolver.resolve(self.registration.credential_reference)
        if not 16 <= len(credential) <= 4_096:
            raise ConnectorNetworkError("database_credential_invalid")
        request_digest = hashlib.sha256(
            json.dumps(
                {
                    "connector_id": self.registration.manifest.connector_id,
                    "connector_version": self.registration.manifest.version,
                    "cursor": cursor,
                    "endpoint": self.registration.endpoint,
                    "idempotency_key": idempotency_key,
                    "manifest_digest": self.registration.digest,
                    "query_profile": self.registration.query_profile.value,
                    "tenant_id": self.registration.tenant_id,
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        try:
            rows = self.transport.fetch_named(
                self.registration.endpoint,
                tenant_id=self.registration.tenant_id,
                query_profile=self.registration.query_profile,
                cursor=cursor,
                credential=credential,
                maximum_rows=self.registration.maximum_rows,
                maximum_cell_characters=self.registration.maximum_cell_characters,
            )
        except ConnectorNetworkError:
            raise
        except Exception as exc:  # provider details must not cross the connector boundary
            raise ConnectorNetworkError("database_transport_failed") from exc
        for row in rows:
            if row.tenant_id != self.registration.tenant_id:
                raise ConnectorNetworkError("database_tenant_scope_mismatch")
            for value in row.model_dump(mode="json").values():
                if isinstance(value, str) and len(value) > self.registration.maximum_cell_characters:
                    raise ConnectorNetworkError("database_cell_too_large")
        ordered = tuple(sorted(rows, key=lambda row: (row.record_id, row.business_date.isoformat(), row.reference)))
        if len({row.record_id for row in ordered}) != len(ordered):
            raise ConnectorNetworkError("database_duplicate_record_id")
        if cursor is not None:
            ordered = tuple(row for row in ordered if row.record_id > cursor)
        selected = ordered[: self.registration.maximum_rows]
        response_digest = hashlib.sha256(
            json.dumps(
                [row.model_dump(mode="json") for row in selected], ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode("ascii")
        ).hexdigest()
        next_cursor = selected[-1].record_id if len(selected) == self.registration.maximum_rows else None
        return DatabaseRead(selected, self.registration.query_profile, request_digest, response_digest, next_cursor)
