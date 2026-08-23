from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.deployment import ManagedKeyManifestError, verify_managed_key_manifest


def _payload() -> dict[str, object]:
    return {
        "provider": "customer-hsm",
        "key_id": "hsm://tenant-a/backup-key",
        "key_version": "2026-08",
        "algorithm": "AES-256-GCM",
        "purpose": "backup",
        "scope": "tenant:tenant-a/workspace:workspace-a",
        "customer_managed": True,
        "status": "active",
        "rotation_period_days": 90,
    }


def test_managed_key_manifest_is_non_secret_and_digest_stable() -> None:
    manifest = verify_managed_key_manifest(_payload())
    assert len(manifest.digest) == 64
    assert manifest.to_dict()["customer_managed"] is True
    assert manifest.digest == verify_managed_key_manifest(dict(_payload())).digest


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("unknown", True, "closed contract"),
        ("customer_managed", False, "customer_managed must be true"),
        ("rotation_period_days", 0, "outside the allowed range"),
        ("provider", "made-up", "provider is unsupported"),
    ],
)
def test_managed_key_manifest_fails_closed(field: str, value: object, message: str) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(ManagedKeyManifestError, match=message):
        verify_managed_key_manifest(payload)


def test_cli_verifies_key_metadata_without_external_calls(tmp_path: Path) -> None:
    path = tmp_path / "key-manifest.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    result = CliRunner().invoke(app, ["deployment", "verify-key-manifest", str(path)])
    assert result.exit_code == 0
    assert "secret_material_present" in result.stdout
    assert "external_calls" in result.stdout


def test_cli_rejects_key_manifest_contract(tmp_path: Path) -> None:
    path = tmp_path / "invalid-key-manifest.json"
    path.write_text(json.dumps({"provider": "customer-hsm"}), encoding="utf-8")
    result = CliRunner().invoke(app, ["deployment", "verify-key-manifest", str(path)])
    assert result.exit_code == 1
    assert "closed contract" in result.stdout
