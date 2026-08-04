"""Data-only signed connector package verification.

External connector packages are manifest envelopes, not executable extensions.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from reconforge.connectors.manifest import ConnectorManifest

MAX_CONNECTOR_PACKAGE_BYTES = 64 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ConnectorPackageError(ValueError):
    """Raised when a connector package cannot cross the trust boundary."""


class SignedConnectorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    package_schema: str = Field(pattern=r"^signed-connector-package-v1$")
    publisher_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
    key_id: str = Field(pattern=r"^[a-zA-Z0-9._-]{1,80}$")
    algorithm: str = Field(pattern=r"^Ed25519$")
    manifest: ConnectorManifest
    signature: str = Field(min_length=86, max_length=88)


class PublisherKeyStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


@dataclass(frozen=True)
class TrustedPublisherKey:
    publisher_id: str
    key_id: str
    public_key: bytes
    status: PublisherKeyStatus = PublisherKeyStatus.ACTIVE

    def __post_init__(self) -> None:
        if len(self.public_key) != 32:
            raise ValueError("Ed25519 public keys must contain exactly 32 bytes")


@dataclass(frozen=True)
class TrustedPublisherRegistry:
    """Versioned operator-owned trust input; private keys are never accepted."""

    version: int
    keys: tuple[TrustedPublisherKey, ...]

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("publisher trust registry version must be positive")
        identities = [(key.publisher_id, key.key_id) for key in self.keys]
        if identities != sorted(identities) or len(identities) != len(set(identities)):
            raise ValueError("publisher trust keys must be unique and canonically sorted")

    @property
    def digest(self) -> str:
        payload = [
            {
                "key_id": key.key_id,
                "public_key": base64.b64encode(key.public_key).decode("ascii"),
                "publisher_id": key.publisher_id,
                "status": key.status.value,
            }
            for key in self.keys
        ]
        encoded = json.dumps(
            {"keys": payload, "registry_schema": "connector-publisher-trust-v1", "version": self.version},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()

    def resolve(self, publisher_id: str, key_id: str) -> TrustedPublisherKey:
        matching = tuple(
            key
            for key in self.keys
            if key.publisher_id == publisher_id and key.key_id == key_id and key.status is PublisherKeyStatus.ACTIVE
        )
        if len(matching) != 1:
            raise ConnectorPackageError("connector_package_untrusted_publisher")
        return matching[0]


@dataclass(frozen=True)
class VerifiedConnectorPackage:
    """A signed package after trust and read-only conformance admission.

    The envelope remains data-only.  The admission record binds the exact
    manifest, publisher trust-registry snapshot, and signature payload so a
    caller cannot treat signature verification alone as executable-plugin
    authorization.
    """

    envelope: SignedConnectorEnvelope
    trust_registry_version: int
    trust_registry_digest: str
    manifest_digest: str
    admission_digest: str
    checks: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.trust_registry_version, bool) or self.trust_registry_version < 1:
            raise ValueError("trust registry version must be positive")
        if any(
            not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None
            for value in (self.trust_registry_digest, self.manifest_digest, self.admission_digest)
        ):
            raise ValueError("verified connector package digests must be SHA-256")
        if self.checks != ("signature_verified", "publisher_trusted", "manifest_conformant", "data_only"):
            raise ValueError("verified connector package checks are not canonical")

    def to_dict(self) -> dict[str, object]:
        return {
            "admission_digest": self.admission_digest,
            "checks": list(self.checks),
            "key_id": self.envelope.key_id,
            "manifest_digest": self.manifest_digest,
            "publisher_id": self.envelope.publisher_id,
            "trust_registry_digest": self.trust_registry_digest,
            "trust_registry_version": self.trust_registry_version,
        }


def signature_payload(envelope: SignedConnectorEnvelope) -> bytes:
    payload = {
        "algorithm": envelope.algorithm,
        "key_id": envelope.key_id,
        "manifest": envelope.manifest.model_dump(mode="json", exclude_none=False),
        "package_schema": envelope.package_schema,
        "publisher_id": envelope.publisher_id,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")


def _verify_envelope_signature(envelope: SignedConnectorEnvelope, registry: TrustedPublisherRegistry) -> None:
    trusted_key = registry.resolve(envelope.publisher_id, envelope.key_id)
    try:
        signature = base64.b64decode(envelope.signature, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ConnectorPackageError("connector_package_signature_invalid") from exc
    if len(signature) != 64:
        raise ConnectorPackageError("connector_package_signature_invalid")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:  # pragma: no cover - exact optional-dependency error is environment-specific
        raise ConnectorPackageError("connector_signature_runtime_unavailable") from exc
    try:
        Ed25519PublicKey.from_public_bytes(trusted_key.public_key).verify(signature, signature_payload(envelope))
    except (InvalidSignature, ValueError) as exc:
        raise ConnectorPackageError("connector_package_signature_invalid") from exc


def load_verified_package(
    path: Path,
    *,
    trusted_keys: tuple[TrustedPublisherKey, ...] = (),
    trusted_registry: TrustedPublisherRegistry | None = None,
) -> SignedConnectorEnvelope:
    """Read and authenticate one bounded JSON manifest envelope."""

    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ConnectorPackageError("connector_package_unreadable") from exc
    if size <= 0 or size > MAX_CONNECTOR_PACKAGE_BYTES:
        raise ConnectorPackageError("connector_package_size_invalid")
    try:
        raw = path.read_bytes()
        if b"\x00" in raw:
            raise ConnectorPackageError("connector_package_binary_content")
        decoded = json.loads(raw.decode("utf-8"))
        envelope = SignedConnectorEnvelope.model_validate(decoded)
    except ConnectorPackageError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ConnectorPackageError("connector_package_invalid") from exc

    if trusted_registry is not None and trusted_keys:
        raise ConnectorPackageError("connector_package_ambiguous_trust_source")
    try:
        registry = trusted_registry or TrustedPublisherRegistry(version=1, keys=trusted_keys)
    except ValueError as exc:
        raise ConnectorPackageError("connector_package_trust_registry_invalid") from exc
    _verify_envelope_signature(envelope, registry)
    return envelope


def admit_verified_package(
    envelope: SignedConnectorEnvelope,
    *,
    trust_registry: TrustedPublisherRegistry,
) -> VerifiedConnectorPackage:
    """Admit one authenticated envelope through the read-only conformance gate.

    This function does not load or execute code from the package.  It is an
    explicit second boundary after Ed25519 verification and binds admission to
    the operator-owned trust registry snapshot.
    """

    if not isinstance(envelope, SignedConnectorEnvelope):
        raise ConnectorPackageError("connector_package_invalid")
    if not isinstance(trust_registry, TrustedPublisherRegistry):
        raise ConnectorPackageError("connector_package_trust_registry_invalid")
    _verify_envelope_signature(envelope, trust_registry)
    try:
        from reconforge.connectors.conformance import verify_manifest_portfolio

        verify_manifest_portfolio((envelope.manifest,))
    except (ValueError, TypeError) as exc:
        raise ConnectorPackageError("connector_package_conformance_failed") from exc
    unsigned = {
        "algorithm": envelope.algorithm,
        "key_id": envelope.key_id,
        "manifest_digest": envelope.manifest.digest,
        "package_schema": envelope.package_schema,
        "publisher_id": envelope.publisher_id,
        "signature_digest": hashlib.sha256(envelope.signature.encode("ascii")).hexdigest(),
        "trust_registry_digest": trust_registry.digest,
        "trust_registry_version": trust_registry.version,
    }
    admission_digest = hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return VerifiedConnectorPackage(
        envelope=envelope,
        trust_registry_version=trust_registry.version,
        trust_registry_digest=trust_registry.digest,
        manifest_digest=envelope.manifest.digest,
        admission_digest=admission_digest,
        checks=("signature_verified", "publisher_trusted", "manifest_conformant", "data_only"),
    )


def load_verified_package_for_admission(
    path: Path,
    *,
    trusted_keys: tuple[TrustedPublisherKey, ...] = (),
    trusted_registry: TrustedPublisherRegistry | None = None,
) -> VerifiedConnectorPackage:
    """Load, authenticate, and admit a signed read-only connector package."""

    if trusted_registry is not None and trusted_keys:
        raise ConnectorPackageError("connector_package_ambiguous_trust_source")
    try:
        registry = trusted_registry or TrustedPublisherRegistry(version=1, keys=trusted_keys)
    except ValueError as exc:
        raise ConnectorPackageError("connector_package_trust_registry_invalid") from exc
    envelope = load_verified_package(path, trusted_registry=registry)
    return admit_verified_package(envelope, trust_registry=registry)
