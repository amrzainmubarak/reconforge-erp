from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from reconforge.connectors.package import (
    ConnectorPackageError,
    PublisherKeyStatus,
    SignedConnectorEnvelope,
    TrustedPublisherKey,
    TrustedPublisherRegistry,
    load_verified_package,
    signature_payload,
)
from reconforge.plugins.registry import get_connector


def _write_signed_package(path: Path) -> tuple[TrustedPublisherKey, dict[str, object]]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    unsigned = {
        "package_schema": "signed-connector-package-v1",
        "publisher_id": "example.publisher",
        "key_id": "test-key-1",
        "algorithm": "Ed25519",
        "manifest": get_connector("generic_csv").manifest.model_dump(mode="json"),
        "signature": base64.b64encode(bytes(64)).decode("ascii"),
    }
    envelope = SignedConnectorEnvelope.model_validate(unsigned)
    unsigned["signature"] = base64.b64encode(private_key.sign(signature_payload(envelope))).decode("ascii")
    path.write_text(json.dumps(unsigned), encoding="utf-8")
    return TrustedPublisherKey("example.publisher", "test-key-1", public_key), unsigned


def test_data_only_package_verifies_against_exact_publisher_key(tmp_path: Path) -> None:
    path = tmp_path / "connector.json"
    trust, _ = _write_signed_package(path)
    envelope = load_verified_package(path, trusted_keys=(trust,))
    assert envelope.manifest.connector_id == "generic_csv"
    assert envelope.algorithm == "Ed25519"


@pytest.mark.parametrize("mutation", ["manifest", "publisher", "signature", "unknown_field"])
def test_package_tampering_and_schema_expansion_fail_closed(tmp_path: Path, mutation: str) -> None:
    path = tmp_path / "connector.json"
    trust, payload = _write_signed_package(path)
    if mutation == "manifest":
        payload["manifest"]["display_name"] = "Tampered"  # type: ignore[index]
    elif mutation == "publisher":
        payload["publisher_id"] = "other.publisher"
    elif mutation == "signature":
        payload["signature"] = base64.b64encode(bytes([1]) * 64).decode("ascii")
    else:
        payload["python_entrypoint"] = "hostile.module:run"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ConnectorPackageError, match="connector_package_(invalid|untrusted_publisher|signature_invalid)"):
        load_verified_package(path, trusted_keys=(trust,))


def test_package_rejects_oversize_binary_and_ambiguous_trust(tmp_path: Path) -> None:
    path = tmp_path / "connector.json"
    trust, _ = _write_signed_package(path)
    with pytest.raises(ConnectorPackageError, match="trust_registry_invalid"):
        load_verified_package(path, trusted_keys=(trust, trust))
    path.write_bytes(b"{}\x00")
    with pytest.raises(ConnectorPackageError, match="binary_content"):
        load_verified_package(path, trusted_keys=(trust,))
    path.write_bytes(b"x" * (64 * 1024 + 1))
    with pytest.raises(ConnectorPackageError, match="size_invalid"):
        load_verified_package(path, trusted_keys=(trust,))


def test_versioned_trust_registry_supports_rotation_and_irreversible_revocation(tmp_path: Path) -> None:
    path = tmp_path / "connector.json"
    trust, _ = _write_signed_package(path)
    active = TrustedPublisherRegistry(version=1, keys=(trust,))
    assert len(active.digest) == 64
    assert load_verified_package(path, trusted_registry=active).publisher_id == "example.publisher"
    revoked_key = TrustedPublisherKey(
        trust.publisher_id, trust.key_id, trust.public_key, status=PublisherKeyStatus.REVOKED
    )
    revoked = TrustedPublisherRegistry(version=2, keys=(revoked_key,))
    assert revoked.digest != active.digest
    with pytest.raises(ConnectorPackageError, match="untrusted_publisher"):
        load_verified_package(path, trusted_registry=revoked)
    with pytest.raises(ConnectorPackageError, match="ambiguous_trust_source"):
        load_verified_package(path, trusted_keys=(trust,), trusted_registry=active)
