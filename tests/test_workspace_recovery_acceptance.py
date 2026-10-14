"""Independent synthetic report/case/private-proof joins; no native workload rerun."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.test_browser_diagnostic_redaction import PASSWORD, workspace_report

ROOT = Path(__file__).resolve().parents[1]
specification = importlib.util.spec_from_file_location(
    "owned_workspace_recovery_acceptance", ROOT / ".github/scripts/verify_erp_expansion_browser.py",
)
assert specification is not None and specification.loader is not None
runner = importlib.util.module_from_spec(specification)
specification.loader.exec_module(runner)

PROJECT = "customer-returns-chromium"
BUSINESS_TITLE = "actual original credit release partial cash refunds lost responses and bilingual native evidence"
RECOVERY_TITLE = "actual rejected lazy workspace preserves {locale} navigation and manual recovery without financial replay"


def native_join_fixture(tmp_path: Path) -> tuple[Path, dict[str, Any], dict[str, Path]]:
    private = tmp_path / "private-native-run"
    artifacts = private / "playwright-artifacts"
    artifacts.mkdir(parents=True)
    paths: dict[str, Path] = {}

    def spec(title: str, file: str, attachments: list[dict[str, Any]]) -> dict[str, Any]:
        return {"title": title, "file": file, "ok": True, "id": hashlib.sha256((file + title).encode()).hexdigest(),
            "line": 1, "column": 1, "tags": [], "tests": [{"projectId": PROJECT, "projectName": PROJECT,
                "expectedStatus": "passed", "status": "expected", "annotations": [], "timeout": 30000,
                "results": [{"status": "passed", "retry": 0, "errors": [], "duration": 123,
                    "workerIndex": 0, "parallelIndex": 0, "startTime": "2026-10-14T00:00:00.000Z",
                    "stdout": [], "stderr": [], "annotations": [], "attachments": attachments}]}]}

    recovery = []
    for locale in ("en", "ar"):
        case = artifacts / f"workspace-recovery-cycles--synthetic-{locale}-{PROJECT}"
        case.mkdir()
        name = f"workspace-recovery-{locale}-original-native-boundary.json"
        sidecar = case / name
        raw = json.dumps(workspace_report("v2", locale), ensure_ascii=False).encode()
        sidecar.write_bytes(raw)
        # Installed Playwright 1.62.0 hashes the ORIGINAL absolute path for the
        # copy filename; SHA256 of full bytes independently joins both originals.
        suffix = hashlib.sha1(str(sidecar).encode(), usedforsecurity=False).hexdigest()
        attachment = case / "attachments" / f"workspace-recovery-{locale}-original-native-boundary-json-{suffix}.json"
        attachment.parent.mkdir()
        attachment.write_bytes(raw)
        paths[locale] = sidecar
        paths[locale + "_attachment"] = attachment
        recovery.append(spec(RECOVERY_TITLE.format(locale=locale), "workspace-recovery-cycles.spec.ts",
            [{"name": name, "contentType": "application/json", "path": str(attachment)}]))
    report = {"config": {"projects": [{"id": PROJECT, "name": PROJECT, "outputDir": str(artifacts),
        "retries": 0, "repeatEach": 1, "testDir": str(ROOT / "apps/web/live"), "testMatch": ["customer-returns-cycles.spec.ts", "workspace-recovery-cycles.spec.ts"]}]},
        "errors": [], "stats": {"expected": 3, "skipped": 0, "unexpected": 0, "flaky": 0,
            "duration": 1234.5, "startTime": "2026-10-14T00:00:00.000Z"},
        "suites": [{"title": "customer-returns-cycles.spec.ts", "file": "customer-returns-cycles.spec.ts",
            "line": 1, "column": 1, "specs": [spec(BUSINESS_TITLE, "customer-returns-cycles.spec.ts", [])]},
            {"title": "workspace-recovery-cycles.spec.ts", "file": "workspace-recovery-cycles.spec.ts",
                "line": 1, "column": 1, "specs": recovery}]}
    return private, report, paths


def write_report(private: Path, report: dict[str, Any]) -> None:
    (private / "playwright.json").write_text(json.dumps(report), encoding="utf-8")


def require(private: Path) -> None:
    runner.require_workspace_recovery_acceptance(private, known_private_values=[PASSWORD])


def recovery_test(report: dict[str, Any], locale: str = "en") -> dict[str, Any]:
    return report["suites"][1]["specs"][0 if locale == "en" else 1]["tests"][0]


def test_genuine_private_attachment_and_sidecar_join_accepts_exact_three_first_attempt_cases(tmp_path: Path) -> None:
    private, report, paths = native_join_fixture(tmp_path)
    original = {name: path.read_bytes() for name, path in paths.items()}
    write_report(private, report)
    require(private)
    assert {name: path.read_bytes() for name, path in paths.items()} == original


@pytest.mark.parametrize("mutation", ["unbound_historical_report", "missing_locale", "duplicate_locale", "extra_spec",
    "business_title", "business_file", "recovery_title", "recovery_file", "suite_file", "multiple_projects",
    "project_id", "project_name", "unexpected_status", "expected_failure", "not_ok", "ok_as_int",
    "failed_result", "retry", "retry_as_bool", "two_results", "no_result", "result_errors", "report_errors",
    "count_as_bool", "skipped", "unexpected", "flaky", "missing_project"])
def test_exact_case_project_outcome_and_first_attempt_binding_rejects_adversarial_report(tmp_path: Path, mutation: str) -> None:
    private, report, _ = native_join_fixture(tmp_path)
    spec = report["suites"][1]["specs"][0]
    test = recovery_test(report)
    result = test["results"][0]
    if mutation == "unbound_historical_report":
        for case in report["suites"][1]["specs"]:
            case["tests"][0]["results"][0]["attachments"] = []
    elif mutation == "missing_locale":
        report["suites"][1]["specs"].pop()
    elif mutation == "duplicate_locale":
        report["suites"][1]["specs"][1] = json.loads(json.dumps(spec))
    elif mutation == "extra_spec":
        report["suites"][1]["specs"].append(json.loads(json.dumps(spec)))
    elif mutation in {"business_title", "business_file"}:
        report["suites"][0]["specs"][0]["title" if mutation == "business_title" else "file"] = "unrelated"
    elif mutation in {"recovery_title", "recovery_file"}:
        spec["title" if mutation == "recovery_title" else "file"] = "unrelated"
    elif mutation == "suite_file":
        report["suites"][1]["file"] = "unrelated.spec.ts"
    elif mutation == "multiple_projects":
        spec["tests"].append(json.loads(json.dumps(test)))
    elif mutation in {"project_id", "project_name"}:
        test["projectId" if mutation == "project_id" else "projectName"] = "other-project"
    elif mutation == "unexpected_status":
        test["status"] = "unexpected"
    elif mutation == "expected_failure":
        test["expectedStatus"] = "failed"
    elif mutation in {"not_ok", "ok_as_int"}:
        spec["ok"] = False if mutation == "not_ok" else 1
    elif mutation == "failed_result":
        result["status"] = "failed"
    elif mutation in {"retry", "retry_as_bool"}:
        result["retry"] = 1 if mutation == "retry" else False
    elif mutation == "two_results":
        test["results"].append(json.loads(json.dumps(result)))
    elif mutation == "no_result":
        test["results"] = []
    elif mutation == "result_errors":
        result["errors"] = [{"message": PASSWORD}]
    elif mutation == "report_errors":
        report["errors"] = [{"message": PASSWORD}]
    elif mutation == "count_as_bool":
        report["stats"]["skipped"] = False
    elif mutation in {"skipped", "unexpected", "flaky"}:
        report["stats"][mutation] = 1
    else:
        report["config"]["projects"] = []
    write_report(private, report)
    with pytest.raises((RuntimeError, ValueError)) as refused:
        require(private)
    assert PASSWORD not in str(refused.value)


@pytest.mark.parametrize("mutation", ["body_only", "external", "relative", "wrong_content_type", "wrong_name", "duplicate",
    "swapped", "wrong_copy_suffix", "missing_copy", "missing_sidecar", "copy_drift", "sidecar_drift", "copy_parent_case",
    "copy_symlink", "sidecar_symlink", "attachment_directory_symlink"])
def test_private_attachment_requires_regular_same_case_exact_original_copy(
    tmp_path: Path, mutation: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    private, report, paths = native_join_fixture(tmp_path)
    attachments = recovery_test(report)["results"][0]["attachments"]
    attachment = attachments[0]
    if mutation == "body_only":
        attachment.pop("path")
        attachment["body"] = paths["en"].read_text(encoding="utf-8")
    elif mutation == "external":
        outside = tmp_path / paths["en_attachment"].name
        outside.write_bytes(paths["en"].read_bytes())
        attachment["path"] = str(outside)
    elif mutation == "relative":
        attachment["path"] = paths["en_attachment"].relative_to(private).as_posix()
    elif mutation == "wrong_content_type":
        attachment["contentType"] = "text/plain"
    elif mutation == "wrong_name":
        attachment["name"] = "oracle.json"
    elif mutation == "duplicate":
        attachments.append(dict(attachment))
    elif mutation == "swapped":
        attachments[0] = dict(recovery_test(report, "ar")["results"][0]["attachments"][0])
    elif mutation == "wrong_copy_suffix":
        wrong = paths["en_attachment"].with_name(paths["en_attachment"].name.replace("boundary-json-", "boundary-"))
        paths["en_attachment"].rename(wrong)
        attachment["path"] = str(wrong)
    elif mutation in {"missing_copy", "missing_sidecar"}:
        paths["en_attachment" if mutation == "missing_copy" else "en"].unlink()
    elif mutation in {"copy_drift", "sidecar_drift"}:
        paths["en_attachment" if mutation == "copy_drift" else "en"].write_bytes(b'{"late_drift":true}')
    elif mutation == "copy_parent_case":
        attachment["path"] = str(paths["ar_attachment"])
    else:
        target = paths["en_attachment"] if mutation == "copy_symlink" else paths["en"]
        directory = mutation == "attachment_directory_symlink"
        if directory:
            target = paths["en_attachment"].parent
        if os.name == "nt":
            # Windows without SeCreateSymbolicLinkPrivilege exercises the
            # exact classified-path denial branch, not OS link creation.
            # Linux executes the actual filesystem symlink attack below.
            original_is_symlink = Path.is_symlink
            monkeypatch.setattr(Path, "is_symlink", lambda item: item == target or original_is_symlink(item))
        else:
            moved = target.with_name("relocated-attachments" if directory else "relocated-original.json")
            target.rename(moved)
            target.symlink_to(moved, target_is_directory=directory)
    write_report(private, report)
    with pytest.raises((RuntimeError, ValueError)) as refused:
        require(private)
    assert PASSWORD not in str(refused.value)


@pytest.mark.parametrize("mutation", ["negative_recovery", "partial_responsive", "wrong_direction", "financial_mutation",
    "original_change", "unknown_extra", "v1_only", "locale_mismatch"])
def test_complete_v2_proof_and_computed_financial_original_equality_required_for_final_case_join(tmp_path: Path, mutation: str) -> None:
    private, report, paths = native_join_fixture(tmp_path)
    proof = json.loads(paths["en"].read_bytes())
    if mutation == "negative_recovery":
        proof["recovered"] = False
    elif mutation == "partial_responsive":
        proof["responsiveChecks"].pop()
    elif mutation == "wrong_direction":
        proof["responsiveChecks"][0]["direction"] = "rtl"
    elif mutation == "financial_mutation":
        proof["financialMutations"] = [{"path": "/api/v1/source", "method": "POST"}]
    elif mutation == "original_change":
        proof["originalAfter"]["stock"]["quantity"] = 4
        proof["rawFinancialOriginalsEqual"] = False
    elif mutation == "unknown_extra":
        proof["Cookie"] = PASSWORD
    elif mutation == "v1_only":
        proof["schema_version"] = "workspace-recovery-native-v1"
        proof.pop("responsiveChecks")
    else:
        proof["locale"] = "ar"
    raw = json.dumps(proof).encode()
    paths["en"].write_bytes(raw)
    paths["en_attachment"].write_bytes(raw)
    write_report(private, report)
    with pytest.raises((RuntimeError, ValueError)) as refused:
        require(private)
    assert PASSWORD not in str(refused.value)


def test_duplicate_report_json_fields_refuse_before_report_or_case_success(tmp_path: Path) -> None:
    private, report, _ = native_join_fixture(tmp_path)
    raw = json.dumps(report)
    (private / "playwright.json").write_text(raw[:-1] + ',"errors":[]}', encoding="utf-8")
    with pytest.raises((RuntimeError, ValueError)):
        require(private)
