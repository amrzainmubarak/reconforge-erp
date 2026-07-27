from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "docs" / "security" / "slsa-provenance-plan.v1.yaml"
SCHEMA_PATH = ROOT / "docs" / "schemas" / "slsa_provenance_plan.schema.json"
ARCHITECTURE_PATH = ROOT / "docs" / "security" / "security-architecture.v2.yaml"
READABLE_PATH = ROOT / "docs" / "security" / "slsa-provenance-plan.md"

ARTIFACT_IDS = ["source-archive", "python-wheel", "python-sdist", "container-image", "cyclonedx-sbom"]
BOUNDARY_IDS = [
    "source-control",
    "tenant-build-definition",
    "hosted-control-plane",
    "build-environment",
    "attestation-signing",
    "distribution",
    "consumer-verification",
]
GATE_IDS = [f"PROV-G{number:02d}" for number in range(1, 13)]
FAILURE_CODES = {
    "PROV_MISSING",
    "PROV_MALFORMED",
    "PROV_UNSUPPORTED_VERSION",
    "PROV_SIGNATURE_INVALID",
    "PROV_IDENTITY_MISMATCH",
    "PROV_SUBJECT_DIGEST_MISMATCH",
    "PROV_SOURCE_MISMATCH",
    "PROV_BUILDER_MISMATCH",
    "PROV_WORKFLOW_MISMATCH",
    "PROV_POLICY_MISMATCH",
    "PROV_REVOKED",
    "PROV_UNEXPECTED_INPUT",
}


def _load_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_slsa_plan_matches_closed_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(_load_yaml(PLAN_PATH))


def test_slsa_approved_source_pin_and_tracks_are_exact() -> None:
    payload = _load_yaml(PLAN_PATH)
    assert payload["specification"] == {
        "name": "Supply-chain Levels for Software Artifacts",
        "version": "1.2",
        "status": "Approved",
        "released": "2025-11-24",
        "verified_at": "2026-07-25",
        "official_spec_url": "https://slsa.dev/spec/v1.2/",
        "official_announcement_url": "https://slsa.dev/blog/2025/11/announce-slsa-v1.2",
        "official_repository_url": "https://github.com/slsa-framework/slsa",
        "release_tag": "v1.2",
        "release_commit": "19e4e2f005f871270c4f555fc47afecfb37f3efe",
        "release_branch": "releases/v1.2",
        "release_branch_head_observed": "ae7fc76215004e8fae250c877eff8919bf048e3b",
        "tracks": ["build", "source"],
        "source_note": (
            "The Approved versioned specification and announcement are normative; the "
            "release tag is pinned, while the observed release-branch head is recorded "
            "separately because branches can receive later editorial changes."
        ),
    }
    assert payload["current_assessment"] == {
        "build_track": "SLSA_BUILD_LEVEL_UNEVALUATED",
        "source_track": "SLSA_SOURCE_LEVEL_UNEVALUATED",
        "verified_properties": [],
        "reasons": payload["current_assessment"]["reasons"],
    }
    assert "no reconforge artifact" in payload["claim_boundary"].lower()


def test_slsa_artifacts_boundaries_attestation_and_verification_are_closed() -> None:
    payload = _load_yaml(PLAN_PATH)
    assert [artifact["id"] for artifact in payload["artifacts"]] == ARTIFACT_IDS
    assert [boundary["id"] for boundary in payload["trust_boundaries"]] == BOUNDARY_IDS
    assert len({artifact["id"] for artifact in payload["artifacts"]}) == 5
    assert len({boundary["id"] for boundary in payload["trust_boundaries"]}) == 7

    contract = payload["attestation_contract"]
    assert contract["statement_type"] == "https://in-toto.io/Statement/v1"
    assert contract["predicate_type"] == "https://slsa.dev/provenance/v1"
    for field in (
        "subject_requirements",
        "build_definition_requirements",
        "run_details_requirements",
        "signature_requirements",
        "prohibited_inputs",
    ):
        assert contract[field]

    verification = payload["verification_policy"]
    assert verification["expected_source_uri"] == "https://github.com/amrzainmubarak/reconforge-erp"
    assert verification["allowed_ref_types"] == ["signed-release-tag"]
    assert set(verification["failure_codes"]) == FAILURE_CODES
    assert any("Block publication" in action for action in verification["on_failure"])
    assert any("Silently overwrite" in action for action in payload["rollback_policy"]["prohibited_actions"])


def test_slsa_gates_owners_evidence_and_review_are_bounded() -> None:
    payload = _load_yaml(PLAN_PATH)
    architecture = _load_yaml(ARCHITECTURE_PATH)
    owners = {owner["id"] for owner in architecture["control_owners"]}
    gates = payload["implementation_gates"]

    assert [gate["id"] for gate in gates] == GATE_IDS
    assert Counter(gate["status"] for gate in gates) == {"partial": 8, "planned": 4}
    assert not any(gate["status"] == "verified" for gate in gates)
    for boundary in payload["trust_boundaries"]:
        assert boundary["owner"] in owners
        for evidence_path in boundary["evidence"]:
            assert (ROOT / evidence_path).is_file(), evidence_path
    for gate in gates:
        assert gate["owner"] in owners
        for evidence_path in [*gate["evidence"], *gate["test_evidence"]]:
            assert (ROOT / evidence_path).is_file(), evidence_path
        if gate["status"] == "partial":
            assert gate["evidence"]
            assert gate["test_evidence"]
        else:
            assert gate["evidence"] == []
            assert gate["test_evidence"] == []
        assert len(gate["exit_criteria"]) >= 3

    review = payload["review"]
    assert review["owner"] in owners
    assert review["cadence_days"] == 90
    assert date.fromisoformat(review["next_review_due"]) > date.fromisoformat(payload["last_reviewed"])


def test_readable_slsa_plan_discloses_scope_and_no_level_claim() -> None:
    readable = READABLE_PATH.read_text(encoding="utf-8")
    for artifact_id in ARTIFACT_IDS:
        assert f"`{artifact_id}`" in readable
    for boundary_id in BOUNDARY_IDS:
        assert f"`{boundary_id}`" in readable
    for gate_id in GATE_IDS:
        assert f"`{gate_id}`" in readable
    assert "SLSA_BUILD_LEVEL_UNEVALUATED" in readable
    assert "SLSA_SOURCE_LEVEL_UNEVALUATED" in readable
    assert "not a SLSA level" in readable
    assert "https://slsa.dev/provenance/v1" in readable
    assert "signed-release-tag" in readable
