from __future__ import annotations

import json
from decimal import ROUND_DOWN, Decimal, localcontext
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import Draft202012Validator, ValidationError
from typer.testing import CliRunner

from reconforge.anonymizer.engine import anonymize_directory, verify_anonymization_manifest
from reconforge.anonymizer.mapping import AnonymizationMap
from reconforge.anonymizer.maskers import mask_frame
from reconforge.cli import app
from reconforge.config import ReconForgeConfig
from reconforge.io.readers import read_required_datasets
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.schemas import DatasetName
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    LegacyFinancialInputWarning,
)

runner = CliRunner()


def test_same_original_value_maps_to_same_masked_value(tmp_path: Path) -> None:
    output = tmp_path / "anon"
    anonymize_directory("examples/sample_data", output, seed=42)
    stock = pd.read_csv(output / "stock_moves.csv")
    invoices = pd.read_csv(output / "invoices.csv")
    masked = stock.loc[stock["move_id"].eq("SM-0001"), "work_order"].iloc[0]
    assert masked in set(invoices["work_order"])


def test_different_values_map_to_different_masked_values(tmp_path: Path) -> None:
    output = tmp_path / "anon"
    anonymize_directory("examples/sample_data", output, seed=42)
    customers = pd.read_csv(output / "customers.csv")
    assert customers["customer_code"].nunique() == len(customers)


def test_matching_still_works_after_anonymization(tmp_path: Path) -> None:
    output = tmp_path / "anon"
    anonymize_directory("examples/sample_data", output, seed=42)
    datasets = read_required_datasets(output, [DatasetName.STOCK_MOVES, DatasetName.GL_ENTRIES])
    result = reconcile_stock_gl(datasets[DatasetName.STOCK_MOVES], datasets[DatasetName.GL_ENTRIES], ReconForgeConfig())
    assert len(result.matched_transactions) > 0


def test_matching_outcome_counts_are_preserved_with_global_amount_noise(tmp_path: Path) -> None:
    original_datasets = read_required_datasets(
        Path("examples/sample_data"),
        [DatasetName.STOCK_MOVES, DatasetName.GL_ENTRIES],
    )
    original = reconcile_stock_gl(
        original_datasets[DatasetName.STOCK_MOVES],
        original_datasets[DatasetName.GL_ENTRIES],
        ReconForgeConfig(),
    )
    output = tmp_path / "anon"
    anonymize_directory(
        "examples/sample_data",
        output,
        mask_amounts=True,
        amount_noise_percent="5.125",
        seed=42,
    )
    masked_datasets = read_required_datasets(output, [DatasetName.STOCK_MOVES, DatasetName.GL_ENTRIES])
    masked = reconcile_stock_gl(
        masked_datasets[DatasetName.STOCK_MOVES],
        masked_datasets[DatasetName.GL_ENTRIES],
        ReconForgeConfig(),
    )

    assert len(masked.matched_transactions) == len(original.matched_transactions)
    assert len(masked.stock_without_gl) == len(original.stock_without_gl)
    assert len(masked.gl_without_stock) == len(original.gl_without_stock)
    assert len(masked.value_differences) == len(original.value_differences)


def test_optional_amount_masking_works(tmp_path: Path) -> None:
    output = tmp_path / "anon"
    anonymize_directory("examples/sample_data", output, mask_amounts=True, seed=42)
    original = pd.read_csv("examples/sample_data/stock_moves.csv")
    masked = pd.read_csv(output / "stock_moves.csv")
    assert not original["total_cost"].equals(masked["total_cost"])


def test_amount_noise_factor_is_exact_bounded_and_context_independent() -> None:
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        first = AnonymizationMap(seed=7).amount_factor("10.123456789012345678", scope="all-amount-columns")
    second = AnonymizationMap(seed=7).amount_factor(Decimal("10.123456789012345678"), scope="all-amount-columns")

    assert isinstance(first, Decimal)
    assert first == second
    assert first.as_tuple().exponent == -4
    assert Decimal("0.8988") <= first <= Decimal("1.1012")


@pytest.mark.parametrize("value", ["-0.01", "100.01", "1e-3", "NaN", float("inf")])
def test_amount_noise_factor_rejects_invalid_policy(value: object) -> None:
    with pytest.raises(ValueError):
        AnonymizationMap(seed=7).amount_factor(value, scope="all-amount-columns")


def test_amount_masking_preserves_source_scale_and_exact_arithmetic() -> None:
    mapping = AnonymizationMap(seed=11)
    factor = mapping.amount_factor("25", scope="all-amount-columns")
    source_value = Decimal("123456789012345678901234567890.12345")
    source = pd.DataFrame(
        {
            "amount": [format(source_value, "f"), "2", "0.100000000000000003"],
            "reference": ["INV-100", "INV-200", "INV-300"],
        },
    )

    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        masked = mask_frame(source, mapping, mask_amounts=True, amount_noise_percent="25")

    with localcontext() as context:
        context.prec = 100
        expected = (source_value * factor).quantize(Decimal("0.00001"))
    assert masked.loc[0, "amount"] == expected
    assert masked.loc[0, "amount"].as_tuple().exponent == -5
    assert masked.loc[1, "amount"].as_tuple().exponent == 0
    assert masked.loc[2, "amount"].as_tuple().exponent == -18


def test_one_global_amount_factor_preserves_cross_file_equalities(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "left.csv").write_text("amount,reference\n10.00,DOC-1\n", encoding="utf-8")
    (source / "right.csv").write_text("total_cost,source_document\n10.00,DOC-1\n", encoding="utf-8")
    output = tmp_path / "anon"

    anonymize_directory(source, output, mask_amounts=True, amount_noise_percent="20", seed=5)

    left = pd.read_csv(output / "left.csv", dtype=str, keep_default_na=False)
    right = pd.read_csv(output / "right.csv", dtype=str, keep_default_na=False)
    assert Decimal(left.loc[0, "amount"]) == Decimal(right.loc[0, "total_cost"])


def test_invalid_amounts_are_preserved_when_masking() -> None:
    mapping = AnonymizationMap(seed=1)
    source = pd.DataFrame(
        {
            "amount": ["123.45", "bad", "", None],
            "total_cost": ["(10.00)", "0", "4.20", "x1"],
            "reference": ["INV-100", "INV-200", "INV-300", "INV-400"],
        },
    )
    masked = mask_frame(source, mapping, mask_amounts=True, amount_noise_percent="10.0")
    assert masked.loc[0, "amount"] != "123.45"
    assert masked.loc[1, "amount"] == "bad"
    assert masked.loc[2, "amount"] == ""
    assert masked.loc[0, "total_cost"] != "-10.00"
    assert masked.loc[3, "total_cost"] == "x1"


def test_shareable_output_omits_reversible_mapping_and_has_versioned_manifest(tmp_path: Path) -> None:
    output = tmp_path / "anon"
    outputs = anonymize_directory(
        "examples/sample_data",
        output,
        mask_amounts=True,
        amount_noise_percent="5.125000000000000003",
        seed=42,
    )

    assert output / "anonymization_manifest.json" in outputs
    assert not (output / "anonymization_map.csv").exists()
    manifest_text = (output / "anonymization_manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    schema = json.loads(Path("docs/schemas/anonymization_manifest.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(manifest)
    verify_anonymization_manifest(manifest, output_dir=output)
    assert manifest["schema_version"] == 2
    assert manifest["algorithm_version"] == "exact-global-decimal-noise-v1"
    assert manifest["amount_noise_percent"] == "5.125000000000000003"
    assert manifest["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY
    assert manifest["private_mapping_exported"] is False
    assert "CUST-001" not in manifest_text
    assert "WO-1001" not in manifest_text

    manifest["amount_noise_percent"] = "6"
    with pytest.raises(ValueError, match="policy digest"):
        verify_anonymization_manifest(manifest)

    unsupported = json.loads(manifest_text)
    unsupported["algorithm_version"] = "future-noise-v99"
    with pytest.raises(ValueError, match="unsupported anonymization manifest algorithm_version"):
        verify_anonymization_manifest(unsupported)

    tampered = json.loads(manifest_text)
    tampered["source_files"].append("extra.csv")
    with pytest.raises(ValueError, match="manifest digest"):
        verify_anonymization_manifest(tampered)

    first_output = output / manifest["outputs"][0]["name"]
    first_output.write_text(first_output.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="output verification failed"):
        verify_anonymization_manifest(json.loads(manifest_text), output_dir=output)


def test_private_mapping_requires_explicit_path_outside_shareable_output(tmp_path: Path) -> None:
    output = tmp_path / "anon"
    private_mapping = tmp_path / "private" / "anonymization_map.csv"

    outputs = anonymize_directory(
        "examples/sample_data",
        output,
        private_mapping_path=private_mapping,
        seed=42,
    )

    assert private_mapping in outputs
    assert private_mapping.exists()
    assert "CUST-001" in private_mapping.read_text(encoding="utf-8")
    assert not (output / "anonymization_map.csv").exists()
    manifest = json.loads((output / "anonymization_manifest.json").read_text(encoding="utf-8"))
    assert manifest["private_mapping_exported"] is True


def test_anonymizer_rejects_unsafe_output_and_private_mapping_paths(tmp_path: Path) -> None:
    populated_output = tmp_path / "populated"
    populated_output.mkdir()
    sentinel = populated_output / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="empty or not exist"):
        anonymize_directory("examples/sample_data", populated_output)
    assert sentinel.read_text(encoding="utf-8") == "keep"

    nested_output = tmp_path / "nested-output"
    with pytest.raises(ValueError, match="outside the anonymized output"):
        anonymize_directory(
            "examples/sample_data",
            nested_output,
            private_mapping_path=nested_output / "anonymization_map.csv",
        )
    assert not nested_output.exists()


def test_cli_anonymizer_preserves_exact_noise_policy_and_handles_invalid_input(tmp_path: Path) -> None:
    output = tmp_path / "anon"
    result = runner.invoke(
        app,
        [
            "anonymize",
            "--input",
            "examples/sample_data",
            "--output",
            str(output),
            "--mask-amounts",
            "--amount-noise-percent",
            "0.110000000000000001",
            "--seed",
            "7",
        ],
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((output / "anonymization_manifest.json").read_text(encoding="utf-8"))
    assert manifest["amount_noise_percent"] == "0.110000000000000001"
    assert manifest["financial_input_policy"] == STRICT_FINANCIAL_INPUT_POLICY

    invalid_output = tmp_path / "invalid"
    invalid = runner.invoke(
        app,
        [
            "anonymize",
            "--input",
            "examples/sample_data",
            "--output",
            str(invalid_output),
            "--amount-noise-percent",
            "1e-3",
        ],
    )
    assert invalid.exit_code == 1
    assert "scientific notation is not allowed" in invalid.output
    assert "Traceback" not in invalid.output
    assert not invalid_output.exists()


def test_anonymizer_service_retains_finite_float_compatibility(tmp_path: Path) -> None:
    output = tmp_path / "anon"
    with pytest.warns(LegacyFinancialInputWarning, match="deprecated"):
        anonymize_directory(
            "examples/sample_data",
            output,
            mask_amounts=True,
            amount_noise_percent=5.25,
            seed=3,
            financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
        )
    manifest = json.loads((output / "anonymization_manifest.json").read_text(encoding="utf-8"))
    assert manifest["amount_noise_percent"] == "5.25"
    assert manifest["financial_input_policy"] == LEGACY_FINANCIAL_INPUT_POLICY


def test_anonymizer_strict_service_rejects_float_before_output(tmp_path: Path) -> None:
    output = tmp_path / "strict-float"

    with pytest.raises(ValueError, match="strict-financial-input-v2"):
        anonymize_directory(
            "examples/sample_data",
            output,
            mask_amounts=True,
            amount_noise_percent=5.25,
            seed=3,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )

    assert not output.exists()


def test_checked_in_anonymized_example_has_no_reversible_map() -> None:
    example = Path("examples/anonymized_data")
    assert not (example / "anonymization_map.csv").exists()
    manifest = json.loads((example / "anonymization_manifest.json").read_text(encoding="utf-8"))
    schema = json.loads(Path("docs/schemas/anonymization_manifest.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(manifest)
    verify_anonymization_manifest(manifest, output_dir=example)

    incomplete_v2 = dict(manifest)
    incomplete_v2["schema_version"] = 2
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(incomplete_v2)


def test_date_shifting_works(tmp_path: Path) -> None:
    output = tmp_path / "anon"
    anonymize_directory("examples/sample_data", output, seed=42, date_shift_days=30)
    original = pd.to_datetime(pd.read_csv("examples/sample_data/stock_moves.csv")["date"]).iloc[0]
    shifted = pd.to_datetime(pd.read_csv(output / "stock_moves.csv")["date"]).iloc[0]
    assert (shifted - original).days == 30
