"""Backend discovery cannot turn metadata into installation or local parity."""


import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from reconforge.cli import app
from reconforge.modules.postgres_registry import (
    get_postgres_module,
    list_postgres_modules,
    postgres_registry_payload,
    validate_postgres_registry,
)
from reconforge.modules.registry import ModuleRegistryError, list_modules, registry_payload


def test_backend_discovery_retains_legacy_contract_and_does_not_inspect_deployment() -> None:
    before = registry_payload()
    payload = postgres_registry_payload()
    assert registry_payload() == before and before["schema_version"] == 1
    assert len(list_modules()) == 17
    assert payload["schema_version"] == 2 and payload["backend"] == "postgresql"
    assert payload["metadata_only"] is True and payload["installation_status"] == "not_inspected"
    records = list_postgres_modules()
    assert len(records) == 6 and records == tuple(sorted(records, key=lambda item: item.module_id))
    assert all(record.sqlite_operating_adapter is False and record.acceptance_status == "development" for record in records)
    assert all(record.migration_versions == () and record.maturity == "experimental" for record in records)
    assert validate_postgres_registry() == ()


def test_unknown_pg_migration_cannot_be_resolved_by_a_local_integer() -> None:
    record = get_postgres_module("finance.intercompany-fx")
    changed = record.model_copy(update={"migration_revisions": ("9999_missing",)})
    issues = validate_postgres_registry((changed,))
    assert any(issue.code == "unknown_postgres_revision" for issue in issues)
    absent_core = validate_postgres_registry((record,), known_revisions=frozenset(record.migration_revisions))
    assert any(issue.code == "missing_core_postgres_revision" for issue in absent_core)
    for revisions in (("x" * 33,), ("source;sql",), ("a", "a"), ()):
        with pytest.raises(ValidationError):
            type(record)(**{**record.model_dump(), "migration_revisions": revisions})
    with pytest.raises(ValidationError):
        type(record)(**{**record.model_dump(), "migration_versions": (139,)})
    with pytest.raises(ModuleRegistryError):
        get_postgres_module("unregistered.claim")


def test_pg_discovery_cli_is_additive_and_rejects_other_backends() -> None:
    import json

    runner = CliRunner()
    listed = runner.invoke(app, ["modules", "list", "--backend", "postgresql", "--format", "json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output) == postgres_registry_payload()
    shown = runner.invoke(app, ["modules", "show", "people.project-payroll", "--backend", "postgresql", "--format", "json"])
    assert shown.exit_code == 0 and json.loads(shown.output)["sqlite_operating_adapter"] is False
    validated = runner.invoke(app, ["modules", "validate", "--backend", "postgresql"])
    assert validated.exit_code == 0 and "deployment not inspected" in " ".join(validated.output.split())
    bad = runner.invoke(app, ["modules", "list", "--backend", "unreviewed"])
    assert bad.exit_code != 0 and "Metadata backend must be" in bad.output and "Traceback" not in bad.output
