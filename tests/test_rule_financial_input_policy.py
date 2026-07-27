from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.rules.engine import (
    execute_rule_pack,
    read_rule_results,
    verify_rule_results_payload,
    write_rule_execution,
)
from reconforge.rules.loader import load_rule_pack
from reconforge.rules.models import Condition
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    LegacyFinancialInputWarning,
)

runner = CliRunner()


def _write_pack(pack: Path, *, value: str) -> None:
    pack.mkdir()
    (pack / "pack.yml").write_text(
        "\n".join(
            [
                "pack_id: exact-boundary",
                "name: Exact Boundary",
                'version: "1.0.0"',
                "description: Exact financial threshold test pack.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (pack / "rules.yml").write_text(
        "\n".join(
            [
                "rules:",
                "  - rule_id: EXACT-001",
                "    rule_name: Exact threshold",
                "    severity: high",
                "    entity_type: test_record",
                "    source_file: records.csv",
                "    condition:",
                "      operator: greater_than",
                "      field: amount",
                f"      value: {value}",
                "    message: Amount is above the exact threshold.",
                "    recommended_action: Review the source amount.",
                "    risk_impact: 50",
                "    evidence_fields: [record_id, amount]",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_input(input_dir: Path, *, amount: str) -> None:
    input_dir.mkdir()
    (input_dir / "records.csv").write_text(
        f"record_id,amount\nROW-1,{amount}\n",
        encoding="utf-8",
    )


def test_strict_rule_yaml_preserves_exact_lexeme_while_legacy_is_compatible(
    tmp_path: Path,
) -> None:
    pack_path = tmp_path / "pack"
    input_path = tmp_path / "input"
    _write_pack(pack_path, value="0.100000000000000005")
    _write_input(input_path, amount="0.100000000000000004")

    strict_pack = load_rule_pack(
        pack_path,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    with pytest.warns(LegacyFinancialInputWarning, match="deprecated"):
        legacy_execution = execute_rule_pack(
            input_path,
            pack_path,
            financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
        )
    strict_execution = execute_rule_pack(
        input_path,
        pack_path,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )

    assert str(strict_pack.rules[0].condition.value) == "0.100000000000000005"
    assert len(legacy_execution.results) == 1
    assert strict_execution.results == []
    assert legacy_execution.pack.rule_pack_digest != strict_execution.pack.rule_pack_digest
    assert legacy_execution.decision_digest != strict_execution.decision_digest


@pytest.mark.parametrize("value", [".nan", ".inf", "-.inf"])
def test_strict_numeric_rule_value_rejects_non_finite_yaml(
    tmp_path: Path,
    value: str,
) -> None:
    pack_path = tmp_path / "pack"
    _write_pack(pack_path, value=value)

    with pytest.raises(ValueError, match="finite decimal"):
        load_rule_pack(
            pack_path,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )


def test_strict_variance_fallback_value_rejects_non_finite_input() -> None:
    with pytest.raises(ValueError, match="finite decimal"):
        Condition.model_validate(
            {
                "operator": "variance_above",
                "field": "actual",
                "other_field": "expected",
                "value": float("nan"),
            },
            context={"financial_input_policy": STRICT_FINANCIAL_INPUT_POLICY},
        )


def test_rule_loader_rejects_unsafe_yaml_tag(tmp_path: Path) -> None:
    pack_path = tmp_path / "pack"
    _write_pack(pack_path, value="1")
    (pack_path / "rules.yml").write_text(
        "!!python/object/apply:os.system ['whoami']\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="YAML is invalid"):
        load_rule_pack(
            pack_path,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )


def test_unknown_rule_policy_fails_before_path_access_without_echo(tmp_path: Path) -> None:
    missing = tmp_path / "987654321.01"

    with pytest.raises(ValueError, match="financial-input policy") as captured:
        load_rule_pack(
            missing,
            financial_input_policy="unknown-v9",  # type: ignore[arg-type]
        )

    assert "987654321.01" not in str(captured.value)


def test_current_rule_execution_writes_and_reads_verified_v2(tmp_path: Path) -> None:
    execution = execute_rule_pack(
        "examples/sample_data",
        "control-packs/audit-basic",
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    paths = write_rule_execution(execution, tmp_path / "results")
    payload = json.loads(paths[1].read_text(encoding="utf-8"))
    schema = json.loads(
        Path("docs/schemas/rule_results.schema.json").read_text(encoding="utf-8")
    )

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(payload)
    document = read_rule_results(paths[1])
    with paths[0].open("r", encoding="utf-8", newline="") as handle:
        csv_records = list(csv.DictReader(handle))
    assert document.schema_version == 2
    assert document.verification_status == "verified"
    assert payload["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert payload["result_count"] == len(execution.results)
    assert [item["name"] for item in payload["input_files"]] == sorted(
        item["name"] for item in payload["input_files"]
    )
    assert payload["rule_pack"]["digest"] == execution.pack.rule_pack_digest
    assert payload["decision_digest"] == execution.decision_digest
    assert csv_records
    assert csv_records[0]["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert csv_records[0]["decision_digest"] == execution.decision_digest
    repeated = execute_rule_pack(
        "examples/sample_data",
        "control-packs/audit-basic",
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    assert repeated.decision_digest == execution.decision_digest
    assert len(paths) == 2


def test_rule_results_reader_preserves_historical_unversioned_v1(tmp_path: Path) -> None:
    execution = execute_rule_pack(
        "examples/sample_data",
        "control-packs/audit-basic",
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    current_paths = write_rule_execution(execution, tmp_path / "current")
    current = json.loads(current_paths[1].read_text(encoding="utf-8"))
    legacy = {"results": current["results"]}
    legacy_path = tmp_path / "legacy-rule-results.json"
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    schema = json.loads(
        Path("docs/schemas/rule_results.schema.json").read_text(encoding="utf-8")
    )

    Draft202012Validator(schema).validate(legacy)
    document = read_rule_results(legacy_path)
    assert document.schema_version == 1
    assert document.verification_status == "legacy-unverified"
    assert document.results == legacy["results"]


def test_rule_result_verifier_detects_decision_and_timestamp_tampering(
    tmp_path: Path,
) -> None:
    execution = execute_rule_pack(
        "examples/sample_data",
        "control-packs/audit-basic",
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    payload = json.loads(
        write_rule_execution(execution, tmp_path)[1].read_text(encoding="utf-8")
    )
    changed_decision = json.loads(json.dumps(payload))
    changed_decision["results"][0]["risk_impact"] += 1
    with pytest.raises(ValueError, match="decision digest"):
        verify_rule_results_payload(changed_decision)

    changed_timestamp = json.loads(json.dumps(payload))
    changed_timestamp["results"][0]["triggered_at"] = "2099-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="artifact digest"):
        verify_rule_results_payload(changed_timestamp)


def test_cli_rule_run_uses_strict_policy_and_v2_artifact(tmp_path: Path) -> None:
    pack_path = tmp_path / "pack"
    input_path = tmp_path / "input"
    output_path = tmp_path / "output"
    _write_pack(pack_path, value="0.100000000000000005")
    _write_input(input_path, amount="0.100000000000000004")

    result = runner.invoke(
        app,
        [
            "rules",
            "run",
            "--input",
            str(input_path),
            "--pack",
            str(pack_path),
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads((output_path / "rule_results.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2
    assert payload["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert payload["result_count"] == 0
    assert payload["results"] == []
    assert read_rule_results(output_path / "rule_results.json").verification_status == "verified"


def test_rule_result_verifier_can_recheck_local_pack_and_input_bytes(
    tmp_path: Path,
) -> None:
    pack_path = tmp_path / "pack"
    input_path = tmp_path / "input"
    _write_pack(pack_path, value="1")
    _write_input(input_path, amount="2")
    execution = execute_rule_pack(
        input_path,
        pack_path,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    payload = json.loads(
        write_rule_execution(execution, tmp_path / "output")[1].read_text(
            encoding="utf-8"
        )
    )

    verify_rule_results_payload(
        payload,
        input_dir=input_path,
        pack_path=pack_path,
    )
    input_file = input_path / "records.csv"
    input_file.write_text(
        "record_id,amount\nROW-1,3\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="input fingerprint"):
        verify_rule_results_payload(
            payload,
            input_dir=input_path,
            pack_path=pack_path,
        )


def test_rule_execution_writer_validates_before_creating_output(tmp_path: Path) -> None:
    execution = execute_rule_pack(
        "examples/sample_data",
        "control-packs/audit-basic",
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    invalid = replace(execution, decision_digest="0" * 64)
    output_path = tmp_path / "invalid-output"

    with pytest.raises(ValueError, match="decision digest"):
        write_rule_execution(invalid, output_path)

    assert not output_path.exists()
