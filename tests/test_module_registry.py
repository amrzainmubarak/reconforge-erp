from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from reconforge.auth import RoleRepository
from reconforge.cli import app
from reconforge.db import connect, run_migrations
from reconforge.modules import ModuleDescriptor, get_module, list_modules, registry_payload, validate_registry

runner = CliRunner()


def test_registry_is_deterministic_complete_and_valid() -> None:
    descriptors = list_modules()

    assert len(descriptors) == 14
    assert [record.module_id for record in descriptors] == sorted(record.module_id for record in descriptors)
    assert validate_registry() == ()
    assert all(record.local_first is True for record in descriptors)
    assert all(record.external_calls is False for record in descriptors)
    assert all(record.maturity != "planned" for record in descriptors)
    assert {record.capability_status for record in descriptors} == {"implemented", "foundation"}


def test_registry_payload_is_versioned_and_serialization_safe() -> None:
    payload = registry_payload(maturity="experimental")

    assert payload["schema_version"] == 1
    assert payload["local_first"] is True
    assert payload["external_calls"] is False
    modules = payload["modules"]
    assert isinstance(modules, list)
    assert modules
    assert all(record["maturity"] == "experimental" for record in modules)
    json.dumps(payload)


def test_registry_declared_test_evidence_exists() -> None:
    repository_root = Path(__file__).resolve().parents[1]

    missing = [path for record in list_modules() for path in record.test_evidence if not (repository_root / path).is_file()]

    assert missing == []


def test_registry_permissions_exist_in_migrated_database(tmp_path: Path) -> None:
    database_path = tmp_path / "modules.db"
    run_migrations(database_path)
    connection = connect(database_path, require_exists=True)
    try:
        known_permissions = {permission.name for permission in RoleRepository(connection).list_permissions()}
    finally:
        connection.close()

    declared_permissions = {permission for record in list_modules() for permission in record.permissions}
    assert declared_permissions <= known_permissions


def test_registry_reports_unknown_dependency_migration_and_cycle() -> None:
    platform = get_module("platform.core")
    reconciliation = get_module("reconciliation.core")
    first = platform.model_copy(
        update={"dependencies": ("reconciliation.core", "missing.module"), "migration_versions": (999,)}
    )
    second = reconciliation.model_copy(update={"dependencies": ("platform.core",)})

    issues = validate_registry((first, second), known_migrations=frozenset())
    codes = {issue.code for issue in issues}

    assert codes == {"dependency_cycle", "unknown_dependency", "unknown_migration"}
    assert sum(issue.code == "unknown_migration" for issue in issues) == 2
    assert all("Traceback" not in issue.message for issue in issues)


def test_registry_rejects_duplicate_ids() -> None:
    descriptor = get_module("platform.core")

    issues = validate_registry((descriptor, descriptor))

    assert [(issue.code, issue.module_id) for issue in issues] == [("duplicate_module_id", "platform.core")]


def test_descriptor_rejects_planned_runtime_modules_and_unsafe_evidence_paths() -> None:
    source = get_module("platform.core").model_dump()

    with pytest.raises(ValidationError):
        ModuleDescriptor.model_validate({**source, "maturity": "planned"})
    with pytest.raises(ValidationError):
        ModuleDescriptor.model_validate({**source, "test_evidence": ("../secret.txt",)})


def test_modules_cli_lists_filters_and_shows_json() -> None:
    listed = runner.invoke(app, ["modules", "list", "--format", "json", "--maturity", "experimental"])
    shown = runner.invoke(app, ["modules", "show", "studio.modern", "--format", "json"])
    validated = runner.invoke(app, ["modules", "validate"])

    assert listed.exit_code == 0
    listed_payload = json.loads(listed.output)
    assert all(record["maturity"] == "experimental" for record in listed_payload["modules"])
    assert shown.exit_code == 0
    assert json.loads(shown.output)["module_id"] == "studio.modern"
    assert validated.exit_code == 0
    assert "14 runtime modules" in validated.output


def test_modules_cli_rejects_unknown_values_without_traceback() -> None:
    unknown_module = runner.invoke(app, ["modules", "show", "missing.module"])
    unknown_maturity = runner.invoke(app, ["modules", "list", "--maturity", "planned"])
    unknown_format = runner.invoke(app, ["modules", "list", "--format", "yaml"])

    assert unknown_module.exit_code == 1
    assert "Unknown module" in unknown_module.output
    assert unknown_maturity.exit_code == 1
    assert "Maturity must be one of" in unknown_maturity.output
    assert unknown_format.exit_code == 1
    assert "Output format must be" in unknown_format.output
    assert "Traceback" not in unknown_module.output + unknown_maturity.output + unknown_format.output
