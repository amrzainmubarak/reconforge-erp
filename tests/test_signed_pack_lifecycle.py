from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from reconforge.connectors.package import TrustedPublisherKey, TrustedPublisherRegistry
from reconforge.packs.lifecycle import (
    PackLifecycleError,
    PackLifecycleStore,
    SignedPackEnvelope,
    load_verified_pack,
    signature_payload,
)

cryptography_ed25519 = pytest.importorskip(
    "cryptography.hazmat.primitives.asymmetric.ed25519", reason="connector crypto extra is optional"
)
Ed25519PrivateKey = cryptography_ed25519.Ed25519PrivateKey

def _manifest(pack_id: str = "synthetic-close", version: str = "1.0.0", dependencies: list[dict[str, str]] | None = None) -> dict[str, object]:
    rule = {
        "rule_id": "SC-001",
        "rule_name": "Missing reference",
        "severity": "high",
        "entity_type": "gl_entry",
        "source_file": "gl_entries.csv",
        "condition": {"operator": "missing", "field": "reference"},
        "message": "Reference is required.",
        "recommended_action": "Review the synthetic source record.",
        "risk_impact": 70,
        "evidence_fields": ["entry_id", "reference"],
    }
    return {
        "schema": "signed-data-pack-manifest-v1",
        "pack_id": pack_id,
        "name": "Synthetic close controls",
        "version": version,
        "kind": "control",
        "reconforge_version": ">=0.7.0,<0.8.0",
        "dependencies": dependencies or [],
        "metadata": {"pack_id": pack_id, "name": "Synthetic close controls", "version": version, "description": "Synthetic test-only pack."},
        "rules": {"rules": [rule]},
        "golden": {"rule_count": 1, "rule_ids": ["SC-001"]},
    }


def _write_signed(path: Path, private_key: Ed25519PrivateKey, *, manifest: dict[str, object] | None = None) -> None:
    unsigned = {
        "package_schema": "signed-data-pack-v1",
        "publisher_id": "test.publisher",
        "key_id": "key-1",
        "algorithm": "Ed25519",
        "manifest": manifest or _manifest(),
        "signature": base64.b64encode(b"0" * 64).decode("ascii"),
    }
    envelope = SignedPackEnvelope.model_validate(unsigned)
    unsigned["signature"] = base64.b64encode(private_key.sign(signature_payload(envelope))).decode("ascii")
    path.write_text(json.dumps(unsigned), encoding="utf-8")


@pytest.fixture
def trust() -> tuple[Ed25519PrivateKey, TrustedPublisherRegistry]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes_raw()
    registry = TrustedPublisherRegistry(version=1, keys=(TrustedPublisherKey("test.publisher", "key-1", public_key),))
    return private_key, registry


def test_signed_data_only_pack_verifies_identity_signature_and_golden_contract(tmp_path: Path, trust: tuple[Ed25519PrivateKey, TrustedPublisherRegistry]) -> None:
    private_key, registry = trust
    package = tmp_path / "pack.json"
    _write_signed(package, private_key)

    envelope = load_verified_pack(package, trusted_registry=registry)

    assert envelope.envelope.manifest.pack_id == "synthetic-close"
    assert len(envelope.envelope.manifest.content_digest) == 64
    assert "entrypoint" not in package.read_text(encoding="utf-8")


@pytest.mark.parametrize("mutation", ["rule", "identity", "signature", "entrypoint", "golden"])
def test_pack_boundary_rejects_tampering_schema_expansion_and_false_golden_data(tmp_path: Path, trust: tuple[Ed25519PrivateKey, TrustedPublisherRegistry], mutation: str) -> None:
    private_key, registry = trust
    package = tmp_path / "pack.json"
    _write_signed(package, private_key)
    payload = json.loads(package.read_text(encoding="utf-8"))
    if mutation == "rule":
        payload["manifest"]["rules"]["rules"][0]["message"] = "tampered"
    elif mutation == "identity":
        payload["manifest"]["metadata"]["version"] = "2.0.0"
    elif mutation == "signature":
        payload["signature"] = base64.b64encode(b"x" * 64).decode("ascii")
    elif mutation == "entrypoint":
        payload["manifest"]["entrypoint"] = "evil:run"
    else:
        payload["manifest"]["golden"]["rule_count"] = 2
        envelope = SignedPackEnvelope.model_validate(payload)
        payload["signature"] = base64.b64encode(private_key.sign(signature_payload(envelope))).decode("ascii")
    package.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PackLifecycleError):
        load_verified_pack(package, trusted_registry=registry)


def test_maker_checker_install_migration_disable_and_rollback_are_atomic(tmp_path: Path, trust: tuple[Ed25519PrivateKey, TrustedPublisherRegistry]) -> None:
    private_key, registry = trust
    store = PackLifecycleStore(tmp_path / "packs.sqlite3", trusted_registry=registry)
    try:
        one_path = tmp_path / "one.json"
        _write_signed(one_path, private_key)
        one = load_verified_pack(one_path, trusted_registry=registry)
        assert store.submit(one, actor="maker").status == "submitted"
        with pytest.raises(PackLifecycleError):
            store.approve("synthetic-close", "1.0.0", actor="maker")
        assert store.approve("synthetic-close", "1.0.0", actor="checker").status == "approved"
        assert store.install("synthetic-close", "1.0.0", actor="operator").status == "enabled"

        two_path = tmp_path / "two.json"
        _write_signed(two_path, private_key, manifest=_manifest(version="1.1.0"))
        two = load_verified_pack(two_path, trusted_registry=registry)
        store.submit(two, actor="maker")
        store.approve("synthetic-close", "1.1.0", actor="checker")
        assert store.install("synthetic-close", "1.1.0", actor="operator").status == "enabled"
        assert store.get("synthetic-close", "1.0.0").status == "disabled"
        assert store.rollback("synthetic-close", target_version="1.0.0", actor="operator").status == "enabled"
        assert store.disable("synthetic-close", actor="operator").status == "disabled"
        assert [event["action"] for event in store.events("synthetic-close")] == [
            "submitted", "approved", "installed", "submitted", "approved", "installed", "rolled_back", "disabled"
        ]
    finally:
        store.close()


def test_dependency_compatibility_fails_closed_until_approved_dependency_is_enabled(tmp_path: Path, trust: tuple[Ed25519PrivateKey, TrustedPublisherRegistry]) -> None:
    private_key, registry = trust
    store = PackLifecycleStore(tmp_path / "packs.sqlite3", trusted_registry=registry)
    try:
        child_path = tmp_path / "child.json"
        _write_signed(child_path, private_key, manifest=_manifest("synthetic-child", dependencies=[{"pack_id": "synthetic-close", "version_constraint": ">=1.0.0,<2.0.0"}]))
        child = load_verified_pack(child_path, trusted_registry=registry)
        store.submit(child, actor="maker")
        store.approve("synthetic-child", "1.0.0", actor="checker")
        with pytest.raises(PackLifecycleError, match="pack_dependency_unsatisfied"):
            store.install("synthetic-child", "1.0.0", actor="operator")
        assert store.get("synthetic-child", "1.0.0").status == "approved"

        parent_path = tmp_path / "parent.json"
        _write_signed(parent_path, private_key)
        parent = load_verified_pack(parent_path, trusted_registry=registry)
        store.submit(parent, actor="maker")
        store.approve("synthetic-close", "1.0.0", actor="checker")
        store.install("synthetic-close", "1.0.0", actor="operator")
        assert store.install("synthetic-child", "1.0.0", actor="operator").status == "enabled"
    finally:
        store.close()
