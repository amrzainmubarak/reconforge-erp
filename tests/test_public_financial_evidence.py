from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import subprocess
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from urllib.request import Request

import pytest
from pydantic import ValidationError

from reconforge.benchmark.public_financial import (
    PublicFinancialEvidenceError,
    PublicFinancialEvidenceManifest,
    canonical_sha256,
    load_public_financial_manifest,
    run_public_financial_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / ".github" / "scripts" / "verify_public_financial_evidence.py"
RETAINED_REPORT = ROOT / "docs" / "execution" / "PUBLIC_FINANCIAL_EVIDENCE_RUN_2026-08-01.json"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_public_financial_evidence", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = _load_runner()


def _csv_bytes(headers: tuple[str, ...], rows: list[tuple[str, ...]], *, encoding: str = "utf-8") -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue().encode(encoding)


def _artifact(
    artifact_id: str,
    content: bytes,
    *,
    host: str,
    data_format: str,
    encoding: str,
) -> dict[str, object]:
    content_type = "application/json" if data_format == "json" else "text/csv"
    return {
        "id": artifact_id,
        "publisher": "Public test publisher",
        "dataset": "Bounded public test dataset",
        "license": "Open test licence",
        "metadata_url": (
            "https://fiscaldata.treasury.gov/test"
            if host == "api.fiscaldata.treasury.gov"
            else "https://financesone.worldbank.org/test"
            if host == "datacatalogapi.worldbank.org"
            else "https://ckan.publishing.service.gov.uk/test"
        ),
        "url": f"https://{host}/public/{artifact_id}.{data_format}",
        "format": data_format,
        "encoding": encoding,
        "expected_sha256": hashlib.sha256(content).hexdigest(),
        "max_bytes": len(content) + 100,
        "allowed_content_types": [content_type],
    }


def _fixture() -> tuple[PublicFinancialEvidenceManifest, dict[str, bytes]]:
    treasury_record = {
        "record_date": "2025-07-01",
        "debt_held_public_amt": "10.00",
        "intragov_hold_amt": "2.00",
        "tot_pub_debt_out_amt": "12.00",
        "src_line_nbr": "1",
        "record_fiscal_year": "2025",
        "record_fiscal_quarter": "4",
        "record_calendar_year": "2025",
        "record_calendar_quarter": "3",
        "record_calendar_month": "07",
        "record_calendar_day": "01",
    }
    treasury_json = json.dumps(
        {"data": [treasury_record], "meta": {"total-count": 1}, "links": {}}, separators=(",", ":")
    ).encode()
    treasury_csv = _csv_bytes(tuple(treasury_record), [tuple(treasury_record.values())])

    world_record = {
        "category": "Commitments",
        "country": "Example",
        "development_policy": "1.000000",
        "investment_lending": "2.000000",
        "organization": "IBRD",
        "private_sector_window": "0.000000",
        "program_for_results": "0.000000",
        "region": "EXAMPLE REGION",
        "time_period": "FY24",
        "total": "3.000000",
    }
    world_json_record = {
        key: Decimal(value) if key in {
            "development_policy",
            "investment_lending",
            "private_sector_window",
            "program_for_results",
            "total",
        } else value
        for key, value in world_record.items()
    }
    world_json = json.dumps(
        {"count": 1, "data": [world_json_record]},
        default=lambda value: int(value) if value == value.to_integral() else str(value),
        separators=(",", ":"),
    ).encode()
    world_csv = _csv_bytes(tuple(world_record), [tuple(world_record.values())])

    uk_headers = (
        "Department",
        "Organisation",
        "Check Date",
        "Expense type",
        "Supplier",
        "Invoice number",
        "Invoice Amount",
        "Postcode",
    )
    uk_january_rows = [
        ("DFE", "Department", "10/01/2026", "Grant", "SUPPLIER-A", "INV-1", "£25,000.00", "AA1 1AA"),
        ("DFE", "Department", "11/01/2026", "Grant", "SUPPLIER-A", "INV-1", "-£25,001.00", "AA1 1AA"),
    ]
    uk_february_rows = [
        ("DFE", "Department", "12/02/2026", "Grant", "SUPPLIER-B", "INV-2", "£25,002.00", "BB1 1BB"),
    ]
    uk_january = _csv_bytes(uk_headers, uk_january_rows, encoding="cp1252")
    uk_february = _csv_bytes(uk_headers, uk_february_rows, encoding="utf-8-sig")

    contents = {
        "treasury-json": treasury_json,
        "treasury-csv": treasury_csv,
        "world-json": world_json,
        "world-csv": world_csv,
        "uk-january": uk_january,
        "uk-february": uk_february,
    }
    normalized_world = {
        **world_record,
        "development_policy": "1",
        "investment_lending": "2",
        "private_sector_window": "0",
        "program_for_results": "0",
        "total": "3",
    }
    january_canonical = [
        {
            "month": "2026-01",
            "department": row[0],
            "organisation": row[1],
            "check_date": datetime.strptime(row[2], "%d/%m/%Y").date().isoformat(),
            "expense_type": row[3],
            "supplier": row[4],
            "invoice_number": row[5],
            "amount": row[6].replace("£", "").replace(",", ""),
            "postcode": row[7],
            "currency": "GBP",
        }
        for row in uk_january_rows
    ]
    february_canonical = [
        {
            "month": "2026-02",
            "department": row[0],
            "organisation": row[1],
            "check_date": datetime.strptime(row[2], "%d/%m/%Y").date().isoformat(),
            "expense_type": row[3],
            "supplier": row[4],
            "invoice_number": row[5],
            "amount": row[6].replace("£", "").replace(",", ""),
            "postcode": row[7],
            "currency": "GBP",
        }
        for row in uk_february_rows
    ]
    for rows in (january_canonical, february_canonical):
        rows.sort(key=lambda row: tuple(row[key] for key in row))
    combined = sorted(january_canonical + february_canonical, key=lambda row: tuple(row[key] for key in row))
    document = {
        "schema_version": "reconforge-public-financial-evidence-manifest-v1",
        "manifest_id": "public-test-evidence",
        "captured_at": "2026-08-01T10:00:00+03:00",
        "artifacts": [
            _artifact(
                "treasury-json",
                treasury_json,
                host="api.fiscaldata.treasury.gov",
                data_format="json",
                encoding="utf-8",
            ),
            _artifact(
                "treasury-csv",
                treasury_csv,
                host="api.fiscaldata.treasury.gov",
                data_format="csv",
                encoding="utf-8-sig",
            ),
            _artifact(
                "world-json",
                world_json,
                host="datacatalogapi.worldbank.org",
                data_format="json",
                encoding="utf-8",
            ),
            _artifact(
                "world-csv",
                world_csv,
                host="datacatalogapi.worldbank.org",
                data_format="csv",
                encoding="utf-8-sig",
            ),
            _artifact(
                "uk-january",
                uk_january,
                host="admin.opendatani.gov.uk",
                data_format="csv",
                encoding="auto-strict",
            ),
            _artifact(
                "uk-february",
                uk_february,
                host="admin.opendatani.gov.uk",
                data_format="csv",
                encoding="auto-strict",
            ),
        ],
        "experiments": [
            {
                "id": "treasury-test",
                "kind": "treasury-debt-cross-format",
                "artifact_ids": ["treasury-json", "treasury-csv"],
                "expected_record_count": 1,
                "expected_canonical_sha256": canonical_sha256([treasury_record]),
                "expected_equation_violations": 0,
            },
            {
                "id": "world-bank-test",
                "kind": "world-bank-cross-format",
                "json_artifact_ids": ["world-json"],
                "csv_artifact_ids": ["world-csv"],
                "selected_time_period": "FY24",
                "accounting_date": "2024-06-30",
                "expected_source_record_count": 1,
                "expected_selected_record_count": 1,
                "expected_canonical_sha256": canonical_sha256([normalized_world]),
                "expected_component_equation_violations": 0,
            },
            {
                "id": "uk-test",
                "kind": "uk-spending-ingress-replay",
                "artifact_ids": ["uk-january", "uk-february"],
                "period_by_artifact": {"uk-january": "2026-01", "uk-february": "2026-02"},
                "expected_encoding_by_artifact": {"uk-january": "cp1252", "uk-february": "utf-8-sig"},
                "expected_rows_by_artifact": {"uk-january": 2, "uk-february": 1},
                "expected_totals_by_artifact": {"uk-january": "-1.00", "uk-february": "25002.00"},
                "expected_digests_by_artifact": {
                    "uk-january": canonical_sha256(january_canonical),
                    "uk-february": canonical_sha256(february_canonical),
                },
                "expected_record_count": 3,
                "expected_canonical_sha256": canonical_sha256(combined),
                "expected_negative_amount_count": 1,
                "expected_reference_collision_groups": 1,
                "expected_threshold_violations": 0,
            },
        ],
    }
    return PublicFinancialEvidenceManifest.model_validate(document), contents


def test_public_financial_evidence_is_exact_redacted_and_permutation_stable() -> None:
    manifest, contents = _fixture()
    report = run_public_financial_evidence(manifest, dict(reversed(list(contents.items()))))

    assert report["status"] == "passed"
    assert report["checks"] == {
        "artifact_integrity": True,
        "closed_schema": True,
        "exact_decimal_financial_inputs": True,
        "cross_format_semantic_parity": True,
        "financial_equations": True,
        "deterministic_matching": True,
        "row_permutation_stability": True,
        "raw_identifiers_excluded_from_report": True,
    }
    experiments = {value["kind"]: value for value in report["experiments"]}
    assert experiments["treasury-debt-cross-format"]["matching"]["matched_count"] == 1
    assert experiments["world-bank-cross-format"]["matching"]["matched_count"] == 1
    assert experiments["uk-spending-ingress-replay"]["matching"]["matched_count"] == 3
    assert experiments["uk-spending-ingress-replay"]["negative_amount_count"] == 1
    assert experiments["uk-spending-ingress-replay"]["reference_collision_groups"] == 1
    serialized = json.dumps(report, sort_keys=True)
    assert "SUPPLIER-A" not in serialized
    assert "INV-1" not in serialized
    assert report["claim_boundary"]["qualifies_as_external_pilot_without_operator_attestation"] is False


def test_public_financial_evidence_rejects_tampering_missing_payloads_and_schema_expansion() -> None:
    manifest, contents = _fixture()
    tampered = dict(contents)
    tampered["treasury-json"] += b"\n"
    with pytest.raises(PublicFinancialEvidenceError, match="SHA-256"):
        run_public_financial_evidence(manifest, tampered)

    missing = dict(contents)
    missing.pop("world-csv")
    with pytest.raises(PublicFinancialEvidenceError, match="exactly match"):
        run_public_financial_evidence(manifest, missing)

    expanded = deepcopy(manifest.model_dump(mode="json"))
    expanded["unexpected"] = True
    with pytest.raises(ValidationError):
        PublicFinancialEvidenceManifest.model_validate(expanded)


def test_public_financial_evidence_rejects_duplicate_json_keys_and_truncated_csv_rows() -> None:
    manifest, contents = _fixture()

    duplicate_json = contents["treasury-json"].replace(b'"data":', b'"data":[],"data":', 1)
    duplicate_manifest = deepcopy(manifest.model_dump(mode="json"))
    duplicate_manifest["artifacts"][0]["expected_sha256"] = hashlib.sha256(duplicate_json).hexdigest()
    duplicate_manifest["artifacts"][0]["max_bytes"] = len(duplicate_json) + 100
    with pytest.raises(PublicFinancialEvidenceError, match="not valid declared JSON"):
        run_public_financial_evidence(
            PublicFinancialEvidenceManifest.model_validate(duplicate_manifest),
            {**contents, "treasury-json": duplicate_json},
        )

    truncated_csv = contents["uk-february"].rsplit(b",", 1)[0] + b"\r\n"
    truncated_manifest = deepcopy(manifest.model_dump(mode="json"))
    artifact = next(value for value in truncated_manifest["artifacts"] if value["id"] == "uk-february")
    artifact["expected_sha256"] = hashlib.sha256(truncated_csv).hexdigest()
    artifact["max_bytes"] = len(truncated_csv) + 100
    with pytest.raises(PublicFinancialEvidenceError, match="malformed CSV rows"):
        run_public_financial_evidence(
            PublicFinancialEvidenceManifest.model_validate(truncated_manifest),
            {**contents, "uk-february": truncated_csv},
        )


def test_public_financial_manifest_rejects_non_allowlisted_or_credentialed_urls() -> None:
    manifest, _contents = _fixture()
    for url in ("http://api.fiscaldata.treasury.gov/data", "https://user:secret@example.com/data"):
        expanded = deepcopy(manifest.model_dump(mode="json"))
        expanded["artifacts"][0]["url"] = url
        with pytest.raises(ValidationError):
            PublicFinancialEvidenceManifest.model_validate(expanded)


def test_public_financial_runner_rejects_cross_origin_redirect_and_extra_offline_file(tmp_path: Path) -> None:
    request = Request("https://admin.opendatani.gov.uk/dataset/file.csv")
    handler = RUNNER._SameOriginRedirectHandler()
    with pytest.raises(PublicFinancialEvidenceError, match="redirect"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://example.com/stolen.csv",
        )

    manifest, contents = _fixture()
    for artifact in manifest.artifacts:
        (tmp_path / f"{artifact.id}.{artifact.format}").write_bytes(contents[artifact.id])
    (tmp_path / "unexpected.csv").write_text("unexpected", encoding="utf-8")
    with pytest.raises(PublicFinancialEvidenceError, match="exactly match"):
        RUNNER.load_artifact_directory(manifest, tmp_path)


def test_public_financial_runner_binds_only_a_clean_exact_git_revision(tmp_path: Path) -> None:
    subprocess.run(("git", "init", "--quiet"), cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("governed\n", encoding="utf-8")
    subprocess.run(("git", "add", "tracked.txt"), cwd=tmp_path, check=True)
    subprocess.run(
        (
            "git",
            "-c",
            "user.name=ReconForge Test",
            "-c",
            "user.email=reconforge-test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "test fixture",
        ),
        cwd=tmp_path,
        check=True,
    )
    revision = RUNNER._source_revision(tmp_path)
    assert len(revision) == 40

    (tmp_path / "untracked.txt").write_text("drift\n", encoding="utf-8")
    with pytest.raises(PublicFinancialEvidenceError, match="clean source revision"):
        RUNNER._source_revision(tmp_path)


def test_governed_public_manifest_is_closed_real_data_but_not_external_attestation() -> None:
    manifest = load_public_financial_manifest("docs/validation/public-financial-evidence-manifest.v1.yaml")

    assert len(manifest.artifacts) == 11
    assert {experiment.kind for experiment in manifest.experiments} == {
        "treasury-debt-cross-format",
        "world-bank-cross-format",
        "uk-spending-ingress-replay",
    }
    assert all(artifact.url.startswith("https://") for artifact in manifest.artifacts)
    assert all(artifact.expected_sha256 != "0" * 64 for artifact in manifest.artifacts)


def test_retained_live_public_financial_report_is_exact_redacted_and_claim_bounded() -> None:
    content = RETAINED_REPORT.read_bytes()
    report = json.loads(content)

    assert hashlib.sha256(content).hexdigest() == "bcc1147b98997dd2d8149f5b060e66638ea483d939037d87e0a6f5b402251859"
    assert report["status"] == "passed"
    assert report["execution"]["scope"] == "maintainer-local"
    assert report["execution"]["source_revision"] == "d792477deb5bbeb1591a8c7bf9c730594b551d0c"
    assert report["execution"]["network_calls"] == 11
    assert len(report["artifact_receipts"]) == 11
    assert sum(value["matching"]["matched_count"] for value in report["experiments"]) == 967
    assert report["reproducibility_sha256"] == (
        "890a4aa8f7b362981bfdd1f0f333d3bad55a886d842c0ff0a82ff165c48e26c5"
    )
    assert report["claim_boundary"] == {
        "external_operator_count": 0,
        "qualifies_as_external_pilot_without_operator_attestation": False,
        "qualifies_as_independent_security_review": False,
        "real_public_financial_data": True,
    }
    lowered = content.lower()
    assert all(marker not in lowered for marker in (b'"supplier"', b'"invoice_number"', b'"postcode"'))
