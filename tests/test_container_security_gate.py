from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
SCRIPT = SCRIPTS / "validate_container_security.py"
SCHEMA = ROOT / "docs" / "schemas" / "container_security_evidence.schema.json"
POLICY = ROOT / "docs" / "security" / "supply-chain-policy.v1.json"
LOCAL_EVIDENCE = ROOT / "docs" / "execution" / "CONTAINER_SECURITY_LOCAL_2026-08-22.json"
CONFIG_DIGEST = "sha256:" + "a" * 64
MANIFEST_DIGEST = "sha256:" + "b" * 64


def _load_module() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location("validate_container_security", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


MODULE = _load_module()
ContainerSecurityError = MODULE.ContainerSecurityError


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _artifact(index: int, *, licensed: bool = True) -> dict[str, Any]:
    name = "python" if index == 0 else f"package-{index}"
    version = "3.11.16" if index == 0 else "1.0.0"
    package_type = "binary" if index == 0 else "python"
    purl = "pkg:generic/python@3.11.16" if index == 0 else f"pkg:pypi/{name}@{version}"
    return {
        "id": f"artifact-{index}",
        "name": name,
        "version": version,
        "type": package_type,
        "purl": purl,
        "licenses": ([{"value": "MIT", "spdxExpression": "MIT"}] if licensed else []),
    }


def _syft(*, licensed: int = 9) -> dict[str, Any]:
    return {
        "artifacts": [_artifact(index, licensed=index < licensed) for index in range(10)],
        "descriptor": {
            "name": "syft",
            "version": "1.51.0",
            "configuration": {
                "search": {"scope": "squashed"},
                "licenses": {"coverage": 75},
            },
        },
        "schema": {"version": "16.1.10"},
        "source": {
            "type": "image",
            "name": "ghcr.io/amrzainmubarak/reconforge-erp",
            "version": "0.7.1",
            "metadata": {
                "imageID": CONFIG_DIGEST,
                "manifestDigest": MANIFEST_DIGEST,
                "architecture": "amd64",
                "os": "linux",
            },
        },
        "distro": {"id": "alpine", "versionID": "3.24.1"},
    }


def _finding(*, severity: str = "High", identifier: str = "CVE-2026-0001") -> dict[str, Any]:
    return {
        "vulnerability": {
            "id": identifier,
            "severity": severity,
            "namespace": "nvd:cpe",
            "fix": {"state": "unknown"},
        },
        "artifact": {
            "name": "python",
            "version": "3.11.16",
            "purl": "pkg:generic/python@3.11.16",
        },
        "matchDetails": [{"type": "cpe-match"}],
    }


def _grype(*, matches: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "matches": [] if matches is None else matches,
        "ignoredMatches": [],
        "source": {
            "type": "image",
            "target": {
                "imageID": CONFIG_DIGEST,
                "manifestDigest": MANIFEST_DIGEST,
                "architecture": "amd64",
                "os": "linux",
            },
        },
        "descriptor": {
            "name": "grype",
            "version": "0.117.0",
            "timestamp": "2026-08-22T12:00:00Z",
            "configuration": {
                "output": ["json"],
                "exclude": [],
                "externalSources": {"enable": False},
                "search": {"scope": "squashed"},
                "vex-documents": ["docs/security/container-runtime.openvex.json"],
            },
            "db": {
                "status": {
                    "built": "2026-08-22T06:00:00Z",
                    "schemaVersion": "v6.1.9",
                    "valid": True,
                }
            },
        },
    }


def _write(path: Path, document: dict[str, Any]) -> None:
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _evaluate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    syft: dict[str, Any] | None = None,
    grype: dict[str, Any] | None = None,
    active: list[dict[str, Any]] | None = None,
    scanner_exit_code: int = 0,
) -> tuple[dict[str, Any], bool]:
    policy = _json(POLICY)
    monkeypatch.setattr(
        MODULE,
        "validate_project",
        lambda _root, _as_of: (deepcopy(policy), [] if active is None else active, 0, 0, 0),
    )
    syft_path = tmp_path / "inventory.syft.json"
    grype_path = tmp_path / "report.grype.json"
    _write(syft_path, _syft() if syft is None else syft)
    _write(grype_path, _grype() if grype is None else grype)
    return MODULE.build_evidence(
        project_root=ROOT,
        syft_json=syft_path,
        grype_report=grype_path,
        scanner_exit_code=scanner_exit_code,
        image_config_digest=CONFIG_DIGEST,
        as_of=date(2026, 8, 22),
    )


def test_clean_exact_image_gate_passes_and_matches_closed_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence, blocked = _evaluate(tmp_path, monkeypatch)

    assert blocked is False
    assert evidence["status"] == "passed"
    assert evidence["blockers"] == []
    assert evidence["image"]["config_digest"] == CONFIG_DIGEST
    assert evidence["license_inventory"]["coverage_basis_points"] == 9000
    schema = _json(SCHEMA)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(evidence),
        key=lambda error: list(error.path),
    )
    assert not errors, "\n".join(error.message for error in errors)


def test_checked_local_blocked_evidence_matches_closed_schema() -> None:
    schema = _json(SCHEMA)
    evidence = _json(LOCAL_EVIDENCE)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(evidence),
        key=lambda error: list(error.path),
    )
    assert not errors, "\n".join(error.message for error in errors)
    assert evidence["status"] == "blocked"
    assert evidence["vulnerabilities"]["counts"]["high"] == 5
    assert len(evidence["blockers"]) == 2


def test_high_is_blocked_but_an_exact_active_container_exception_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = _grype(matches=[_finding()])
    evidence, blocked = _evaluate(tmp_path, monkeypatch, grype=report)
    assert blocked is True
    assert evidence["status"] == "blocked"
    assert evidence["vulnerabilities"]["counts"]["high"] == 1
    assert evidence["vulnerabilities"]["critical_or_high_findings"][0]["exception_id"] is None

    exception = {
        "id": "SC-EXC-0001",
        "ecosystem": "container",
        "kind": "vulnerability",
        "subject": "python",
        "identifiers": ["CVE-2026-0001"],
    }
    excepted, excepted_blocked = _evaluate(
        tmp_path, monkeypatch, grype=report, active=[exception]
    )
    assert excepted_blocked is False
    assert excepted["active_exception_count"] == 1
    assert (
        excepted["vulnerabilities"]["critical_or_high_findings"][0]["exception_id"]
        == "SC-EXC-0001"
    )


def test_critical_cannot_be_excepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exception = {
        "id": "SC-EXC-0001",
        "ecosystem": "container",
        "kind": "vulnerability",
        "subject": "python",
        "identifiers": ["CVE-2026-0001"],
    }
    evidence, blocked = _evaluate(
        tmp_path,
        monkeypatch,
        grype=_grype(matches=[_finding(severity="Critical")]),
        active=[exception],
    )
    assert blocked is True
    assert "cannot be excepted" in evidence["blockers"][0]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda syft, grype: syft["source"]["metadata"].update(imageID="sha256:" + "c" * 64), "configuration"),
        (lambda syft, grype: grype["source"]["target"].update(manifestDigest="sha256:" + "c" * 64), "not bound"),
        (lambda syft, grype: grype["descriptor"].update(version="0.116.0"), "pinned tool"),
        (lambda syft, grype: grype["descriptor"]["db"]["status"].update(built="2026-08-15T00:00:00Z"), "age"),
        (lambda syft, grype: grype.update(ignoredMatches=[_finding()]), "governed VEX"),
    ],
)
def test_gate_rejects_unbound_stale_or_suppressed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: Any,
    message: str,
) -> None:
    syft = _syft()
    grype = _grype()
    mutation(syft, grype)
    with pytest.raises(ContainerSecurityError, match=message):
        _evaluate(tmp_path, monkeypatch, syft=syft, grype=grype)


def test_license_coverage_unknown_severity_and_operational_failure_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence, blocked = _evaluate(tmp_path, monkeypatch, syft=_syft(licensed=8))
    assert blocked is True
    assert "license inventory coverage" in evidence["blockers"][0]

    unknown, unknown_blocked = _evaluate(
        tmp_path, monkeypatch, grype=_grype(matches=[_finding(severity="Unknown")])
    )
    assert unknown_blocked is True
    assert "unknown-severity" in unknown["blockers"][0]

    with pytest.raises(ContainerSecurityError, match="operationally"):
        _evaluate(tmp_path, monkeypatch, scanner_exit_code=2)


def test_exact_reviewed_fixed_vex_is_recorded_without_weakening_other_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed = _finding(identifier="CVE-2026-3644")
    fixed["appliedIgnoreRules"] = [{"namespace": "vex", "vex-status": "fixed"}]
    remaining = _finding(identifier="CVE-2026-9999")
    report = _grype(matches=[remaining])
    report["ignoredMatches"] = [fixed]

    evidence, blocked = _evaluate(tmp_path, monkeypatch, grype=report)

    assert blocked is True
    assert evidence["vulnerabilities"]["counts"]["high"] == 2
    assert evidence["vex"]["reviewed_fixed_statements"] == 3
    assert evidence["vex"]["applied_fixed_findings"] == 1
    findings = evidence["vulnerabilities"]["critical_or_high_findings"]
    assert [item["id"] for item in findings] == ["CVE-2026-3644", "CVE-2026-9999"]
    assert findings[0]["vex_status"] == "fixed"
    assert findings[1]["vex_status"] is None
    assert evidence["blockers"] == [
        "unexcepted high finding CVE-2026-9999 for python@3.11.16"
    ]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda vex: vex.update(
                timestamp="2026-07-01T00:00:00Z",
                last_updated="2026-07-01T00:00:00Z",
            ),
            "older than",
        ),
        (
            lambda vex: vex["statements"][0].update(status="not_affected"),
            "incomplete",
        ),
        (
            lambda vex: vex["statements"][0]["products"][0].update(
                {"@id": "pkg:generic/python@3.11.15"}
            ),
            "absent from",
        ),
        (
            lambda vex: vex["statements"][0].update(unreviewed=True),
            "unreviewed fields",
        ),
    ],
)
def test_vex_staleness_status_product_and_shape_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: Any,
    message: str,
) -> None:
    original_load = MODULE._load_json

    def load_with_mutated_vex(path: Path, *, label: str) -> dict[str, Any]:
        document = original_load(path, label=label)
        if label == "OpenVEX document":
            document = deepcopy(document)
            mutation(document)
        return document

    monkeypatch.setattr(MODULE, "_load_json", load_with_mutated_vex)
    with pytest.raises(ContainerSecurityError, match=message):
        _evaluate(tmp_path, monkeypatch)


def test_vex_cannot_suppress_critical_or_unconfigured_medium(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for severity in ("Critical", "Medium"):
        finding = _finding(severity=severity, identifier="CVE-2026-3644")
        finding["appliedIgnoreRules"] = [{"namespace": "vex", "vex-status": "fixed"}]
        report = _grype()
        report["ignoredMatches"] = [finding]
        with pytest.raises(ContainerSecurityError, match="suppress"):
            _evaluate(tmp_path, monkeypatch, grype=report)


def test_loader_rejects_duplicate_json_keys_and_links(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"a": 1, "a": 2}\n', encoding="utf-8")
    with pytest.raises(ContainerSecurityError, match="duplicate key"):
        MODULE._load_json(duplicate, label="test")

    target = tmp_path / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "link.json"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links are not available in this environment")
    with pytest.raises(ContainerSecurityError, match="regular non-link"):
        MODULE._load_json(link, label="test")
