"""Typed, deterministic registry for implemented ReconForge module slices."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from reconforge import __version__
from reconforge.db.migrations import MIGRATIONS

MODULE_REGISTRY_SCHEMA_VERSION = 1
ModuleMaturity = Literal["stable", "beta", "experimental"]
CapabilityStatus = Literal["implemented", "foundation"]
ModuleInterface = Literal["cli", "api", "current-studio", "modern-studio", "artifacts", "library"]
NetworkRequirement = Literal["none", "loopback-optional"]


class ModuleRegistryError(ValueError):
    """Raised when module metadata is missing, incompatible, or structurally invalid."""


class ModuleDescriptor(BaseModel):
    """One runtime-visible module contract; planned-only work is intentionally excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    module_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$", max_length=80)
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(pattern=r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")
    maturity: ModuleMaturity
    capability_status: CapabilityStatus
    summary: str = Field(min_length=1, max_length=500)
    local_first: Literal[True] = True
    external_calls: Literal[False] = False
    network_requirement: NetworkRequirement = "none"
    default_enabled: bool
    dependencies: tuple[str, ...] = ()
    incompatible_with: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    migration_versions: tuple[int, ...] = ()
    domain_events: tuple[str, ...] = ()
    interfaces: tuple[ModuleInterface, ...]
    import_contracts: tuple[str, ...]
    export_contracts: tuple[str, ...]
    data_classification: tuple[str, ...]
    retention_note: str = Field(min_length=1, max_length=500)
    activation_note: str = Field(min_length=1, max_length=500)
    test_evidence: tuple[str, ...]

    @field_validator(
        "dependencies",
        "incompatible_with",
        "permissions",
        "domain_events",
        "import_contracts",
        "export_contracts",
        "data_classification",
    )
    @classmethod
    def _unique_sorted_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item or len(item) > 160 for item in value):
            raise ValueError("module metadata names must contain 1 to 160 characters")
        if len(set(value)) != len(value):
            raise ValueError("module metadata names must be unique")
        return tuple(sorted(value))

    @field_validator("migration_versions")
    @classmethod
    def _valid_migration_versions(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(version < 1 for version in value):
            raise ValueError("migration versions must be positive")
        if len(set(value)) != len(value):
            raise ValueError("migration versions must be unique")
        return tuple(sorted(value))

    @field_validator("interfaces")
    @classmethod
    def _interfaces_are_unique(cls, value: tuple[ModuleInterface, ...]) -> tuple[ModuleInterface, ...]:
        if not value:
            raise ValueError("at least one interface is required")
        if len(set(value)) != len(value):
            raise ValueError("interfaces must be unique")
        return tuple(sorted(value))

    @field_validator("test_evidence")
    @classmethod
    def _safe_test_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("at least one test-evidence path is required")
        for item in value:
            path = PurePosixPath(item)
            if not item or len(item) > 240 or path.is_absolute() or ".." in path.parts or "\\" in item:
                raise ValueError("test-evidence paths must be bounded repository-relative POSIX paths")
            if not (item.startswith("tests/") or item.startswith("apps/web/")):
                raise ValueError("test evidence must point to the Python or modern Studio test suites")
        if len(set(value)) != len(value):
            raise ValueError("test-evidence paths must be unique")
        return tuple(sorted(value))


@dataclass(frozen=True)
class RegistryValidationIssue:
    """A deterministic module-registry validation result."""

    code: str
    module_id: str
    message: str


_MODULES = (
    ModuleDescriptor(
        module_id="platform.core",
        name="Local platform core",
        version=__version__,
        maturity="experimental",
        capability_status="foundation",
        summary="Local SQLite, users/RBAC, workflow, audit-ledger, API-session, and import/export foundations.",
        network_requirement="loopback-optional",
        default_enabled=True,
        permissions=("audit.read", "audit.verify", "db.read", "roles.manage", "users.manage"),
        migration_versions=(1, 2, 3, 4, 5),
        domain_events=("audit.event.appended", "workflow.transitioned"),
        interfaces=("api", "cli", "current-studio", "library"),
        import_contracts=("local-db-bridge.v1",),
        export_contracts=("audit-ledger.v1", "local-db-export.v1"),
        data_classification=("authentication-metadata", "financial-workflow-metadata"),
        retention_note="The operator controls the local SQLite file, backups, exports, and retention schedule.",
        activation_note="Available locally after explicit database initialization; the API binds to loopback by default.",
        test_evidence=(
            "tests/test_api_foundation.py",
            "tests/test_db_backup_structured_ingress.py",
            "tests/test_db_export_import.py",
            "tests/test_db_import_structured_ingress.py",
            "tests/test_studio_auth.py",
            "tests/test_upgrade_orchestrator.py",
        ),
    ),
    ModuleDescriptor(
        module_id="reconciliation.core",
        name="Reconciliation and control engine",
        version=__version__,
        maturity="experimental",
        capability_status="implemented",
        summary="Deterministic export-based stock-to-GL, WIP, rule-pack, review, comparison, and reporting workflows.",
        default_enabled=True,
        permissions=("reconciliation.approve", "reconciliation.prepare", "reconciliation.review", "reports.read"),
        migration_versions=(1,),
        domain_events=("reconciliation.reviewed", "reconciliation.run.completed"),
        interfaces=("artifacts", "cli", "current-studio", "library"),
        import_contracts=("canonical-gl-postings.v1", "canonical-stock-movements.v1", "canonical-workorders.v1"),
        export_contracts=("exception-register.v1", "management-pack.v1", "reconciliation-summary.v1"),
        data_classification=("user-provided-financial-exports", "workflow-review-metadata"),
        retention_note="Inputs and outputs remain in user-selected local paths and follow the operator's retention policy.",
        activation_note="Enabled by default for local file workflows; no database or external network is required.",
        test_evidence=(
            "tests/test_file_ingestion_inventory.py",
            "tests/test_file_ingress_security.py",
            "tests/test_client_pack_csv_redaction_ingress.py",
            "tests/test_client_pack_copy_publication.py",
            "tests/test_client_pack_publication_recovery.py",
            "tests/test_client_pack_redaction_ingress.py",
            "tests/test_generated_manifest_structured_ingress.py",
            "tests/test_structured_ingress_security.py",
            "tests/test_reports.py",
            "tests/test_review_workflow.py",
            "tests/test_stock_gl_reconciliation.py",
            "tests/test_workorder_reconciliation.py",
        ),
    ),
    ModuleDescriptor(
        module_id="platform.master-data",
        name="Organization and fiscal master data",
        version=__version__,
        maturity="experimental",
        capability_status="foundation",
        summary="Governed local organizations, legal entities, branches, currencies, and non-overlapping fiscal periods.",
        network_requirement="loopback-optional",
        default_enabled=True,
        dependencies=("platform.core",),
        permissions=("master_data.manage", "master_data.read"),
        migration_versions=(7,),
        domain_events=(
            "branch_upserted",
            "currency_upserted",
            "fiscal_period_status_changed",
            "fiscal_period_upserted",
            "legal_entity_upserted",
            "organization_upserted",
        ),
        interfaces=("api", "cli", "library"),
        import_contracts=(),
        export_contracts=("organization-master-data.v1",),
        data_classification=("financial-reference-metadata", "organization-reference-metadata"),
        retention_note="References remain in the operator-selected local SQLite database and controlled local exports.",
        activation_note="Requires schema migration 7; period status is workflow metadata and does not lock source ERP postings.",
        test_evidence=("tests/test_master_data.py",),
    ),
    ModuleDescriptor(
        module_id="finance.core",
        name="Finance core control ledger",
        version=__version__,
        maturity="experimental",
        capability_status="foundation",
        summary=(
            "Governed charts, account hierarchy, dimensions, journals, balanced entries, trial-balance controls, "
            "deterministic multi-entity translation artifacts, non-posting effective-ownership worksheets, and a "
            "governed local consolidation control-journal lifecycle."
        ),
        network_requirement="loopback-optional",
        default_enabled=True,
        dependencies=("platform.core", "platform.master-data"),
        permissions=("finance_core.manage", "finance_core.read", "finance_core.validate"),
        migration_versions=(8, 26),
        domain_events=(
            "accounting_dimension_upserted",
            "accounting_dimension_value_upserted",
            "chart_of_accounts_upserted",
            "finance_journal_upserted",
            "financial_account_upserted",
            "ledger_entry_draft_saved",
            "ledger_entry_validated",
            "ledger_entry_voided",
            "consolidation_period_created",
            "consolidation_period_locked",
            "consolidation_period_reopened",
            "consolidation_reversal_prepared",
            "consolidation_run_approved",
            "consolidation_run_posted",
            "consolidation_run_prepared",
            "consolidation_run_reversed",
        ),
        interfaces=("api", "artifacts", "cli", "library"),
        import_contracts=("ledger-entry-lines.v1",),
        export_contracts=(
            "consolidation-translation-result.v1",
            "consolidation-worksheet.v1",
            "consolidation-management-trial-balance.v1",
            "ownership-change-adjustment.v1",
            "finance-core-snapshot.v1",
            "ledger-control-trial-balance.v1",
        ),
        data_classification=(
            "consolidation-financial-control-data",
            "financial-master-data",
            "financial-transaction-control-data",
        ),
        retention_note="Records remain in the operator-selected local SQLite database and controlled local exports.",
        activation_note=(
            "Requires migrations 7-8 for the local ledger and 25-26 for the optional consolidation lifecycle. "
            "Translation and worksheet artifacts remain non-posting. Migration 25 persists only verified "
            "worksheets and exact balanced control-journal effects through maker-checker, posting, reversal, and "
            "period locks. It has a local SQLite/library boundary only and never mutates Finance Core entries, "
            "legal books, or a source ERP."
        ),
        test_evidence=(
            "tests/test_consolidation_lifecycle.py",
            "tests/test_consolidation_translation.py",
            "tests/test_consolidation_ownership_changes.py",
            "tests/test_consolidation_statement.py",
            "tests/test_finance_core.py",
            "tests/test_sqlite_consolidation_close.py",
        ),
    ),
    ModuleDescriptor(
        module_id="inventory.core",
        name="Inventory core movement ledger",
        version=__version__,
        maturity="experimental",
        capability_status="foundation",
        summary=(
            "Governed units, items, warehouses, locations, lot/serial references, exact movements, "
            "on-hand balances, physical-count review, reorder advice, FIFO cost layers, and an explicit "
            "balanced Finance Core Draft and exact reversal bridge."
        ),
        network_requirement="loopback-optional",
        default_enabled=True,
        dependencies=("finance.core", "platform.core", "platform.master-data"),
        permissions=(
            "inventory.count.approve",
            "inventory.count.manage",
            "inventory.manage",
            "inventory.post",
            "inventory.read",
            "inventory.reorder.manage",
            "inventory.valuation.approve",
            "inventory.valuation.manage",
            "inventory.valuation.reverse.approve",
            "inventory.valuation.reverse.manage",
        ),
        migration_versions=(9, 10, 11, 12),
        domain_events=(
            "inventory_count_adjustment_draft_created",
            "inventory_count_approved",
            "inventory_count_cancelled",
            "inventory_count_created",
            "inventory_count_quantity_recorded",
            "inventory_count_started",
            "inventory_count_submitted",
            "inventory_item_upserted",
            "inventory_location_upserted",
            "inventory_lot_upserted",
            "inventory_movement_draft_saved",
            "inventory_movement_posted",
            "inventory_movement_voided",
            "inventory_reorder_rule_upserted",
            "inventory_valuation_approved",
            "inventory_valuation_cancelled",
            "inventory_valuation_draft_created",
            "inventory_valuation_policy_upserted",
            "inventory_valuation_reversal_approved",
            "inventory_valuation_reversal_cancelled",
            "inventory_valuation_reversal_draft_created",
            "unit_of_measure_upserted",
            "warehouse_upserted",
        ),
        interfaces=("api", "cli", "library", "modern-studio"),
        import_contracts=("inventory-movement-lines.v1",),
        export_contracts=(
            "inventory-control-exceptions.v1",
            "inventory-core-snapshot.v1",
            "inventory-on-hand.v1",
            "inventory-planning-snapshot.v1",
            "inventory-reorder-signals.v1",
            "inventory-valuation-document.v1",
            "inventory-valuation-snapshot.v1",
            "inventory-valuation-reversal.v1",
            "inventory-valuation-reversal-snapshot.v1",
            "studio-inventory-control.v1",
        ),
        data_classification=("inventory-master-data", "inventory-transaction-control-data"),
        retention_note="Records remain in the operator-selected local SQLite database and controlled local exports.",
        activation_note=(
            "Requires migrations 7-12; Posted means the local inventory ledger only. FIFO approval and "
            "reversal approval create Finance Core Drafts, not validated postings or ERP writeback."
        ),
        test_evidence=(
            "apps/web/src/App.test.tsx",
            "tests/test_inventory_core.py",
            "tests/test_inventory_planning.py",
            "tests/test_inventory_valuation.py",
            "tests/test_inventory_valuation_reversal.py",
            "tests/test_studio_demo_bridge.py",
        ),
    ),
    ModuleDescriptor(
        module_id="finance.controls",
        name="DB-backed finance controls",
        version=__version__,
        maturity="experimental",
        capability_status="foundation",
        summary="Account, close, approvals, evidence, journals, intercompany, testing, matching, exceptions, and metric services.",
        network_requirement="loopback-optional",
        default_enabled=True,
        dependencies=("platform.core", "reconciliation.core"),
        permissions=(
            "accounts.read",
            "accounts.prepare",
            "accounts.review",
            "accounts.complete",
            "approval.approve",
            "approval.submit",
            "close.manage",
            "close.read",
            "controls.manage",
            "evidence.manage",
            "evidence.read",
            "exceptions.manage",
            "exceptions.read",
            "intercompany.manage",
            "intercompany.read",
            "journals.manage",
            "journals.read",
            "match.read",
            "match.run",
            "metrics.read",
            "ops.read",
        ),
        migration_versions=(6,),
        domain_events=("exception.updated", "evidence.registered", "period.close.updated"),
        interfaces=("api", "cli", "current-studio", "library"),
        import_contracts=("finance-platform-import.v1", "local-evidence-reference.v1"),
        export_contracts=("finance-platform-report.v1", "unified-exceptions.v1"),
        data_classification=("financial-workflow-metadata", "local-evidence-references"),
        retention_note="Finance records and evidence references remain in the operator-selected local database and paths.",
        activation_note="Foundation services require an explicitly initialized and migrated local database.",
        test_evidence=(
            "tests/test_close_workflow.py",
            "tests/test_close_workflow_structured_ingress.py",
            "tests/test_platform_close_evidence_metrics.py",
            "tests/test_platform_controls_matching_exceptions.py",
        ),
    ),
    ModuleDescriptor(
        module_id="mapping.profiles",
        name="ERP export mapping profiles",
        version=__version__,
        maturity="experimental",
        capability_status="implemented",
        summary="Safe local validation and canonical projection support for export-based ERP profiles.",
        default_enabled=True,
        interfaces=("artifacts", "cli", "library"),
        import_contracts=("export-profile-mapping.v1", "local-csv-xlsx-headers.v1"),
        export_contracts=("mapping-validation-report.v1", "profile-template.v1"),
        data_classification=("export-header-metadata", "mapping-configuration"),
        retention_note="Profiles, inspected headers, and reports remain in user-selected local paths.",
        activation_note="Enabled for explicit local commands; profiles are not live or vendor-certified connectors.",
        test_evidence=(
            "tests/test_file_ingestion_inventory.py",
            "tests/test_file_ingress_security.py",
            "tests/test_structured_ingress_security.py",
            "tests/test_mapping_validation_cli.py",
            "tests/test_mapping_wizard.py",
        ),
    ),
    ModuleDescriptor(
        module_id="packs.lifecycle",
        name="Signed data-only pack lifecycle",
        version=__version__,
        maturity="experimental",
        capability_status="foundation",
        summary="Local signature, conformance, maker-checker, dependency, install, disable, and rollback boundary for declarative packs.",
        default_enabled=False,
        dependencies=("finance.controls",),
        permissions=("controls.manage",),
        interfaces=("library",),
        import_contracts=("signed-data-pack-v1",),
        export_contracts=("pack-lifecycle-events-v1",),
        data_classification=("control-policy-metadata", "publisher-key-metadata"),
        retention_note="Operators govern the local SQLite lifecycle registry and must retain events according to evidence policy.",
        activation_note="Requires explicit trusted publisher keys and distinct maker-checker approval; external executable code is never loaded.",
        test_evidence=("tests/test_p3_ent_008_exit_audit.py", "tests/test_signed_pack_lifecycle.py"),
    ),
    ModuleDescriptor(
        module_id="plugins.export",
        name="Local export-adapter plugins",
        version=__version__,
        maturity="experimental",
        capability_status="foundation",
        summary="Allowlisted local adapter interfaces for generic CSV and sanitized ERP export formats.",
        default_enabled=True,
        dependencies=("mapping.profiles",),
        interfaces=("library",),
        import_contracts=("local-export-adapter.v1",),
        export_contracts=("canonical-reconciliation-inputs.v1",),
        data_classification=("user-provided-financial-exports",),
        retention_note="Adapters read explicit local files and do not own or upload retained data.",
        activation_note="Only built-in local export adapters are registered; direct ERP credentials and network calls are excluded.",
        test_evidence=(
            "tests/test_file_ingestion_inventory.py",
            "tests/test_file_ingress_security.py",
            "tests/test_v03_platform.py",
        ),
    ),
    ModuleDescriptor(
        module_id="studio.modern",
        name="Modern Studio synthetic preview",
        version=__version__,
        maturity="experimental",
        capability_status="foundation",
        summary="Read-only responsive dashboard, exception queue, evidence metadata, and inventory-control views for generated synthetic contracts.",
        default_enabled=False,
        dependencies=("finance.controls", "inventory.core"),
        interfaces=("artifacts", "modern-studio"),
        import_contracts=(
            "studio-evidence.v1",
            "studio-exceptions.v1",
            "studio-inventory-control.v1",
            "studio-overview.v1",
        ),
        export_contracts=("verified-ui-screenshots.v1",),
        data_classification=("synthetic-only",),
        retention_note="Static synthetic contracts remain in the local web build or operator-selected local path.",
        activation_note="Requires an explicit Node.js build and generated synthetic demo bundle; it is read-only and not API-authenticated.",
        test_evidence=(
            "apps/web/e2e/screenshots.spec.ts",
            "apps/web/src/App.test.tsx",
            "tests/test_studio_demo_bridge.py",
        ),
    ),
)


def list_modules(*, maturity: ModuleMaturity | None = None) -> tuple[ModuleDescriptor, ...]:
    """Return registry entries in stable ID order, optionally filtered by maturity."""

    records = tuple(sorted(_MODULES, key=lambda item: item.module_id))
    if maturity is None:
        return records
    return tuple(record for record in records if record.maturity == maturity)


def get_module(module_id: str) -> ModuleDescriptor:
    """Return one exact module descriptor without loading or activating module code."""

    normalized = module_id.strip().lower()
    for descriptor in _MODULES:
        if descriptor.module_id == normalized:
            return descriptor
    raise ModuleRegistryError("Unknown module ID. Use 'reconforge modules list' to inspect available modules.")


def validate_registry(
    descriptors: tuple[ModuleDescriptor, ...] | None = None,
    *,
    known_migrations: frozenset[int] | None = None,
) -> tuple[RegistryValidationIssue, ...]:
    """Validate uniqueness, references, migration compatibility, and dependency acyclicity."""

    records = descriptors if descriptors is not None else _MODULES
    migration_versions = (
        known_migrations if known_migrations is not None else frozenset(migration.version for migration in MIGRATIONS)
    )
    issues: list[RegistryValidationIssue] = []
    ids = [record.module_id for record in records]
    known_ids = set(ids)

    for module_id in sorted({item for item in ids if ids.count(item) > 1}):
        issues.append(RegistryValidationIssue("duplicate_module_id", module_id, "Module IDs must be unique."))

    for record in sorted(records, key=lambda item: item.module_id):
        for dependency in record.dependencies:
            if dependency == record.module_id:
                issues.append(
                    RegistryValidationIssue("self_dependency", record.module_id, "A module cannot depend on itself.")
                )
            elif dependency not in known_ids:
                issues.append(
                    RegistryValidationIssue(
                        "unknown_dependency", record.module_id, f"Dependency '{dependency}' is not registered."
                    )
                )
        for incompatible in record.incompatible_with:
            if incompatible not in known_ids:
                issues.append(
                    RegistryValidationIssue(
                        "unknown_incompatibility",
                        record.module_id,
                        f"Incompatible module '{incompatible}' is not registered.",
                    )
                )
        for migration_version in record.migration_versions:
            if migration_version not in migration_versions:
                issues.append(
                    RegistryValidationIssue(
                        "unknown_migration",
                        record.module_id,
                        f"Migration version {migration_version} is not available in this package.",
                    )
                )

    graph = {record.module_id: tuple(dep for dep in record.dependencies if dep in known_ids) for record in records}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(module_id: str, path: tuple[str, ...]) -> None:
        if module_id in visiting:
            cycle = " -> ".join((*path, module_id))
            issues.append(
                RegistryValidationIssue("dependency_cycle", module_id, f"Dependency cycle detected: {cycle}.")
            )
            return
        if module_id in visited:
            return
        visiting.add(module_id)
        for dependency in graph.get(module_id, ()):
            visit(dependency, (*path, module_id))
        visiting.remove(module_id)
        visited.add(module_id)

    for module_id in sorted(graph):
        visit(module_id, ())

    return tuple(sorted(set(issues), key=lambda issue: (issue.code, issue.module_id, issue.message)))


def registry_payload(*, maturity: ModuleMaturity | None = None) -> dict[str, object]:
    """Return the deterministic, serialization-safe local registry contract."""

    return {
        "schema_version": MODULE_REGISTRY_SCHEMA_VERSION,
        "package_version": __version__,
        "local_first": True,
        "external_calls": False,
        "modules": [descriptor.model_dump(mode="json") for descriptor in list_modules(maturity=maturity)],
    }
