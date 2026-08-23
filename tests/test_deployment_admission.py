from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.deployment import RegulatedAdmissionError, verify_regulated_admission
from reconforge.deployment.profiles import deployment_profile


def _runtime() -> dict[str, object]:
    return {
        "edition": "regulated",
        "profile_digest": deployment_profile("regulated").digest,
        "storage_backend": "customer-managed-postgresql",
        "identity_provider": "oidc-saml-scim-mfa",
        "queue_backend": "ha-durable-queue",
        "object_store": "worm-compatible-customer-managed",
        "network_enabled": False,
        "writeback_enabled": False,
        "human_approval_enabled": False,
        "air_gap_enabled": True,
        "customer_managed_keys_enabled": True,
        "independent_failure_domains_verified": True,
        "worker_discovery_execution_separation_verified": True,
        "backup_restore_verified": True,
        "rollback_verified": True,
        "retention_privacy_verified": True,
    }


def _key() -> dict[str, object]:
    return {
        "provider": "customer-hsm",
        "key_id": "hsm://regulated/backup-key",
        "key_version": "2026-08",
        "algorithm": "AES-256-GCM",
        "purpose": "backup",
        "scope": "tenant:regulated/workspace:primary",
        "customer_managed": True,
        "status": "active",
        "rotation_period_days": 30,
    }


def test_regulated_admission_binds_runtime_and_key_digests() -> None:
    evidence = verify_regulated_admission({"runtime_evidence": _runtime(), "key_manifest": _key()})
    assert len(evidence.digest) == 64
    assert evidence.to_dict()["edition"] == "regulated"
    assert evidence.to_dict()["key_provider"] == "customer-hsm"


def test_regulated_admission_rejects_local_key_provider() -> None:
    key = _key()
    key["provider"] = "local-development"
    with pytest.raises(RegulatedAdmissionError, match="non-local"):
        verify_regulated_admission({"runtime_evidence": _runtime(), "key_manifest": key})


def test_regulated_admission_rejects_unverified_runtime() -> None:
    runtime = _runtime()
    runtime["independent_failure_domains_verified"] = False
    with pytest.raises(RegulatedAdmissionError, match="unresolved profile findings"):
        verify_regulated_admission({"runtime_evidence": runtime, "key_manifest": _key()})


def test_cli_verifies_regulated_admission_without_claiming_readiness(tmp_path: Path) -> None:
    path = tmp_path / "regulated-admission.json"
    path.write_text(json.dumps({"runtime_evidence": _runtime(), "key_manifest": _key()}), encoding="utf-8")
    result = CliRunner().invoke(app, ["deployment", "verify-regulated-admission", str(path)])
    assert result.exit_code == 0
    assert "production_readiness_claim" in result.stdout
    assert "external_calls" in result.stdout


def test_cli_rejects_regulated_admission_envelope(tmp_path: Path) -> None:
    path = tmp_path / "invalid-admission.json"
    path.write_text(json.dumps({"runtime_evidence": _runtime()}), encoding="utf-8")
    result = CliRunner().invoke(app, ["deployment", "verify-regulated-admission", str(path)])
    assert result.exit_code == 1
    assert "closed contract" in result.stdout
