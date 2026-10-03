from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from reconforge.auth import RoleRepository
from reconforge.cli import app
from reconforge.db import connect, run_migrations
from reconforge.modules import (
    ModuleDescriptor,
    get_module,
    list_modules,
    registry_payload,
    validate_module_readiness,
    validate_registry,
)

runner = CliRunner()


def test_registry_is_deterministic_complete_and_valid() -> None:
    descriptors = list_modules()

    assert len(descriptors) == 16
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
    assert all("readiness" not in record for record in modules)
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

    legacy = ModuleDescriptor.model_validate({key: value for key, value in source.items() if key != "readiness"})
    assert legacy.readiness is None
    with pytest.raises(ValidationError):
        ModuleDescriptor.model_validate({**source, "maturity": "planned"})
    with pytest.raises(ValidationError):
        ModuleDescriptor.model_validate({**source, "test_evidence": ("../secret.txt",)})
    with pytest.raises(ValidationError, match="readiness evidence paths"):
        ModuleDescriptor.model_validate(
            {**source, "readiness": {"benchmark_evidence": ("../secret.txt",)}}
        )


def _write_readiness_evidence(repository_root: Path, *relative_paths: str) -> None:
    for relative_path in relative_paths:
        path = repository_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic readiness evidence\n", encoding="utf-8")


def _promoted_platform_descriptor(*, maturity: str, readiness: dict[str, object] | None = None) -> ModuleDescriptor:
    source = get_module("platform.core").model_dump()
    return ModuleDescriptor.model_validate({**source, "maturity": maturity, "readiness": readiness})


def _promotion_migrations() -> frozenset[int]:
    # platform.core owns the retained inbox schema slice as well as the
    # original platform bootstrap migrations.
    return frozenset({1, 2, 3, 4, 5, 51})


def _complete_readiness_evidence(repository_root: Path, *, include_operational: bool = False) -> dict[str, object]:
    evidence: dict[str, object] = {
        "accountable_owner": "financial-controls-team",
        "threat_model_evidence": ("docs/security/platform-core-threat-model.md",),
        "rollback_evidence": ("docs/runbooks/platform-core-rollback.md",),
        "test_matrix_evidence": ("tests/test_platform_core_readiness.py",),
        "benchmark_evidence": ("benchmarks/platform-core-readiness.json",),
    }
    if include_operational:
        evidence["operational_evidence"] = ("docs/runbooks/platform-core-operations.md",)
    _write_readiness_evidence(
        repository_root,
        *(path for paths in evidence.values() if isinstance(paths, tuple) for path in paths),
    )
    return evidence


def test_experimental_module_can_declare_gaps_without_fabricating_promotion_evidence(tmp_path: Path) -> None:
    experimental = _promoted_platform_descriptor(
        maturity="experimental",
        readiness={"declared_gaps": ("A dedicated benchmark has not been completed.",)},
    )

    assert validate_module_readiness(experimental, repository_root=tmp_path) == ()
    assert validate_registry(
        (experimental,),
        known_migrations=_promotion_migrations(),
        repository_root=tmp_path,
    ) == ()


def test_beta_promotion_is_rejected_without_readiness_contract() -> None:
    promoted = _promoted_platform_descriptor(maturity="beta")

    issues = validate_registry((promoted,), known_migrations=_promotion_migrations())

    assert [(issue.code, issue.module_id) for issue in issues] == [
        ("missing_readiness_contract", "platform.core")
    ]
    assert "accountable_owner" in issues[0].message
    assert "benchmark_evidence" in issues[0].message


def test_beta_promotion_requires_real_readiness_evidence_and_named_owner(tmp_path: Path) -> None:
    readiness = _complete_readiness_evidence(tmp_path)
    promoted = _promoted_platform_descriptor(maturity="beta", readiness=readiness)

    assert validate_registry(
        (promoted,),
        known_migrations=_promotion_migrations(),
        repository_root=tmp_path,
    ) == ()

    placeholder_owner = promoted.model_copy(
        update={"readiness": promoted.readiness.model_copy(update={"accountable_owner": "TBD"})}
    )
    missing_benchmark = promoted.model_copy(
        update={
            "readiness": promoted.readiness.model_copy(
                update={"benchmark_evidence": ("benchmarks/not-present.json",)}
            )
        }
    )
    misplaced_threat_model = promoted.model_copy(
        update={
            "readiness": promoted.readiness.model_copy(
                update={"threat_model_evidence": ("tests/test_platform_core_readiness.py",)}
            )
        }
    )

    owner_issues = validate_module_readiness(placeholder_owner, repository_root=tmp_path)
    benchmark_issues = validate_module_readiness(missing_benchmark, repository_root=tmp_path)
    threat_model_issues = validate_module_readiness(misplaced_threat_model, repository_root=tmp_path)

    assert [(issue.code, issue.module_id) for issue in owner_issues] == [
        ("unassigned_readiness_owner", "platform.core")
    ]
    assert [(issue.code, issue.module_id) for issue in benchmark_issues] == [
        ("missing_readiness_evidence_file", "platform.core")
    ]
    assert "not-present.json" in benchmark_issues[0].message
    assert [(issue.code, issue.module_id) for issue in threat_model_issues] == [
        ("invalid_readiness_evidence_location", "platform.core")
    ]
    assert "docs/security/" in threat_model_issues[0].message


def test_stable_promotion_requires_operational_evidence_and_no_declared_gaps(tmp_path: Path) -> None:
    readiness = _complete_readiness_evidence(tmp_path)
    promoted = _promoted_platform_descriptor(maturity="stable", readiness=readiness)

    missing_operational = validate_module_readiness(promoted, repository_root=tmp_path)

    assert [(issue.code, issue.module_id) for issue in missing_operational] == [
        ("missing_readiness_evidence", "platform.core")
    ]
    assert "operational_evidence" in missing_operational[0].message

    stable_readiness = _complete_readiness_evidence(tmp_path, include_operational=True)
    stable = _promoted_platform_descriptor(maturity="stable", readiness=stable_readiness)
    assert validate_module_readiness(stable, repository_root=tmp_path) == ()

    declared_gap = stable.model_copy(
        update={
            "readiness": stable.readiness.model_copy(
                update={"declared_gaps": ("Recovery exercise remains unverified.",)}
            )
        }
    )
    gap_issues = validate_module_readiness(declared_gap, repository_root=tmp_path)

    assert [(issue.code, issue.module_id) for issue in gap_issues] == [
        ("unresolved_readiness_gaps", "platform.core")
    ]


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
    assert "16 runtime modules" in validated.output


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
