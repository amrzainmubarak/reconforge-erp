"""Additive PostgreSQL contracts without claiming a SQLite operating adapter.

The legacy v1 registry and its local migration integers remain unchanged. This
v2 metadata describes packaged contracts; it never probes a database, installs
modules, grants permissions or certifies a running deployment.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import field_validator

from reconforge import __version__
from reconforge.infrastructure.postgres_operations import POSTGRES_MIGRATION_REVISIONS
from reconforge.modules.registry import (
    ModuleDescriptor,
    ModuleMaturity,
    ModuleReadinessContract,
    ModuleRegistryError,
    RegistryValidationIssue,
    list_modules,
    validate_registry,
)

POSTGRES_MODULE_REGISTRY_SCHEMA_VERSION = 2
_CORE_REVISIONS = {
    "platform.core": ("0001_postgres_tenant_boundary", "0004_postgres_identity", "0013_postgres_domain_uow"),
    "finance.core": ("0019_postgres_finance_core",),
    "finance.budget-control": ("0102_pg_budget_control",),
    "inventory.core": ("0024_postgres_inventory_core",),
}


class PostgresModuleDescriptor(ModuleDescriptor):
    """A backend-qualified experimental module contract, not an activation result."""

    backend: Literal["postgresql"] = "postgresql"
    sqlite_operating_adapter: Literal[False] = False
    installation_status: Literal["not_inspected"] = "not_inspected"
    acceptance_status: Literal["development"] = "development"
    migration_revisions: tuple[str, ...]
    manifest: str

    @field_validator("migration_versions")
    @classmethod
    def _no_local_migration_numbers(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if value:
            raise ValueError("PostgreSQL modules reference revisions, not local migration numbers")
        return value

    @field_validator("migration_revisions")
    @classmethod
    def _bounded_revisions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(set(value)) != len(value):
            raise ValueError("PostgreSQL migration revisions must be present and unique")
        if any(not item.isascii() or len(item) > 32 or not item or not item.replace("_", "").isalnum() for item in value):
            raise ValueError("PostgreSQL revisions must fit the version table and use safe identifiers")
        return value

    @field_validator("manifest")
    @classmethod
    def _safe_manifest(cls, value: str) -> str:
        path = PurePosixPath(value)
        if not value.startswith("docs/modules/") or path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("A module manifest must be a repository-relative docs/modules path")
        return value


def _descriptor(
    *, module_id: str, name: str, revision: str, namespace: str, actions: tuple[str, ...],
    manifest: str, dependencies: tuple[str, ...], tests: tuple[str, ...], summary: str, gaps: tuple[str, ...],
) -> PostgresModuleDescriptor:
    return PostgresModuleDescriptor(
        module_id=module_id, name=name, version="1.0.0", maturity="experimental", capability_status="foundation",
        summary=summary, default_enabled=False, network_requirement="loopback-optional",
        dependencies=dependencies, permissions=tuple(f"{namespace}.{action}" for action in actions),
        interfaces=("api", "library", "modern-studio"), import_contracts=(f"{namespace}.command.v1",),
        export_contracts=(f"{namespace}.evidence.v1",), data_classification=("financial-sensitive", "operational-sensitive"),
        retention_note="Posted source, evidence, approvals and native financial effects remain immutable; operator retention applies.",
        activation_note="Requires an explicit migrated PostgreSQL deployment and current permissions. Metadata does not activate the module.",
        test_evidence=tests, readiness=ModuleReadinessContract(accountable_owner="Amr", declared_gaps=gaps),
        migration_revisions=(revision,), manifest=manifest,
    )


_POSTGRES_MODULES = (
    _descriptor(
        module_id="manufacturing.execution-v2", name="Inspected production and original cost claims",
        revision="0138_pg_manufacturing_v2", namespace="manufacturing_execution_v2",
        actions=("read", "manage", "approve", "post"), manifest="docs/modules/manufacturing-execution-v2.yaml",
        dependencies=("platform.core", "finance.core", "inventory.core"),
        tests=("tests/test_manufacturing_execution_v2.py", "tests/test_postgres_manufacturing_execution_v2.py"),
        summary="Versioned material delegation, original expense claims, held WIP, inspection, native finished goods and abnormal loss.",
        gaps=("Final integrated source acceptance and comparative resource benchmarks are pending.",
              "Full MRP, finite capacity planning, serial traceability and statutory industry packs are not established."),
    ),
    _descriptor(
        module_id="finance.intercompany-fx", name="Paired foreign trade and group translation",
        revision="0139_pg_intercompany_fx", namespace="intercompany_fx", actions=("read", "prepare", "review", "post"),
        manifest="docs/modules/intercompany-fx.yaml", dependencies=("platform.core", "finance.core"),
        tests=("tests/test_intercompany_fx.py", "tests/test_postgres_intercompany_fx.py"),
        summary="Original-rate functional currency books, partial settlement, revaluation, exact inverse and native group elimination.",
        gaps=("Final integrated source acceptance and comparative resource benchmarks are pending.",
              "Investment elimination, noncontrolling interests, hyperinflation and universal statutory reporting are outside this contract."),
    ),
    _descriptor(
        module_id="people.project-payroll", name="Governed time, project wage accrual and partial cash",
        revision="0140_pg_people_project_payroll", namespace="people_project_payroll",
        actions=("read", "read_sensitive", "personnel", "manage", "approve_time", "prepare", "review", "post", "pay"),
        manifest="docs/modules/people-project-payroll.yaml", dependencies=("platform.core", "finance.core", "finance.budget-control"),
        tests=("tests/test_people_project_payroll.py", "tests/test_postgres_people_project_payroll.py"),
        summary="Effective wage agreements, approved time, native project dimensions, budget claims, wage liability and partial/final cash.",
        gaps=("Final integrated source acceptance and comparative resource benchmarks are pending.",
              "Country-specific tax, benefits, deductions, overtime and statutory payroll packs are not proven.",
              "Sensitive operations require an operator-provisioned separate personnel database login."),
    ),
)


def list_postgres_modules(*, maturity: ModuleMaturity | None = None) -> tuple[PostgresModuleDescriptor, ...]:
    return tuple(sorted((record for record in _POSTGRES_MODULES if maturity is None or record.maturity == maturity),
                        key=lambda record: record.module_id))


def get_postgres_module(module_id: str) -> PostgresModuleDescriptor:
    normalized = module_id.strip().lower()
    for record in _POSTGRES_MODULES:
        if record.module_id == normalized:
            return record
    raise ModuleRegistryError("Unknown PostgreSQL module ID. Use 'reconforge modules list --backend postgresql'.")


def validate_postgres_registry(
    descriptors: tuple[PostgresModuleDescriptor, ...] | None = None, *,
    known_revisions: frozenset[str] | None = None, repository_root: Path | None = None,
) -> tuple[RegistryValidationIssue, ...]:
    records = _POSTGRES_MODULES if descriptors is None else descriptors
    revisions = frozenset(POSTGRES_MIGRATION_REVISIONS) if known_revisions is None else known_revisions
    # Reuse the existing dependency, cycle and maturity validator. PostgreSQL
    # descriptors intentionally carry no SQLite migration numbers.
    issues = list(validate_registry((*list_modules(), *records), repository_root=repository_root))
    for record in records:
        for revision in record.migration_revisions:
            if revision not in revisions:
                issues.append(RegistryValidationIssue("unknown_postgres_revision", record.module_id, revision))
        for dependency in record.dependencies:
            if dependency in _CORE_REVISIONS:
                for revision in _CORE_REVISIONS[dependency]:
                    if revision not in revisions:
                        issues.append(RegistryValidationIssue("missing_core_postgres_revision", record.module_id, revision))
        if repository_root is not None:
            for path in (record.manifest, *record.test_evidence):
                if not (repository_root / path).is_file():
                    issues.append(RegistryValidationIssue("missing_packaged_contract", record.module_id, path))
    return tuple(sorted(set(issues), key=lambda item: (item.code, item.module_id, item.message)))


def postgres_registry_payload(*, maturity: ModuleMaturity | None = None) -> dict[str, object]:
    return {
        "schema_version": POSTGRES_MODULE_REGISTRY_SCHEMA_VERSION, "package_version": __version__,
        "backend": "postgresql", "local_first": True, "external_calls": False,
        "installation_status": "not_inspected", "metadata_only": True,
        "core_backend_dependencies": [
            {"module_id": key, "backend": "postgresql", "migration_revisions": list(_CORE_REVISIONS[key])}
            for key in sorted(_CORE_REVISIONS)
        ],
        "modules": [record.model_dump(mode="json", exclude_none=True) for record in list_postgres_modules(maturity=maturity)],
    }
