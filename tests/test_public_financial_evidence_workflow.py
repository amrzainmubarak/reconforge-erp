from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "public-financial-evidence.yml"
PROTOCOL = ROOT / "docs" / "validation" / "public-financial-evidence.md"
ATTESTATION_TEMPLATE = ROOT / "docs" / "execution" / "P3_EXT_001_OPEN_SOURCE_OPERATOR_ATTESTATION_TEMPLATE.md"
SECURITY_PROTOCOL = ROOT / "docs" / "security" / "open-source-independent-review-protocol.md"


def test_public_evidence_workflow_is_manual_least_privilege_and_sha_pinned() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.load(raw, Loader=yaml.BaseLoader)

    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {}
    job = workflow["jobs"]["verify-public-data"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
    }
    action_refs = re.findall(r"^\s*uses:\s*([^\s#]+)", raw, re.MULTILINE)
    assert Counter(action_refs) == Counter(
        {
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1": 1,
            "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97": 1,
            "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9": 1,
            "actions/attest@f7c74d28b9d84cb8768d0b8ca14a4bac6ef463e6": 1,
            "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a": 1,
        }
    )
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", ref) for ref in action_refs)
    for forbidden in (
        "pull_request:",
        "push:",
        "schedule:",
        "contents: write",
        "packages: write",
        "continue-on-error",
        "${{ secrets.",
    ):
        assert forbidden not in raw


def test_public_evidence_workflow_is_exact_fail_closed_and_provenance_bound() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8")
    runner = (ROOT / ".github" / "scripts" / "verify_public_financial_evidence.py").read_text(
        encoding="utf-8"
    )

    for required in (
        "uv sync --locked --extra dev --no-editable --python 3.12",
        "--allow-network",
        "--execution-scope external-operator-candidate",
        "sha256sum --check public-evidence/SHA256SUMS",
        "--signer-workflow",
        "--signer-digest",
        "--source-ref",
        "--source-digest",
        "--deny-self-hosted-runners",
        "persist-credentials: false",
        "This candidate is not an accepted external pilot or independent security review.",
    ):
        assert required in raw
    assert "build_opener(ProxyHandler({}), _SameOriginRedirectHandler())" in runner
    assert '"git", "status", "--porcelain=v1", "--untracked-files=all"' in runner


def test_public_evidence_protocols_preserve_external_and_security_gates() -> None:
    protocol = PROTOCOL.read_text(encoding="utf-8")
    attestation = ATTESTATION_TEMPLATE.read_text(encoding="utf-8")
    security = SECURITY_PROTOCOL.read_text(encoding="utf-8")

    assert "three distinct independent" in protocol
    assert "operators" in protocol
    assert "does not automatically close `P3-EXT-001`" in protocol
    assert re.search(r"do not satisfy\s+`P3-EXT-002`", protocol)
    assert "Workflow run URL" in attestation
    assert "Reproducibility SHA-256" in attestation
    assert "Conflict-of-interest declaration" in attestation
    assert "three accepted attestations" in attestation
    assert "Private vulnerability reporting is currently disabled" in security
    assert "must not be filed in a public issue" in security
    assert "qualified independent human reviewer" in security
