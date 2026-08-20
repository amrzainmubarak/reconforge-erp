"""Synthetic, read-only SFTP reference connector.

The runtime is transport-injected on purpose: this slice proves the security
and replay contract without bundling an SSH client or making network calls.
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

SFTP_REFERENCE_ENDPOINT = "sftp://sftp.example.test:22/inbound"
SFTP_REFERENCE_MANIFEST = ConnectorManifest(
    schema_version="connector-manifest-v1",
    connector_id="reference-sftp-readonly",
    display_name="Reference SFTP read-only source",
    version="1.0.0",
    kind=ConnectorKind.NETWORK_SOURCE,
    capabilities=frozenset({ConnectorCapability.READ}),
    authentication=AuthenticationMethod.SECRET_REFERENCE,
    network_required=True,
    data_classification=DataClassification.RESTRICTED,
    rate_limit_per_minute=30,
    incremental_cursor=True,
    idempotent_reads=True,
    retry_policy=RetryPolicy(maximum_attempts=2, initial_delay_seconds=1, maximum_delay_seconds=4),
    schema_versions=("reference-sftp-file-v1",),
    synthetic_sandbox=True,
    threat_model=("credential-disclosure", "path-traversal", "remote-file-amplification", "replay"),
    secret_handling="Resolve SSH credential_reference at runtime; never persist, log, or return it.",  # nosec B106
    egress_destinations=(SFTP_REFERENCE_ENDPOINT,),
    support_level=SupportLevel.COMMUNITY,
)


class SftpConnectorRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    registration_schema: str = Field(pattern=r"^sftp-connector-registration-v1$")
    manifest: ConnectorManifest
    endpoint: str = Field(min_length=1, max_length=2_048)
    credential_reference: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,255}$")
    root_path: str = Field(default="/inbound", min_length=1, max_length=512)
    maximum_files: int = Field(default=100, ge=1, le=10_000)
    maximum_file_bytes: int = Field(default=16_777_216, ge=1, le=67_108_864)

    @model_validator(mode="after")
    def validate_boundary(self) -> SftpConnectorRegistration:
        parsed = urlsplit(self.endpoint)
        if self.manifest.kind is not ConnectorKind.NETWORK_SOURCE or not self.manifest.network_required:
            raise ValueError("sftp registration requires a network-source manifest")
        if self.manifest.authentication is not AuthenticationMethod.SECRET_REFERENCE:
            raise ValueError("sftp registration requires secret-reference authentication")
        if parsed.scheme != "sftp" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("sftp endpoint must be a credential-free exact sftp URL")
        if self.endpoint not in self.manifest.egress_destinations:
            raise ValueError("endpoint must exactly match one declared SFTP egress destination")
        if not self.root_path.startswith("/") or ".." in self.root_path.split("/"):
            raise ValueError("sftp root_path must be absolute and traversal-free")
        return self

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json", exclude_none=False), ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SftpRemoteFile:
    path: str
    content: bytes
    modified_at: str


class SftpTransport(Protocol):
    def list_files(
        self,
        endpoint: str,
        *,
        root_path: str,
        credential: bytes,
        maximum_files: int,
        maximum_file_bytes: int,
    ) -> tuple[SftpRemoteFile, ...]: ...


@dataclass(frozen=True)
class SftpFileRead:
    path: str
    content: bytes
    modified_at: str
    sha256: str


@dataclass(frozen=True)
class SftpRead:
    files: tuple[SftpFileRead, ...]
    request_digest: str
    response_digest: str
    next_cursor: str | None


def sftp_reference_registration(*, credential_reference: str) -> SftpConnectorRegistration:
    return SftpConnectorRegistration(
        registration_schema="sftp-connector-registration-v1",
        manifest=SFTP_REFERENCE_MANIFEST,
        endpoint=SFTP_REFERENCE_ENDPOINT,
        credential_reference=credential_reference,
    )


@dataclass(frozen=True)
class ReferenceSftpConnector:
    transport: SftpTransport
    secret_resolver: ConnectorSecretResolver
    registration: SftpConnectorRegistration

    def read_files(self, *, idempotency_key: str, cursor: str | None = None) -> SftpRead:
        key_bytes = idempotency_key.encode("utf-8")
        if not key_bytes or len(key_bytes) > MAX_IDEMPOTENCY_KEY_BYTES or any(ord(c) < 33 for c in idempotency_key):
            raise ConnectorNetworkError("sftp_idempotency_key_invalid")
        if cursor is not None and (not cursor or len(cursor.encode("utf-8")) > MAX_CURSOR_BYTES):
            raise ConnectorNetworkError("sftp_cursor_invalid")
        credential = self.secret_resolver.resolve(self.registration.credential_reference)
        if not 16 <= len(credential) <= 4_096:
            raise ConnectorNetworkError("sftp_credential_invalid")
        request_digest = hashlib.sha256(
            json.dumps(
                {
                    "connector_id": self.registration.manifest.connector_id,
                    "connector_version": self.registration.manifest.version,
                    "cursor": cursor,
                    "endpoint": self.registration.endpoint,
                    "idempotency_key": idempotency_key,
                    "manifest_digest": self.registration.digest,
                    "root_path": self.registration.root_path,
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        try:
            remote_files = self.transport.list_files(
                self.registration.endpoint,
                root_path=self.registration.root_path,
                credential=credential,
                maximum_files=self.registration.maximum_files,
                maximum_file_bytes=self.registration.maximum_file_bytes,
            )
        except ConnectorNetworkError:
            raise
        except Exception as exc:  # transport adapters must not leak provider errors
            raise ConnectorNetworkError("sftp_transport_failed") from exc
        ordered: list[SftpRemoteFile] = []
        root = posixpath.normpath(self.registration.root_path)
        for remote in remote_files:
            normalized = posixpath.normpath(remote.path)
            if normalized != root and not normalized.startswith(root.rstrip("/") + "/"):
                raise ConnectorNetworkError("sftp_path_outside_root")
            if normalized.endswith("/") or not normalized.lower().endswith((".csv", ".json", ".xml")):
                raise ConnectorNetworkError("sftp_file_type_not_allowlisted")
            if len(remote.content) > self.registration.maximum_file_bytes:
                raise ConnectorNetworkError("sftp_file_too_large")
            ordered.append(SftpRemoteFile(normalized, remote.content, remote.modified_at))
        ordered.sort(key=lambda item: (item.path, item.modified_at, hashlib.sha256(item.content).hexdigest()))
        if cursor is not None:
            ordered = [item for item in ordered if item.path > cursor]
        selected = tuple(ordered[: self.registration.maximum_files])
        files = tuple(
            SftpFileRead(item.path, item.content, item.modified_at, hashlib.sha256(item.content).hexdigest())
            for item in selected
        )
        response_digest = hashlib.sha256(
            json.dumps(
                [{"path": item.path, "modified_at": item.modified_at, "sha256": item.sha256} for item in files],
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        next_cursor = files[-1].path if len(files) == self.registration.maximum_files else None
        return SftpRead(files, request_digest, response_digest, next_cursor)
