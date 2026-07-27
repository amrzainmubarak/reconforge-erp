from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.evidence.binder import (
    collect_evidence_cases,
    generate_evidence_binder,
    read_evidence_index,
    verify_evidence_index_payload,
)
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
)

runner = CliRunner()


def _write_boundary_source(path: Path, value: str = "60.000000000000000001") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    source = path / "stock_gl_all_exceptions.csv"
    source.write_text(
        f"exception_type,risk_score\nboundary,{value}\n",
        encoding="utf-8",
    )
    return source


def _index(path: Path) -> dict[str, object]:
    return json.loads((path / "evidence_index.json").read_text(encoding="utf-8"))


def test_strict_csv_ingress_keeps_fractional_boundary_visible_legacy_collapses(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write_boundary_source(source)

    legacy = collect_evidence_cases(
        source,
        financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
    )
    strict = collect_evidence_cases(
        source,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )

    assert legacy == []
    assert len(strict) == 1
    assert strict[0].risk_score is None
    assert strict[0].risk_score_status == "invalid"
    assert strict[0].severity == "Data Quality"
    assert strict[0].source_record["risk_score"] == "60.000000000000000001"


def test_current_index_schema_policy_fingerprints_and_local_recheck(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_boundary_source(source, "61")
    output = tmp_path / "evidence"
    generate_evidence_binder(
        source,
        output,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    payload = _index(output)
    schema = json.loads(
        Path("docs/schemas/evidence_index.schema.json").read_text(encoding="utf-8")
    )

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)
    document = read_evidence_index(output / "evidence_index.json")
    verify_evidence_index_payload(payload, source_dir=source)
    assert document.schema_version == 3
    assert document.verification_status == "verified"
    assert payload["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert payload["input_files"] == [
        {
            "path": "stock_gl_all_exceptions.csv",
            "size_bytes": (source / "stock_gl_all_exceptions.csv").stat().st_size,
            "sha256": payload["input_files"][0]["sha256"],
        }
    ]


def test_direct_default_writes_current_strict_schema_v3(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_boundary_source(source, "61")
    output = tmp_path / "strict-default"
    generate_evidence_binder(source, output)
    payload = _index(output)
    schema = json.loads(
        Path("docs/schemas/evidence_index.schema.json").read_text(encoding="utf-8")
    )

    Draft202012Validator(schema).validate(payload)
    document = read_evidence_index(output / "evidence_index.json")
    assert payload["schema_version"] == 3
    assert payload["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert document.verification_status == "verified"


def test_index_verifier_detects_policy_artifact_path_and_source_tampering(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source_file = _write_boundary_source(source, "61")
    output = tmp_path / "evidence"
    generate_evidence_binder(
        source,
        output,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    payload = _index(output)

    changed_policy = json.loads(json.dumps(payload))
    changed_policy["risk_score_policy"] = "tampered"
    with pytest.raises(ValueError, match="risk-score policy"):
        verify_evidence_index_payload(changed_policy)

    changed_timestamp = json.loads(json.dumps(payload))
    changed_timestamp["generated_at"] = "tampered"
    with pytest.raises(ValueError, match="artifact digest"):
        verify_evidence_index_payload(changed_timestamp)

    unsafe = json.loads(json.dumps(payload))
    unsafe["input_files"][0]["path"] = "../outside.csv"
    with pytest.raises(ValueError, match="unsafe input path"):
        verify_evidence_index_payload(unsafe)

    source_file.write_text("exception_type,risk_score\nboundary,62\n", encoding="utf-8")
    with pytest.raises(ValueError, match="input fingerprint"):
        verify_evidence_index_payload(payload, source_dir=source)


def test_content_digest_is_path_independent_and_excludes_generation_time(
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "a" / "source"
    source_b = tmp_path / "b" / "relocated"
    _write_boundary_source(source_a, "61")
    _write_boundary_source(source_b, "61")
    output_a = tmp_path / "evidence-a"
    output_b = tmp_path / "evidence-b"

    generate_evidence_binder(
        source_a,
        output_a,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    generate_evidence_binder(
        source_b,
        output_b,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )

    first = _index(output_a)
    second = _index(output_b)
    assert first["content_digest"] == second["content_digest"]
    assert first["input_files"] == second["input_files"]


def test_cli_evidence_binder_selects_strict_policy(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_boundary_source(source)
    output = tmp_path / "evidence"

    result = runner.invoke(
        app,
        [
            "report",
            "evidence-binder",
            "--input",
            str(source),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    payload = _index(output)
    assert payload["schema_version"] == 3
    assert payload["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert payload["cases"][0]["risk_score_status"] == "invalid"


def test_unknown_evidence_policy_fails_before_path_or_output(tmp_path: Path) -> None:
    missing = tmp_path / "987654321.01"
    output = tmp_path / "evidence"

    with pytest.raises(ValueError, match="unsupported financial input policy") as captured:
        generate_evidence_binder(
            missing,
            output,
            financial_input_policy="unknown-v9",  # type: ignore[arg-type]
        )

    assert "987654321.01" not in str(captured.value)
    assert not output.exists()
