from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from reconforge.auth.policy_analysis import (
    POLICY_ANALYSIS_ALGORITHM_VERSION,
    PolicyAnalysisError,
    PolicyAnalysisRequest,
    PolicyGrant,
    PolicyScope,
    analyze_policy_conflicts,
    verify_policy_analysis_payload,
)
from reconforge.cli import app

ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def _scope(*, workspace: str | None = "W-1", entity: str | None = None) -> PolicyScope:
    return PolicyScope(
        tenant_id="TENANT-1",
        workspace_id=workspace,
        entity_ids=frozenset({entity}) if entity else frozenset(),
        period_ids=frozenset(),
        region_ids=frozenset(),
        data_classifications=frozenset(),
    )


def _grant(
    grant_id: str,
    principal_id: str,
    permissions: set[str],
    *,
    principal_type: str = "user",
    workspace: str | None = "W-1",
    status: str = "active",
) -> PolicyGrant:
    return PolicyGrant(
        grant_id=grant_id,
        principal_id=principal_id,
        principal_type=principal_type,
        role_id=f"ROLE-{grant_id}",
        scope=_scope(workspace=workspace),
        permissions=frozenset(permissions),
        status=status,
    )


def _request(*grants: PolicyGrant, require_scoped_privileged: bool = True) -> PolicyAnalysisRequest:
    return PolicyAnalysisRequest(
        policy_id="POLICY-1",
        policy_version="1.0.0",
        grants=tuple(grants),
        require_scoped_privileged=require_scoped_privileged,
        prepared_by="policy-preparer",
        prepared_at="2026-08-03T12:00:00Z",
        approved_by="policy-reviewer",
        approved_at="2026-08-03T11:00:00Z",
    )


def test_policy_analysis_detects_sod_and_service_account_conflicts() -> None:
    request = _request(
        _grant("G-1", "U-1", {"close.prepare", "close.approve"}),
        _grant("G-2", "SVC-1", {"close.manage"}, principal_type="service_account", workspace=None),
    )

    result = analyze_policy_conflicts(request)
    codes = {finding.code for finding in result.findings}

    assert result.algorithm_version == POLICY_ANALYSIS_ALGORITHM_VERSION
    assert result.status == "conflicts"
    assert "sod_permission_overlap" in codes
    assert "service_account_human_permission" in codes
    assert "unscoped_privileged_grant" in codes
    assert verify_policy_analysis_payload(result.to_dict())["result_digest"] == result.result_digest


def test_policy_analysis_ignores_revoked_and_disjoint_scopes() -> None:
    request = _request(
        _grant("G-1", "U-1", {"close.prepare"}, workspace="W-1"),
        _grant("G-2", "U-1", {"close.approve"}, workspace="W-2"),
        _grant("G-3", "U-1", {"close.approve"}, workspace="W-1", status="revoked"),
    )

    result = analyze_policy_conflicts(request)

    assert result.status == "clear"
    assert result.findings == ()
    assert result.active_grant_count == 2
    assert result.revoked_grant_count == 1


def test_policy_analysis_is_permutation_stable_and_requires_maker_checker() -> None:
    first_request = _request(
        _grant("G-2", "U-1", {"close.approve"}),
        _grant("G-1", "U-1", {"close.prepare"}),
    )
    second_request = replace(first_request, grants=tuple(reversed(first_request.grants)))

    first = analyze_policy_conflicts(first_request)
    second = analyze_policy_conflicts(second_request)

    assert first_request.digest == second_request.digest
    assert first.result_digest == second.result_digest
    with pytest.raises(PolicyAnalysisError, match="different actors"):
        PolicyAnalysisRequest(
            policy_id="POLICY-1",
            policy_version="1.0.0",
            grants=first_request.grants,
            require_scoped_privileged=True,
            prepared_by="same",
            prepared_at="2026-08-03T12:00:00Z",
            approved_by="same",
            approved_at="2026-08-03T11:00:00Z",
        )


def test_policy_analysis_tamper_and_schema_detection(tmp_path: Path) -> None:
    request = _request(_grant("G-1", "U-1", {"close.prepare"}))
    result = analyze_policy_conflicts(request)
    payload = result.to_dict()
    payload["findings"] = [{"unexpected": True}]
    with pytest.raises(PolicyAnalysisError, match="digest mismatch"):
        verify_policy_analysis_payload(payload)

    schema = json.loads(
        (ROOT / "docs/schemas/enterprise_policy_conflict_analysis_v1.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(result.to_dict())

    input_path = tmp_path / "policy-request.json"
    input_path.write_text(json.dumps(request.to_dict()), encoding="utf-8")
    completed = runner.invoke(app, ["policy", "analyze-conflicts", "--input", str(input_path)])
    assert completed.exit_code == 0, completed.output
    cli_result = json.loads(completed.output)
    assert cli_result["algorithm_version"] == POLICY_ANALYSIS_ALGORITHM_VERSION
    assert cli_result["status"] == "clear"

    invalid = json.loads(input_path.read_text(encoding="utf-8"))
    invalid["unexpected"] = True
    input_path.write_text(json.dumps(invalid), encoding="utf-8")
    rejected = runner.invoke(app, ["policy", "analyze-conflicts", "--input", str(input_path)])
    assert rejected.exit_code == 1
    assert "declared contract" in rejected.output


def test_policy_scope_requires_tenant_and_validates_timestamps() -> None:
    with pytest.raises(PolicyAnalysisError, match="tenant"):
        PolicyScope(tenant_id="")
    with pytest.raises(PolicyAnalysisError, match="timezone"):
        PolicyAnalysisRequest(
            policy_id="POLICY-1",
            policy_version="1.0.0",
            grants=(),
            require_scoped_privileged=True,
            prepared_by="preparer",
            prepared_at="2026-08-03T12:00:00",
            approved_by="reviewer",
            approved_at="2026-08-03T11:00:00Z",
        )
