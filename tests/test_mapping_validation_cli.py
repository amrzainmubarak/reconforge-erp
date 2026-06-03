from __future__ import annotations

from pathlib import Path
from shutil import copytree

import yaml
from typer.testing import CliRunner

from reconforge.cli import app

runner = CliRunner()


def _copy_pack(tmp_path: Path, name: str = "odoo-inventory-valuation") -> Path:
    target = tmp_path / name
    copytree(Path("control-packs") / name, target)
    return target


def test_mappings_validate_valid_odoo_pack() -> None:
    result = runner.invoke(app, ["mappings", "validate", "--pack", "control-packs/odoo-inventory-valuation"])
    assert result.exit_code == 0
    assert "Summary:" in result.output
    assert "0 failed" in result.output


def test_mappings_validate_valid_sap_pack() -> None:
    result = runner.invoke(app, ["mappings", "validate", "--pack", "control-packs/sap-mb51-fagll03"])
    assert result.exit_code == 0
    assert "0 failed" in result.output


def test_mappings_validate_missing_mapping_yml(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path)
    (pack / "mapping.yml").unlink()
    result = runner.invoke(app, ["mappings", "validate", "--pack", str(pack)])
    assert result.exit_code == 1
    assert "Missing required file" in result.output


def test_mappings_validate_duplicate_rule_id(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path)
    path = pack / "rules.yml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["rules"][1]["rule_id"] = payload["rules"][0]["rule_id"]
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    result = runner.invoke(app, ["mappings", "validate", "--pack", str(pack)])
    assert result.exit_code == 1
    assert "Duplicate rule IDs" in result.output


def test_mappings_validate_invalid_severity(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path)
    path = pack / "rules.yml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["rules"][0]["severity"] = "urgent"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    result = runner.invoke(app, ["mappings", "validate", "--pack", str(pack)])
    assert result.exit_code == 1
    assert "Invalid severities" in result.output


def test_mappings_validate_malformed_yaml(tmp_path: Path) -> None:
    pack = _copy_pack(tmp_path)
    (pack / "rules.yml").write_text("rules:\n  - rule_id: [bad\n", encoding="utf-8")
    result = runner.invoke(app, ["mappings", "validate", "--pack", str(pack)])
    assert result.exit_code == 1
    assert "Malformed YAML" in result.output
