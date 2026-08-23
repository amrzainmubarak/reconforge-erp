from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.deployment import (
    DeploymentProfileError,
    DeploymentRuntimeFacts,
    deployment_profile,
    list_deployment_profiles,
    validate_deployment_profile,
)


def test_deployment_profiles_are_ordered_digest_bound_and_conservative() -> None:
    profiles = list_deployment_profiles()

    assert [profile.edition for profile in profiles] == ["community", "team", "enterprise", "regulated"]
    assert len({profile.digest for profile in profiles}) == len(profiles)
    assert profiles[0].network_default == "disabled"
    assert profiles[0].writeback_default == "disabled"
    assert profiles[-1].requires_customer_managed_keys is True
    assert profiles[0].requires_worker_discovery_execution_separation is False
    assert all(profile.requires_worker_discovery_execution_separation for profile in profiles[1:])
    assert all(isinstance(profile.to_dict()["claim_boundary"], str) for profile in profiles)


def test_community_profile_rejects_network_and_writeback() -> None:
    facts = DeploymentRuntimeFacts(
        storage_backend="sqlite",
        identity_provider="local",
        queue_backend="local",
        object_store="local-files",
        network_enabled=True,
        writeback_enabled=True,
        human_approval_enabled=True,
    )

    assert validate_deployment_profile("community", facts) == (
        "network_must_remain_disabled",
        "writeback_must_remain_disabled",
        "backup_restore_evidence_required",
        "rollback_evidence_required",
        "retention_privacy_evidence_required",
    )


def test_regulated_profile_requires_customer_keys_and_failure_domains() -> None:
    facts = DeploymentRuntimeFacts(
        storage_backend="customer-managed-postgresql",
        identity_provider="oidc-saml-scim-mfa",
        queue_backend="ha-durable-queue",
        object_store="worm-compatible-customer-managed",
    )

    assert validate_deployment_profile("regulated", facts) == (
        "customer_managed_keys_required",
        "independent_failure_domains_required",
        "worker_discovery_execution_separation_required",
        "backup_restore_evidence_required",
        "rollback_evidence_required",
        "retention_privacy_evidence_required",
    )


def test_complete_community_runtime_facts_clear_readiness_findings() -> None:
    facts = DeploymentRuntimeFacts(
        storage_backend="sqlite",
        identity_provider="local",
        queue_backend="local",
        object_store="local-files",
        backup_restore_verified=True,
        rollback_verified=True,
        retention_privacy_verified=True,
    )

    assert validate_deployment_profile("community", facts) == ()


def test_writeback_always_requires_human_approval() -> None:
    facts = DeploymentRuntimeFacts(
        storage_backend="postgresql",
        identity_provider="local-or-oidc",
        queue_backend="redis",
        object_store="s3-compatible",
        writeback_enabled=True,
    )

    assert "writeback_requires_human_approval" in validate_deployment_profile("team", facts)


def test_hosted_profiles_require_discovery_execution_separation_evidence() -> None:
    facts = DeploymentRuntimeFacts(
        storage_backend="postgresql",
        identity_provider="local-or-oidc",
        queue_backend="redis",
        object_store="s3-compatible",
        backup_restore_verified=True,
        rollback_verified=True,
        retention_privacy_verified=True,
    )
    findings = validate_deployment_profile("team", facts)
    assert findings == ("worker_discovery_execution_separation_required",)

    verified = DeploymentRuntimeFacts(
        storage_backend="postgresql",
        identity_provider="local-or-oidc",
        queue_backend="redis",
        object_store="s3-compatible",
        worker_discovery_execution_separation_verified=True,
        backup_restore_verified=True,
        rollback_verified=True,
        retention_privacy_verified=True,
    )
    assert validate_deployment_profile("team", verified) == ()


def test_invalid_edition_and_runtime_facts_fail_closed() -> None:
    with pytest.raises(DeploymentProfileError, match="edition"):
        deployment_profile("global")
    with pytest.raises(DeploymentProfileError, match="boolean"):
        DeploymentRuntimeFacts(
            storage_backend="sqlite",
            identity_provider="local",
            queue_backend="local",
            object_store="local-files",
            network_enabled="yes",  # type: ignore[arg-type]
        )


def test_cli_lists_profiles_and_filters_one_edition() -> None:
    runner = CliRunner()

    listed = runner.invoke(app, ["deployment", "profiles"])
    assert listed.exit_code == 0
    assert "community" in listed.stdout
    assert "regulated" in listed.stdout

    selected = runner.invoke(app, ["deployment", "profiles", "--edition", "community"])
    assert selected.exit_code == 0
    assert "community" in selected.stdout
    assert "regulated" not in selected.stdout


def test_cli_rejects_unknown_edition() -> None:
    result = CliRunner().invoke(app, ["deployment", "profiles", "--edition", "global"])

    assert result.exit_code == 1
    assert "deployment edition is unsupported" in result.stdout


def test_cli_verifies_worker_permission_manifest(tmp_path: Path) -> None:
    import json

    manifest_path = tmp_path / "worker-permissions.json"
    manifest_path.write_text(
        json.dumps(
            {
                "worker_id": "reconciliation-worker-a",
                "principal_id": "svc-reconciliation-a",
                "discovery_permission": "match.discover",
                "execution_permission": "match.run",
                "granted_permissions": ["match.discover", "match.run"],
                "scope": "tenant:tenant-a/workspace:workspace-a",
            }
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["deployment", "verify-worker-manifest", str(manifest_path)])
    assert result.exit_code == 0
    assert "discovery_execution_separated" in result.stdout
    assert "match.discover" in result.stdout


def test_cli_rejects_invalid_worker_permission_manifest(tmp_path: Path) -> None:
    import json

    manifest_path = tmp_path / "invalid-worker-permissions.json"
    manifest_path.write_text(json.dumps({"worker_id": "bad"}), encoding="utf-8")
    result = CliRunner().invoke(app, ["deployment", "verify-worker-manifest", str(manifest_path)])
    assert result.exit_code == 1
    assert "closed contract" in result.stdout
