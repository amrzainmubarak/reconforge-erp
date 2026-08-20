"""Concrete PostgreSQL read-only source for the named database profiles.

The adapter deliberately exposes views, not arbitrary SQL.  A deployment must
publish the two versioned views named by :data:`_QUERY_BY_PROFILE`; the
credential is resolved at call time and is never part of a registration digest
or an error message.  This is a source-reader contract, not ERP or bank
provider interoperability.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from types import ModuleType
from typing import cast
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reconforge.connectors.database_reference import (
    DatabaseQueryProfile,
    DatabaseRead,
    DatabaseRecordRow,
    DatabaseTransport,
)
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
from reconforge.io.writers import canonical_decimal_text

POSTGRES_DATABASE_ENDPOINT = "postgresql://db.example.test/reconforge"
_TENANT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_POSTGRES_SCHEMES = {"postgresql", "postgres"}

POSTGRES_DATABASE_MANIFEST = ConnectorManifest(
    schema_version="connector-manifest-v1",
    connector_id="reference-postgres-readonly",
    display_name="Reference PostgreSQL read-only source",
    version="1.0.0",
    kind=ConnectorKind.DATABASE_SOURCE,
    capabilities=frozenset({ConnectorCapability.READ}),
    authentication=AuthenticationMethod.SECRET_REFERENCE,
    network_required=True,
    data_classification=DataClassification.RESTRICTED,
    rate_limit_per_minute=120,
    incremental_cursor=True,
    idempotent_reads=True,
    retry_policy=RetryPolicy(maximum_attempts=1, initial_delay_seconds=0, maximum_delay_seconds=0),
    schema_versions=("reference-database-row-v1", "postgres-named-query-v1"),
    synthetic_sandbox=False,
    threat_model=("sql-injection", "tenant-crossing", "read-only-bypass", "response-amplification"),
    secret_handling="Resolve PostgreSQL DSN at runtime; never persist, log, or return it.",  # nosec B106
    egress_destinations=(POSTGRES_DATABASE_ENDPOINT,),
    support_level=SupportLevel.EXPERIMENTAL,
)


class PostgresDatabaseConnectorRegistration(BaseModel):
    """Credential-free runtime registration for one exact PostgreSQL endpoint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    registration_schema: str = Field(pattern=r"^postgres-database-registration-v1$")
    manifest: ConnectorManifest
    endpoint: str = Field(min_length=1, max_length=2_048)
    credential_reference: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,255}$")
    tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    query_profile: DatabaseQueryProfile
    maximum_rows: int = Field(default=1_000, ge=1, le=100_000)
    maximum_cell_characters: int = Field(default=16_384, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def validate_boundary(self) -> PostgresDatabaseConnectorRegistration:
        parsed = urlsplit(self.endpoint)
        if self.manifest.kind is not ConnectorKind.DATABASE_SOURCE or not self.manifest.network_required:
            raise ValueError("PostgreSQL registration requires a database-source manifest")
        if self.manifest.authentication is not AuthenticationMethod.SECRET_REFERENCE:
            raise ValueError("PostgreSQL registration requires secret-reference authentication")
        if parsed.scheme not in _POSTGRES_SCHEMES or not parsed.hostname:
            raise ValueError("PostgreSQL endpoint must use a credential-free postgresql URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.path.strip("/"):
            raise ValueError("PostgreSQL endpoint must not contain credentials, query, or fragment")
        if self.endpoint not in self.manifest.egress_destinations:
            raise ValueError("endpoint must exactly match one declared PostgreSQL egress destination")
        return self

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json", exclude_none=False), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


def postgres_database_registration(
    *,
    endpoint: str,
    credential_reference: str,
    tenant_id: str,
    query_profile: DatabaseQueryProfile = DatabaseQueryProfile.STATEMENT_LINES_V1,
) -> PostgresDatabaseConnectorRegistration:
    """Build a registration whose manifest pins the caller's exact endpoint."""

    endpoint_manifest = POSTGRES_DATABASE_MANIFEST.model_copy(update={"egress_destinations": (endpoint,)})
    return PostgresDatabaseConnectorRegistration(
        registration_schema="postgres-database-registration-v1",
        manifest=endpoint_manifest,
        endpoint=endpoint,
        credential_reference=credential_reference,
        tenant_id=tenant_id,
        query_profile=query_profile,
    )


_QUERY_BY_PROFILE: dict[DatabaseQueryProfile, str] = {
    DatabaseQueryProfile.STATEMENT_LINES_V1: """
        SELECT tenant_id, record_id, amount, currency, business_date, reference
        FROM reconforge_connector_statement_lines
        WHERE tenant_id = %s AND (%s::text IS NULL OR record_id > %s::text)
        ORDER BY record_id ASC, business_date ASC, reference ASC
        LIMIT %s
    """,
    DatabaseQueryProfile.TRIAL_BALANCE_V1: """
        SELECT tenant_id, record_id, amount, currency, business_date, reference
        FROM reconforge_connector_trial_balance
        WHERE tenant_id = %s AND (%s::text IS NULL OR record_id > %s::text)
        ORDER BY record_id ASC, business_date ASC, reference ASC
        LIMIT %s
    """,
}


def _load_psycopg() -> ModuleType:
    try:
        return importlib.import_module("psycopg")
    except ImportError as exc:
        raise ConnectorNetworkError("postgres_driver_unavailable") from exc


def _canonical_amount(value: object) -> str:
    if isinstance(value, float):
        raise ConnectorNetworkError("postgres_amount_type_invalid")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ConnectorNetworkError("postgres_amount_invalid") from exc
    if not amount.is_finite():
        raise ConnectorNetworkError("postgres_amount_nonfinite")
    return canonical_decimal_text(amount)


def _validate_endpoint_and_dsn(endpoint: str, credential: bytes) -> str:
    try:
        credential_text = credential.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ConnectorNetworkError("postgres_credential_invalid") from exc
    if not 16 <= len(credential) <= 4_096 or any(ord(character) < 33 or ord(character) > 126 for character in credential_text):
        raise ConnectorNetworkError("postgres_credential_invalid")
    endpoint_parts = urlsplit(endpoint)
    dsn_parts = urlsplit(credential_text)
    if dsn_parts.scheme not in _POSTGRES_SCHEMES or not dsn_parts.hostname or not dsn_parts.path.strip("/"):
        raise ConnectorNetworkError("postgres_credential_invalid")
    if dsn_parts.fragment:
        raise ConnectorNetworkError("postgres_credential_invalid")
    try:
        endpoint_port = endpoint_parts.port or 5432
        dsn_port = dsn_parts.port or 5432
    except ValueError as exc:
        raise ConnectorNetworkError("postgres_endpoint_invalid") from exc
    if (
        (endpoint_parts.hostname or "").lower() != (dsn_parts.hostname or "").lower()
        or endpoint_port != dsn_port
        or endpoint_parts.path.rstrip("/") != dsn_parts.path.rstrip("/")
    ):
        raise ConnectorNetworkError("postgres_endpoint_credential_mismatch")
    return credential_text


def _row_from_values(values: object) -> DatabaseRecordRow:
    try:
        row: tuple[object, ...] = tuple(values)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ConnectorNetworkError("postgres_row_invalid") from exc
    if len(row) != 6:
        raise ConnectorNetworkError("postgres_row_shape_invalid")
    raw_tenant, raw_record_id, raw_amount, raw_currency, raw_date, raw_reference = row
    if isinstance(raw_date, date):
        business_date = raw_date
    else:
        try:
            business_date = date.fromisoformat(str(raw_date))
        except ValueError as exc:
            raise ConnectorNetworkError("postgres_business_date_invalid") from exc
    if not all(isinstance(value, str) for value in (raw_tenant, raw_record_id, raw_currency, raw_reference)):
        raise ConnectorNetworkError("postgres_row_text_invalid")
    tenant_id = cast(str, raw_tenant)
    record_id = cast(str, raw_record_id)
    currency = cast(str, raw_currency)
    reference = cast(str, raw_reference)
    return DatabaseRecordRow(
        tenant_id=tenant_id,
        record_id=record_id,
        amount=_canonical_amount(raw_amount),
        currency=currency,
        business_date=business_date,
        reference=reference,
    )


@dataclass(frozen=True)
class PostgresNamedQueryTransport(DatabaseTransport):
    """Execute only the two fixed, parameterized PostgreSQL query profiles."""

    connect_timeout_seconds: int = 10
    statement_timeout_ms: int = 30_000

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
    ) -> tuple[DatabaseRecordRow, ...]:
        if not _TENANT_ID_PATTERN.fullmatch(tenant_id):
            raise ConnectorNetworkError("postgres_tenant_invalid")
        if cursor is not None and (not cursor or len(cursor.encode("utf-8")) > MAX_CURSOR_BYTES):
            raise ConnectorNetworkError("postgres_cursor_invalid")
        if maximum_rows < 1 or maximum_rows > 100_000:
            raise ConnectorNetworkError("postgres_row_limit_invalid")
        if maximum_cell_characters < 1 or maximum_cell_characters > 1_000_000:
            raise ConnectorNetworkError("postgres_cell_limit_invalid")
        credential_text = _validate_endpoint_and_dsn(endpoint, credential)
        sql = _QUERY_BY_PROFILE.get(query_profile)
        if sql is None:
            raise ConnectorNetworkError("postgres_query_profile_invalid")
        connection = None
        try:
            psycopg = _load_psycopg()
            connection = psycopg.connect(
                credential_text,
                connect_timeout=self.connect_timeout_seconds,
                options=f"-c statement_timeout={self.statement_timeout_ms}",
            )
            with connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                connection.execute("SELECT set_config('reconforge.connector_tenant', %s, true)", (tenant_id,))
                result = connection.execute(sql, (tenant_id, cursor, cursor, maximum_rows))
                rows = tuple(_row_from_values(row) for row in result.fetchall())
            for row in rows:
                for value in row.model_dump(mode="json").values():
                    if isinstance(value, str) and len(value) > maximum_cell_characters:
                        raise ConnectorNetworkError("postgres_cell_too_large")
            return rows
        except ConnectorNetworkError:
            raise
        except Exception as exc:  # provider details must not cross the connector boundary
            raise ConnectorNetworkError("postgres_database_transport_failed") from exc
        finally:
            if connection is not None:
                connection.close()


@dataclass(frozen=True)
class PostgresDatabaseConnector:
    transport: DatabaseTransport
    secret_resolver: ConnectorSecretResolver
    registration: PostgresDatabaseConnectorRegistration

    def read_rows(self, *, idempotency_key: str, cursor: str | None = None) -> DatabaseRead:
        from reconforge.connectors.database_reference import ReferenceDatabaseConnector

        if not idempotency_key or len(idempotency_key.encode("utf-8")) > MAX_IDEMPOTENCY_KEY_BYTES:
            raise ConnectorNetworkError("postgres_idempotency_key_invalid")
        return ReferenceDatabaseConnector(self.transport, self.secret_resolver, self.registration).read_rows(
            idempotency_key=idempotency_key,
            cursor=cursor,
        )
