"""Synthetic tenant-scoped object-storage reference connector.

The connector uses an injected transport so local tests can prove key,
tenant, checksum, cursor, and replay boundaries without requiring S3 or
cloud credentials.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

OBJECT_REFERENCE_ENDPOINT = "https://objects.example.test/reconforge"
OBJECT_REFERENCE_MANIFEST = ConnectorManifest(
    schema_version="connector-manifest-v1",
    connector_id="reference-object-storage-readonly",
    display_name="Reference object-storage read-only source",
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
    schema_versions=("reference-object-storage-object-v1",),
    synthetic_sandbox=True,
    threat_model=("tenant-crossing", "key-traversal", "checksum-confusion", "response-amplification"),
    secret_handling="Resolve object-storage credential_reference at runtime; never persist, log, or return it.",  # nosec B106
    egress_destinations=(OBJECT_REFERENCE_ENDPOINT,),
    support_level=SupportLevel.COMMUNITY,
)


class ObjectConnectorRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    registration_schema: str = Field(pattern=r"^object-storage-registration-v1$")
    manifest: ConnectorManifest
    endpoint: str = Field(min_length=1, max_length=2_048)
    credential_reference: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,255}$")
    tenant_id: str = Field(min_length=1, max_length=256)
    key_prefix: str = Field(default="incoming", min_length=1, max_length=512)
    maximum_objects: int = Field(default=100, ge=1, le=10_000)
    maximum_object_bytes: int = Field(default=16_777_216, ge=1, le=67_108_864)

    @model_validator(mode="after")
    def validate_boundary(self) -> ObjectConnectorRegistration:
        parsed = urlsplit(self.endpoint)
        if self.manifest.kind is not ConnectorKind.NETWORK_SOURCE or not self.manifest.network_required:
            raise ValueError("object registration requires a network-source manifest")
        if self.manifest.authentication is not AuthenticationMethod.SECRET_REFERENCE:
            raise ValueError("object registration requires secret-reference authentication")
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("object endpoint must be a credential-free exact HTTPS URL")
        if self.endpoint not in self.manifest.egress_destinations:
            raise ValueError("endpoint must exactly match one declared object-storage egress destination")
        if self.key_prefix.startswith("/") or any(part in {"", ".", ".."} for part in self.key_prefix.replace("\\", "/").split("/")):
            raise ValueError("object key_prefix must be relative and traversal-free")
        return self

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json", exclude_none=False), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ObjectRemoteEntry:
    key: str
    content: bytes
    sha256: str
    metadata: dict[str, str]


class ObjectStorageTransport(Protocol):
    def list_objects(
        self,
        endpoint: str,
        *,
        tenant_id: str,
        key_prefix: str,
        credential: bytes,
        maximum_objects: int,
        maximum_object_bytes: int,
    ) -> tuple[ObjectRemoteEntry, ...]: ...


@dataclass(frozen=True)
class ObjectRead:
    key: str
    content: bytes
    sha256: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class ObjectStorageRead:
    objects: tuple[ObjectRead, ...]
    request_digest: str
    response_digest: str
    next_cursor: str | None


def object_reference_registration(*, credential_reference: str, tenant_id: str) -> ObjectConnectorRegistration:
    return ObjectConnectorRegistration(
        registration_schema="object-storage-registration-v1",
        manifest=OBJECT_REFERENCE_MANIFEST,
        endpoint=OBJECT_REFERENCE_ENDPOINT,
        credential_reference=credential_reference,
        tenant_id=tenant_id,
    )


@dataclass(frozen=True)
class ReferenceObjectStorageConnector:
    transport: ObjectStorageTransport
    secret_resolver: ConnectorSecretResolver
    registration: ObjectConnectorRegistration

    def read_objects(self, *, idempotency_key: str, cursor: str | None = None) -> ObjectStorageRead:
        key_bytes = idempotency_key.encode("utf-8")
        if not key_bytes or len(key_bytes) > MAX_IDEMPOTENCY_KEY_BYTES or any(ord(c) < 33 for c in idempotency_key):
            raise ConnectorNetworkError("object_idempotency_key_invalid")
        if cursor is not None and (not cursor or len(cursor.encode("utf-8")) > MAX_CURSOR_BYTES):
            raise ConnectorNetworkError("object_cursor_invalid")
        credential = self.secret_resolver.resolve(self.registration.credential_reference)
        if not 16 <= len(credential) <= 4_096:
            raise ConnectorNetworkError("object_credential_invalid")
        request_digest = hashlib.sha256(
            json.dumps(
                {
                    "connector_id": self.registration.manifest.connector_id,
                    "connector_version": self.registration.manifest.version,
                    "cursor": cursor,
                    "endpoint": self.registration.endpoint,
                    "idempotency_key": idempotency_key,
                    "key_prefix": self.registration.key_prefix,
                    "manifest_digest": self.registration.digest,
                    "tenant_id": self.registration.tenant_id,
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        try:
            entries = self.transport.list_objects(
                self.registration.endpoint,
                tenant_id=self.registration.tenant_id,
                key_prefix=self.registration.key_prefix,
                credential=credential,
                maximum_objects=self.registration.maximum_objects,
                maximum_object_bytes=self.registration.maximum_object_bytes,
            )
        except ConnectorNetworkError:
            raise
        except Exception as exc:  # provider details must not cross the connector boundary
            raise ConnectorNetworkError("object_transport_failed") from exc
        prefix = posixpath.normpath(self.registration.key_prefix)
        ordered: list[ObjectRemoteEntry] = []
        for entry in entries:
            key = entry.key.replace("\\", "/")
            if any(part in {"", ".", ".."} for part in key.split("/")):
                raise ConnectorNetworkError("object_key_traversal")
            normalized = posixpath.normpath(key)
            if normalized != prefix and not normalized.startswith(prefix + "/"):
                raise ConnectorNetworkError("object_key_outside_prefix")
            if len(entry.content) > self.registration.maximum_object_bytes:
                raise ConnectorNetworkError("object_too_large")
            actual = hashlib.sha256(entry.content).hexdigest()
            if entry.sha256 != actual:
                raise ConnectorNetworkError("object_checksum_mismatch")
            if entry.metadata.get("reconforge-tenant") != self.registration.tenant_id:
                raise ConnectorNetworkError("object_tenant_scope_mismatch")
            ordered.append(ObjectRemoteEntry(normalized, entry.content, actual, dict(entry.metadata)))
        ordered.sort(key=lambda item: (item.key, item.sha256))
        if cursor is not None:
            ordered = [item for item in ordered if item.key > cursor]
        selected = tuple(ordered[: self.registration.maximum_objects])
        objects = tuple(ObjectRead(item.key, item.content, item.sha256, item.metadata) for item in selected)
        response_digest = hashlib.sha256(
            json.dumps(
                [{"key": item.key, "sha256": item.sha256, "metadata": item.metadata} for item in objects],
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        next_cursor = objects[-1].key if len(objects) == self.registration.maximum_objects else None
        return ObjectStorageRead(objects, request_digest, response_digest, next_cursor)
