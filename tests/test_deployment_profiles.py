from __future__ import annotations

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
