from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.deployment import (
    DeploymentRuntimeEvidenceError,
    verify_deployment_runtime_evidence,
)


def _payload() -> dict[str, object]:
    return {
        "edition": "team",
        "storage_backend": "postgresql",
        "identity_provider": "local-or-oidc",
        "queue_backend": "redis",
        "object_store": "s3-compatible",
        "network_enabled": False,
        "writeback_enabled": False,
        "human_approval_enabled": False,
        "air_gap_enabled": False,
        "customer_managed_keys_enabled": False,
        "independent_failure_domains_verified": False,
        "worker_discovery_execution_separation_verified": True,
        "backup_restore_verified": True,
        "rollback_verified": True,
        "retention_privacy_verified": True,
    }


def test_runtime_evidence_is_closed_digest_bound_and_reports_findings() -> None:
    evidence = verify_deployment_runtime_evidence(_payload())
    assert evidence.findings == ()
    assert len(evidence.digest) == 64
    assert evidence.digest == verify_deployment_runtime_evidence(dict(_payload())).digest


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("unknown", True, "closed contract"),
        ("backup_restore_verified", "yes", "must be boolean"),
        ("edition", "global", "unsupported"),
    ],
)
def test_runtime_evidence_fails_closed(field: str, value: object, message: str) -> None:
    payload = _payload()
    if field == "unknown":
        payload[field] = value
    else:
        payload[field] = value
    with pytest.raises(DeploymentRuntimeEvidenceError, match=message):
        verify_deployment_runtime_evidence(payload)


def test_cli_verifies_runtime_evidence_and_preserves_findings(tmp_path: Path) -> None:
    manifest_path = tmp_path / "runtime-evidence.json"
    manifest_path.write_text(json.dumps(_payload()), encoding="utf-8")
    result = CliRunner().invoke(app, ["deployment", "verify-runtime-evidence", str(manifest_path)])
    assert result.exit_code == 0
    assert "external_calls" in result.stdout
    assert "findings" in result.stdout
    assert "external_calls" in result.stdout


def test_cli_rejects_runtime_evidence_contract(tmp_path: Path) -> None:
    manifest_path = tmp_path / "invalid-runtime-evidence.json"
    manifest_path.write_text(json.dumps({"edition": "team"}), encoding="utf-8")
    result = CliRunner().invoke(app, ["deployment", "verify-runtime-evidence", str(manifest_path)])
    assert result.exit_code == 1
    assert "closed contract" in result.stdout
