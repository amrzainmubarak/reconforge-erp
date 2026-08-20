from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.reports.client_pack import (
    ClientPackOptions,
    generate_client_pack,
    read_client_pack_manifest,
    verify_client_pack_manifest_payload,
)
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    LegacyFinancialInputWarning,
)

runner = CliRunner()


def _write_source(
    path: Path,
    *,
    amount: str = "99.999999999999999999",
) -> Path:
    evidence = path / "evidence"
    evidence.mkdir(parents=True)
    source = evidence / "evidence_index.json"
    source.write_text(
        '{"total_amount":' + amount + ',"display_ratio":0.125}',
        encoding="utf-8",
    )
    return source


def _manifest(path: Path) -> dict[str, object]:
    return json.loads((path / "files_manifest.json").read_text(encoding="utf-8"))


def test_direct_client_pack_options_reject_unsupported_financial_policy() -> None:
    with pytest.raises(ValueError, match="unsupported financial input policy"):
        ClientPackOptions(financial_input_policy="unknown-v9")  # type: ignore[arg-type]


def test_strict_json_redaction_preserves_bucket_boundary_legacy_collapses(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write_source(source)

    strict = generate_client_pack(
        source,
        tmp_path / "strict",
        redact_amounts=True,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    with pytest.warns(LegacyFinancialInputWarning, match="deprecated"):
        legacy = generate_client_pack(
            source,
            tmp_path / "legacy",
            redact_amounts=True,
            financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
        )

    strict_json = json.loads(
        (strict.output_dir / "evidence" / "evidence_index.json").read_text(
            encoding="utf-8"
        )
    )
    legacy_json = json.loads(
        (legacy.output_dir / "evidence" / "evidence_index.json").read_text(
            encoding="utf-8"
        )
    )
    assert strict_json["total_amount"] == "0-99"
    assert legacy_json["total_amount"] == "100-999"
    assert strict_json["display_ratio"] == "0.125"
    assert legacy_json["display_ratio"] == 0.125


def test_current_manifest_schema_policy_hashes_and_local_recheck(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write_source(source, amount="250.25")
    artifacts = generate_client_pack(
        source,
        tmp_path / "output",
        redact_amounts=True,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    payload = _manifest(artifacts.output_dir)
    schema = json.loads(
        Path("docs/schemas/client_pack_manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)
    document = read_client_pack_manifest(artifacts.manifest_path)
    verify_client_pack_manifest_payload(
        payload,
        source_dir=source,
        output_dir=artifacts.output_dir,
    )
    assert document.schema_version == 2
    assert document.verification_status == "verified"
    assert payload["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert payload["redaction_policy"]["output_checksum_policy"] == "required-v2"
    assert payload["source_output_folder"] == "[local path omitted]"
    assert len(payload["content_digest"]) == 64
    assert payload["input_files"][0]["path"] == "evidence/evidence_index.json"
    assert all("sha256" in item for item in payload["included_files"])


def test_direct_default_writes_current_strict_manifest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write_source(source, amount="250.25")
    artifacts = generate_client_pack(source, tmp_path / "strict-default")
    payload = _manifest(artifacts.output_dir)
    schema = json.loads(
        Path("docs/schemas/client_pack_manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )

    Draft202012Validator(schema).validate(payload)
    document = read_client_pack_manifest(artifacts.manifest_path)
    assert payload["schema_version"] == 2
    assert payload["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert document.schema_version == 2
    assert document.verification_status == "verified"
    assert all("sha256" in item for item in payload["included_files"])


def test_manifest_verifier_detects_manifest_output_and_source_tampering(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source_file = _write_source(source, amount="250.25")
    artifacts = generate_client_pack(
        source,
        tmp_path / "output",
        redact_amounts=True,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    payload = _manifest(artifacts.output_dir)
    changed = json.loads(json.dumps(payload))
    changed["redaction_settings"]["redact_amounts"] = False
    with pytest.raises(ValueError, match="content digest"):
        verify_client_pack_manifest_payload(changed)

    changed_timestamp = json.loads(json.dumps(payload))
    changed_timestamp["generated_at"] = "tampered"
    with pytest.raises(ValueError, match="artifact digest"):
        verify_client_pack_manifest_payload(changed_timestamp)

    unsafe = json.loads(json.dumps(payload))
    unsafe["included_files"][0]["path"] = "../outside"
    with pytest.raises(ValueError, match="unsafe file path"):
        verify_client_pack_manifest_payload(unsafe)

    copied = artifacts.output_dir / "evidence" / "evidence_index.json"
    copied.write_text('{"total_amount":"tampered"}', encoding="utf-8")
    with pytest.raises(ValueError, match="output fingerprint"):
        verify_client_pack_manifest_payload(payload, output_dir=artifacts.output_dir)

    source_file.write_text('{"total_amount":251}', encoding="utf-8")
    with pytest.raises(ValueError, match="input fingerprint"):
        verify_client_pack_manifest_payload(payload, source_dir=source)


def test_content_digest_is_path_independent_for_equivalent_sources(
    tmp_path: Path,
) -> None:
    source_a = tmp_path / "a" / "source"
    source_b = tmp_path / "b" / "relocated"
    _write_source(source_a, amount="250.25")
    _write_source(source_b, amount="250.25")

    first = generate_client_pack(
        source_a,
        tmp_path / "output-a",
        redact_amounts=True,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    second = generate_client_pack(
        source_b,
        tmp_path / "output-b",
        redact_amounts=True,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )

    first_payload = _manifest(first.output_dir)
    second_payload = _manifest(second.output_dir)
    assert first_payload["content_digest"] == second_payload["content_digest"]


def test_cli_client_pack_selects_strict_policy(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_source(source)
    output = tmp_path / "output"

    result = runner.invoke(
        app,
        [
            "report",
            "client-pack",
            "--input",
            str(source),
            "--output",
            str(output),
            "--redact-amounts",
        ],
    )

    assert result.exit_code == 0
    payload = _manifest(output)
    copied = json.loads(
        (output / "evidence" / "evidence_index.json").read_text(encoding="utf-8")
    )
    assert payload["schema_version"] == 2
    assert payload["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert copied["total_amount"] == "0-99"


def test_unknown_client_pack_policy_fails_before_path_or_output(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "987654321.01"
    output = tmp_path / "output"

    with pytest.raises(ValueError, match="unsupported financial input policy") as captured:
        generate_client_pack(
            missing,
            output,
            financial_input_policy="unknown-v9",  # type: ignore[arg-type]
        )

    assert "987654321.01" not in str(captured.value)
    assert not output.exists()
