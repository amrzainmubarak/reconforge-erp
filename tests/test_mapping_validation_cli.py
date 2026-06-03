from __future__ import annotations

from pathlib import Path
from shutil import copytree

import pytest
import yaml
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.mappings.validator import validate_mapping_pack

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


def test_additional_export_profiles_validate_and_document_limits() -> None:
    profiles = [
        "erpnext-stock-gl",
        "dynamics-inventory-gl",
        "netsuite-inventory-gl",
    ]
    required_files = {"pack.yml", "mapping.yml", "rules.yml", "risk_model.yml", "README.md", "expected-exceptions.md", "sample-command.md"}
    for profile in profiles:
        pack = Path("control-packs") / profile
        assert {path.name for path in pack.iterdir() if path.is_file()} >= required_files
        result = runner.invoke(app, ["mappings", "validate", "--pack", str(pack)])
        assert result.exit_code == 0, result.output
        readme = (pack / "README.md").read_text(encoding="utf-8").lower()
        sample_command = (pack / "sample-command.md").read_text(encoding="utf-8").lower()
        assert "export-based" in readme
        assert "not a direct" in readme
        assert "reconforge mappings validate" in sample_command
        assert "direct_api_connector: false" in (pack / "mapping.yml").read_text(encoding="utf-8")


def test_mappings_validate_sample_command_paths_from_non_repo_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = Path.cwd().resolve()
    pack = repo_root / "control-packs" / "odoo-inventory-valuation"
    monkeypatch.chdir(tmp_path)

    result = validate_mapping_pack(pack)

    assert result.passed
    sample_command_check = next(check for check in result.checks if check.name == "sample command paths")
    assert sample_command_check.passed


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
