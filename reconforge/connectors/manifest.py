"""Closed, deterministic connector capability declarations.

The manifest is data, never executable plugin code. Network and write capabilities
are denied unless explicitly declared; runtime authorization remains a separate gate.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$")


class ConnectorKind(StrEnum):
    LOCAL_FILE = "local_file"
    EXPORT_PROFILE = "export_profile"
    NETWORK_SOURCE = "network_source"
    DATABASE_SOURCE = "database_source"


class ConnectorCapability(StrEnum):
    READ = "read"
    WRITE = "write"


class AuthenticationMethod(StrEnum):
    NONE = "none"
    SECRET_REFERENCE = "secret_reference"  # nosec B105
    OAUTH2 = "oauth2"
    MTLS = "mtls"


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class SupportLevel(StrEnum):
    EXPERIMENTAL = "experimental"
    COMMUNITY = "community"
    MAINTAINED = "maintained"


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    maximum_attempts: int = Field(ge=1, le=10)
    initial_delay_seconds: int = Field(ge=0, le=300)
    maximum_delay_seconds: int = Field(ge=0, le=3600)

    @model_validator(mode="after")
    def validate_delay_order(self) -> Self:
        if self.maximum_delay_seconds < self.initial_delay_seconds:
            raise ValueError("maximum_delay_seconds cannot be less than initial_delay_seconds")
        return self


class ConnectorManifest(BaseModel):
    """Versioned security and operations contract for one connector implementation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(pattern=r"^connector-manifest-v1$")
    connector_id: str
    display_name: str = Field(min_length=1, max_length=100)
    version: str
    kind: ConnectorKind
    capabilities: frozenset[ConnectorCapability]
    authentication: AuthenticationMethod
    network_required: bool
    data_classification: DataClassification
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=1_000_000)
    incremental_cursor: bool
    idempotent_reads: bool
    retry_policy: RetryPolicy
    schema_versions: tuple[str, ...] = Field(min_length=1, max_length=32)
    synthetic_sandbox: bool
    threat_model: tuple[str, ...] = Field(min_length=1, max_length=32)
    secret_handling: str = Field(min_length=1, max_length=500)
    egress_destinations: tuple[str, ...] = Field(max_length=32)
    support_level: SupportLevel

    @model_validator(mode="after")
    def validate_security_boundary(self) -> Self:
        if not _ID_PATTERN.fullmatch(self.connector_id):
            raise ValueError("connector_id must be a lowercase stable identifier")
        if not _SEMVER_PATTERN.fullmatch(self.version):
            raise ValueError("version must be semantic version text")
        if ConnectorCapability.READ not in self.capabilities:
            raise ValueError("every connector must declare read capability")
        if ConnectorCapability.WRITE in self.capabilities:
            raise ValueError("write capability is not supported by connector-manifest-v1")
        if self.network_required != bool(self.egress_destinations):
            raise ValueError("network_required must exactly match declared egress destinations")
        if not self.network_required and self.authentication is not AuthenticationMethod.NONE:
            raise ValueError("local connectors cannot request authentication")
        if self.network_required and self.authentication is AuthenticationMethod.NONE:
            raise ValueError("network connectors must declare an authentication method")
        if self.network_required and self.rate_limit_per_minute is None:
            raise ValueError("network connectors must declare a rate limit")
        if not self.network_required and self.rate_limit_per_minute is not None:
            raise ValueError("local connectors cannot declare a network rate limit")
        if any(not value.strip() for value in (*self.schema_versions, *self.threat_model)):
            raise ValueError("schema versions and threat-model entries cannot be blank")
        if tuple(sorted(set(self.egress_destinations))) != self.egress_destinations:
            raise ValueError("egress destinations must be unique and canonically sorted")
        for destination in self.egress_destinations:
            parsed = urlsplit(destination)
            allowed_schemes = {"https", "sftp"}
            if self.kind is ConnectorKind.DATABASE_SOURCE:
                allowed_schemes = {"postgresql", "postgres"}
            if (
                parsed.scheme not in allowed_schemes
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
                or parsed.query
            ):
                raise ValueError("egress destinations must be exact HTTPS URLs or exact SFTP URLs without credentials, query, or fragment")
            try:
                port = parsed.port
            except ValueError as exc:
                raise ValueError("egress destination port is invalid") from exc
            if port is not None and not 1 <= port <= 65_535:
                raise ValueError("egress destination port is invalid")
        return self

    def canonical_bytes(self) -> bytes:
        payload = self.model_dump(mode="json", exclude_none=False)
        return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()
