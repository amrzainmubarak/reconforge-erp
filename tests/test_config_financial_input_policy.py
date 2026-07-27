from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from reconforge.config import load_config, write_default_config
from reconforge.utils.money import (
    LEGACY_FINANCIAL_INPUT_POLICY,
    STRICT_FINANCIAL_INPUT_POLICY,
    LegacyFinancialInputWarning,
)


def _write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "reconforge.yml"
    path.write_text(text, encoding="utf-8")
    return path


def test_strict_config_reader_preserves_unquoted_yaml_decimal_lexeme(tmp_path: Path) -> None:
    path = _write_config(tmp_path, "amount_tolerance: 0.100000000000000005\n")

    config = load_config(
        path,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )

    assert config.amount_tolerance == Decimal("0.100000000000000005")


def test_legacy_config_reader_retains_float_compatibility_with_warning(tmp_path: Path) -> None:
    path = _write_config(tmp_path, "amount_tolerance: 0.100000000000000005\n")

    with pytest.warns(LegacyFinancialInputWarning, match="deprecated"):
        config = load_config(
            path,
            financial_input_policy=LEGACY_FINANCIAL_INPUT_POLICY,
        )

    assert config.amount_tolerance == Decimal("0.1")


def test_config_reader_default_is_strict_financial_input_v2(tmp_path: Path) -> None:
    path = _write_config(tmp_path, "amount_tolerance: 2.5\n")

    config = load_config(path)

    assert config.amount_tolerance == Decimal("2.5")


@pytest.mark.parametrize("value", [".nan", ".inf", "-.inf"])
def test_strict_config_reader_rejects_non_finite_yaml_scalars(
    tmp_path: Path,
    value: str,
) -> None:
    path = _write_config(tmp_path, f"amount_tolerance: {value}\n")

    with pytest.raises(ValueError, match="Invalid ReconForge config values"):
        load_config(
            path,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )


def test_config_reader_rejects_unknown_policy_before_path_access(tmp_path: Path) -> None:
    secret = "secret-policy-value"

    with pytest.raises(ValueError, match="Invalid ReconForge config financial-input policy") as captured:
        load_config(
            tmp_path / "missing.yml",
            financial_input_policy=secret,  # type: ignore[arg-type]
        )

    assert secret not in str(captured.value)


def test_strict_config_reader_remains_safe_for_untrusted_yaml_tags(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        "amount_tolerance: !!python/object/apply:builtins.eval ['1 + 1']\n",
    )

    with pytest.raises(ValueError, match="Invalid ReconForge config YAML"):
        load_config(
            path,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )


def test_default_config_writer_emits_amount_tolerance_as_text(tmp_path: Path) -> None:
    path = write_default_config(tmp_path / "config" / "reconforge.yml")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert raw["amount_tolerance"] == "2"
    assert isinstance(raw["amount_tolerance"], str)
    assert load_config(
        path,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    ).amount_tolerance == Decimal("2")
