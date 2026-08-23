"""Command-line interface for ReconForge ERP."""

from __future__ import annotations

import base64
import binascii
import json
import shutil
import sqlite3
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, cast

import pandas as pd
import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from reconforge import __version__
from reconforge.ai.summaries import explain_exception_file
from reconforge.anonymizer.engine import anonymize_directory
from reconforge.api import create_api_app
from reconforge.application.consolidation_close import ConsolidationCloseApplicationService
from reconforge.application.intercompany_elimination import IntercompanyEliminationApplicationService
from reconforge.application.jobs import DurableJobApplicationService
from reconforge.audit import AuditLedgerError, list_audit_events, verify_audit_events
from reconforge.auth import AuthRepositoryError, AuthServiceError, LocalAuthService, RoleRepository
from reconforge.auth.federation_config import FederationConfigurationError, load_federation_runtime
from reconforge.auth.policy_analysis import PolicyAnalysisRequest, PolicyGrant, PolicyScope, analyze_policy_conflicts
from reconforge.auth.scim import SCIMError
from reconforge.auth.webauthn_config import WebAuthnConfigurationError, load_webauthn_runtime
from reconforge.benchmark.reconciliation_execution import (
    run_reconciliation_execution_benchmark,
    run_reconciliation_execution_streaming_benchmark,
)
from reconforge.benchmark.runner import run_benchmark
from reconforge.cli_bank_statement_control import bank_statement_app
from reconforge.cli_individual_cashflow_control import individual_cashflow_app
from reconforge.cli_inventory_planning import inventory_planning_app
from reconforge.cli_inventory_valuation import inventory_valuation_app
from reconforge.cli_inventory_valuation_reversal import inventory_valuation_reversal_app
from reconforge.cli_manufacturing_cost_control import manufacturing_cost_control_app
from reconforge.cli_professional_invoice_payment_control import professional_invoice_payment_app
from reconforge.cli_retail_settlement import retail_settlement_app
from reconforge.close import (
    ALLOWED_CLOSE_STATUSES,
    close_summary_frame,
    close_tasks_frame,
    export_close_report,
    load_close_checklist,
    update_close_task_status,
    write_close_checklist,
)
from reconforge.config import load_config, write_default_config
from reconforge.connectors.camt053 import Camt053Error, parse_camt053_file
from reconforge.connectors.package import (
    ConnectorPackageError,
    TrustedPublisherKey,
    TrustedPublisherRegistry,
    load_verified_package_for_admission,
)
from reconforge.control_matrix import export_control_matrix
from reconforge.dashboard.app import create_app
from reconforge.db import (
    DatabaseError,
    TenantDatabaseRouter,
    TenantRoutingError,
    connect,
    database_status,
    run_migrations,
)
from reconforge.db.backup import create_backup, restore_backup, verify_backup
from reconforge.db.encrypted_backup import (
    create_encrypted_backup,
    read_operator_backup_key,
    restore_encrypted_backup,
)
from reconforge.db.exporter import (
    DBBridgeError,
    export_database,
    recover_database_export_publication,
    resolve_input_file,
)
from reconforge.db.importers import (
    import_account_reconciliations,
    import_close_checklist,
    import_control_tests,
    import_review_state,
)
from reconforge.deployment import (
    DeploymentProfileError,
    DeploymentReadinessError,
    DeploymentRuntimeEvidenceError,
    ManagedKeyManifestError,
    WorkerPermissionManifestError,
    deployment_profile,
    list_deployment_profiles,
    load_deployment_readiness_matrix,
    verify_deployment_runtime_evidence,
    verify_managed_key_manifest,
    verify_worker_permission_manifest,
)
from reconforge.domain.consolidation import ConsolidationError
from reconforge.domain.consolidation_acquisition import (
    AcquisitionFairValueBridgeRequest,
    prepare_acquisition_fair_value_bridge,
)
from reconforge.domain.consolidation_deferred_tax import (
    AcquisitionDeferredTaxBridgeRequest,
    AcquisitionDeferredTaxItem,
    prepare_acquisition_deferred_tax_bridge,
)
from reconforge.domain.consolidation_impairment import (
    ConsolidationImpairmentBridgeRequest,
    ConsolidationImpairmentUnit,
    prepare_consolidation_impairment_bridge,
)
from reconforge.domain.consolidation_ownership_changes import (
    OwnershipChangeAdjustmentRequest,
    prepare_ownership_change_adjustment,
)
from reconforge.domain.consolidation_ppa import (
    AcquisitionPpaItem,
    AcquisitionPurchasePriceAllocationRequest,
    prepare_acquisition_purchase_price_allocation,
)
from reconforge.domain.intercompany_elimination import IntercompanyEliminationInputLine
from reconforge.enterprise_demo import EnterpriseDemoError, generate_enterprise_demo
from reconforge.evidence.binder import generate_evidence_binder
from reconforge.generator.synthetic import generate_synthetic_dataset
from reconforge.infrastructure.object_storage import (
    ObjectStorageConnectionFactory,
    ObjectStorageSettings,
    S3ObjectStore,
)
from reconforge.infrastructure.postgres import (
    PostgresConfigurationError,
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    PostgresUnavailableError,
)
from reconforge.infrastructure.postgres_scim_auth import PostgresSCIMCredentialRepository
from reconforge.infrastructure.postgres_service_accounts import (
    IssuedServiceCredential,
    PostgresServiceAccountRepository,
    ServiceAccountError,
)
from reconforge.infrastructure.sqlite_consolidation_close import SQLiteConsolidationCloseRepository
from reconforge.infrastructure.sqlite_jobs import SQLiteDurableJobRepository, SQLiteJobRepositoryError
from reconforge.io.excel import audit_metadata, write_excel_workbook
from reconforge.io.generated import GeneratedArtifactError
from reconforge.io.readers import read_required_datasets
from reconforge.io.records import RecordIngressError, read_json_record_document
from reconforge.io.writers import ensure_output_dir, frame_to_records, write_json, write_report_frames
from reconforge.mappings.inspector import inspect_mapping_inputs
from reconforge.mappings.profile_template import write_profile_template
from reconforge.mappings.validator import validate_mapping_pack
from reconforge.modules import (
    ModuleMaturity,
    ModuleRegistryError,
    get_module,
    list_modules,
    registry_payload,
    validate_registry,
)
from reconforge.observability import (
    ObservabilityConfigurationError,
    ObservabilityRuntime,
    OTLPHTTPConfiguration,
    create_otlp_http_runtime,
)
from reconforge.periods import compare_period_outputs
from reconforge.platform.accounts import AccountReconciliationService
from reconforge.platform.approvals import ApprovalService
from reconforge.platform.close import CloseManagementService
from reconforge.platform.common import PlatformError
from reconforge.platform.controls import ControlTestingService
from reconforge.platform.evidence import OBJECT_STORAGE_BACKEND, EvidenceRegistryService
from reconforge.platform.exceptions import ExceptionQueueService
from reconforge.platform.finance_core import FinanceCoreService
from reconforge.platform.intercompany import IntercompanyService
from reconforge.platform.inventory_core import InventoryCoreService
from reconforge.platform.journals import JournalControlService
from reconforge.platform.master_data import MasterDataService
from reconforge.platform.matching import MatchingService
from reconforge.platform.metrics import MetricsService
from reconforge.platform.operations import OperationsService
from reconforge.platform.outbox import OutboxError, OutboxService
from reconforge.platform.receivables import ReceiptAllocationInput, ReceivableInvoiceLineInput, ReceivablesService
from reconforge.reconciliation.matching import RECORD_IDENTITY_POLICY, MatchingStrategy
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.reconciliation.stock_gl import result_frames as stock_gl_result_frames
from reconforge.reconciliation.workorders import reconcile_workorders
from reconforge.reconciliation.workorders import result_frames as workorder_result_frames
from reconforge.reliability import AlertState, evaluate_alerts
from reconforge.reliability_sources import HttpReliabilityWindow, SQLiteReliabilityCollector, process_memory_mib
from reconforge.reports.client_pack import generate_client_pack, recover_client_pack_publication
from reconforge.reports.management_pack import generate_management_pack
from reconforge.reports.wip_aging import aging_summary, generate_wip_aging
from reconforge.review.state import (
    ALLOWED_STATUSES,
    collect_exception_frame,
    export_review_register,
    load_review_state,
    merge_review_state_with_exceptions,
    save_review_state,
    update_review_status,
)
from reconforge.rules.engine import execute_rule_pack, write_rule_execution
from reconforge.rules.explain import explain_rule
from reconforge.rules.loader import load_rule_pack
from reconforge.rules.recon_as_code import ReconciliationAsCodeSpec
from reconforge.schemas import DatasetName
from reconforge.studio.app import create_studio_app
from reconforge.studio.demo_bridge import StudioDemoBridgeError, build_studio_demo_bundle
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY, Money, parse_exact_amount
from reconforge.validators import issues_to_frame, validate_input_directory
from reconforge.variance import analyze_variance
from reconforge.workflow import WorkflowRepositoryError, WorkflowService, WorkflowServiceError

console = Console()
ALL_INTERFACES_HOST = ".".join(("0", "0", "0", "0"))
app = typer.Typer(help="ReconForge ERP reconciliation intelligence CLI.")
reconcile_app = typer.Typer(help="Run reconciliation controls.")
report_app = typer.Typer(help="Generate audit and management reports.")
rules_app = typer.Typer(help="Validate, list, and run control-pack rules.")
recon_as_code_app = typer.Typer(help="Validate, lint, test, diff, and simulate Reconciliation-as-Code packs.")
mappings_app = typer.Typer(help="Validate ERP mapping profiles.")
generate_app = typer.Typer(help="Generate synthetic ERP datasets.")
explain_app = typer.Typer(help="Explain exceptions and controls deterministically.")
review_app = typer.Typer(help="Review exceptions with local JSON state.")
demo_app = typer.Typer(help="Run first-time-user demo workflows.")
compare_app = typer.Typer(help="Compare generated exception outputs across periods.")
close_app = typer.Typer(help="Manage local close checklist workflow state.")
consolidation_app = typer.Typer(help="Inspect replay-verified consolidation close runs.")
accounts_app = typer.Typer(help="Manage DB-backed account reconciliations.")
approvals_app = typer.Typer(help="Manage local approval and certification metadata.")
certifications_app = typer.Typer(help="Manage local certification workflow metadata.")
evidence_app = typer.Typer(help="Manage DB-backed evidence registry records.")
journals_app = typer.Typer(help="Run DB-backed journal controls.")
intercompany_app = typer.Typer(help="Manage DB-backed intercompany workflows.")
match_app = typer.Typer(help="Run DB-backed deterministic matching jobs.")
exceptions_app = typer.Typer(help="Manage the unified DB-backed exception queue.")
metrics_app = typer.Typer(help="Compute governed DB-backed dashboard metrics.")
deployment_app = typer.Typer(help="Run local deployment verification checks.")
ops_app = typer.Typer(help="Inspect local operational health and job records.")
analyze_app = typer.Typer(help="Analyze local ReconForge output folders.")
controls_app = typer.Typer(help="Generate local control intelligence outputs.")
db_app = typer.Typer(help="Manage the local SQLite database foundation.")
audit_app = typer.Typer(help="Inspect local append-only audit events.")
users_app = typer.Typer(help="Manage local users for DB-backed workflows.")
roles_app = typer.Typer(help="Inspect local RBAC roles and permissions.")
policy_app = typer.Typer(help="Analyze versioned enterprise policy snapshots without mutating access.")
workflow_app = typer.Typer(help="Manage local workflow state machine foundations.")
api_app = typer.Typer(help="Serve the local REST API foundation.")
scim_app = typer.Typer(help="Manage PostgreSQL-backed SCIM client credentials.")
service_accounts_app = typer.Typer(help="Manage least-privilege PostgreSQL service accounts.")
modules_app = typer.Typer(help="Inspect deterministic local module capability metadata.")
connectors_app = typer.Typer(help="Verify data-only signed connector packages.")
master_data_app = typer.Typer(help="Manage governed local organization and fiscal master data.")
finance_core_app = typer.Typer(help="Manage local chart-of-accounts and balanced ledger-control foundations.")
inventory_app = typer.Typer(help="Manage local inventory masters, movements, balances, and controls.")
receivables_app = typer.Typer(help="Manage bounded local Accounts Receivable, credit controls, receipts, and aging.")
outbox_app = typer.Typer(help="Inspect and replay local transactional outbox events.")
retail_app = typer.Typer(help="Run bounded retail operations controls.")
bank_app = typer.Typer(help="Run bounded banking and professional cash controls.")
manufacturing_app = typer.Typer(help="Run bounded manufacturing production controls.")
professional_app = typer.Typer(help="Run bounded professional services controls.")
individual_app = typer.Typer(help="Run bounded individual and freelancer controls.")
app.add_typer(reconcile_app, name="reconcile")
app.add_typer(report_app, name="report")
app.add_typer(rules_app, name="rules")
rules_app.add_typer(recon_as_code_app, name="recon-as-code")
app.add_typer(mappings_app, name="mappings")
app.add_typer(generate_app, name="generate")
app.add_typer(explain_app, name="explain")
app.add_typer(review_app, name="review")
app.add_typer(demo_app, name="demo")
app.add_typer(compare_app, name="compare")
app.add_typer(close_app, name="close")
app.add_typer(consolidation_app, name="consolidation")
app.add_typer(accounts_app, name="accounts")
app.add_typer(approvals_app, name="approvals")
app.add_typer(certifications_app, name="certifications")
app.add_typer(evidence_app, name="evidence")
app.add_typer(journals_app, name="journals")
app.add_typer(intercompany_app, name="intercompany")
app.add_typer(match_app, name="match")
app.add_typer(exceptions_app, name="exceptions")
app.add_typer(metrics_app, name="metrics")
app.add_typer(deployment_app, name="deployment")
app.add_typer(ops_app, name="ops")
app.add_typer(analyze_app, name="analyze")
app.add_typer(controls_app, name="controls")
app.add_typer(db_app, name="db")
app.add_typer(audit_app, name="audit")
app.add_typer(users_app, name="users")
app.add_typer(roles_app, name="roles")
app.add_typer(policy_app, name="policy")
app.add_typer(workflow_app, name="workflow")
app.add_typer(api_app, name="api")
app.add_typer(scim_app, name="scim")
app.add_typer(service_accounts_app, name="service-accounts")
app.add_typer(modules_app, name="modules")
app.add_typer(connectors_app, name="connectors")
app.add_typer(master_data_app, name="master-data")
app.add_typer(finance_core_app, name="finance-core")
app.add_typer(inventory_app, name="inventory")
app.add_typer(receivables_app, name="receivables")
app.add_typer(outbox_app, name="outbox")
app.add_typer(retail_app, name="retail")
app.add_typer(bank_app, name="bank")
app.add_typer(manufacturing_app, name="manufacturing")
app.add_typer(professional_app, name="professional")
app.add_typer(individual_app, name="individual")
inventory_app.add_typer(inventory_planning_app, name="planning")
inventory_app.add_typer(inventory_valuation_app, name="valuation")
inventory_valuation_app.add_typer(inventory_valuation_reversal_app, name="reversal")
retail_app.add_typer(retail_settlement_app, name="settlement")
bank_app.add_typer(bank_statement_app, name="statement")
manufacturing_app.add_typer(manufacturing_cost_control_app, name="cost-control")
professional_app.add_typer(professional_invoice_payment_app, name="invoice-payment")
individual_app.add_typer(individual_cashflow_app, name="cashflow")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"ReconForge ERP {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version_callback, help="Show version and exit.")
    ] = False,
) -> None:
    """ReconForge ERP command group."""


def _print_frame(title: str, frame: pd.DataFrame, max_rows: int = 12) -> None:
    table = Table(title=title, show_lines=False)
    visible = frame.head(max_rows)
    for column in visible.columns:
        table.add_column(str(column))
    for _, row in visible.iterrows():
        table.add_row(*(str(row[column]) for column in visible.columns))
    console.print(table)
    if len(frame) > max_rows:
        console.print(f"[dim]Showing {max_rows} of {len(frame)} rows.[/dim]")


def _config_option(config_path: Path | None) -> Path | None:
    return config_path


def _print_success_paths(paths: list[Path]) -> None:
    for path in paths:
        console.print(f"[green]Written:[/green] {path}")


def _db_option(db_path: Path) -> Path:
    return db_path


def _prompt_password() -> str:
    return str(typer.prompt("Password", hide_input=True, confirmation_prompt=True))


def _auth_service(db_path: Path) -> tuple[LocalAuthService, sqlite3.Connection]:
    connection = connect(_db_option(db_path), require_exists=True)
    try:
        service = LocalAuthService(connection)
    except (DatabaseError, AuthRepositoryError, AuthServiceError):
        connection.close()
        raise
    return service, connection


def _workflow_service(db_path: Path) -> tuple[WorkflowService, sqlite3.Connection]:
    connection = connect(_db_option(db_path), require_exists=True)
    try:
        service = WorkflowService(connection)
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError):
        connection.close()
        raise
    return service, connection


def _db_connection(db_path: Path) -> sqlite3.Connection:
    return connect(_db_option(db_path), require_exists=True)


def _master_data_service(db_path: Path) -> tuple[MasterDataService, sqlite3.Connection]:
    connection = _db_connection(db_path)
    try:
        service = MasterDataService(connection)
    except (DatabaseError, PlatformError):
        connection.close()
        raise
    return service, connection


def _finance_core_service(db_path: Path) -> tuple[FinanceCoreService, sqlite3.Connection]:
    connection = _db_connection(db_path)
    try:
        service = FinanceCoreService(connection)
    except (DatabaseError, PlatformError):
        connection.close()
        raise
    return service, connection


def _inventory_service(db_path: Path) -> tuple[InventoryCoreService, sqlite3.Connection]:
    connection = _db_connection(db_path)
    try:
        service = InventoryCoreService(connection)
    except (DatabaseError, PlatformError):
        connection.close()
        raise
    return service, connection


def _receivables_service(db_path: Path) -> tuple[ReceivablesService, sqlite3.Connection]:
    connection = _db_connection(db_path)
    try:
        service = ReceivablesService(connection)
    except (DatabaseError, PlatformError):
        connection.close()
        raise
    return service, connection


def _ledger_lines_from_json(input_path: Path) -> list[dict[str, object]]:
    try:
        resolved = resolve_input_file(input_path)
        if resolved.suffix.lower() != ".json":
            raise PlatformError("Ledger lines input must be a local JSON file.")
        document = read_json_record_document(resolved, envelope_keys=("lines",))
    except DBBridgeError as exc:
        raise PlatformError(str(exc)) from exc
    except RecordIngressError as exc:
        if exc.code == "json_record_collection_required":
            raise PlatformError("Ledger lines JSON must be a list or an object containing a lines list.") from exc
        if exc.code == "json_record_not_object":
            raise PlatformError("Each ledger line in JSON must be an object.") from exc
        raise PlatformError("Ledger lines JSON could not be parsed.") from exc
    allowed = {"account_code", "description", "debit", "credit", "dimensions"}
    records: list[dict[str, object]] = []
    for raw_line in document.records:
        if set(raw_line) - allowed:
            raise PlatformError("Ledger lines JSON contains unsupported fields.")
        records.append({str(key): value for key, value in raw_line.items()})
    return records


def _inventory_lines_from_json(input_path: Path) -> list[dict[str, object]]:
    try:
        resolved = resolve_input_file(input_path)
        if resolved.suffix.lower() != ".json":
            raise PlatformError("Inventory movement lines input must be a local JSON file.")
        document = read_json_record_document(resolved, envelope_keys=("lines",))
    except DBBridgeError as exc:
        raise PlatformError(str(exc)) from exc
    except RecordIngressError as exc:
        if exc.code == "json_record_collection_required":
            raise PlatformError("Inventory lines JSON must be a list or an object containing a lines list.") from exc
        if exc.code == "json_record_not_object":
            raise PlatformError("Each inventory movement line in JSON must be an object.") from exc
        raise PlatformError("Inventory movement lines JSON could not be parsed.") from exc
    allowed = {
        "item_code",
        "quantity",
        "from_location",
        "to_location",
        "lot_serial_code",
        "description",
    }
    records: list[dict[str, object]] = []
    for raw_line in document.records:
        if set(raw_line) - allowed:
            raise PlatformError("Inventory movement lines JSON contains unsupported fields.")
        records.append({str(key): value for key, value in raw_line.items()})
    return records


def _print_records(title: str, records: list[dict[str, object]], *, max_rows: int = 50) -> None:
    if not records:
        console.print("[yellow]No records found.[/yellow]")
        return
    _print_frame(title, pd.DataFrame(records), max_rows=max_rows)


def _print_record_detail(title: str, record: dict[str, object]) -> None:
    """Print one record vertically so narrow terminals preserve complete values."""

    table = Table(title=title, show_lines=True)
    table.add_column("Field", style="bold", no_wrap=True)
    table.add_column("Value", overflow="fold")
    for field, value in record.items():
        table.add_row(str(field), str(value))
    console.print(table)


def _safe_cli_error(exc: Exception) -> None:
    # Keep machine-assertable error phrases contiguous even on narrow TTYs.
    # Rich otherwise folds long error messages at the terminal width.
    console.print(f"[red]{exc}[/red]", soft_wrap=True)
    raise typer.Exit(code=1) from exc


def _module_maturity(value: str | None) -> ModuleMaturity | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized not in {"stable", "beta", "experimental"}:
        raise ModuleRegistryError("Maturity must be one of: stable, beta, experimental.")
    return cast(ModuleMaturity, normalized)


def _module_output_format(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"table", "json"}:
        raise ModuleRegistryError("Output format must be 'table' or 'json'.")
    return normalized


@modules_app.command("list")
def modules_list(
    output_format: Annotated[str, typer.Option("--format", help="Output format: table or json.")] = "table",
    maturity: Annotated[str | None, typer.Option(help="Filter by stable, beta, or experimental maturity.")] = None,
) -> None:
    """List runtime-visible modules without activating them."""

    try:
        selected_format = _module_output_format(output_format)
        selected_maturity = _module_maturity(maturity)
        descriptors = list_modules(maturity=selected_maturity)
    except ModuleRegistryError as exc:
        _safe_cli_error(exc)
    if selected_format == "json":
        typer.echo(json.dumps(registry_payload(maturity=selected_maturity), indent=2, sort_keys=True))
        return
    table = Table(title="ReconForge Runtime Modules", show_lines=False)
    for column in ("Module", "Maturity", "Capability", "Default", "Interfaces", "Name"):
        table.add_column(column)
    for descriptor in descriptors:
        table.add_row(
            descriptor.module_id,
            descriptor.maturity,
            descriptor.capability_status,
            "yes" if descriptor.default_enabled else "no",
            ", ".join(descriptor.interfaces),
            descriptor.name,
        )
    console.print(table)
    console.print("[dim]Planned-only work is intentionally excluded from the runtime registry.[/dim]")


@modules_app.command("show")
def modules_show(
    module_id: Annotated[str, typer.Argument(help="Exact registered module ID.")],
    output_format: Annotated[str, typer.Option("--format", help="Output format: table or json.")] = "table",
) -> None:
    """Show one module's contracts, dependencies, permissions, and evidence."""

    try:
        selected_format = _module_output_format(output_format)
        descriptor = get_module(module_id)
    except ModuleRegistryError as exc:
        _safe_cli_error(exc)
    payload = descriptor.model_dump(mode="json")
    if selected_format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    table = Table(title=f"ReconForge Module: {descriptor.module_id}", show_lines=True)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    for field, value in payload.items():
        rendered = ", ".join(str(item) for item in value) if isinstance(value, list) else str(value)
        table.add_row(field, rendered or "—")
    console.print(table)


@modules_app.command("validate")
def modules_validate() -> None:
    """Validate registry identity, dependency graph, and migration references."""

    issues = validate_registry()
    if issues:
        for issue in issues:
            console.print(f"[red]{issue.code}[/red] {issue.module_id}: {issue.message}")
        raise typer.Exit(code=1)
    console.print(f"[green]Module registry is valid.[/green] {len(list_modules())} runtime modules, schema v1.")


@connectors_app.command("verify-package")
def connectors_verify_package_command(
    package_path: Annotated[Path, typer.Argument(help="Signed connector package JSON path.")],
    publisher_id: Annotated[str, typer.Option("--publisher-id", help="Trusted publisher identifier.")],
    key_id: Annotated[str, typer.Option("--key-id", help="Trusted Ed25519 key identifier.")],
    public_key: Annotated[str, typer.Option("--public-key", help="Base64-encoded raw Ed25519 public key.")],
) -> None:
    """Authenticate and admit one data-only signed read-only package."""

    try:
        decoded_key = base64.b64decode(public_key, validate=True)
        if len(decoded_key) != 32:
            raise ValueError("Ed25519 public keys must contain exactly 32 bytes")
        registry = TrustedPublisherRegistry(
            version=1,
            keys=(TrustedPublisherKey(publisher_id, key_id, decoded_key),),
        )
        admitted = load_verified_package_for_admission(package_path, trusted_registry=registry)
    except (binascii.Error, ConnectorPackageError, OSError, ValueError) as exc:
        _safe_cli_error(exc)
    typer.echo(json.dumps(admitted.to_dict(), ensure_ascii=True, indent=2, sort_keys=True))


@connectors_app.command("parse-camt053")
def connectors_parse_camt053_command(
    input_path: Annotated[Path, typer.Argument(help="Local ISO 20022 CAMT.053 XML statement path.")],
    output_path: Annotated[Path | None, typer.Option("--output", help="Optional exact JSON output path.")] = None,
) -> None:
    """Parse one bounded CAMT.053 statement without network or provider I/O."""

    try:
        statement = parse_camt053_file(str(input_path))
        rendered = json.dumps(statement.to_dict(), ensure_ascii=True, indent=2, sort_keys=True)
        if output_path is None:
            typer.echo(rendered)
        else:
            target = ensure_output_dir(output_path.parent) / output_path.name
            target.write_text(rendered + "\n", encoding="utf-8", newline="\n")
            typer.echo(f"CAMT.053 statement written: {target}")
    except (Camt053Error, OSError) as exc:
        _safe_cli_error(PlatformError(f"CAMT.053 input is invalid: {exc}"))


@policy_app.command("analyze-conflicts")
def policy_analyze_conflicts_command(
    input_path: Annotated[Path, typer.Option("--input", help="JSON policy analysis request.")],
    output_path: Annotated[Path | None, typer.Option("--output", help="Optional exact JSON output path.")] = None,
) -> None:
    """Analyze a policy snapshot for deterministic SoD and scope conflicts."""

    try:
        document = read_json_record_document(input_path, envelope_keys=("request",), allow_single_object=True)
        if len(document.records) != 1:
            raise PlatformError("Policy analysis input must contain exactly one JSON request object.")
        raw = document.records[0]
        expected = {
            "policy_id",
            "policy_version",
            "grants",
            "require_scoped_privileged",
            "prepared_by",
            "prepared_at",
            "approved_by",
            "approved_at",
        }
        if set(raw) != expected:
            raise PlatformError("Policy analysis input fields are not exactly the declared contract.")
        raw_grants = raw["grants"]
        if not isinstance(raw_grants, list):
            raise PlatformError("Policy analysis grants must be a JSON array.")
        grant_fields = {"grant_id", "principal_id", "principal_type", "role_id", "scope", "permissions", "status"}
        scope_fields = {"tenant_id", "workspace_id", "entity_ids", "period_ids", "region_ids", "data_classifications"}
        amount_scope_fields = {"minimum_amount", "maximum_amount"}
        grants: list[PolicyGrant] = []
        for index, raw_grant in enumerate(raw_grants):
            if not isinstance(raw_grant, dict) or set(raw_grant) != grant_fields:
                raise PlatformError(f"Policy analysis grant {index} fields are not exactly declared.")
            raw_scope = raw_grant["scope"]
            if not isinstance(raw_scope, dict) or not set(raw_scope).issubset(scope_fields | amount_scope_fields) or not scope_fields.issubset(raw_scope):
                raise PlatformError(f"Policy analysis grant {index} scope fields are not exactly declared.")
            permissions = raw_grant["permissions"]
            if not isinstance(permissions, list) or not all(isinstance(value, str) for value in permissions):
                raise PlatformError(f"Policy analysis grant {index} permissions must be string values.")
            scope_values = dict(raw_scope)
            for field in ("entity_ids", "period_ids", "region_ids", "data_classifications"):
                values = raw_scope[field]
                if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                    raise PlatformError(f"Policy analysis grant {index} {field} must be a string array.")
                scope_values[field] = frozenset(values)
            for field in amount_scope_fields:
                raw_value = raw_scope.get(field)
                if raw_value is None:
                    scope_values[field] = None
                elif not isinstance(raw_value, str):
                    raise PlatformError(f"Policy analysis grant {index} {field} must be an exact Decimal string.")
                else:
                    try:
                        scope_values[field] = Decimal(raw_value)
                    except InvalidOperation as exc:
                        raise PlatformError(
                            f"Policy analysis grant {index} {field} must be an exact Decimal string."
                        ) from exc
            grants.append(
                PolicyGrant(
                    grant_id=raw_grant["grant_id"],
                    principal_id=raw_grant["principal_id"],
                    principal_type=raw_grant["principal_type"],
                    role_id=raw_grant["role_id"],
                    scope=PolicyScope(**scope_values),
                    permissions=frozenset(permissions),
                    status=raw_grant["status"],
                )
            )
        values = dict(raw)
        values["grants"] = tuple(grants)
        result = analyze_policy_conflicts(PolicyAnalysisRequest(**values))
        rendered = json.dumps(result.to_dict(), sort_keys=True, indent=2)
        if output_path is None:
            console.print(rendered)
        else:
            target = ensure_output_dir(output_path.parent) / output_path.name
            target.write_text(rendered + "\n", encoding="utf-8", newline="\n")
            console.print(f"[green]Policy analysis written:[/green] {target}")
    except (OSError, PlatformError, TypeError, ValueError) as exc:
        _safe_cli_error(PlatformError(f"Policy analysis input is invalid: {exc}"))


@master_data_app.command("summary")
def master_data_summary_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Show bounded organization master-data counts."""

    try:
        service, connection = _master_data_service(db_path)
        try:
            record = service.summary(workspace=workspace, actor_label=actor).to_dict()
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Master Data Summary", record)


@master_data_app.command("currencies")
def master_data_currencies_command(
    active_only: Annotated[bool, typer.Option("--active-only", help="Show active currencies only.")] = False,
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List governed local currency references."""

    try:
        service, connection = _master_data_service(db_path)
        try:
            records = service.list_currencies(active_only=active_only, limit=limit, offset=offset, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Currencies", records)


@master_data_app.command("snapshot")
def master_data_snapshot_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Print the versioned master-data snapshot as JSON for local redirection or inspection."""

    try:
        service, connection = _master_data_service(db_path)
        try:
            payload = service.snapshot(workspace=workspace, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@master_data_app.command("currency-registry-check")
def master_data_currency_registry_check_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name to bind into the evidence scope.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Check master-data currency precision against the installed policy registry."""

    try:
        service, connection = _master_data_service(db_path)
        try:
            result = service.currency_registry_reconciliation(workspace=workspace, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    typer.echo(json.dumps(result, indent=2, sort_keys=True))


@master_data_app.command("currency-registry-bind")
def master_data_currency_registry_bind_command(
    workspace: Annotated[str, typer.Option(help="Local workspace to bind to the installed registry snapshot.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Persist an explicit currency-registry snapshot binding for one workspace."""

    try:
        service, connection = _master_data_service(db_path)
        try:
            result = service.bind_currency_registry(workspace=workspace, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    typer.echo(json.dumps(result, indent=2, sort_keys=True))


@master_data_app.command("currency-upsert")
def master_data_currency_upsert_command(
    code: Annotated[str, typer.Option(help="Three-letter currency code.")],
    name: Annotated[str, typer.Option(help="Currency display name.")],
    minor_units: Annotated[int, typer.Option(help="Decimal minor units, from 0 to 6.")] = 2,
    active: Annotated[bool, typer.Option("--active/--inactive", help="Whether the currency is active.")] = True,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update one local currency reference."""

    try:
        service, connection = _master_data_service(db_path)
        try:
            record = service.upsert_currency(
                code=code,
                name=name,
                minor_units=minor_units,
                active=active,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Currency Saved", record)


@master_data_app.command("organizations")
def master_data_organizations_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List organization references in one workspace."""

    try:
        service, connection = _master_data_service(db_path)
        try:
            records = service.list_organizations(workspace=workspace, limit=limit, offset=offset, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Organizations", records)


@master_data_app.command("organization-upsert")
def master_data_organization_upsert_command(
    code: Annotated[str, typer.Option(help="Organization code.")],
    name: Annotated[str, typer.Option(help="Organization display name.")],
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    active: Annotated[bool, typer.Option("--active/--inactive", help="Whether the organization is active.")] = True,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update one local organization reference."""

    try:
        service, connection = _master_data_service(db_path)
        try:
            record = service.upsert_organization(
                organization_code=code,
                name=name,
                workspace=workspace,
                active=active,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Organization Saved", record)


@master_data_app.command("entities")
def master_data_entities_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    organization: Annotated[str, typer.Option(help="Optional organization-code filter.")] = "",
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List legal-entity references in one workspace."""

    try:
        service, connection = _master_data_service(db_path)
        try:
            records = service.list_legal_entities(
                workspace=workspace,
                organization_code=organization,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Legal Entities", records)


@master_data_app.command("entity-upsert")
def master_data_entity_upsert_command(
    organization: Annotated[str, typer.Option(help="Organization code.")],
    code: Annotated[str, typer.Option(help="Legal-entity code.")],
    name: Annotated[str, typer.Option(help="Legal-entity display name.")],
    currency: Annotated[str, typer.Option(help="Registered three-letter currency code.")],
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    active: Annotated[bool, typer.Option("--active/--inactive", help="Whether the entity is active.")] = True,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update one local legal-entity reference."""

    try:
        service, connection = _master_data_service(db_path)
        try:
            record = service.upsert_legal_entity(
                organization_code=organization,
                entity_code=code,
                name=name,
                currency_code=currency,
                workspace=workspace,
                active=active,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Legal Entity Saved", record)


@master_data_app.command("branches")
def master_data_branches_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    organization: Annotated[str, typer.Option(help="Optional organization-code filter.")] = "",
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List branch references in one workspace."""

    try:
        service, connection = _master_data_service(db_path)
        try:
            records = service.list_branches(
                workspace=workspace,
                organization_code=organization,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Branches", records)


@master_data_app.command("branch-upsert")
def master_data_branch_upsert_command(
    organization: Annotated[str, typer.Option(help="Organization code.")],
    code: Annotated[str, typer.Option(help="Branch code.")],
    name: Annotated[str, typer.Option(help="Branch display name.")],
    entity: Annotated[str, typer.Option(help="Optional legal-entity code in the same organization.")] = "",
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    active: Annotated[bool, typer.Option("--active/--inactive", help="Whether the branch is active.")] = True,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update one local branch reference."""

    try:
        service, connection = _master_data_service(db_path)
        try:
            record = service.upsert_branch(
                organization_code=organization,
                branch_code=code,
                name=name,
                entity_code=entity,
                workspace=workspace,
                active=active,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Branch Saved", record)


@master_data_app.command("periods")
def master_data_periods_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local fiscal-period metadata."""

    try:
        service, connection = _master_data_service(db_path)
        try:
            records = service.list_periods(workspace=workspace, limit=limit, offset=offset, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Fiscal Periods", records)


@master_data_app.command("period-upsert")
def master_data_period_upsert_command(
    name: Annotated[str, typer.Option(help="Fiscal-period name.")],
    start_date: Annotated[str, typer.Option("--start", help="ISO start date, YYYY-MM-DD.")],
    end_date: Annotated[str, typer.Option("--end", help="ISO end date, YYYY-MM-DD.")],
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    fiscal_year: Annotated[int | None, typer.Option(help="Optional fiscal year.")] = None,
    period_number: Annotated[int | None, typer.Option(help="Optional period number.")] = None,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update one non-overlapping local fiscal period."""

    try:
        service, connection = _master_data_service(db_path)
        try:
            record = service.upsert_period(
                name=name,
                start_date=start_date,
                end_date=end_date,
                workspace=workspace,
                fiscal_year=fiscal_year,
                period_number=period_number,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Fiscal Period Saved", record)


@master_data_app.command("period-status")
def master_data_period_status_command(
    period_id: Annotated[str, typer.Option("--period-id", help="Fiscal-period identifier.")],
    status: Annotated[str, typer.Option(help="Target status: Open, Soft Closed, or Closed.")],
    reason: Annotated[str, typer.Option(help="Reason required when reopening.")] = "",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Transition fiscal-period metadata without implying ERP posting locks."""

    try:
        service, connection = _master_data_service(db_path)
        try:
            record = service.set_period_status(
                period_id,
                status=status,
                reason=reason,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Fiscal Period Status", record)


@receivables_app.command("customer-upsert")
def receivables_customer_upsert_command(
    code: Annotated[str, typer.Option(help="Customer code.")],
    name: Annotated[str, typer.Option(help="Customer display name.")],
    currency: Annotated[str, typer.Option(help="Three-letter customer currency code.")],
    credit_limit: Annotated[
        int, typer.Option("--credit-limit-minor", min=0, help="Exact credit limit in currency minor units.")
    ],
    credit_hold: Annotated[
        bool, typer.Option("--credit-hold/--no-credit-hold", help="Block approvals unless explicitly overridden.")
    ] = False,
    payment_terms: Annotated[
        int, typer.Option("--payment-terms-days", min=0, help="Default payment terms in days.")
    ] = 0,
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    organization: Annotated[str, typer.Option(help="Optional organization code.")] = "",
    entity: Annotated[str, typer.Option(help="Optional legal-entity code.")] = "",
    status: Annotated[str, typer.Option(help="Draft, Active, Suspended, or Closed.")] = "Active",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update a customer credit profile."""

    try:
        service, connection = _receivables_service(db_path)
        try:
            record = service.upsert_customer(
                customer_code=code,
                name=name,
                currency_code=currency,
                credit_limit_minor=credit_limit,
                credit_hold=credit_hold,
                payment_terms_days=payment_terms,
                workspace=workspace,
                organization_code=organization,
                entity_code=entity,
                status=status,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Receivables Customer", record)


@receivables_app.command("customers")
def receivables_customers_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    status: Annotated[str, typer.Option(help="Optional customer-status filter.")] = "",
    limit: Annotated[int, typer.Option(min=1, max=100_000)] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000)] = 0,
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List customer credit profiles in deterministic order."""

    try:
        service, connection = _receivables_service(db_path)
        try:
            records = service.list_customers(workspace=workspace, status=status)[offset : offset + limit]
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Receivables Customers", records)


@receivables_app.command("invoice-create")
def receivables_invoice_create_command(
    number: Annotated[str, typer.Option(help="Invoice number.")],
    customer: Annotated[str, typer.Option(help="Customer code.")],
    invoice_date: Annotated[str, typer.Option("--date", help="Invoice date in YYYY-MM-DD format.")],
    currency: Annotated[str, typer.Option(help="Three-letter invoice currency code.")],
    lines: Annotated[Path, typer.Option("--lines", help='JSON list or {"lines": [...]} of invoice lines.')],
    tax: Annotated[int, typer.Option("--tax-minor", min=0, help="Exact invoice tax in minor units.")] = 0,
    due_date: Annotated[str, typer.Option("--due-date", help="Optional due date in YYYY-MM-DD format.")] = "",
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    organization: Annotated[str, typer.Option(help="Optional organization code.")] = "",
    entity: Annotated[str, typer.Option(help="Optional legal-entity code.")] = "",
    idempotency_key: Annotated[str, typer.Option(help="Optional idempotency key.")] = "",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create a Draft customer invoice from a strict JSON line file."""

    try:
        raw_lines = _receivables_json_records(lines, key="lines")
        service, connection = _receivables_service(db_path)
        try:
            record = service.create_invoice(
                invoice_number=number,
                customer_code=customer,
                invoice_date=invoice_date,
                currency_code=currency,
                tax_minor=tax,
                lines=[_receivable_invoice_line_from_json(item) for item in raw_lines],
                due_date=due_date,
                workspace=workspace,
                organization_code=organization,
                entity_code=entity,
                idempotency_key=idempotency_key,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError, TypeError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Receivables Invoice", record)


@receivables_app.command("invoices")
def receivables_invoices_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    status: Annotated[str, typer.Option(help="Optional invoice-status filter.")] = "",
    limit: Annotated[int, typer.Option(min=1, max=100_000)] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000)] = 0,
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List customer invoices in deterministic order."""

    try:
        service, connection = _receivables_service(db_path)
        try:
            records = service.list_invoices(workspace=workspace, status=status)[offset : offset + limit]
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Receivables Invoices", records)


@receivables_app.command("invoice-submit")
def receivables_invoice_submit_command(
    invoice_id: Annotated[str, typer.Option("--invoice-id", help="Invoice identifier.")],
    expected_version: Annotated[int, typer.Option(min=1, help="Expected optimistic row version.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Submit a Draft customer invoice."""

    try:
        service, connection = _receivables_service(db_path)
        try:
            record = service.submit_invoice(invoice_id, expected_version=expected_version, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Submitted Receivables Invoice", record)


@receivables_app.command("invoice-approve")
def receivables_invoice_approve_command(
    invoice_id: Annotated[str, typer.Option("--invoice-id", help="Invoice identifier.")],
    expected_version: Annotated[int, typer.Option(min=1, help="Expected optimistic row version.")],
    override_reason: Annotated[
        str, typer.Option("--credit-override-reason", help="Required when credit controls block approval.")
    ] = "",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Approve a submitted invoice after deterministic credit controls."""

    try:
        service, connection = _receivables_service(db_path)
        try:
            record = service.approve_invoice(
                invoice_id,
                expected_version=expected_version,
                credit_override_reason=override_reason,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Approved Receivables Invoice", record)


@receivables_app.command("receipt-post")
def receivables_receipt_post_command(
    number: Annotated[str, typer.Option(help="Receipt number.")],
    customer: Annotated[str, typer.Option(help="Customer code.")],
    receipt_date: Annotated[str, typer.Option("--date", help="Receipt date in YYYY-MM-DD format.")],
    currency: Annotated[str, typer.Option(help="Three-letter receipt currency code.")],
    amount: Annotated[int, typer.Option("--amount-minor", min=1, help="Exact receipt amount in minor units.")],
    allocations: Annotated[
        Path | None, typer.Option("--allocations", help='Optional JSON list or {"allocations": [...]}.')
    ] = None,
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    organization: Annotated[str, typer.Option(help="Optional organization code.")] = "",
    entity: Annotated[str, typer.Option(help="Optional legal-entity code.")] = "",
    idempotency_key: Annotated[str, typer.Option(help="Optional idempotency key.")] = "",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Post a receipt with optional atomic invoice allocations."""

    try:
        raw_allocations = _receivables_json_records(allocations, key="allocations") if allocations is not None else []
        service, connection = _receivables_service(db_path)
        try:
            record = service.post_receipt(
                receipt_number=number,
                customer_code=customer,
                receipt_date=receipt_date,
                currency_code=currency,
                amount_minor=amount,
                allocations=[_receivable_allocation_from_json(item) for item in raw_allocations],
                workspace=workspace,
                organization_code=organization,
                entity_code=entity,
                idempotency_key=idempotency_key,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError, TypeError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Receivables Receipt", record)


@receivables_app.command("receipt-allocate")
def receivables_receipt_allocate_command(
    receipt_id: Annotated[str, typer.Option("--receipt-id", help="Posted receipt identifier.")],
    invoice_id: Annotated[str, typer.Option("--invoice-id", help="Approved invoice identifier.")],
    amount: Annotated[int, typer.Option("--amount-minor", min=1, help="Exact allocation amount in minor units.")],
    expected_version: Annotated[int, typer.Option(min=1, help="Expected receipt row version.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Allocate additional unapplied receipt value with a row-version check."""

    try:
        service, connection = _receivables_service(db_path)
        try:
            record = service.allocate_receipt(
                receipt_id,
                invoice_id=invoice_id,
                amount_minor=amount,
                expected_version=expected_version,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Allocated Receivables Receipt", record)


@receivables_app.command("credit-exposure")
def receivables_credit_exposure_command(
    customer: Annotated[str, typer.Option(help="Customer code.")],
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Show deterministic customer credit exposure."""

    try:
        service, connection = _receivables_service(db_path)
        try:
            record = service.credit_exposure(customer, workspace=workspace)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Receivables Credit Exposure", record)


@receivables_app.command("aging")
def receivables_aging_command(
    as_of_date: Annotated[str, typer.Option("--as-of", help="Aging date in YYYY-MM-DD format.")],
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Print deterministic open-item aging buckets."""

    try:
        service, connection = _receivables_service(db_path)
        try:
            payload = service.aging_report(workspace=workspace, as_of_date=as_of_date)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@finance_core_app.command("summary")
def finance_core_summary_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Show local finance-core record counts."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            record = service.summary(workspace=workspace, actor_label=actor).to_dict()
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Finance Core Summary", record)


@finance_core_app.command("snapshot")
def finance_core_snapshot_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Print the bounded, path-free finance-core snapshot as JSON."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            payload = service.snapshot(workspace=workspace, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@finance_core_app.command("charts")
def finance_core_charts_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local charts of accounts."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            records = service.list_charts(workspace=workspace, limit=limit, offset=offset, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Charts of Accounts", records)


@finance_core_app.command("chart-upsert")
def finance_core_chart_upsert_command(
    code: Annotated[str, typer.Option(help="Chart code.")],
    name: Annotated[str, typer.Option(help="Chart display name.")],
    organization: Annotated[str, typer.Option(help="Optional organization code.")] = "",
    description: Annotated[str, typer.Option(help="Optional chart description.")] = "",
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    active: Annotated[bool, typer.Option("--active/--inactive", help="Whether the chart is active.")] = True,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update one chart of accounts."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            record = service.upsert_chart(
                chart_code=code,
                name=name,
                workspace=workspace,
                organization_code=organization,
                description=description,
                active=active,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Chart of Accounts Saved", record)


@finance_core_app.command("accounts")
def finance_core_accounts_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    chart: Annotated[str, typer.Option(help="Optional chart-code filter.")] = "",
    active_only: Annotated[bool, typer.Option("--active-only", help="Show active accounts only.")] = False,
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List governed financial accounts."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            records = service.list_accounts(
                workspace=workspace,
                chart_code=chart,
                active_only=active_only,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Financial Accounts", records)


@finance_core_app.command("account-upsert")
def finance_core_account_upsert_command(
    code: Annotated[str, typer.Option(help="Account code.")],
    name: Annotated[str, typer.Option(help="Account display name.")],
    account_type: Annotated[
        str, typer.Option("--type", help="Asset, Liability, Equity, Income, Expense, or Off Balance.")
    ],
    normal_balance: Annotated[str, typer.Option(help="Debit or Credit.")],
    chart: Annotated[str, typer.Option(help="Chart code.")] = "DEFAULT",
    parent: Annotated[str, typer.Option(help="Optional parent account code.")] = "",
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    posting: Annotated[bool, typer.Option("--posting/--no-posting", help="Allow ledger lines.")] = True,
    manual_posting: Annotated[
        bool, typer.Option("--manual-posting/--no-manual-posting", help="Allow manual entry lines.")
    ] = True,
    reconciliation_required: Annotated[
        bool, typer.Option("--reconciliation-required/--no-reconciliation-required")
    ] = False,
    active: Annotated[bool, typer.Option("--active/--inactive", help="Whether the account is active.")] = True,
    description: Annotated[str, typer.Option(help="Optional account description.")] = "",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update a governed financial account."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            record = service.upsert_account(
                account_code=code,
                name=name,
                workspace=workspace,
                chart_code=chart,
                parent_account_code=parent,
                account_type=account_type,
                normal_balance=normal_balance,
                allow_posting=posting,
                allow_manual_posting=manual_posting,
                reconciliation_required=reconciliation_required,
                active=active,
                description=description,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Financial Account Saved", record)


@finance_core_app.command("dimension-upsert")
def finance_core_dimension_upsert_command(
    code: Annotated[str, typer.Option(help="Dimension code.")],
    name: Annotated[str, typer.Option(help="Dimension display name.")],
    dimension_type: Annotated[
        str, typer.Option("--type", help="Cost Center, Department, Project, or Custom.")
    ] = "Custom",
    organization: Annotated[str, typer.Option(help="Optional organization code.")] = "",
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    required: Annotated[
        bool, typer.Option("--required/--optional", help="Require this dimension on every line.")
    ] = False,
    active: Annotated[bool, typer.Option("--active/--inactive", help="Whether the dimension is active.")] = True,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update an accounting dimension."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            record = service.upsert_dimension(
                dimension_code=code,
                name=name,
                workspace=workspace,
                organization_code=organization,
                dimension_type=dimension_type,
                required_on_entries=required,
                active=active,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Accounting Dimension Saved", record)


@finance_core_app.command("dimension-value-upsert")
def finance_core_dimension_value_upsert_command(
    dimension: Annotated[str, typer.Option(help="Dimension code.")],
    code: Annotated[str, typer.Option(help="Dimension value code.")],
    name: Annotated[str, typer.Option(help="Dimension value display name.")],
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    active: Annotated[bool, typer.Option("--active/--inactive", help="Whether the value is active.")] = True,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update an accounting dimension value."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            record = service.upsert_dimension_value(
                dimension_code=dimension,
                value_code=code,
                name=name,
                workspace=workspace,
                active=active,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Accounting Dimension Value Saved", record)


@finance_core_app.command("dimensions")
def finance_core_dimensions_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    dimension: Annotated[str, typer.Option(help="Optional dimension code for value filtering.")] = "",
    values: Annotated[bool, typer.Option("--values", help="List dimension values instead of dimensions.")] = False,
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List accounting dimensions or their values."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            if values:
                records = service.list_dimension_values(
                    workspace=workspace,
                    dimension_code=dimension,
                    limit=limit,
                    offset=offset,
                    actor_label=actor,
                )
                title = "Accounting Dimension Values"
            else:
                records = service.list_dimensions(workspace=workspace, limit=limit, offset=offset, actor_label=actor)
                title = "Accounting Dimensions"
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records(title, records)


@finance_core_app.command("journal-upsert")
def finance_core_journal_upsert_command(
    code: Annotated[str, typer.Option(help="Journal code.")],
    name: Annotated[str, typer.Option(help="Journal display name.")],
    organization: Annotated[str, typer.Option(help="Organization code.")],
    currency: Annotated[str, typer.Option(help="Registered currency code.")],
    journal_type: Annotated[str, typer.Option("--type", help="Journal type.")] = "General",
    chart: Annotated[str, typer.Option(help="Chart code.")] = "DEFAULT",
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    active: Annotated[bool, typer.Option("--active/--inactive", help="Whether the journal is active.")] = True,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update a local finance journal definition."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            record = service.upsert_journal(
                journal_code=code,
                name=name,
                organization_code=organization,
                currency_code=currency,
                workspace=workspace,
                chart_code=chart,
                journal_type=journal_type,
                active=active,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Finance Journal Saved", record)


@finance_core_app.command("journals")
def finance_core_journals_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    organization: Annotated[str, typer.Option(help="Optional organization-code filter.")] = "",
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local finance journal definitions."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            records = service.list_journals(
                workspace=workspace,
                organization_code=organization,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Finance Journals", records)


@finance_core_app.command("entry-create")
def finance_core_entry_create_command(
    number: Annotated[str, typer.Option(help="Unique local entry number.")],
    organization: Annotated[str, typer.Option(help="Organization code.")],
    entity: Annotated[str, typer.Option(help="Legal-entity code.")],
    period_id: Annotated[str, typer.Option("--period-id", help="Fiscal-period identifier.")],
    journal: Annotated[str, typer.Option(help="Finance journal code.")],
    posting_date: Annotated[str, typer.Option("--date", help="Posting date in YYYY-MM-DD format.")],
    description: Annotated[str, typer.Option(help="Entry description.")],
    lines_path: Annotated[Path, typer.Option("--lines", help="Local JSON file containing balanced entry lines.")],
    reference: Annotated[str, typer.Option(help="Optional external reference.")] = "",
    source_type: Annotated[str, typer.Option("--source-type", help="Manual, Imported, or Generated.")] = "Manual",
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or replace a balanced Draft ledger-control entry from local JSON."""

    try:
        lines = _ledger_lines_from_json(lines_path)
        service, connection = _finance_core_service(db_path)
        try:
            record = service.create_entry(
                entry_number=number,
                organization_code=organization,
                entity_code=entity,
                period_id=period_id,
                journal_code=journal,
                posting_date=posting_date,
                description=description,
                lines=lines,
                workspace=workspace,
                external_reference=reference,
                source_type=source_type,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Ledger-Control Entry Saved", {key: value for key, value in record.items() if key != "lines"})


@finance_core_app.command("entries")
def finance_core_entries_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    organization: Annotated[str, typer.Option(help="Optional organization-code filter.")] = "",
    entity: Annotated[str, typer.Option(help="Optional entity-code filter.")] = "",
    period_id: Annotated[str, typer.Option("--period-id", help="Optional fiscal-period filter.")] = "",
    status: Annotated[str, typer.Option(help="Optional Draft, Validated, or Voided filter.")] = "",
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local ledger-control entry headers."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            records = service.list_entries(
                workspace=workspace,
                organization_code=organization,
                entity_code=entity,
                period_id=period_id,
                status=status,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Ledger-Control Entries", records)


@finance_core_app.command("entry-show")
def finance_core_entry_show_command(
    entry_id: Annotated[str, typer.Option("--entry-id", help="Ledger-entry identifier.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Print one ledger-control entry with its lines as JSON."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            record = service.get_entry(entry_id, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    typer.echo(json.dumps(record, indent=2, sort_keys=True))


@finance_core_app.command("entry-validate")
def finance_core_entry_validate_command(
    entry_id: Annotated[str, typer.Option("--entry-id", help="Ledger-entry identifier.")],
    reason: Annotated[str, typer.Option(help="Documented validation reason.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Validate a balanced local entry without posting to a source ERP."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            record = service.validate_entry(entry_id, reason=reason, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail(
        "Ledger-Control Entry Validated", {key: value for key, value in record.items() if key != "lines"}
    )


@finance_core_app.command("entry-void")
def finance_core_entry_void_command(
    entry_id: Annotated[str, typer.Option("--entry-id", help="Ledger-entry identifier.")],
    reason: Annotated[str, typer.Option(help="Documented void reason.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Void validated local control metadata while retaining immutable lines."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            record = service.void_entry(entry_id, reason=reason, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Ledger-Control Entry Voided", {key: value for key, value in record.items() if key != "lines"})


@finance_core_app.command("trial-balance")
def finance_core_trial_balance_command(
    period_id: Annotated[str, typer.Option("--period-id", help="Fiscal-period identifier.")],
    organization: Annotated[str, typer.Option(help="Organization code.")],
    entity: Annotated[str, typer.Option(help="Legal-entity code.")],
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Print a validated local ledger-control trial balance as JSON."""

    try:
        service, connection = _finance_core_service(db_path)
        try:
            payload = service.trial_balance(
                period_id=period_id,
                organization_code=organization,
                entity_code=entity,
                workspace=workspace,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@inventory_app.command("summary")
def inventory_summary_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Show local inventory-core record counts."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            record = service.summary(workspace=workspace, actor_label=actor).to_dict()
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Inventory Core Summary", record)


@inventory_app.command("snapshot")
def inventory_snapshot_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Print the bounded, path-free inventory-core snapshot as JSON."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            payload = service.snapshot(workspace=workspace, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@inventory_app.command("units")
def inventory_units_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local units of measure."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            records = service.list_uoms(workspace=workspace, limit=limit, offset=offset, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Units of Measure", records)


@inventory_app.command("unit-upsert")
def inventory_unit_upsert_command(
    code: Annotated[str, typer.Option(help="Unit code.")],
    name: Annotated[str, typer.Option(help="Unit display name.")],
    category: Annotated[str, typer.Option(help="Count, Weight, Volume, Length, Time, or Custom.")] = "Count",
    decimal_places: Annotated[int, typer.Option("--decimals", min=0, max=6, help="Quantity decimal places.")] = 0,
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    active: Annotated[bool, typer.Option("--active/--inactive", help="Whether the unit is active.")] = True,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update one exact-precision unit of measure."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            record = service.upsert_uom(
                uom_code=code,
                name=name,
                workspace=workspace,
                category=category,
                decimal_places=decimal_places,
                active=active,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Unit of Measure Saved", record)


@inventory_app.command("items")
def inventory_items_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    organization: Annotated[str, typer.Option(help="Optional organization-code filter.")] = "",
    active_only: Annotated[bool, typer.Option("--active-only", help="Return active items only.")] = False,
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local inventory items."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            records = service.list_items(
                workspace=workspace,
                organization_code=organization,
                active_only=active_only,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Inventory Items", records)


@inventory_app.command("item-upsert")
def inventory_item_upsert_command(
    code: Annotated[str, typer.Option(help="Item code.")],
    name: Annotated[str, typer.Option(help="Item display name.")],
    organization: Annotated[str, typer.Option(help="Optional organization scope.")] = "",
    unit: Annotated[str, typer.Option(help="Unit-of-measure code.")] = "EA",
    item_type: Annotated[str, typer.Option("--type", help="Stock, Consumable, or Service.")] = "Stock",
    tracking: Annotated[str, typer.Option(help="None, Lot, or Serial.")] = "None",
    inventory_account: Annotated[str, typer.Option(help="Optional local inventory account code.")] = "",
    description: Annotated[str, typer.Option(help="Optional item description.")] = "",
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    active: Annotated[bool, typer.Option("--active/--inactive", help="Whether the item is active.")] = True,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update one governed inventory item."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            record = service.upsert_item(
                item_code=code,
                name=name,
                workspace=workspace,
                organization_code=organization,
                uom_code=unit,
                item_type=item_type,
                tracking_mode=tracking,
                inventory_account_code=inventory_account,
                description=description,
                active=active,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Inventory Item Saved", record)


@inventory_app.command("warehouses")
def inventory_warehouses_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    organization: Annotated[str, typer.Option(help="Optional organization-code filter.")] = "",
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local warehouses."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            records = service.list_warehouses(
                workspace=workspace,
                organization_code=organization,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Warehouses", records)


@inventory_app.command("warehouse-upsert")
def inventory_warehouse_upsert_command(
    code: Annotated[str, typer.Option(help="Warehouse code.")],
    name: Annotated[str, typer.Option(help="Warehouse display name.")],
    organization: Annotated[str, typer.Option(help="Organization code.")],
    entity: Annotated[str, typer.Option(help="Optional legal-entity scope.")] = "",
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    active: Annotated[bool, typer.Option("--active/--inactive", help="Whether the warehouse is active.")] = True,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update one local warehouse."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            record = service.upsert_warehouse(
                warehouse_code=code,
                name=name,
                organization_code=organization,
                workspace=workspace,
                entity_code=entity,
                active=active,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Warehouse Saved", record)


@inventory_app.command("locations")
def inventory_locations_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    organization: Annotated[str, typer.Option(help="Optional organization-code filter.")] = "",
    warehouse: Annotated[str, typer.Option(help="Optional warehouse-code filter.")] = "",
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local warehouse locations."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            records = service.list_locations(
                workspace=workspace,
                organization_code=organization,
                warehouse_code=warehouse,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Inventory Locations", records)


@inventory_app.command("location-upsert")
def inventory_location_upsert_command(
    warehouse: Annotated[str, typer.Option(help="Warehouse code.")],
    code: Annotated[str, typer.Option(help="Location code.")],
    name: Annotated[str, typer.Option(help="Location display name.")],
    organization: Annotated[str, typer.Option(help="Organization code.")],
    parent: Annotated[str, typer.Option(help="Optional parent-location code.")] = "",
    location_type: Annotated[str, typer.Option("--type", help="Location type.")] = "Internal",
    allow_negative: Annotated[
        bool, typer.Option("--allow-negative/--protect-negative", help="Allow local negative on-hand stock.")
    ] = False,
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    active: Annotated[bool, typer.Option("--active/--inactive", help="Whether the location is active.")] = True,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update one hierarchical inventory location."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            record = service.upsert_location(
                warehouse_code=warehouse,
                location_code=code,
                name=name,
                organization_code=organization,
                workspace=workspace,
                parent_location_code=parent,
                location_type=location_type,
                allow_negative=allow_negative,
                active=active,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Inventory Location Saved", record)


@inventory_app.command("lots")
def inventory_lots_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    organization: Annotated[str, typer.Option(help="Optional organization-code filter.")] = "",
    item: Annotated[str, typer.Option(help="Optional item-code filter.")] = "",
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local lot and serial references."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            records = service.list_lots(
                workspace=workspace,
                organization_code=organization,
                item_code=item,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Lots and Serials", records)


@inventory_app.command("lot-upsert")
def inventory_lot_upsert_command(
    item: Annotated[str, typer.Option(help="Tracked item code.")],
    code: Annotated[str, typer.Option(help="Lot or serial code.")],
    organization: Annotated[str, typer.Option(help="Organization code.")],
    manufactured_on: Annotated[str, typer.Option("--manufactured-on", help="Optional YYYY-MM-DD date.")] = "",
    expires_on: Annotated[str, typer.Option("--expires-on", help="Optional YYYY-MM-DD date.")] = "",
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    active: Annotated[bool, typer.Option("--active/--inactive", help="Whether the reference is active.")] = True,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or update one governed lot or serial reference."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            record = service.upsert_lot(
                item_code=item,
                lot_serial_code=code,
                organization_code=organization,
                workspace=workspace,
                manufactured_on=manufactured_on,
                expires_on=expires_on,
                active=active,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Lot or Serial Saved", record)


@inventory_app.command("movement-create")
def inventory_movement_create_command(
    number: Annotated[str, typer.Option(help="Unique local movement number.")],
    movement_type: Annotated[str, typer.Option("--type", help="Receipt, Delivery, Transfer, or Adjustment.")],
    organization: Annotated[str, typer.Option(help="Organization code.")],
    entity: Annotated[str, typer.Option(help="Legal-entity code.")],
    period_id: Annotated[str, typer.Option("--period-id", help="Fiscal-period identifier.")],
    movement_date: Annotated[str, typer.Option("--date", help="Movement date in YYYY-MM-DD format.")],
    description: Annotated[str, typer.Option(help="Movement description.")],
    lines_path: Annotated[Path, typer.Option("--lines", help="Local JSON movement-lines file.")],
    reference: Annotated[str, typer.Option(help="Optional source-document reference.")] = "",
    source_type: Annotated[str, typer.Option("--source-type", help="Manual, Imported, or Generated.")] = "Manual",
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Create or replace a Draft local inventory movement from strict JSON."""

    try:
        lines = _inventory_lines_from_json(lines_path)
        service, connection = _inventory_service(db_path)
        try:
            record = service.create_movement(
                movement_number=number,
                movement_type=movement_type,
                organization_code=organization,
                entity_code=entity,
                period_id=period_id,
                movement_date=movement_date,
                description=description,
                lines=lines,
                workspace=workspace,
                source_reference=reference,
                source_type=source_type,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Inventory Movement Saved", {key: value for key, value in record.items() if key != "lines"})


@inventory_app.command("movements")
def inventory_movements_command(
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    organization: Annotated[str, typer.Option(help="Optional organization-code filter.")] = "",
    entity: Annotated[str, typer.Option(help="Optional entity-code filter.")] = "",
    period_id: Annotated[str, typer.Option("--period-id", help="Optional fiscal-period filter.")] = "",
    status: Annotated[str, typer.Option(help="Optional Draft, Posted, or Voided filter.")] = "",
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local inventory movement headers."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            records = service.list_movements(
                workspace=workspace,
                organization_code=organization,
                entity_code=entity,
                period_id=period_id,
                status=status,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Inventory Movements", records)


@inventory_app.command("movement-show")
def inventory_movement_show_command(
    movement_id: Annotated[str, typer.Option("--movement-id", help="Inventory-movement identifier.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Print one local inventory movement and its lines as JSON."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            record = service.get_movement(movement_id, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    typer.echo(json.dumps(record, indent=2, sort_keys=True))


@inventory_app.command("movement-post")
def inventory_movement_post_command(
    movement_id: Annotated[str, typer.Option("--movement-id", help="Inventory-movement identifier.")],
    reason: Annotated[str, typer.Option(help="Documented local posting reason.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Post a reviewed local movement without updating a source ERP."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            record = service.post_movement(movement_id, reason=reason, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Inventory Movement Posted", {key: value for key, value in record.items() if key != "lines"})


@inventory_app.command("movement-void")
def inventory_movement_void_command(
    movement_id: Annotated[str, typer.Option("--movement-id", help="Inventory-movement identifier.")],
    reason: Annotated[str, typer.Option(help="Documented void reason.")],
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Void a Posted local movement when stock constraints remain valid."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            record = service.void_movement(movement_id, reason=reason, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Inventory Movement Voided", {key: value for key, value in record.items() if key != "lines"})


@inventory_app.command("on-hand")
def inventory_on_hand_command(
    organization: Annotated[str, typer.Option(help="Organization code.")],
    entity: Annotated[str, typer.Option(help="Legal-entity code.")],
    item: Annotated[str, typer.Option(help="Optional item-code filter.")] = "",
    warehouse: Annotated[str, typer.Option(help="Optional warehouse-code filter.")] = "",
    include_zero: Annotated[bool, typer.Option("--include-zero", help="Include zero-balance rows.")] = False,
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    limit: Annotated[int, typer.Option(min=1, max=100_000, help="Maximum records to return.")] = 500,
    offset: Annotated[int, typer.Option(min=0, max=10_000_000, help="Records to skip.")] = 0,
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Print exact local on-hand quantities derived from Posted movements."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            payload = service.on_hand(
                organization_code=organization,
                entity_code=entity,
                workspace=workspace,
                item_code=item,
                warehouse_code=warehouse,
                include_zero=include_zero,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@inventory_app.command("control-exceptions")
def inventory_control_exceptions_command(
    organization: Annotated[str, typer.Option(help="Organization code.")],
    entity: Annotated[str, typer.Option(help="Legal-entity code.")],
    as_of: Annotated[str, typer.Option("--as-of", help="Optional deterministic YYYY-MM-DD control date.")] = "",
    workspace: Annotated[str, typer.Option(help="Local workspace name.")] = "default",
    actor: Annotated[str, typer.Option(help="Actor username or local label.")] = "local-cli",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Print deterministic local inventory-control exceptions as JSON."""

    try:
        service, connection = _inventory_service(db_path)
        try:
            payload = service.control_exceptions(
                organization_code=organization,
                entity_code=entity,
                workspace=workspace,
                as_of=as_of,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _postgres_operator_boundary(
    postgres_dsn: str | None,
    *,
    require_tls: bool,
) -> PostgresTenantBoundary:
    if postgres_dsn is None:
        raise PostgresConfigurationError(
            "PostgreSQL DSN is required through RECONFORGE_POSTGRES_DSN or --postgres-dsn."
        )
    settings = PostgresSettings(
        dsn=postgres_dsn,
        application_name="reconforge-scim-operator",
        require_tls=require_tls,
    )
    return PostgresTenantBoundary(PostgresConnectionFactory(settings))


def _scim_operator_failure(exc: Exception) -> None:
    if isinstance(exc, (PostgresConfigurationError, PostgresUnavailableError, SCIMError)):
        console.print(f"[red]{exc}[/red]")
    else:
        console.print("[red]SCIM credential operation failed; inspect server logs using the request time.[/red]")
    raise typer.Exit(code=1) from exc


@scim_app.command("credential-issue")
def scim_credential_issue_command(
    tenant: Annotated[str, typer.Option(help="Tenant identifier owning the credential.")],
    domain: Annotated[str, typer.Option(help="Provisioning-domain identifier.")],
    client: Annotated[str, typer.Option(help="SCIM client identifier.")],
    actor: Annotated[str, typer.Option(help="Operator identity recorded for the issuance.")],
    ttl_hours: Annotated[int, typer.Option("--ttl-hours", min=1, max=8784, help="Credential lifetime in hours.")] = 24,
    postgres_dsn: Annotated[
        str | None,
        typer.Option(
            "--postgres-dsn",
            envvar="RECONFORGE_POSTGRES_DSN",
            help="PostgreSQL DSN; prefer RECONFORGE_POSTGRES_DSN.",
        ),
    ] = None,
    require_tls: Annotated[
        bool,
        typer.Option("--require-tls/--no-require-tls", help="Require PostgreSQL TLS verification."),
    ] = True,
) -> None:
    """Issue an opaque bearer credential and print its secret exactly once."""

    try:
        boundary = _postgres_operator_boundary(postgres_dsn, require_tls=require_tls)
        with boundary.transaction(tenant) as connection:
            issued = PostgresSCIMCredentialRepository(connection).issue(
                tenant_id=tenant,
                provisioning_domain=domain,
                client_id=client,
                actor_id=actor,
                ttl=timedelta(hours=ttl_hours),
            )
    except Exception as exc:
        _scim_operator_failure(exc)
    typer.echo(
        json.dumps(
            {
                "credential_id": issued.id,
                "tenant_id": issued.tenant_id,
                "provisioning_domain": issued.provisioning_domain,
                "client_id": issued.client_id,
                "expires_at": issued.expires_at.isoformat(),
                "token": issued.token,
                "warning": "Store this token now; ReconForge persists only its hash and cannot display it again.",
            },
            indent=2,
            sort_keys=True,
        )
    )


@scim_app.command("credential-rotate")
def scim_credential_rotate_command(
    credential_id: Annotated[str, typer.Option("--credential-id", help="Active credential to replace.")],
    tenant: Annotated[str, typer.Option(help="Tenant identifier owning the credential.")],
    domain: Annotated[str, typer.Option(help="Provisioning-domain identifier.")],
    client: Annotated[str, typer.Option(help="SCIM client identifier.")],
    actor: Annotated[str, typer.Option(help="Operator identity recorded for the rotation.")],
    ttl_hours: Annotated[int, typer.Option("--ttl-hours", min=1, max=8784, help="New lifetime in hours.")] = 24,
    postgres_dsn: Annotated[
        str | None,
        typer.Option(
            "--postgres-dsn", envvar="RECONFORGE_POSTGRES_DSN", help="PostgreSQL DSN; prefer the environment."
        ),
    ] = None,
    require_tls: Annotated[bool, typer.Option("--require-tls/--no-require-tls")] = True,
) -> None:
    """Atomically issue a successor and revoke the previous credential."""

    try:
        boundary = _postgres_operator_boundary(postgres_dsn, require_tls=require_tls)
        with boundary.transaction(tenant) as connection:
            issued = PostgresSCIMCredentialRepository(connection).issue(
                tenant_id=tenant,
                provisioning_domain=domain,
                client_id=client,
                actor_id=actor,
                ttl=timedelta(hours=ttl_hours),
                rotated_from_id=credential_id,
            )
    except Exception as exc:
        _scim_operator_failure(exc)
    typer.echo(
        json.dumps(
            {
                "credential_id": issued.id,
                "rotated_from_id": credential_id,
                "tenant_id": issued.tenant_id,
                "provisioning_domain": issued.provisioning_domain,
                "client_id": issued.client_id,
                "expires_at": issued.expires_at.isoformat(),
                "token": issued.token,
                "warning": "Store this token now; the previous credential is revoked and this token cannot be displayed again.",
            },
            indent=2,
            sort_keys=True,
        )
    )


@scim_app.command("credential-revoke")
def scim_credential_revoke_command(
    credential_id: Annotated[str, typer.Option("--credential-id", help="Credential to revoke.")],
    tenant: Annotated[str, typer.Option(help="Tenant identifier owning the credential.")],
    actor: Annotated[str, typer.Option(help="Operator identity recorded for the revocation.")],
    postgres_dsn: Annotated[
        str | None,
        typer.Option(
            "--postgres-dsn", envvar="RECONFORGE_POSTGRES_DSN", help="PostgreSQL DSN; prefer the environment."
        ),
    ] = None,
    require_tls: Annotated[bool, typer.Option("--require-tls/--no-require-tls")] = True,
) -> None:
    """Revoke one active SCIM credential without revealing secret material."""

    try:
        boundary = _postgres_operator_boundary(postgres_dsn, require_tls=require_tls)
        with boundary.transaction(tenant) as connection:
            revoked = PostgresSCIMCredentialRepository(connection).revoke(
                tenant_id=tenant,
                credential_id=credential_id,
                actor_id=actor,
            )
    except Exception as exc:
        _scim_operator_failure(exc)
    typer.echo(
        json.dumps(
            {"credential_id": credential_id, "tenant_id": tenant, "revoked": revoked},
            indent=2,
            sort_keys=True,
        )
    )


def _service_account_operator_failure(exc: Exception) -> None:
    if isinstance(exc, (PostgresConfigurationError, PostgresUnavailableError, ServiceAccountError)):
        console.print(f"[red]{exc}[/red]")
    else:
        console.print("[red]Service-account operation failed; inspect server logs using the request time.[/red]")
    raise typer.Exit(code=1) from exc


@service_accounts_app.command("create")
def service_account_create_command(
    account_id: Annotated[str, typer.Option("--account-id", help="Stable svc-* account identifier.")],
    name: Annotated[str, typer.Option(help="Stable machine-readable account name.")],
    display_name: Annotated[str, typer.Option("--display-name", help="Operator-facing account name.")],
    permission: Annotated[list[str], typer.Option("--permission", help="Explicit permission; repeat as needed.")],
    tenant: Annotated[str, typer.Option(help="Tenant identifier owning the account.")],
    actor: Annotated[str, typer.Option(help="Human operator identity recorded in audit.")],
    max_ttl_hours: Annotated[
        int, typer.Option("--max-ttl-hours", min=1, max=2160, help="Maximum credential lifetime in hours.")
    ] = 720,
    postgres_dsn: Annotated[
        str | None,
        typer.Option("--postgres-dsn", envvar="RECONFORGE_POSTGRES_DSN", help="Prefer the environment."),
    ] = None,
    require_tls: Annotated[bool, typer.Option("--require-tls/--no-require-tls")] = True,
) -> None:
    """Create a role-free service account with explicit direct permissions."""

    try:
        boundary = _postgres_operator_boundary(postgres_dsn, require_tls=require_tls)
        with boundary.transaction(tenant) as connection:
            account = PostgresServiceAccountRepository(connection).create_account(
                tenant_id=tenant,
                account_id=account_id,
                name=name,
                display_name=display_name,
                permissions=frozenset(permission),
                actor_id=actor,
                max_credential_ttl=timedelta(hours=max_ttl_hours),
            )
    except Exception as exc:
        _service_account_operator_failure(exc)
    typer.echo(json.dumps(asdict(account), indent=2, sort_keys=True, default=list))


def _service_credential_payload(
    credential: IssuedServiceCredential, *, rotated_from_id: str | None = None
) -> dict[str, object]:
    payload: dict[str, object] = {
        "credential_id": credential.id,
        "service_account_id": credential.service_account_id,
        "expires_at": credential.expires_at.isoformat(),
        "token": credential.token,
        "warning": "Store this token now; ReconForge persists only its hash and cannot display it again.",
    }
    if rotated_from_id is not None:
        payload["rotated_from_id"] = rotated_from_id
    return payload


@service_accounts_app.command("credential-issue")
def service_account_credential_issue_command(
    account_id: Annotated[str, typer.Option("--account-id")],
    tenant: Annotated[str, typer.Option()],
    actor: Annotated[str, typer.Option()],
    ttl_hours: Annotated[int, typer.Option("--ttl-hours", min=1, max=2160)] = 24,
    postgres_dsn: Annotated[
        str | None, typer.Option("--postgres-dsn", envvar="RECONFORGE_POSTGRES_DSN", help="Prefer the environment.")
    ] = None,
    require_tls: Annotated[bool, typer.Option("--require-tls/--no-require-tls")] = True,
) -> None:
    """Issue a service credential and reveal its token exactly once."""

    try:
        boundary = _postgres_operator_boundary(postgres_dsn, require_tls=require_tls)
        with boundary.transaction(tenant) as connection:
            issued = PostgresServiceAccountRepository(connection).issue_credential(
                tenant_id=tenant, account_id=account_id, actor_id=actor, ttl=timedelta(hours=ttl_hours)
            )
    except Exception as exc:
        _service_account_operator_failure(exc)
    typer.echo(json.dumps(_service_credential_payload(issued), indent=2, sort_keys=True))


@service_accounts_app.command("credential-rotate")
def service_account_credential_rotate_command(
    credential_id: Annotated[str, typer.Option("--credential-id")],
    account_id: Annotated[str, typer.Option("--account-id")],
    tenant: Annotated[str, typer.Option()],
    actor: Annotated[str, typer.Option()],
    ttl_hours: Annotated[int, typer.Option("--ttl-hours", min=1, max=2160)] = 24,
    postgres_dsn: Annotated[
        str | None, typer.Option("--postgres-dsn", envvar="RECONFORGE_POSTGRES_DSN", help="Prefer the environment.")
    ] = None,
    require_tls: Annotated[bool, typer.Option("--require-tls/--no-require-tls")] = True,
) -> None:
    """Issue a successor and revoke the previous credential atomically."""

    try:
        boundary = _postgres_operator_boundary(postgres_dsn, require_tls=require_tls)
        with boundary.transaction(tenant) as connection:
            issued = PostgresServiceAccountRepository(connection).issue_credential(
                tenant_id=tenant,
                account_id=account_id,
                actor_id=actor,
                ttl=timedelta(hours=ttl_hours),
                rotated_from_id=credential_id,
            )
    except Exception as exc:
        _service_account_operator_failure(exc)
    typer.echo(json.dumps(_service_credential_payload(issued, rotated_from_id=credential_id), indent=2, sort_keys=True))


@service_accounts_app.command("credential-revoke")
def service_account_credential_revoke_command(
    credential_id: Annotated[str, typer.Option("--credential-id")],
    tenant: Annotated[str, typer.Option()],
    actor: Annotated[str, typer.Option()],
    postgres_dsn: Annotated[
        str | None, typer.Option("--postgres-dsn", envvar="RECONFORGE_POSTGRES_DSN", help="Prefer the environment.")
    ] = None,
    require_tls: Annotated[bool, typer.Option("--require-tls/--no-require-tls")] = True,
) -> None:
    """Revoke one service credential without revealing secret material."""

    try:
        boundary = _postgres_operator_boundary(postgres_dsn, require_tls=require_tls)
        with boundary.transaction(tenant) as connection:
            revoked = PostgresServiceAccountRepository(connection).revoke_credential(
                tenant_id=tenant, credential_id=credential_id, actor_id=actor
            )
    except Exception as exc:
        _service_account_operator_failure(exc)
    typer.echo(json.dumps({"credential_id": credential_id, "tenant_id": tenant, "revoked": revoked}, sort_keys=True))


@service_accounts_app.command("disable")
def service_account_disable_command(
    account_id: Annotated[str, typer.Option("--account-id")],
    expected_version: Annotated[int, typer.Option("--expected-version", min=1)],
    tenant: Annotated[str, typer.Option()],
    actor: Annotated[str, typer.Option()],
    postgres_dsn: Annotated[
        str | None, typer.Option("--postgres-dsn", envvar="RECONFORGE_POSTGRES_DSN", help="Prefer the environment.")
    ] = None,
    require_tls: Annotated[bool, typer.Option("--require-tls/--no-require-tls")] = True,
) -> None:
    """Disable an account and revoke all of its active credentials atomically."""

    try:
        boundary = _postgres_operator_boundary(postgres_dsn, require_tls=require_tls)
        with boundary.transaction(tenant) as connection:
            account = PostgresServiceAccountRepository(connection).set_enabled(
                tenant_id=tenant,
                account_id=account_id,
                enabled=False,
                expected_version=expected_version,
                actor_id=actor,
            )
    except Exception as exc:
        _service_account_operator_failure(exc)
    typer.echo(json.dumps(asdict(account), indent=2, sort_keys=True, default=list))


@api_app.command("serve")
def api_serve_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    tenant_db_root: Annotated[
        Path | None,
        typer.Option(
            "--tenant-db-root", help="Optional database-per-tenant root; requests require X-ReconForge-Tenant."
        ),
    ] = None,
    host: Annotated[str, typer.Option("--host", help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Bind port.")] = 8765,
    postgres_dsn: Annotated[
        str | None,
        typer.Option(
            "--postgres-dsn",
            envvar="RECONFORGE_POSTGRES_DSN",
            help="Optional PostgreSQL server-auth DSN; prefer RECONFORGE_POSTGRES_DSN in the environment.",
        ),
    ] = None,
    postgres_require_tls: Annotated[
        bool,
        typer.Option("--postgres-require-tls/--postgres-no-tls", help="Require PostgreSQL TLS verification."),
    ] = True,
    redis_url: Annotated[
        str | None,
        typer.Option(
            "--redis-url",
            envvar="RECONFORGE_REDIS_URL",
            help="Optional Redis coordination URL; prefer RECONFORGE_REDIS_URL in the environment.",
        ),
    ] = None,
    redis_require_tls: Annotated[
        bool,
        typer.Option("--redis-require-tls/--redis-no-tls", help="Require Redis TLS."),
    ] = True,
    federation_config: Annotated[
        Path | None,
        typer.Option(
            "--federation-config",
            envvar="RECONFORGE_FEDERATION_CONFIG",
            help="Optional bounded JSON OIDC/SAML configuration containing public verification material only.",
        ),
    ] = None,
    webauthn_config: Annotated[
        Path | None,
        typer.Option(
            "--webauthn-config",
            envvar="RECONFORGE_WEBAUTHN_CONFIG",
            help="Optional closed JSON WebAuthn RP ID and exact-origin configuration.",
        ),
    ] = None,
    web_root: Annotated[
        Path | None,
        typer.Option("--web-root", envvar="RECONFORGE_WEB_ROOT", help="Optional built Studio directory served from the API origin."),
    ] = None,
    allowed_host: Annotated[
        list[str] | None,
        typer.Option("--allowed-host", help="Repeatable exact Host allowlist for a deployed browser origin."),
    ] = None,
    tls_certfile: Annotated[
        Path | None,
        typer.Option("--tls-certfile", envvar="RECONFORGE_TLS_CERTFILE", help="PEM certificate chain for direct HTTPS."),
    ] = None,
    tls_keyfile: Annotated[
        Path | None,
        typer.Option("--tls-keyfile", envvar="RECONFORGE_TLS_KEYFILE", help="PEM private key for direct HTTPS."),
    ] = None,
    secure_transport: Annotated[
        bool,
        typer.Option("--secure-transport/--insecure-transport", help="Assert reviewed upstream TLS termination and emit HSTS."),
    ] = False,
    otlp_http_endpoint: Annotated[
        str | None,
        typer.Option("--otlp-http-endpoint", help="Explicit OTLP/HTTP collector origin; disabled when omitted."),
    ] = None,
    otlp_allowed_host: Annotated[
        list[str] | None,
        typer.Option("--otlp-allowed-host", help="Repeatable exact non-loopback OTLP host allowlist."),
    ] = None,
    otlp_certificate_file: Annotated[
        Path | None,
        typer.Option("--otlp-certificate-file", help="Optional collector CA certificate path."),
    ] = None,
    otlp_client_certificate_file: Annotated[
        Path | None,
        typer.Option("--otlp-client-certificate-file", help="Optional mTLS client certificate path."),
    ] = None,
    otlp_client_key_file: Annotated[
        Path | None,
        typer.Option("--otlp-client-key-file", help="Optional mTLS client key path."),
    ] = None,
) -> None:
    """Start the local REST API or explicit PostgreSQL server-auth profile."""

    runtime = ObservabilityRuntime.disabled()
    try:
        if (tls_certfile is None) != (tls_keyfile is None):
            raise ValueError("TLS certificate and key must be configured together.")
        if tls_certfile is not None and (not tls_certfile.is_file() or not tls_keyfile or not tls_keyfile.is_file()):
            raise ValueError("TLS certificate and key files must exist.")
        direct_tls = tls_certfile is not None
        if web_root is not None and not allowed_host:
            raise ValueError("A deployed web root requires at least one exact --allowed-host.")
        if secure_transport and direct_tls:
            raise ValueError("Use direct TLS files or --secure-transport for upstream termination, not both.")
        if tenant_db_root is None:
            status = database_status(_db_option(db_path))
            if status.pending_versions:
                console.print(
                    "[red]ReconForge database has pending migrations. Run 'reconforge db migrate' first.[/red]"
                )
                raise typer.Exit(code=1)
        else:
            TenantDatabaseRouter.from_root(tenant_db_root)
    except (DatabaseError, TenantRoutingError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if host == ALL_INTERFACES_HOST:
        console.print(
            f"[yellow]Warning:[/yellow] binding to {ALL_INTERFACES_HOST} exposes the local API beyond localhost. This is not a public internet deployment mode."
        )
    try:
        if federation_config is not None and postgres_dsn is None:
            raise ValueError("Federation configuration requires the PostgreSQL server-auth profile.")
        if webauthn_config is not None and postgres_dsn is None:
            raise ValueError("WebAuthn configuration requires the PostgreSQL server-auth profile.")
        federation = load_federation_runtime(federation_config) if federation_config is not None else None
        webauthn_runtime = load_webauthn_runtime(webauthn_config) if webauthn_config is not None else None
        if otlp_http_endpoint is not None:
            runtime = create_otlp_http_runtime(
                OTLPHTTPConfiguration(
                    endpoint=otlp_http_endpoint,
                    allowed_hosts=tuple(otlp_allowed_host or ()),
                    certificate_file=otlp_certificate_file,
                    client_certificate_file=otlp_client_certificate_file,
                    client_key_file=otlp_client_key_file,
                )
            )
        application = create_api_app(
            db_path,
            tenant_db_root=tenant_db_root,
            postgres_dsn=postgres_dsn,
            postgres_require_tls=postgres_require_tls,
            redis_url=redis_url,
            redis_require_tls=redis_require_tls,
            federation_providers=federation.providers if federation is not None else None,
            federation_verifiers=federation.verifiers if federation is not None else None,
            federation_air_gap_mode=federation.air_gap_mode if federation is not None else False,
            webauthn_runtime=webauthn_runtime,
            web_root=web_root,
            allowed_hosts=tuple(allowed_host or ()),
            secure_transport=direct_tls or secure_transport,
            observability=runtime,
            reliability_window=HttpReliabilityWindow() if runtime.enabled else None,
        )
    except (
        DatabaseError,
        FederationConfigurationError,
        WebAuthnConfigurationError,
        ObservabilityConfigurationError,
        TenantRoutingError,
        ValueError,
    ) as exc:
        runtime.shutdown()
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    scheme = "https" if tls_certfile is not None else "http"
    console.print(f"[green]Starting ReconForge local API:[/green] {scheme}://{host}:{port}")
    try:
        uvicorn.run(
            application,
            host=host,
            port=port,
            log_level="info",
            ssl_certfile=str(tls_certfile) if tls_certfile is not None else None,
            ssl_keyfile=str(tls_keyfile) if tls_keyfile is not None else None,
        )
    finally:
        runtime.force_flush()
        runtime.shutdown()


@db_app.command("init")
def db_init_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Initialize the local SQLite database."""

    try:
        status = run_migrations(_db_option(db_path))
    except DatabaseError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    applied = ", ".join(str(version) for version in status.applied_versions) or "already current"
    console.print(f"[green]Database ready:[/green] {status.path}")
    console.print(f"Schema version: {status.current_version}/{status.latest_version} | Applied: {applied}")


@outbox_app.command("list")
def outbox_list_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    status: Annotated[str, typer.Option("--status", help="pending, published, dead_letter, or all.")] = "pending",
    limit: Annotated[int, typer.Option("--limit", help="Maximum events to return.")] = 100,
) -> None:
    """List local transactional outbox events as machine-readable JSON."""

    connection: sqlite3.Connection | None = None
    try:
        connection = connect(_db_option(db_path), require_exists=True)
        events = OutboxService(connection).list_events(status=status, limit=limit)
        typer.echo(json.dumps([asdict(event) for event in events], indent=2, sort_keys=True))
    except (DatabaseError, OutboxError) as exc:
        _safe_cli_error(exc)
    finally:
        if connection is not None:
            connection.close()


@outbox_app.command("requeue")
def outbox_requeue_command(
    event_id: Annotated[str, typer.Argument(help="Dead-lettered outbox event identifier.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Requeue one dead-lettered event for an explicit operator replay."""

    connection: sqlite3.Connection | None = None
    try:
        connection = connect(_db_option(db_path), require_exists=True)
        OutboxService(connection).requeue_dead_letter(event_id=event_id)
    except (DatabaseError, OutboxError) as exc:
        _safe_cli_error(exc)
    finally:
        if connection is not None:
            connection.close()
    typer.echo(json.dumps({"event_id": event_id, "status": "requeued"}, sort_keys=True))


@db_app.command("migrate")
def db_migrate_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Apply pending local SQLite migrations."""

    try:
        status = run_migrations(_db_option(db_path))
    except DatabaseError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    applied = ", ".join(str(version) for version in status.applied_versions) or "none"
    console.print(f"[green]Database migrated:[/green] {status.path}")
    console.print(f"Schema version: {status.current_version}/{status.latest_version} | Applied now: {applied}")


@db_app.command("status")
def db_status_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Show local SQLite migration status."""

    try:
        status = database_status(_db_option(db_path))
    except DatabaseError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    table = Table(title="ReconForge Database")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Path", str(status.path))
    table.add_row("Current version", str(status.current_version))
    table.add_row("Latest version", str(status.latest_version))
    table.add_row("Applied versions", ", ".join(str(version) for version in status.applied_versions) or "none")
    table.add_row("Pending versions", ", ".join(str(version) for version in status.pending_versions) or "none")
    console.print(table)


@db_app.command("export")
def db_export_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    output_path: Annotated[
        Path, typer.Option("--output", help="Local output directory for sanitized JSON export.")
    ] = Path("output/db_export"),
) -> None:
    """Export sanitized local DB records to deterministic JSON files."""

    try:
        result = export_database(_db_option(db_path), output_path)
    except (DatabaseError, DBBridgeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Database export written:[/green] {result.output_dir}")
    console.print(f"Schema version: {result.schema_version} | Files: {len(result.paths)}")
    _print_success_paths(result.paths)


@db_app.command("export-recover")
def db_export_recover_command(
    output_path: Annotated[Path, typer.Option("--output", help="Interrupted local DB export directory.")] = Path(
        "output/db_export"
    ),
) -> None:
    """Explicitly recover one integrity-verified interrupted DB export publication."""

    try:
        result = recover_database_export_publication(output_path)
    except DBBridgeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps({"action": result.action, "transaction_id": result.transaction_id}, sort_keys=True))


@db_app.command("import-review-state")
def db_import_review_state_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    input_path: Annotated[Path, typer.Option("--input", help="Local review_state.json file.")] = Path(
        "output/review_state.json"
    ),
) -> None:
    """Import legacy review_state.json into DB bridge references."""

    try:
        result = import_review_state(_db_option(db_path), input_path)
    except (DatabaseError, DBBridgeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]Imported review state:[/green] {result.imported_count} records from {result.source_path.name}"
    )


@db_app.command("import-close")
def db_import_close_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    input_path: Annotated[
        Path, typer.Option("--input", help="Local close folder or close_checklist.json file.")
    ] = Path("output/close"),
) -> None:
    """Import legacy close_checklist.json task state into DB bridge references."""

    try:
        result = import_close_checklist(_db_option(db_path), input_path)
    except (DatabaseError, DBBridgeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]Imported close checklist:[/green] {result.imported_count} records from {result.source_path.name}"
    )


@db_app.command("import-accounts")
def db_import_accounts_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    input_path: Annotated[
        Path, typer.Option("--input", help="Local accounts folder or account_reconciliations.json file.")
    ] = Path("output/accounts"),
) -> None:
    """Import legacy account_reconciliations.json summaries into DB bridge references."""

    try:
        result = import_account_reconciliations(_db_option(db_path), input_path)
    except (DatabaseError, DBBridgeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]Imported account reconciliations:[/green] {result.imported_count} records from {result.source_path.name}"
    )


@db_app.command("import-control-tests")
def db_import_control_tests_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    input_path: Annotated[
        Path, typer.Option("--input", help="Local control_testing folder or control_tests.json file.")
    ] = Path("output/control_testing"),
) -> None:
    """Import legacy control_tests.json summaries into DB bridge references."""

    try:
        result = import_control_tests(_db_option(db_path), input_path)
    except (DatabaseError, DBBridgeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]Imported control tests:[/green] {result.imported_count} records from {result.source_path.name}"
    )


@db_app.command("backup")
def db_backup_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    output_path: Annotated[Path, typer.Option("--output", help="Local backup output directory.")] = Path(
        "output/backups"
    ),
) -> None:
    """Create a local DB backup with checksum manifest."""

    try:
        result = create_backup(_db_option(db_path), output_path)
    except (DatabaseError, DBBridgeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        "[yellow]Backup warning:[/yellow] local DB backups may contain sensitive business data and password hashes. Protect these files."
    )
    console.print(f"[green]Database backup written:[/green] {result.output_dir}")
    console.print(f"Schema version: {result.schema_version} | SHA-256: {result.checksum_sha256}")
    _print_success_paths([result.backup_path, result.manifest_path])


@db_app.command("restore")
def db_restore_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path to restore.")] = Path(
        "output/reconforge.db"
    ),
    input_path: Annotated[Path, typer.Option("--input", help="Local backup.json file or backup folder.")] = Path(
        "output/backups/backup.json"
    ),
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite an existing local DB after checksum validation.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Validate restore inputs without writing the target DB.")
    ] = False,
) -> None:
    """Restore a local DB backup after checksum validation."""

    try:
        result = restore_backup(_db_option(db_path), input_path, force=force, dry_run=dry_run)
    except (DatabaseError, DBBridgeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if result.dry_run:
        console.print("[green]Restore dry-run passed:[/green] backup checksum and schema are supported.")
        console.print(
            f"Target: {result.db_path} | Backup: {result.backup_path} | Schema version: {result.schema_version}"
        )
        return
    console.print(
        "[yellow]Restore warning:[/yellow] restored data is local only and may include sensitive business data."
    )
    console.print(f"[green]Database restored:[/green] {result.db_path}")
    console.print(f"Schema version: {result.schema_version} | Tables restored: {len(result.restored_tables)}")


@db_app.command("backup-encrypted")
def db_backup_encrypted_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    output_path: Annotated[Path, typer.Option("--output", help="Encrypted .rfbackup output file.")] = Path(
        "output/backups/reconforge.rfbackup"
    ),
    key_file: Annotated[
        Path,
        typer.Option("--key-file", help="File containing a 32-byte raw or 64-character hexadecimal key."),
    ] = Path("backup.key"),
) -> None:
    """Create an authenticated AES-256-GCM local backup envelope."""

    try:
        key = read_operator_backup_key(key_file)
        result = create_encrypted_backup(_db_option(db_path), output_path, key=key)
    except (DatabaseError, DBBridgeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Encrypted database backup written:[/green] {result.path}")
    console.print(f"Schema version: {result.source_schema_version} | Ciphertext SHA-256: {result.ciphertext_sha256}")
    console.print(
        "[yellow]Key custody:[/yellow] keep the operator key separate; loss of the key makes recovery impossible."
    )


@db_app.command("restore-encrypted")
def db_restore_encrypted_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path to restore.")] = Path(
        "output/reconforge.db"
    ),
    input_path: Annotated[Path, typer.Option("--input", help="Encrypted .rfbackup input file.")] = Path(
        "output/backups/reconforge.rfbackup"
    ),
    key_file: Annotated[
        Path,
        typer.Option("--key-file", help="File containing the backup's operator-owned key."),
    ] = Path("backup.key"),
    force: Annotated[
        bool, typer.Option("--force", help="Replace an existing local DB only after full authentication.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Authenticate and validate without writing the target DB.")
    ] = False,
) -> None:
    """Authenticate and restore an AES-256-GCM local backup envelope."""

    try:
        key = read_operator_backup_key(key_file)
        result = restore_encrypted_backup(_db_option(db_path), input_path, key=key, force=force, dry_run=dry_run)
    except (DatabaseError, DBBridgeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if result.dry_run:
        console.print("[green]Encrypted restore dry-run passed:[/green] authentication and schema checks succeeded.")
        return
    console.print(f"[green]Encrypted database restored:[/green] {result.db_path}")
    console.print(f"Schema version: {result.schema_version} | Tables restored: {len(result.restored_tables)}")


@db_app.command("backup-verify")
def db_backup_verify_command(
    input_path: Annotated[Path, typer.Option("--input", help="Local backup.json file or backup folder.")] = Path(
        "output/backups/backup.json"
    ),
) -> None:
    """Verify a local DB backup manifest and checksum."""

    try:
        result = verify_backup(input_path)
    except DBBridgeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Backup verified:[/green] {result.backup_path}")
    console.print(f"Schema version: {result.schema_version} | SHA-256: {result.checksum_sha256}")


@db_app.command("migration-dry-run")
def db_migration_dry_run_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Inspect migration status without mutating the database."""

    try:
        status = database_status(_db_option(db_path))
    except DatabaseError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    pending = ", ".join(str(version) for version in status.pending_versions) or "none"
    console.print(
        f"[green]Migration dry-run:[/green] current {status.current_version}/{status.latest_version} | pending: {pending}"
    )


@audit_app.command("list")
def audit_list_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    limit: Annotated[int | None, typer.Option("--limit", help="Maximum number of audit events to show.")] = None,
) -> None:
    """List local audit events."""

    try:
        connection = connect(_db_option(db_path), require_exists=True)
        try:
            events = list_audit_events(connection, limit=limit)
        finally:
            connection.close()
    except (DatabaseError, AuditLedgerError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    if not events:
        console.print("[yellow]No audit events found.[/yellow]")
        return
    table = Table(title="Audit Events")
    table.add_column("Seq", justify="right")
    table.add_column("Actor")
    table.add_column("Object")
    table.add_column("Action")
    table.add_column("Created")
    table.add_column("Hash")
    for event in events:
        table.add_row(
            str(event.sequence),
            event.actor_label,
            f"{event.object_type}:{event.object_id}",
            event.action,
            event.created_at,
            event.event_hash[:12],
        )
    console.print(table)


@audit_app.command("verify")
def audit_verify_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Verify the local audit event hash chain."""

    try:
        connection = connect(_db_option(db_path), require_exists=True)
        try:
            result = verify_audit_events(connection)
        finally:
            connection.close()
    except (DatabaseError, AuditLedgerError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    if result.ok:
        console.print(
            f"[green]Audit ledger verified:[/green] {result.checked_events} events | head {result.head_hash[:12]}"
        )
        return

    table = Table(title="Audit Verification Issues")
    table.add_column("Sequence")
    table.add_column("Issue")
    for issue in result.issues:
        table.add_row("" if issue.sequence is None else str(issue.sequence), issue.message)
    console.print(table)
    console.print("[red]Audit ledger verification failed.[/red]")
    raise typer.Exit(code=1)


def _receivables_json_records(input_path: Path, *, key: str) -> list[dict[str, object]]:
    try:
        resolved = resolve_input_file(input_path)
        document = read_json_record_document(resolved, envelope_keys=(key,))
    except DBBridgeError as exc:
        raise PlatformError("Receivables JSON input could not be read.") from exc
    except RecordIngressError as exc:
        if exc.code in {"json_record_collection_required", "json_record_not_object"}:
            raise PlatformError(f"Receivables JSON must be a list or an object containing a {key} list.") from exc
        raise PlatformError("Receivables JSON input could not be read.") from exc
    return document.records


def _receivable_invoice_line_from_json(item: dict[str, object]) -> ReceivableInvoiceLineInput:
    try:
        return ReceivableInvoiceLineInput(
            description=str(item.get("description", "")),
            quantity=str(item["quantity"]),
            unit_price_minor=int(str(item["unit_price_minor"])),
            line_total_minor=int(str(item["line_total_minor"])),
            tax_minor=int(str(item.get("tax_minor", 0))),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PlatformError(
            "Each receivables invoice line must contain quantity, unit_price_minor, and line_total_minor."
        ) from exc


def _receivable_allocation_from_json(item: dict[str, object]) -> ReceiptAllocationInput:
    try:
        return ReceiptAllocationInput(
            invoice_id=str(item["invoice_id"]),
            amount_minor=int(str(item["amount_minor"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PlatformError("Each receipt allocation must contain invoice_id and amount_minor.") from exc


@users_app.command("init-admin")
def users_init_admin_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    username: Annotated[str, typer.Option("--username", help="Admin username.")] = "admin",
) -> None:
    """Create the first local admin user."""

    password = _prompt_password()
    try:
        service, connection = _auth_service(db_path)
        try:
            user = service.init_admin(username=username, password=password)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Local admin created:[/green] {user.username}")


@users_app.command("add")
def users_add_command(
    username: Annotated[str, typer.Option("--username", help="Username to create.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    role: Annotated[str, typer.Option("--role", help="Built-in role to assign.")] = "reviewer",
    display_name: Annotated[str | None, typer.Option("--display-name", help="Optional display name.")] = None,
    email: Annotated[str | None, typer.Option("--email", help="Optional email reference.")] = None,
) -> None:
    """Create a local user and assign one role."""

    password = _prompt_password()
    try:
        service, connection = _auth_service(db_path)
        try:
            user = service.create_user(
                username=username,
                password=password,
                role=role,
                display_name=display_name,
                email=email,
            )
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Local user created:[/green] {user.username} | role: {role}")


@users_app.command("list")
def users_list_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local users without credential data."""

    try:
        service, connection = _auth_service(db_path)
        try:
            users = service.users.list()
            roles_by_user = {user.username: service.roles.user_roles(user.username) for user in users}
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if not users:
        console.print("[yellow]No local users found.[/yellow]")
        return
    table = Table(title="Local Users")
    table.add_column("Username")
    table.add_column("Display Name")
    table.add_column("Disabled")
    table.add_column("Roles")
    table.add_column("Created")
    for user in users:
        table.add_row(
            user.username,
            user.display_name,
            "yes" if user.disabled else "no",
            ", ".join(roles_by_user[user.username]) or "none",
            user.created_at,
        )
    console.print(table)


@users_app.command("disable")
def users_disable_command(
    username: Annotated[str, typer.Option("--username", help="Username to disable.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Disable a local user."""

    try:
        service, connection = _auth_service(db_path)
        try:
            user = service.disable_user(username=username)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Local user disabled:[/green] {user.username}")


@users_app.command("set-role")
def users_set_role_command(
    username: Annotated[str, typer.Option("--username", help="Username to update.")],
    role: Annotated[str, typer.Option("--role", help="Role to set.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Replace a local user's roles with one role."""

    try:
        service, connection = _auth_service(db_path)
        try:
            service.set_single_role(username=username, role=role)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Local user role updated:[/green] {username} | role: {role}")


@users_app.command("check-permission")
def users_check_permission_command(
    username: Annotated[str, typer.Option("--username", help="Username to check.")],
    permission: Annotated[str, typer.Option("--permission", help="Permission name to check.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Check whether a local user has a permission."""

    try:
        service, connection = _auth_service(db_path)
        try:
            allowed = service.user_has_permission(username=username, permission=permission)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if allowed:
        console.print(f"[green]Permission allowed:[/green] {username} | {permission}")
        return
    console.print(f"[red]Permission denied:[/red] {username} | {permission}")
    raise typer.Exit(code=1)


@roles_app.command("list")
def roles_list_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local built-in roles."""

    try:
        connection = connect(_db_option(db_path), require_exists=True)
        try:
            repository = RoleRepository(connection)
            roles = repository.list_roles()
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    table = Table(title="Local Roles")
    table.add_column("Role")
    for role in roles:
        table.add_row(role.name)
    console.print(table)


@roles_app.command("permissions")
def roles_permissions_command(
    role: Annotated[str, typer.Option("--role", help="Role to inspect.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List permissions assigned to one local role."""

    try:
        connection = connect(_db_option(db_path), require_exists=True)
        try:
            repository = RoleRepository(connection)
            permissions = repository.role_permissions(role)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, AuthServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    table = Table(title=f"Role Permissions: {role}")
    table.add_column("Permission")
    for permission in permissions:
        table.add_row(permission)
    console.print(table)


@workflow_app.command("transitions")
def workflow_transitions_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Workflow object type.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List allowed transition templates for a workflow object type."""

    try:
        service, connection = _workflow_service(db_path)
        try:
            transitions = service.list_allowed_transitions(object_type=object_type)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if not transitions:
        console.print("[yellow]No workflow transitions found.[/yellow]")
        return
    table = Table(title=f"Workflow Transitions: {object_type}")
    table.add_column("From")
    table.add_column("To")
    table.add_column("Permission")
    table.add_column("SoD")
    table.add_column("Reason")
    for transition in transitions:
        table.add_row(
            transition.from_status,
            transition.to_status,
            transition.required_permission or "",
            transition.sod_rule or "",
            "required" if transition.reason_required else "",
        )
    console.print(table)


@workflow_app.command("init-object")
def workflow_init_object_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Workflow object type.")],
    object_id: Annotated[str, typer.Option("--object-id", help="Workflow object identifier.")],
    status: Annotated[str, typer.Option("--status", help="Initial workflow status.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Initialize a local workflow object."""

    try:
        service, connection = _workflow_service(db_path)
        try:
            workflow_object = service.initialize_object(object_type=object_type, object_id=object_id, status=status)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]Workflow object initialized:[/green] {workflow_object.object_type}:{workflow_object.object_id} | {workflow_object.status}"
    )


@workflow_app.command("status")
def workflow_status_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Workflow object type.")],
    object_id: Annotated[str, typer.Option("--object-id", help="Workflow object identifier.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Show local workflow object status."""

    try:
        service, connection = _workflow_service(db_path)
        try:
            workflow_object = service.get_status(object_type=object_type, object_id=object_id)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    table = Table(title="Workflow Status")
    table.add_column("Object")
    table.add_column("Status")
    table.add_column("Updated")
    table.add_row(
        f"{workflow_object.object_type}:{workflow_object.object_id}", workflow_object.status, workflow_object.updated_at
    )
    console.print(table)


@workflow_app.command("transition")
def workflow_transition_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Workflow object type.")],
    object_id: Annotated[str, typer.Option("--object-id", help="Workflow object identifier.")],
    to_status: Annotated[str, typer.Option("--to-status", help="Target workflow status.")],
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
    reason: Annotated[str, typer.Option("--reason", help="Transition reason when required.")] = "",
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Perform a local workflow transition."""

    try:
        service, connection = _workflow_service(db_path)
        try:
            workflow_object = service.perform_transition(
                object_type=object_type,
                object_id=object_id,
                to_status=to_status,
                actor_label=actor,
                reason=reason,
            )
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]Workflow transitioned:[/green] {workflow_object.object_type}:{workflow_object.object_id} | {workflow_object.status}"
    )


@workflow_app.command("history")
def workflow_history_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Workflow object type.")],
    object_id: Annotated[str, typer.Option("--object-id", help="Workflow object identifier.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local workflow transition history."""

    try:
        service, connection = _workflow_service(db_path)
        try:
            events = service.list_history(object_type=object_type, object_id=object_id)
        finally:
            connection.close()
    except (DatabaseError, AuthRepositoryError, WorkflowRepositoryError, WorkflowServiceError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if not events:
        console.print("[yellow]No workflow transition history found.[/yellow]")
        return
    table = Table(title=f"Workflow History: {object_type}:{object_id}")
    table.add_column("From")
    table.add_column("To")
    table.add_column("Actor")
    table.add_column("Reason")
    table.add_column("Created")
    for event in events:
        table.add_row(event.from_status, event.to_status, event.actor_label, event.reason, event.created_at)
    console.print(table)


@accounts_app.command("import-trial-balance")
def accounts_import_trial_balance_command(
    input_path: Annotated[Path, typer.Option("--input", help="Local CSV/JSON trial balance export.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace key.")] = "default",
    period: Annotated[str, typer.Option("--period", help="Default period when missing in input.")] = "current",
    entity: Annotated[str, typer.Option("--entity", help="Default entity when missing in input.")] = "local",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Import a local trial balance and create draft reconciliation records."""

    try:
        connection = _db_connection(db_path)
        try:
            result = AccountReconciliationService(connection).import_trial_balance(
                input_path,
                workspace=workspace,
                default_period=period,
                default_entity=entity,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError, WorkflowServiceError) as exc:
        _safe_cli_error(exc)
    console.print(
        f"[green]Trial balance imported:[/green] {result.imported_rows} rows | records: {result.reconciliation_records}"
    )


@accounts_app.command("create-template")
def accounts_create_template_command(
    account_code: Annotated[str, typer.Option("--account-code", help="Account code.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace key.")] = "default",
    name: Annotated[str, typer.Option("--name", help="Template name.")] = "",
    risk_rating: Annotated[str, typer.Option("--risk", help="Risk rating.")] = "medium",
    materiality_threshold: Annotated[
        str,
        typer.Option("--materiality", help="Exact decimal materiality threshold."),
    ] = "0",
    required_evidence: Annotated[str, typer.Option("--required-evidence", help="Evidence expectation text.")] = "",
    owner: Annotated[str, typer.Option("--owner", help="Owner/preparer reference.")] = "",
    reviewer: Annotated[str, typer.Option("--reviewer", help="Reviewer reference.")] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Create or update a DB-backed account reconciliation template."""

    try:
        connection = _db_connection(db_path)
        try:
            template = AccountReconciliationService(connection).create_template(
                account_code=account_code,
                name=name,
                workspace=workspace,
                risk_rating=risk_rating,
                materiality_threshold=materiality_threshold,
                required_evidence=required_evidence,
                owner=owner,
                reviewer=reviewer,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Account Template", [template])


@accounts_app.command("prepare")
def accounts_prepare_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    reconciliation_id: Annotated[str | None, typer.Option("--id", help="Reconciliation record id.")] = None,
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace key.")] = "default",
    period: Annotated[str, typer.Option("--period", help="Period name.")] = "current",
    entity: Annotated[str, typer.Option("--entity", help="Entity code.")] = "local",
    account_code: Annotated[str, typer.Option("--account-code", help="Account code when --id is omitted.")] = "",
    preparer: Annotated[str, typer.Option("--preparer", help="Preparer reference.")] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Prepare an account reconciliation through the workflow engine."""

    try:
        connection = _db_connection(db_path)
        try:
            record = AccountReconciliationService(connection).prepare(
                reconciliation_id=reconciliation_id,
                workspace=workspace,
                period_name=period,
                entity_code=entity,
                account_code=account_code,
                preparer=preparer,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError, WorkflowServiceError) as exc:
        _safe_cli_error(exc)
    _print_records("Account Reconciliation", [record])


@accounts_app.command("submit")
def accounts_submit_command(
    reconciliation_id: Annotated[str, typer.Option("--id", help="Reconciliation record id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Submit a prepared account reconciliation for review."""

    try:
        connection = _db_connection(db_path)
        try:
            record = AccountReconciliationService(connection).submit(reconciliation_id, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError, WorkflowServiceError) as exc:
        _safe_cli_error(exc)
    _print_records("Account Reconciliation", [record])


@accounts_app.command("review")
def accounts_review_command(
    reconciliation_id: Annotated[str, typer.Option("--id", help="Reconciliation record id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    reviewer: Annotated[str, typer.Option("--reviewer", help="Reviewer reference.")] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Review a submitted account reconciliation."""

    try:
        connection = _db_connection(db_path)
        try:
            record = AccountReconciliationService(connection).review(
                reconciliation_id, reviewer=reviewer, actor_label=actor
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError, WorkflowServiceError) as exc:
        _safe_cli_error(exc)
    _print_records("Account Reconciliation", [record])


@accounts_app.command("complete")
def accounts_complete_command(
    reconciliation_id: Annotated[str, typer.Option("--id", help="Reconciliation record id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Complete a reviewed account reconciliation."""

    try:
        connection = _db_connection(db_path)
        try:
            record = AccountReconciliationService(connection).complete(reconciliation_id, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError, WorkflowServiceError) as exc:
        _safe_cli_error(exc)
    _print_records("Account Reconciliation", [record])


@accounts_app.command("roll-forward")
def accounts_roll_forward_command(
    from_period: Annotated[str, typer.Option("--from-period", help="Source period.")],
    to_period: Annotated[str, typer.Option("--to-period", help="Target period.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace key.")] = "default",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Roll forward account reconciliation records to a new period."""

    try:
        connection = _db_connection(db_path)
        try:
            count = AccountReconciliationService(connection).roll_forward(
                from_period=from_period,
                to_period=to_period,
                workspace=workspace,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    console.print(f"[green]Rolled forward account reconciliations:[/green] {count}")


@accounts_app.command("report")
def accounts_report_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    status: Annotated[str, typer.Option("--status", help="Optional status filter.")] = "",
    owner: Annotated[str, typer.Option("--owner", help="Optional owner filter.")] = "",
    period: Annotated[str, typer.Option("--period", help="Optional period filter.")] = "",
    entity: Annotated[str, typer.Option("--entity", help="Optional entity filter.")] = "",
    risk: Annotated[str, typer.Option("--risk", help="Optional risk filter.")] = "",
) -> None:
    """List DB-backed account reconciliation records."""

    try:
        connection = _db_connection(db_path)
        try:
            records = AccountReconciliationService(connection).list_reconciliations(
                status=status,
                owner=owner,
                period_name=period,
                entity_code=entity,
                risk_rating=risk,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Account Reconciliations", records, max_rows=100)


@close_app.command("period-init")
def close_period_init_command(
    period: Annotated[str, typer.Option("--period", help="Close period name.")],
    start_date: Annotated[str, typer.Option("--start-date", help="Period start date.")],
    end_date: Annotated[str, typer.Option("--end-date", help="Period end date.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace key.")] = "default",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Initialize a DB-backed close period with default tasks."""

    try:
        connection = _db_connection(db_path)
        try:
            close_period = CloseManagementService(connection).period_init(
                period_name=period,
                start_date=start_date,
                end_date=end_date,
                workspace=workspace,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Close Period", [close_period])


@close_app.command("task-add")
def close_task_add_command(
    period_id: Annotated[str, typer.Option("--period-id", help="Close period id.")],
    task_code: Annotated[str, typer.Option("--task-code", help="Close task code.")],
    name: Annotated[str, typer.Option("--name", help="Task name.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    owner: Annotated[str, typer.Option("--owner", help="Task owner.")] = "",
    category: Annotated[str, typer.Option("--category", help="Task category.")] = "",
    risk: Annotated[str, typer.Option("--risk", help="Risk rating.")] = "medium",
    due_date: Annotated[str, typer.Option("--due-date", help="Due date text.")] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Add or update a DB-backed close task."""

    try:
        connection = _db_connection(db_path)
        try:
            task = CloseManagementService(connection).task_add(
                period_id=period_id,
                task_code=task_code,
                name=name,
                owner=owner,
                category=category,
                risk_rating=risk,
                due_date=due_date,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Close Task", [task])


@close_app.command("task-dependency")
def close_task_dependency_command(
    task_id: Annotated[str, typer.Option("--task-id", help="Task id.")],
    depends_on_task_id: Annotated[str, typer.Option("--depends-on", help="Dependency task id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Add a DB-backed close task dependency."""

    try:
        connection = _db_connection(db_path)
        try:
            dependency = CloseManagementService(connection).task_dependency(
                task_id=task_id,
                depends_on_task_id=depends_on_task_id,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Close Task Dependency", [dependency])


@close_app.command("task-status")
def close_task_status_command(
    task_id: Annotated[str, typer.Option("--task-id", help="Task id.")],
    status: Annotated[str, typer.Option("--status", help="Close task status.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    blocker_reason: Annotated[str, typer.Option("--blocker-reason", help="Required detail for blocked tasks.")] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Update a DB-backed close task status."""

    try:
        connection = _db_connection(db_path)
        try:
            task = CloseManagementService(connection).task_status(
                task_id=task_id,
                status=status,
                blocker_reason=blocker_reason,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Close Task", [task])


@close_app.command("readiness")
def close_readiness_command(
    period_id: Annotated[str, typer.Option("--period-id", help="Close period id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Compute DB-backed close readiness."""

    try:
        connection = _db_connection(db_path)
        try:
            readiness = CloseManagementService(connection).readiness(period_id=period_id, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Close Readiness", [readiness.__dict__])


@close_app.command("lock-period")
def close_lock_period_command(
    period_id: Annotated[str, typer.Option("--period-id", help="Close period id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Lock a DB-backed close period."""

    try:
        connection = _db_connection(db_path)
        try:
            period = CloseManagementService(connection).lock_period(period_id, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Close Period", [period])


@close_app.command("reopen-period")
def close_reopen_period_command(
    period_id: Annotated[str, typer.Option("--period-id", help="Close period id.")],
    reason: Annotated[str, typer.Option("--reason", help="Audited reopen reason.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Reopen a DB-backed close period with an audited reason."""

    try:
        connection = _db_connection(db_path)
        try:
            period = CloseManagementService(connection).reopen_period(period_id, reason=reason, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Close Period", [period])


@close_app.command("db-report")
def close_db_report_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    period_id: Annotated[str, typer.Option("--period-id", help="Optional close period id.")] = "",
    status: Annotated[str, typer.Option("--status", help="Optional task status.")] = "",
    owner: Annotated[str, typer.Option("--owner", help="Optional owner.")] = "",
) -> None:
    """List DB-backed close periods and tasks."""

    try:
        connection = _db_connection(db_path)
        try:
            service = CloseManagementService(connection)
            periods = service.list_periods()
            tasks = service.list_tasks(period_id=period_id, status=status, owner=owner)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Close Periods", periods, max_rows=50)
    _print_records("Close Tasks", tasks, max_rows=100)


@consolidation_app.command("runs")
def consolidation_runs_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    workspace: Annotated[str, typer.Option("--workspace", help="Workspace scope.")] = "default",
    status: Annotated[str, typer.Option("--status", help="Optional lifecycle status filter.")] = "",
    limit: Annotated[int, typer.Option("--limit", min=1, max=500, help="Maximum rows to return.")] = 100,
    offset: Annotated[int, typer.Option("--offset", min=0, help="Rows to skip.")] = 0,
    actor: Annotated[str, typer.Option("--actor", help="Actor label for audit attribution.")] = "local-cli",
) -> None:
    """List replay-verified consolidation close runs in one workspace."""

    try:
        connection = _db_connection(db_path)
        try:
            service = ConsolidationCloseApplicationService(SQLiteConsolidationCloseRepository(connection))
            runs = service.list_runs(
                workspace=workspace,
                status=status,
                limit=limit,
                offset=offset,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    if not runs:
        console.print("[yellow]No consolidation close runs found.[/yellow]")
    else:
        for run in runs:
            _print_record_detail("Consolidation Close Run", run)


@consolidation_app.command("run")
def consolidation_run_command(
    run_id: Annotated[str, typer.Option("--run-id", help="Consolidation close run id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    actor: Annotated[str, typer.Option("--actor", help="Actor label for audit attribution.")] = "local-cli",
) -> None:
    """Show one run with replay-verified evidence and management statement sections."""

    try:
        connection = _db_connection(db_path)
        try:
            service = ConsolidationCloseApplicationService(SQLiteConsolidationCloseRepository(connection))
            run = service.get_run(run_id, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Consolidation Close Run", run)


@consolidation_app.command("summary")
def consolidation_summary_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    workspace: Annotated[str, typer.Option("--workspace", help="Workspace scope.")] = "default",
    actor: Annotated[str, typer.Option("--actor", help="Actor label for audit attribution.")] = "local-cli",
) -> None:
    """Show bounded close lifecycle counts for one workspace."""

    try:
        connection = _db_connection(db_path)
        try:
            service = ConsolidationCloseApplicationService(SQLiteConsolidationCloseRepository(connection))
            summary = service.summary(workspace=workspace, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_record_detail("Consolidation Close Summary", summary.to_dict())


@consolidation_app.command("acquisition-bridge")
def consolidation_acquisition_bridge_command(
    input_path: Annotated[Path, typer.Option("--input", help="JSON acquisition bridge request.")],
    output_path: Annotated[Path | None, typer.Option("--output", help="Optional exact JSON output path.")] = None,
) -> None:
    """Prepare a deterministic, non-posting acquisition fair-value bridge."""

    try:
        document = read_json_record_document(input_path, envelope_keys=("request",), allow_single_object=True)
        if len(document.records) != 1:
            raise PlatformError("Acquisition bridge input must contain exactly one JSON request object.")
        raw = document.records[0]
        expected = {
            "acquisition_id",
            "subsidiary_entity_code",
            "period_id",
            "acquisition_date",
            "reporting_currency",
            "consideration",
            "nci_fair_value",
            "identifiable_net_assets_fair_value",
            "allow_bargain_purchase",
            "consideration_account_code",
            "nci_account_code",
            "identifiable_net_assets_account_code",
            "goodwill_account_code",
            "bargain_purchase_account_code",
            "policy_id",
            "policy_version",
            "source_reference",
            "source_digest",
            "prepared_by",
            "prepared_at",
            "approved_by",
            "approved_at",
        }
        if set(raw) != expected:
            raise PlatformError("Acquisition bridge input fields are not exactly the declared contract.")

        def parse_money(field: str) -> Money:
            value = raw[field]
            if not isinstance(value, dict) or not isinstance(value.get("amount"), str) or not isinstance(value.get("currency"), str):
                raise PlatformError(f"Acquisition bridge {field} must be a canonical money object.")
            return Money.from_exact(value["amount"], value["currency"], strict_precision=True)

        values = dict(raw)
        for field in ("consideration", "nci_fair_value", "identifiable_net_assets_fair_value"):
            values[field] = parse_money(field)
        result = prepare_acquisition_fair_value_bridge(AcquisitionFairValueBridgeRequest(**values))
        rendered = json.dumps(result.to_dict(), sort_keys=True, indent=2)
        if output_path is None:
            console.print(rendered)
        else:
            target = ensure_output_dir(output_path.parent) / output_path.name
            target.write_text(rendered + "\n", encoding="utf-8", newline="\n")
            console.print(f"[green]Acquisition bridge written:[/green] {target}")
    except (ConsolidationError, OSError, TypeError, ValueError) as exc:
        _safe_cli_error(PlatformError(f"Acquisition bridge input is invalid: {exc}"))


@consolidation_app.command("acquisition-ppa")
def consolidation_acquisition_ppa_command(
    input_path: Annotated[Path, typer.Option("--input", help="JSON acquisition PPA request.")],
    output_path: Annotated[Path | None, typer.Option("--output", help="Optional exact JSON output path.")] = None,
) -> None:
    """Prepare a deterministic, non-posting acquisition purchase-price allocation."""

    try:
        document = read_json_record_document(input_path, envelope_keys=("request",), allow_single_object=True)
        if len(document.records) != 1:
            raise PlatformError("Acquisition PPA input must contain exactly one JSON request object.")
        raw = document.records[0]
        expected = {
            "acquisition_id",
            "subsidiary_entity_code",
            "period_id",
            "acquisition_date",
            "reporting_currency",
            "consideration",
            "nci_fair_value",
            "items",
            "allow_bargain_purchase",
            "consideration_account_code",
            "nci_account_code",
            "identifiable_net_assets_account_code",
            "goodwill_account_code",
            "bargain_purchase_account_code",
            "policy_id",
            "policy_version",
            "source_reference",
            "source_digest",
            "prepared_by",
            "prepared_at",
            "approved_by",
            "approved_at",
        }
        if set(raw) != expected:
            raise PlatformError("Acquisition PPA input fields are not exactly the declared contract.")

        def parse_money(value: object, field: str) -> Money:
            if not isinstance(value, dict) or not isinstance(value.get("amount"), str) or not isinstance(value.get("currency"), str):
                raise PlatformError(f"Acquisition PPA {field} must be a canonical money object.")
            return Money.from_exact(value["amount"], value["currency"], strict_precision=True)

        raw_items = raw["items"]
        if not isinstance(raw_items, list):
            raise PlatformError("Acquisition PPA items must be a JSON array.")
        item_fields = {
            "item_id",
            "item_kind",
            "class_code",
            "account_code",
            "book_value",
            "fair_value",
            "valuation_reference",
            "source_reference",
        }
        items: list[AcquisitionPpaItem] = []
        for index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, dict) or set(raw_item) != item_fields:
                raise PlatformError(f"Acquisition PPA item {index} fields are not exactly the declared contract.")
            item_values = dict(raw_item)
            item_values["book_value"] = parse_money(raw_item["book_value"], f"item {index} book_value")
            item_values["fair_value"] = parse_money(raw_item["fair_value"], f"item {index} fair_value")
            items.append(AcquisitionPpaItem(**item_values))

        values = dict(raw)
        values["consideration"] = parse_money(raw["consideration"], "consideration")
        values["nci_fair_value"] = parse_money(raw["nci_fair_value"], "nci_fair_value")
        values["items"] = tuple(items)
        result = prepare_acquisition_purchase_price_allocation(AcquisitionPurchasePriceAllocationRequest(**values))
        rendered = json.dumps(result.to_dict(), sort_keys=True, indent=2)
        if output_path is None:
            console.print(rendered)
        else:
            target = ensure_output_dir(output_path.parent) / output_path.name
            target.write_text(rendered + "\n", encoding="utf-8", newline="\n")
            console.print(f"[green]Acquisition PPA written:[/green] {target}")
    except (ConsolidationError, OSError, TypeError, ValueError) as exc:
        _safe_cli_error(PlatformError(f"Acquisition PPA input is invalid: {exc}"))


@consolidation_app.command("acquisition-deferred-tax")
def consolidation_acquisition_deferred_tax_command(
    input_path: Annotated[Path, typer.Option("--input", help="JSON acquisition deferred-tax request.")],
    output_path: Annotated[Path | None, typer.Option("--output", help="Optional exact JSON output path.")] = None,
) -> None:
    """Prepare a deterministic, non-posting acquisition deferred-tax bridge."""

    try:
        document = read_json_record_document(input_path, envelope_keys=("request",), allow_single_object=True)
        if len(document.records) != 1:
            raise PlatformError("Acquisition deferred-tax input must contain exactly one JSON request object.")
        raw = document.records[0]
        expected = {
            "acquisition_id",
            "subsidiary_entity_code",
            "period_id",
            "acquisition_date",
            "reporting_currency",
            "items",
            "deferred_tax_asset_account_code",
            "deferred_tax_liability_account_code",
            "policy_id",
            "policy_version",
            "source_reference",
            "source_digest",
            "prepared_by",
            "prepared_at",
            "approved_by",
            "approved_at",
        }
        if set(raw) != expected:
            raise PlatformError("Acquisition deferred-tax input fields are not exactly the declared contract.")

        def parse_money(value: object, field: str) -> Money:
            if not isinstance(value, dict) or not isinstance(value.get("amount"), str) or not isinstance(value.get("currency"), str):
                raise PlatformError(f"Acquisition deferred-tax {field} must be a canonical money object.")
            return Money.from_exact(value["amount"], value["currency"], strict_precision=True)

        raw_items = raw["items"]
        if not isinstance(raw_items, list):
            raise PlatformError("Acquisition deferred-tax items must be a JSON array.")
        item_fields = {
            "item_id",
            "item_kind",
            "account_code",
            "fair_value",
            "tax_basis",
            "tax_rate",
            "source_reference",
            "tax_basis_reference",
        }
        items: list[AcquisitionDeferredTaxItem] = []
        for index, raw_item in enumerate(raw_items):
            if not isinstance(raw_item, dict) or set(raw_item) != item_fields:
                raise PlatformError(f"Acquisition deferred-tax item {index} fields are not exactly the declared contract.")
            item_values = dict(raw_item)
            item_values["fair_value"] = parse_money(raw_item["fair_value"], f"item {index} fair_value")
            item_values["tax_basis"] = parse_money(raw_item["tax_basis"], f"item {index} tax_basis")
            try:
                item_values["tax_rate"] = parse_exact_amount(raw_item["tax_rate"])
            except (TypeError, ValueError) as exc:
                raise PlatformError(f"Acquisition deferred-tax item {index} tax_rate must be exact decimal text.") from exc
            items.append(AcquisitionDeferredTaxItem(**item_values))

        values = dict(raw)
        values["items"] = tuple(items)
        result = prepare_acquisition_deferred_tax_bridge(AcquisitionDeferredTaxBridgeRequest(**values))
        rendered = json.dumps(result.to_dict(), sort_keys=True, indent=2)
        if output_path is None:
            console.print(rendered)
        else:
            target = ensure_output_dir(output_path.parent) / output_path.name
            target.write_text(rendered + "\n", encoding="utf-8", newline="\n")
            console.print(f"[green]Acquisition deferred-tax bridge written:[/green] {target}")
    except (ConsolidationError, OSError, TypeError, ValueError) as exc:
        _safe_cli_error(PlatformError(f"Acquisition deferred-tax input is invalid: {exc}"))


@consolidation_app.command("impairment-bridge")
def consolidation_impairment_bridge_command(
    input_path: Annotated[Path, typer.Option("--input", help="JSON consolidation impairment request.")],
    output_path: Annotated[Path | None, typer.Option("--output", help="Optional exact JSON output path.")] = None,
) -> None:
    """Prepare a deterministic, non-posting consolidation impairment bridge."""

    try:
        document = read_json_record_document(input_path, envelope_keys=("request",), allow_single_object=True)
        if len(document.records) != 1:
            raise PlatformError("Consolidation impairment input must contain exactly one JSON request object.")
        raw = document.records[0]
        expected = {
            "impairment_test_id",
            "entity_code",
            "period_id",
            "reporting_currency",
            "units",
            "policy_id",
            "policy_version",
            "source_reference",
            "source_digest",
            "prepared_by",
            "prepared_at",
            "approved_by",
            "approved_at",
        }
        if set(raw) != expected:
            raise PlatformError("Consolidation impairment input fields are not exactly the declared contract.")

        def parse_money(value: object, field: str) -> Money:
            if not isinstance(value, dict) or not isinstance(value.get("amount"), str) or not isinstance(value.get("currency"), str):
                raise PlatformError(f"Consolidation impairment {field} must be a canonical money object.")
            return Money.from_exact(value["amount"], value["currency"], strict_precision=True)

        raw_units = raw["units"]
        if not isinstance(raw_units, list):
            raise PlatformError("Consolidation impairment units must be a JSON array.")
        unit_fields = {
            "unit_id",
            "unit_kind",
            "account_code",
            "carrying_amount",
            "recoverable_amount",
            "source_reference",
            "source_digest",
        }
        units: list[ConsolidationImpairmentUnit] = []
        for index, raw_unit in enumerate(raw_units):
            if not isinstance(raw_unit, dict) or set(raw_unit) != unit_fields:
                raise PlatformError(f"Consolidation impairment unit {index} fields are not exactly the declared contract.")
            values = dict(raw_unit)
            values["carrying_amount"] = parse_money(raw_unit["carrying_amount"], f"unit {index} carrying_amount")
            values["recoverable_amount"] = parse_money(raw_unit["recoverable_amount"], f"unit {index} recoverable_amount")
            units.append(ConsolidationImpairmentUnit(**values))

        values = dict(raw)
        values["units"] = tuple(units)
        result = prepare_consolidation_impairment_bridge(ConsolidationImpairmentBridgeRequest(**values))
        rendered = json.dumps(result.to_dict(), sort_keys=True, indent=2)
        if output_path is None:
            console.print(rendered)
        else:
            target = ensure_output_dir(output_path.parent) / output_path.name
            target.write_text(rendered + "\n", encoding="utf-8", newline="\n")
            console.print(f"[green]Consolidation impairment bridge written:[/green] {target}")
    except (ConsolidationError, OSError, TypeError, ValueError) as exc:
        _safe_cli_error(PlatformError(f"Consolidation impairment input is invalid: {exc}"))


@consolidation_app.command("ownership-change")
def consolidation_ownership_change_command(
    input_path: Annotated[Path, typer.Option("--input", help="JSON ownership-change adjustment request.")],
    output_path: Annotated[Path | None, typer.Option("--output", help="Optional exact JSON output path.")] = None,
) -> None:
    """Prepare a deterministic, balanced, non-posting ownership-change proposal."""

    try:
        document = read_json_record_document(input_path, envelope_keys=("request",), allow_single_object=True)
        if len(document.records) != 1:
            raise PlatformError("Ownership-change input must contain exactly one JSON request object.")
        raw = document.records[0]
        expected = {
            "change_id",
            "subsidiary_entity_code",
            "period_id",
            "effective_date",
            "reporting_currency",
            "prior_group_ownership_percentage",
            "new_group_ownership_percentage",
            "net_assets",
            "consideration_effect",
            "nci_account_code",
            "consideration_account_code",
            "parent_equity_account_code",
            "policy_id",
            "policy_version",
            "source_reference",
            "source_digest",
            "prepared_by",
            "prepared_at",
            "approved_by",
            "approved_at",
        }
        if set(raw) != expected:
            raise PlatformError("Ownership-change input fields are not exactly the declared contract.")

        def parse_money(value: object, field: str) -> Money:
            if (
                not isinstance(value, dict)
                or not isinstance(value.get("amount"), str)
                or not isinstance(value.get("currency"), str)
            ):
                raise PlatformError(f"Ownership-change {field} must be a canonical money object.")
            return Money.from_exact(value["amount"], value["currency"], strict_precision=True)

        values = dict(raw)
        for field in ("prior_group_ownership_percentage", "new_group_ownership_percentage"):
            try:
                values[field] = parse_exact_amount(raw[field])
            except (TypeError, ValueError) as exc:
                raise PlatformError(f"Ownership-change {field} must be exact decimal text.") from exc
        values["net_assets"] = parse_money(raw["net_assets"], "net_assets")
        values["consideration_effect"] = parse_money(raw["consideration_effect"], "consideration_effect")
        result = prepare_ownership_change_adjustment(OwnershipChangeAdjustmentRequest(**values))
        rendered = json.dumps(result.to_dict(), sort_keys=True, indent=2)
        if output_path is None:
            console.print(rendered)
        else:
            target = ensure_output_dir(output_path.parent) / output_path.name
            target.write_text(rendered + "\n", encoding="utf-8", newline="\n")
            console.print(f"[green]Ownership-change proposal written:[/green] {target}")
    except (ConsolidationError, OSError, TypeError, ValueError) as exc:
        _safe_cli_error(PlatformError(f"Ownership-change input is invalid: {exc}"))


@consolidation_app.command("intercompany-eliminations")
def consolidation_intercompany_eliminations_command(
    input_path: Annotated[Path, typer.Option("--input", help="JSON intercompany elimination request.")],
    output_path: Annotated[Path | None, typer.Option("--output", help="Optional exact JSON output path.")] = None,
) -> None:
    """Prepare exact, non-posting intercompany elimination proposals."""

    try:
        document = read_json_record_document(input_path, envelope_keys=("request",), allow_single_object=True)
        if len(document.records) != 1:
            raise PlatformError("Intercompany elimination input must contain exactly one JSON request object.")
        raw = document.records[0]
        expected = {"schema_version", "reporting_currency", "version", "prepared_by", "prepared_at", "lines"}
        if set(raw) != expected or raw["schema_version"] != 1:
            raise PlatformError("Intercompany elimination input fields are not exactly the declared contract.")
        raw_lines = raw["lines"]
        if not isinstance(raw_lines, list):
            raise PlatformError("Intercompany elimination lines must be a JSON array.")
        line_fields = {
            "transaction_id",
            "period_name",
            "entity_code",
            "counterparty_code",
            "reference",
            "group_account_code",
            "account_type",
            "amount",
            "source_reference",
            "source_digest",
        }
        lines: list[IntercompanyEliminationInputLine] = []
        for index, raw_line in enumerate(raw_lines):
            if not isinstance(raw_line, dict) or set(raw_line) != line_fields:
                raise PlatformError(f"Intercompany elimination line {index} fields are not exact.")
            amount = raw_line["amount"]
            if not isinstance(amount, dict):
                raise PlatformError(f"Intercompany elimination line {index} amount must be canonical Money.")
            values = dict(raw_line)
            values["amount"] = Money.from_canonical_dict(cast(dict[str, object], amount))
            lines.append(IntercompanyEliminationInputLine(**values))
        result = IntercompanyEliminationApplicationService.prepare(
            tuple(lines),
            reporting_currency=cast(str, raw["reporting_currency"]),
            prepared_by=cast(str, raw["prepared_by"]),
            prepared_at=cast(str, raw["prepared_at"]),
            version=cast(str, raw["version"]),
        )
        rendered = json.dumps(result.to_dict(), sort_keys=True, indent=2)
        if output_path is None:
            console.print(rendered)
        else:
            target = ensure_output_dir(output_path.parent) / output_path.name
            target.write_text(rendered + "\n", encoding="utf-8", newline="\n")
            console.print(f"[green]Intercompany eliminations written:[/green] {target}")
    except (ConsolidationError, OSError, TypeError, ValueError) as exc:
        _safe_cli_error(PlatformError(f"Intercompany elimination input is invalid: {exc}"))


@approvals_app.command("submit")
def approvals_submit_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Target object type.")],
    object_id: Annotated[str, typer.Option("--object-id", help="Target object id.")],
    title: Annotated[str, typer.Option("--title", help="Approval title.")],
    assigned_to: Annotated[str, typer.Option("--assigned-to", help="Assigned approver reference.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    reason: Annotated[str, typer.Option("--reason", help="Approval request reason.")] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Submit a local approval request."""

    try:
        connection = _db_connection(db_path)
        try:
            request = ApprovalService(connection).submit(
                object_type=object_type,
                object_id=object_id,
                title=title,
                assigned_to=assigned_to,
                reason=reason,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Approval Request", [request])


@approvals_app.command("approve")
def approvals_approve_command(
    approval_id: Annotated[str, typer.Option("--id", help="Approval request id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    reason: Annotated[str, typer.Option("--reason", help="Decision reason.")] = "",
    override_reason: Annotated[
        str,
        typer.Option("--override-reason", help="Deprecated; SoD overrides are rejected."),
    ] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Approve local workflow metadata."""

    try:
        connection = _db_connection(db_path)
        try:
            request = ApprovalService(connection).approve(
                approval_id,
                reason=reason,
                override_reason=override_reason,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Approval Request", [request])


@approvals_app.command("reject")
def approvals_reject_command(
    approval_id: Annotated[str, typer.Option("--id", help="Approval request id.")],
    reason: Annotated[str, typer.Option("--reason", help="Required rejection reason.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Reject local workflow metadata with a reason."""

    try:
        connection = _db_connection(db_path)
        try:
            request = ApprovalService(connection).reject(approval_id, reason=reason, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Approval Request", [request])


@approvals_app.command("report")
def approvals_report_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    status: Annotated[str, typer.Option("--status", help="Optional approval status.")] = "",
) -> None:
    """List approval requests and certification metadata."""

    try:
        connection = _db_connection(db_path)
        try:
            service = ApprovalService(connection)
            requests = service.list_requests(status=status)
            certifications = service.list_certifications()
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Approval Requests", requests, max_rows=100)
    _print_records("Certification Metadata", certifications, max_rows=100)


@approvals_app.command("certifications-prepare")
def certifications_prepare_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Target object type.")],
    object_id: Annotated[str, typer.Option("--object-id", help="Target object id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    period: Annotated[str, typer.Option("--period", help="Optional period name.")] = "",
    entity: Annotated[str, typer.Option("--entity", help="Optional entity code.")] = "",
    note: Annotated[str, typer.Option("--note", help="Workflow note.")] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Prepare certification metadata only; this is not a legal signature."""

    try:
        connection = _db_connection(db_path)
        try:
            record = ApprovalService(connection).prepare_certification(
                object_type=object_type,
                object_id=object_id,
                period_name=period,
                entity_code=entity,
                note=note,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Certification Metadata", [record])


@approvals_app.command("certifications-review")
def certifications_review_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Target object type.")],
    object_id: Annotated[str, typer.Option("--object-id", help="Target object id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    note: Annotated[str, typer.Option("--note", help="Workflow note.")] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Review certification metadata only; this is not compliance certification."""

    try:
        connection = _db_connection(db_path)
        try:
            record = ApprovalService(connection).review_certification(
                object_type=object_type,
                object_id=object_id,
                note=note,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Certification Metadata", [record])


@certifications_app.command("prepare")
def certifications_prepare_alias_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Target object type.")],
    object_id: Annotated[str, typer.Option("--object-id", help="Target object id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    period: Annotated[str, typer.Option("--period", help="Optional period name.")] = "",
    entity: Annotated[str, typer.Option("--entity", help="Optional entity code.")] = "",
    note: Annotated[str, typer.Option("--note", help="Workflow note.")] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Prepare certification metadata only; this is not a legal signature."""

    certifications_prepare_command(
        object_type=object_type,
        object_id=object_id,
        db_path=db_path,
        period=period,
        entity=entity,
        note=note,
        actor=actor,
    )


@certifications_app.command("review")
def certifications_review_alias_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Target object type.")],
    object_id: Annotated[str, typer.Option("--object-id", help="Target object id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    note: Annotated[str, typer.Option("--note", help="Workflow note.")] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Review certification metadata only; this is not compliance certification."""

    certifications_review_command(
        object_type=object_type,
        object_id=object_id,
        db_path=db_path,
        note=note,
        actor=actor,
    )


@certifications_app.command("report")
def certifications_report_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List certification workflow metadata."""

    try:
        connection = _db_connection(db_path)
        try:
            records = ApprovalService(connection).list_certifications()
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Certification Metadata", records, max_rows=100)


@evidence_app.command("register")
def evidence_register_command(
    source_path: Annotated[Path, typer.Option("--file", help="Local evidence file.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    evidence_code: Annotated[str, typer.Option("--evidence-code", help="Evidence code.")] = "",
    object_type: Annotated[str, typer.Option("--object-type", help="Optional linked object type.")] = "",
    object_id: Annotated[str, typer.Option("--object-id", help="Optional linked object id.")] = "",
    redaction_status: Annotated[str, typer.Option("--redaction-status", help="Redaction status.")] = "unknown",
    storage_backend: Annotated[str, typer.Option("--storage-backend", help="Storage backend: local or s3.")] = "local",
    storage_tenant_id: Annotated[
        str, typer.Option("--storage-tenant-id", help="Tenant scope for object storage.")
    ] = "",
    s3_bucket: Annotated[
        str, typer.Option("--s3-bucket", envvar="RECONFORGE_S3_BUCKET", help="S3-compatible bucket.")
    ] = "",
    s3_endpoint_url: Annotated[
        str,
        typer.Option(
            "--s3-endpoint-url", envvar="RECONFORGE_S3_ENDPOINT_URL", help="Optional S3-compatible endpoint URL."
        ),
    ] = "",
    s3_region: Annotated[
        str, typer.Option("--s3-region", envvar="RECONFORGE_S3_REGION", help="S3 region.")
    ] = "us-east-1",
    s3_key_prefix: Annotated[
        str,
        typer.Option("--s3-key-prefix", envvar="RECONFORGE_S3_KEY_PREFIX", help="Tenant-separated object key prefix."),
    ] = "reconforge",
    s3_no_tls: Annotated[
        bool, typer.Option("--s3-no-tls", help="Allow an http:// S3 endpoint for local development only.")
    ] = False,
    retention_until: Annotated[
        str,
        typer.Option("--retention-until", help="Optional ISO-8601 retention timestamp; requires provider object lock."),
    ] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Register evidence with checksum/provenance metadata."""

    object_store = None
    storage_factory = None
    try:
        backend = storage_backend.strip().casefold()
        if backend not in {"local", "s3"}:
            raise PlatformError("Evidence storage backend must be local or s3.")
        parsed_retention: datetime | None = None
        if retention_until:
            try:
                parsed_retention = datetime.fromisoformat(retention_until.replace("Z", "+00:00"))
            except ValueError as exc:
                raise PlatformError("Retention timestamp must be valid ISO-8601 text.") from exc
            if parsed_retention.tzinfo is None:
                raise PlatformError("Retention timestamp must include a timezone offset.")
            parsed_retention = parsed_retention.astimezone(UTC)
        if backend == "s3":
            if not s3_bucket.strip():
                raise PlatformError("--s3-bucket or RECONFORGE_S3_BUCKET is required for s3 evidence storage.")
            storage_factory = ObjectStorageConnectionFactory(
                ObjectStorageSettings(
                    bucket=s3_bucket,
                    endpoint_url=s3_endpoint_url or None,
                    region=s3_region,
                    key_prefix=s3_key_prefix,
                    require_tls=not s3_no_tls,
                )
            )
            object_store = S3ObjectStore(storage_factory)
        connection = _db_connection(db_path)
        try:
            evidence = EvidenceRegistryService(connection).register(
                source_path,
                evidence_code=evidence_code,
                object_type=object_type,
                object_id=object_id,
                redaction_status=redaction_status,
                actor_label=actor,
                object_store=object_store,
                storage_tenant_id=storage_tenant_id,
                retention_until=parsed_retention,
            )
        finally:
            connection.close()
    except (DatabaseError, DBBridgeError, PlatformError, ValueError) as exc:
        _safe_cli_error(exc)
    finally:
        if storage_factory is not None:
            storage_factory.close()
    _print_records("Evidence", [evidence])


@evidence_app.command("verify")
def evidence_verify_command(
    evidence_id: Annotated[str, typer.Option("--id", help="Evidence id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    s3_bucket: Annotated[
        str,
        typer.Option(
            "--s3-bucket", envvar="RECONFORGE_S3_BUCKET", help="S3-compatible bucket for object-backed evidence."
        ),
    ] = "",
    s3_endpoint_url: Annotated[
        str,
        typer.Option(
            "--s3-endpoint-url", envvar="RECONFORGE_S3_ENDPOINT_URL", help="Optional S3-compatible endpoint URL."
        ),
    ] = "",
    s3_region: Annotated[
        str, typer.Option("--s3-region", envvar="RECONFORGE_S3_REGION", help="S3 region.")
    ] = "us-east-1",
    s3_key_prefix: Annotated[
        str,
        typer.Option("--s3-key-prefix", envvar="RECONFORGE_S3_KEY_PREFIX", help="Tenant-separated object key prefix."),
    ] = "reconforge",
    s3_no_tls: Annotated[
        bool, typer.Option("--s3-no-tls", help="Allow an http:// S3 endpoint for local development only.")
    ] = False,
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Verify local or configured object-backed evidence checksum."""

    storage_factory = None
    object_store = None
    try:
        connection = _db_connection(db_path)
        try:
            service = EvidenceRegistryService(connection)
            evidence = service.get(evidence_id)
            if str(evidence.get("storage_backend") or "") == OBJECT_STORAGE_BACKEND:
                if not s3_bucket.strip():
                    raise PlatformError(
                        "--s3-bucket or RECONFORGE_S3_BUCKET is required for object-backed evidence verification."
                    )
                storage_factory = ObjectStorageConnectionFactory(
                    ObjectStorageSettings(
                        bucket=s3_bucket,
                        endpoint_url=s3_endpoint_url or None,
                        region=s3_region,
                        key_prefix=s3_key_prefix,
                        require_tls=not s3_no_tls,
                    )
                )
                object_store = S3ObjectStore(storage_factory)
            result = service.verify(evidence_id, actor_label=actor, object_store=object_store)
        finally:
            connection.close()
    except (DatabaseError, PlatformError, ValueError) as exc:
        _safe_cli_error(exc)
    finally:
        if storage_factory is not None:
            storage_factory.close()
    _print_records("Evidence Verification", [result.__dict__])


@evidence_app.command("requirements")
def evidence_requirements_command(
    object_type: Annotated[str, typer.Option("--object-type", help="Object type.")],
    object_id: Annotated[str, typer.Option("--object-id", help="Object id.")],
    requirement_code: Annotated[str, typer.Option("--requirement-code", help="Requirement code.")],
    description: Annotated[str, typer.Option("--description", help="Requirement description.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Create or update an evidence requirement."""

    try:
        connection = _db_connection(db_path)
        try:
            requirement = EvidenceRegistryService(connection).requirement(
                object_type=object_type,
                object_id=object_id,
                requirement_code=requirement_code,
                description=description,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Evidence Requirement", [requirement])


@evidence_app.command("coverage")
def evidence_coverage_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace key.")] = "default",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Report local evidence coverage by DB object."""

    try:
        connection = _db_connection(db_path)
        try:
            coverage = EvidenceRegistryService(connection).coverage(workspace=workspace, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    console.print(f"[green]Evidence coverage:[/green] {coverage['coverage_pct']}%")
    _print_records("Evidence Coverage Objects", cast(list[dict[str, object]], coverage["objects"]), max_rows=100)


@evidence_app.command("report")
def evidence_report_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    status: Annotated[str, typer.Option("--status", help="Optional evidence status.")] = "",
) -> None:
    """List DB-backed evidence registry records."""

    try:
        connection = _db_connection(db_path)
        try:
            records = EvidenceRegistryService(connection).list_evidence(status=status)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Evidence Registry", records, max_rows=100)


@journals_app.command("import")
def journals_import_command(
    input_path: Annotated[Path, typer.Option("--input", help="Local CSV/JSON journal export.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace key.")] = "default",
    period: Annotated[str, typer.Option("--period", help="Default period when missing in input.")] = "current",
    entity: Annotated[str, typer.Option("--entity", help="Default entity when missing in input.")] = "local",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Import local journal entries for policy checks."""

    try:
        connection = _db_connection(db_path)
        try:
            result = JournalControlService(connection).import_journals(
                input_path,
                workspace=workspace,
                default_period=period,
                default_entity=entity,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, DBBridgeError, PlatformError) as exc:
        _safe_cli_error(exc)
    console.print(f"[green]Journals imported:[/green] {result.imported_rows} rows from {result.source_path.name}")


@journals_app.command("policy-run")
def journals_policy_run_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace key.")] = "default",
    period: Annotated[str, typer.Option("--period", help="Optional period filter.")] = "",
    period_end: Annotated[str, typer.Option("--period-end", help="Period end date for late postings.")] = "",
    high_value_threshold: Annotated[
        str,
        typer.Option("--high-value", help="Exact decimal high-value journal threshold."),
    ] = "100000",
    high_risk_accounts: Annotated[
        str, typer.Option("--high-risk-accounts", help="Comma-separated high-risk account codes.")
    ] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Run deterministic local journal policies."""

    try:
        connection = _db_connection(db_path)
        try:
            count = JournalControlService(connection).policy_run(
                workspace=workspace,
                period_name=period,
                period_end=period_end,
                high_value_threshold=high_value_threshold,
                high_risk_accounts=high_risk_accounts,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    console.print(f"[green]Journal policy exceptions:[/green] {count}")


@journals_app.command("exceptions")
def journals_exceptions_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    period: Annotated[str, typer.Option("--period", help="Optional period filter.")] = "",
) -> None:
    """List journal policy exceptions."""

    try:
        connection = _db_connection(db_path)
        try:
            records = JournalControlService(connection).exceptions(period_name=period)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Journal Exceptions", records, max_rows=100)


@journals_app.command("report")
def journals_report_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Report journal control counts."""

    try:
        connection = _db_connection(db_path)
        try:
            report = JournalControlService(connection).report()
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Journal Controls Report", [report])


@intercompany_app.command("import")
def intercompany_import_command(
    input_path: Annotated[Path, typer.Option("--input", help="Local CSV/JSON intercompany export.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace key.")] = "default",
    period: Annotated[str, typer.Option("--period", help="Default period when missing in input.")] = "current",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Import local intercompany transactions."""

    try:
        connection = _db_connection(db_path)
        try:
            result = IntercompanyService(connection).import_transactions(
                input_path,
                workspace=workspace,
                default_period=period,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, DBBridgeError, PlatformError) as exc:
        _safe_cli_error(exc)
    console.print(f"[green]Intercompany imported:[/green] {result.imported_rows} rows from {result.source_path.name}")


@intercompany_app.command("match")
def intercompany_match_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace key.")] = "default",
    period: Annotated[str, typer.Option("--period", help="Optional period filter.")] = "",
    tolerance: Annotated[
        str,
        typer.Option("--tolerance", help="Exact decimal imbalance tolerance."),
    ] = "0.01",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Match intercompany transactions into local cases."""

    try:
        connection = _db_connection(db_path)
        try:
            count = IntercompanyService(connection).match(
                workspace=workspace,
                period_name=period,
                tolerance=tolerance,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    console.print(f"[green]Intercompany cases created/updated:[/green] {count}")


@intercompany_app.command("cases")
def intercompany_cases_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    status: Annotated[str, typer.Option("--status", help="Optional case status.")] = "",
) -> None:
    """List intercompany cases."""

    try:
        connection = _db_connection(db_path)
        try:
            records = IntercompanyService(connection).cases(status=status)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Intercompany Cases", records, max_rows=100)


@intercompany_app.command("settle")
def intercompany_settle_command(
    case_id: Annotated[str, typer.Option("--case-id", help="Intercompany case id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    settlement_status: Annotated[
        str, typer.Option("--settlement-status", help="Settlement status metadata.")
    ] = "Settled",
    dispute_owner: Annotated[str, typer.Option("--dispute-owner", help="Dispute owner reference.")] = "",
    evidence_note: Annotated[str, typer.Option("--evidence-note", help="Evidence note/reference.")] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Settle/update local intercompany case metadata."""

    try:
        connection = _db_connection(db_path)
        try:
            record = IntercompanyService(connection).settle(
                case_id,
                settlement_status=settlement_status,
                dispute_owner=dispute_owner,
                evidence_note=evidence_note,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Intercompany Case", [record])


@intercompany_app.command("report")
def intercompany_report_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List intercompany case report."""

    try:
        connection = _db_connection(db_path)
        try:
            records = IntercompanyService(connection).cases()
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Intercompany Report", records, max_rows=100)


@controls_app.command("import-library")
def controls_import_library_command(
    input_path: Annotated[Path, typer.Option("--input", help="Local CSV/JSON control library.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace key.")] = "default",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Import a DB-backed control library."""

    try:
        connection = _db_connection(db_path)
        try:
            result = ControlTestingService(connection).import_library(
                input_path, workspace=workspace, actor_label=actor
            )
        finally:
            connection.close()
    except (DatabaseError, DBBridgeError, PlatformError) as exc:
        _safe_cli_error(exc)
    console.print(
        f"[green]Control library imported:[/green] {result.imported_rows} rows from {result.source_path.name}"
    )


@controls_app.command("plan-tests")
def controls_plan_tests_command(
    period: Annotated[str, typer.Option("--period", help="Test period.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace key.")] = "default",
    sample_size: Annotated[int, typer.Option("--sample-size", help="Planned sample size.")] = 0,
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Create DB-backed control test plans."""

    try:
        connection = _db_connection(db_path)
        try:
            count = ControlTestingService(connection).plan_tests(
                period_name=period,
                workspace=workspace,
                sample_size=sample_size,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    console.print(f"[green]Control test plans:[/green] {count}")


@controls_app.command("record-result")
def controls_record_result_command(
    plan_id: Annotated[str, typer.Option("--plan-id", help="Control test plan id.")],
    result_status: Annotated[str, typer.Option("--result", help="Result status.")],
    effectiveness_status: Annotated[str, typer.Option("--effectiveness", help="Effectiveness status.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    note: Annotated[str, typer.Option("--note", help="Result note.")] = "",
    evidence_id: Annotated[str, typer.Option("--evidence-id", help="Evidence id/reference.")] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Record a DB-backed control test result."""

    try:
        connection = _db_connection(db_path)
        try:
            result = ControlTestingService(connection).record_result(
                plan_id=plan_id,
                result_status=result_status,
                effectiveness_status=effectiveness_status,
                note=note,
                evidence_id=evidence_id,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Control Test Result", [result])


@controls_app.command("remediation")
def controls_remediation_command(
    source_type: Annotated[str, typer.Option("--source-type", help="Source type.")],
    source_id: Annotated[str, typer.Option("--source-id", help="Source id.")],
    action_plan: Annotated[str, typer.Option("--action-plan", help="Remediation plan text.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    owner: Annotated[str, typer.Option("--owner", help="Owner reference.")] = "",
    target_date: Annotated[str, typer.Option("--target-date", help="Target date text.")] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Create/update remediation metadata."""

    try:
        connection = _db_connection(db_path)
        try:
            record = ControlTestingService(connection).remediation(
                source_type=source_type,
                source_id=source_id,
                action_plan=action_plan,
                owner=owner,
                target_date=target_date,
                actor_label=actor,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Remediation Plan", [record])


@controls_app.command("report")
def controls_report_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    period: Annotated[str, typer.Option("--period", help="Optional period filter.")] = "",
) -> None:
    """Report DB-backed control testing status."""

    try:
        connection = _db_connection(db_path)
        try:
            service = ControlTestingService(connection)
            report = service.report()
            plans = service.list_plans(period_name=period)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Control Testing Summary", [report])
    _print_records("Control Test Plans", plans, max_rows=100)


@match_app.command("run")
def match_run_command(
    left_path: Annotated[Path, typer.Option("--left", help="Left local CSV/JSON file.")],
    right_path: Annotated[Path, typer.Option("--right", help="Right local CSV/JSON file.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    name: Annotated[str, typer.Option("--name", help="Match job name.")] = "local-match-job",
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace key.")] = "default",
    left_id_field: Annotated[str, typer.Option("--left-id-field", help="Left id field.")] = "id",
    right_id_field: Annotated[str, typer.Option("--right-id-field", help="Right id field.")] = "id",
    amount_field: Annotated[str, typer.Option("--amount-field", help="Amount field name on both sides.")] = "amount",
    date_field: Annotated[str, typer.Option("--date-field", help="Date field name on both sides.")] = "date",
    reference_field: Annotated[
        str, typer.Option("--reference-field", help="Reference field name on both sides.")
    ] = "reference",
    exact_fields: Annotated[str, typer.Option("--exact-fields", help="Comma-separated exact-key fields.")] = "",
    amount_tolerance: Annotated[str, typer.Option("--amount-tolerance", help="Allowed amount difference.")] = "0",
    date_window_days: Annotated[int, typer.Option("--date-window-days", help="Allowed date difference in days.")] = 0,
    allow_many_to_one: Annotated[
        bool, typer.Option("--allow-many-to-one", help="Allow right-side records to match more than once.")
    ] = False,
    allow_one_to_many: Annotated[
        bool,
        typer.Option("--allow-one-to-many", help="Allow left-side records to match more than once."),
    ] = False,
    allow_many_to_many: Annotated[
        bool,
        typer.Option("--allow-many-to-many", help="Allow both sides of records to match multiple times."),
    ] = False,
    idempotency_key: Annotated[
        str,
        typer.Option("--idempotency-key", help="Optional stable key that makes a write retry return the original job."),
    ] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Run deterministic DB-backed matching with indexed candidate generation."""

    try:
        connection = _db_connection(db_path)
        try:
            result = MatchingService(connection).run(
                left_path=left_path,
                right_path=right_path,
                workspace=workspace,
                name=name,
                left_id_field=left_id_field,
                right_id_field=right_id_field,
                amount_field=amount_field,
                date_field=date_field,
                reference_field=reference_field,
                exact_fields=exact_fields,
                amount_tolerance=amount_tolerance,
                date_window_days=date_window_days,
                allow_many_to_one=allow_many_to_one,
                allow_one_to_many=allow_one_to_many,
                allow_many_to_many=allow_many_to_many,
                idempotency_key=idempotency_key or None,
                actor_label=actor,
                financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
                record_identity_policy=RECORD_IDENTITY_POLICY,
            )
        finally:
            connection.close()
    except (DatabaseError, DBBridgeError, PlatformError) as exc:
        _safe_cli_error(exc)
    console.print(
        f"[green]Match job complete:[/green] {result.job_id} | matched {result.matched_count}/{result.result_count}"
    )


@match_app.command("job-status")
def match_job_status_command(
    job_id: Annotated[str, typer.Option("--job-id", help="Match job id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Show one match job status."""

    try:
        connection = _db_connection(db_path)
        try:
            job = MatchingService(connection).job_status(job_id)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Match Job", [job])


@match_app.command("results")
def match_results_command(
    job_id: Annotated[str, typer.Option("--job-id", help="Match job id.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    status: Annotated[str, typer.Option("--status", help="Optional result status.")] = "",
) -> None:
    """List match results."""

    try:
        connection = _db_connection(db_path)
        try:
            records = MatchingService(connection).results(job_id, status=status)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Match Results", records, max_rows=100)


@match_app.command("benchmark")
def match_benchmark_command(
    rows: Annotated[int, typer.Option("--rows", help="Synthetic benchmark rows.")] = 100000,
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace key.")] = "default",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Run a deterministic synthetic local matching benchmark."""

    try:
        connection = _db_connection(db_path)
        try:
            result = MatchingService(connection).benchmark(rows=rows, workspace=workspace, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    console.print(
        f"[green]Benchmark complete:[/green] {result.job_id} | matched {result.matched_count}/{result.result_count}"
    )


@exceptions_app.command("list")
def exceptions_list_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    period: Annotated[str, typer.Option("--period", help="Optional period filter.")] = "",
    entity: Annotated[str, typer.Option("--entity", help="Optional entity filter.")] = "",
    account: Annotated[str, typer.Option("--account", help="Optional account filter.")] = "",
    control: Annotated[str, typer.Option("--control", help="Optional control filter.")] = "",
    risk: Annotated[str, typer.Option("--risk", help="Optional risk filter.")] = "",
    owner: Annotated[str, typer.Option("--owner", help="Optional owner filter.")] = "",
    status: Annotated[str, typer.Option("--status", help="Optional status filter.")] = "",
) -> None:
    """List the unified DB-backed exception queue."""

    try:
        connection = _db_connection(db_path)
        try:
            records = ExceptionQueueService(connection).list(
                period_name=period,
                entity_code=entity,
                account_code=account,
                control_code=control,
                risk_rating=risk,
                owner=owner,
                status=status,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Unified Exceptions", records, max_rows=100)


@exceptions_app.command("assign")
def exceptions_assign_command(
    exception_id: Annotated[str, typer.Option("--id", help="Exception id.")],
    owner: Annotated[str, typer.Option("--owner", help="Owner reference.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Assign a unified exception."""

    try:
        connection = _db_connection(db_path)
        try:
            record = ExceptionQueueService(connection).assign(exception_id, owner=owner, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Unified Exception", [record])


@exceptions_app.command("set-status")
def exceptions_set_status_command(
    exception_id: Annotated[str, typer.Option("--id", help="Exception id.")],
    status: Annotated[str, typer.Option("--status", help="New status.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Set a unified exception status."""

    try:
        connection = _db_connection(db_path)
        try:
            record = ExceptionQueueService(connection).set_status(exception_id, status=status, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Unified Exception", [record])


@exceptions_app.command("bulk-update")
def exceptions_bulk_update_command(
    ids: Annotated[str, typer.Option("--ids", help="Comma-separated exception ids.")],
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    status: Annotated[str, typer.Option("--status", help="Optional new status.")] = "",
    owner: Annotated[str, typer.Option("--owner", help="Optional new owner.")] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Bulk-update selected unified exceptions."""

    exception_ids = [item.strip() for item in ids.split(",") if item.strip()]
    try:
        connection = _db_connection(db_path)
        try:
            count = ExceptionQueueService(connection).bulk_update(
                exception_ids, status=status, owner=owner, actor_label=actor
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    console.print(f"[green]Unified exceptions updated:[/green] {count}")


@exceptions_app.command("report")
def exceptions_report_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Report unified exception queue records."""

    try:
        connection = _db_connection(db_path)
        try:
            records = ExceptionQueueService(connection).list()
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Unified Exception Report", records, max_rows=100)


@metrics_app.command("compute")
def metrics_compute_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    workspace: Annotated[str, typer.Option("--workspace", help="Local workspace key.")] = "default",
    period: Annotated[str, typer.Option("--period", help="Optional period scope.")] = "",
    actor: Annotated[str, typer.Option("--actor", help="Actor username or local label.")] = "local-cli",
) -> None:
    """Compute governed DB-backed dashboard metrics."""

    try:
        connection = _db_connection(db_path)
        try:
            metrics = MetricsService(connection).compute(workspace=workspace, period_name=period, actor_label=actor)
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Dashboard Metrics", metrics, max_rows=100)


@metrics_app.command("report")
def metrics_report_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    period: Annotated[str, typer.Option("--period", help="Optional period scope.")] = "",
) -> None:
    """List governed metric snapshots."""

    try:
        connection = _db_connection(db_path)
        try:
            service = MetricsService(connection)
            metrics = service.dashboard(period_name=period)
            lineage = service.lineage()
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Dashboard Metrics", metrics, max_rows=100)
    _print_records("Metric Lineage", lineage, max_rows=100)


@ops_app.command("health")
def ops_health_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """Show sanitized local operational health."""

    try:
        connection = _db_connection(db_path)
        try:
            health = OperationsService(connection).health(str(db_path))
        finally:
            connection.close()
    except (DatabaseError, PlatformError, AuditLedgerError) as exc:
        _safe_cli_error(exc)
    _print_records("ReconForge Local Health", [health])


@ops_app.command("jobs")
def ops_jobs_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List local job history records."""

    try:
        connection = _db_connection(db_path)
        try:
            jobs = OperationsService(connection).jobs()
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Local Jobs", jobs, max_rows=100)


@ops_app.command("durable-job-queue")
def ops_durable_job_queue_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    tenant_id: Annotated[str, typer.Option("--tenant", help="Tenant scope for the queue projection.")] = "",
    workspace_id: Annotated[str, typer.Option("--workspace", help="Optional workspace lane scope.")] = "",
    organization_id: Annotated[str, typer.Option("--organization", help="Optional organization lane scope.")] = "",
    entity_id: Annotated[str, typer.Option("--entity", help="Optional entity lane scope.")] = "",
) -> None:
    """Show sanitized durable-job queue health without job identifiers or payloads."""

    try:
        connection = _db_connection(db_path)
        try:
            snapshot = DurableJobApplicationService(SQLiteDurableJobRepository(connection)).queue_snapshot(
                tenant_id=tenant_id,
                workspace_id=workspace_id or None,
                organization_id=organization_id or None,
                entity_id=entity_id or None,
            )
        finally:
            connection.close()
    except (DatabaseError, PlatformError, SQLiteJobRepositoryError) as exc:
        _safe_cli_error(exc)
    record = asdict(snapshot)
    record.update({"queue_depth": snapshot.queue_depth, "total_count": snapshot.total_count})
    _print_record_detail("Durable Job Queue Health", record)


@ops_app.command("errors")
def ops_errors_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
) -> None:
    """List sanitized local error records."""

    try:
        connection = _db_connection(db_path)
        try:
            errors = OperationsService(connection).errors()
        finally:
            connection.close()
    except (DatabaseError, PlatformError) as exc:
        _safe_cli_error(exc)
    _print_records("Local Error Records", errors, max_rows=100)


@ops_app.command("reliability")
def ops_reliability_command(
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path.")] = Path("output/reconforge.db"),
    require_complete: Annotated[
        bool,
        typer.Option("--require-complete/--allow-no-data", help="Exit non-zero unless every required signal is observed and normal."),
    ] = False,
) -> None:
    """Evaluate the closed local reliability policy without exposing identifiers."""

    try:
        connection = _db_connection(db_path)
        try:
            snapshot = SQLiteReliabilityCollector(connection, memory_mib=process_memory_mib).collect(
                observed_at=datetime.now(UTC)
            )
        finally:
            connection.close()
    except (DatabaseError, ValueError) as exc:
        _safe_cli_error(exc)
    rows: list[dict[str, object]] = [
        {
            "policy_id": result.policy_id,
            "metric": result.metric.value,
            "state": result.state.value,
            "observed": result.observed,
            "slo_id": result.slo_id,
            "runbook": result.runbook,
            "policy_version": result.policy_version,
        }
        for result in evaluate_alerts(snapshot.values)
    ]
    _print_records("Local Reliability Policy", rows, max_rows=20)
    if snapshot.unavailable_sources:
        console.print("Unavailable sources: " + ", ".join(snapshot.unavailable_sources))
    if require_complete and any(row["state"] != AlertState.NORMAL for row in rows):
        raise typer.Exit(code=1)


@deployment_app.command("docker-verify")
def deployment_docker_verify_command() -> None:
    """Verify local Docker files and tooling presence without claiming production readiness."""

    rows: list[dict[str, object]] = [
        {
            "check": "Dockerfile",
            "status": "OK" if Path("Dockerfile").exists() else "WARN",
            "detail": "Dockerfile present" if Path("Dockerfile").exists() else "Dockerfile not found",
        },
        {
            "check": "Compose file",
            "status": "OK" if Path("docker-compose.yml").exists() or Path("compose.yml").exists() else "WARN",
            "detail": "Compose file present"
            if Path("docker-compose.yml").exists() or Path("compose.yml").exists()
            else "Compose file not found",
        },
        {
            "check": "Docker CLI",
            "status": "OK" if shutil.which("docker") else "WARN",
            "detail": "docker executable found" if shutil.which("docker") else "docker executable not found on PATH",
        },
    ]
    _print_records("Docker Verification", rows)
    if any(row["status"] == "WARN" for row in rows):
        console.print(
            "[yellow]Docker verification is local file/tooling inspection only; no runtime guarantee is claimed.[/yellow]"
        )


@deployment_app.command("profiles")
def deployment_profiles_command(
    edition: Annotated[
        str | None,
        typer.Option("--edition", help="Show one edition; omit to list all editions."),
    ] = None,
) -> None:
    """Show truthful deployment-mode defaults and claim boundaries."""

    try:
        profiles = (deployment_profile(edition),) if edition is not None else list_deployment_profiles()
    except DeploymentProfileError as exc:
        _safe_cli_error(exc)
    for profile in profiles:
        _print_record_detail(
            "Deployment Profile",
            {
                **profile.to_dict(),
                "digest": profile.digest,
            },
        )


@deployment_app.command("verify-worker-manifest")
def deployment_verify_worker_manifest_command(
    manifest_path: Annotated[Path, typer.Argument(help="Closed JSON worker permission manifest to verify.")],
) -> None:
    """Verify a hosted worker permission manifest without network or IAM mutation."""

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = verify_worker_permission_manifest(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, WorkerPermissionManifestError) as exc:
        _safe_cli_error(exc)
    _print_record_detail(
        "Worker Permission Manifest",
        {
            **manifest.to_dict(),
            "digest": manifest.digest,
            "discovery_execution_separated": True,
        },
    )


@deployment_app.command("verify-runtime-evidence")
def deployment_verify_runtime_evidence_command(
    manifest_path: Annotated[Path, typer.Argument(help="Closed JSON deployment runtime-evidence manifest to verify.")],
) -> None:
    """Verify deployment runtime facts and profile findings without external calls."""

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        evidence = verify_deployment_runtime_evidence(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, DeploymentRuntimeEvidenceError) as exc:
        _safe_cli_error(exc)
    _print_record_detail(
        "Deployment Runtime Evidence",
        {
            **evidence.to_dict(),
            "digest": evidence.digest,
            "findings": list(evidence.findings),
            "external_calls": False,
        },
    )


@deployment_app.command("readiness")
def deployment_readiness_command(
    edition: Annotated[
        str | None,
        typer.Option("--edition", help="Show one edition; omit to show all matrix entries."),
    ] = None,
    matrix_path: Annotated[
        Path,
        typer.Option("--matrix", help="Path to the closed deployment readiness matrix."),
    ] = Path("docs/execution/DEPLOYMENT_READINESS_MATRIX.v1.yaml"),
) -> None:
    """Verify and display mode-specific readiness evidence without external calls."""

    try:
        matrix = load_deployment_readiness_matrix(matrix_path)
        selected = matrix.select(edition)
    except (DeploymentReadinessError, OSError, UnicodeError) as exc:
        _safe_cli_error(exc)
    for selected_edition in selected:
        _print_record_detail(
            "Deployment Readiness Evidence",
            {
                "edition": selected_edition["id"],
                "readiness_status": selected_edition["readiness_status"],
                "profile_command": selected_edition["profile_command"],
                "gates": selected_edition["gates"],
                "matrix_id": matrix.matrix_id,
                "matrix_digest": matrix.digest,
                "external_calls": False,
            },
        )


@deployment_app.command("verify-key-manifest")
def deployment_verify_key_manifest_command(
    manifest_path: Annotated[Path, typer.Argument(help="Closed non-secret managed-key custody manifest to verify.")],
) -> None:
    """Verify managed-key custody metadata without contacting a KMS or HSM."""

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = verify_managed_key_manifest(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ManagedKeyManifestError) as exc:
        _safe_cli_error(exc)
    _print_record_detail(
        "Managed Key Custody Evidence",
        {
            **manifest.to_dict(),
            "digest": manifest.digest,
            "external_calls": False,
            "secret_material_present": False,
        },
    )


@deployment_app.command("release-check")
def deployment_release_check_command(
    output_path: Annotated[Path, typer.Option("--output", help="Output directory to check.")] = Path("output"),
) -> None:
    """Run local release-readiness smoke checks."""

    checks: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="reconforge-release-check-") as folder:
        temp_db = Path(folder) / "release_check.db"
        try:
            status = run_migrations(temp_db)
            checks.append(
                {
                    "check": "DB migration smoke",
                    "status": "OK",
                    "detail": f"schema {status.current_version}/{status.latest_version}",
                }
            )
        except DatabaseError as exc:
            checks.append({"check": "DB migration smoke", "status": "FAIL", "detail": str(exc)})
    try:
        output_path.mkdir(parents=True, exist_ok=True)
        probe = output_path / ".reconforge_write_probe"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
        checks.append({"check": "Output directory writable", "status": "OK", "detail": str(output_path)})
    except OSError:
        checks.append(
            {"check": "Output directory writable", "status": "FAIL", "detail": "Unable to write output probe."}
        )
    checks.append(
        {"check": "Default host binding", "status": "OK", "detail": "CLI API/Studio defaults bind to 127.0.0.1"}
    )
    _print_records("Release Check", checks)
    if any(row["status"] == "FAIL" for row in checks):
        raise typer.Exit(code=1)


@app.command("init")
def init_workspace(
    workspace: Annotated[Path, typer.Argument(help="Workspace directory to create.")] = Path("."),
) -> None:
    """Create a ReconForge project workspace."""

    for folder in ("input", "output", "config", "reports", "logs"):
        (workspace / folder).mkdir(parents=True, exist_ok=True)
    config_path = write_default_config(workspace / "config" / "reconforge.yml")
    readme_path = workspace / "README.md"
    if not readme_path.exists():
        readme_path.write_text(
            "# ReconForge Workspace\n\nPlace ERP exports in `input/` and generated reports will be written to `output/` or `reports/`.\n",
            encoding="utf-8",
        )
    console.print(f"[green]Workspace ready:[/green] {workspace}")
    console.print(f"Default config: {config_path}")


@app.command("validate")
def validate(
    input_path: Annotated[Path, typer.Argument(help="Directory containing ERP input files.")],
) -> None:
    """Validate input files and cross-references."""

    issues = validate_input_directory(input_path)
    frame = issues_to_frame(issues)
    if frame.empty:
        console.print("[green]Validation passed with no issues.[/green]")
        return
    _print_frame("Validation Issues", frame)
    error_count = int(frame["severity"].astype(str).eq("error").sum())
    warning_count = int(frame["severity"].astype(str).eq("warning").sum())
    console.print(f"Errors: {error_count} | Warnings: {warning_count}")
    if error_count:
        raise typer.Exit(code=1)


@reconcile_app.command("stock-gl")
def reconcile_stock_gl_command(
    input_path: Annotated[Path, typer.Option("--input", help="Directory containing stock_moves and gl_entries.")],
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path(
        "config/reconforge.yml"
    ),
    output_path: Annotated[Path, typer.Option("--output", help="Output directory.")] = Path("output"),
    matching_strategy: Annotated[
        str,
        typer.Option("--matching-strategy", help="Matching strategy: standard, strict, aggressive, audit-safe."),
    ] = "standard",
) -> None:
    """Compare stock movements with GL postings."""

    config = load_config(
        _config_option(config_path),
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    datasets = read_required_datasets(input_path, [DatasetName.STOCK_MOVES, DatasetName.GL_ENTRIES])
    if matching_strategy not in {"standard", "strict", "aggressive", "audit-safe"}:
        console.print("[red]matching strategy must be one of: standard, strict, aggressive, audit-safe[/red]")
        raise typer.Exit(code=1)
    result = reconcile_stock_gl(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.GL_ENTRIES],
        config,
        matching_strategy=cast(MatchingStrategy, matching_strategy),
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    output_dir = ensure_output_dir(output_path)
    frames = stock_gl_result_frames(result)
    write_report_frames(frames, output_dir, "stock_gl")
    workbook_path = write_excel_workbook(
        frames,
        output_dir / "stock_gl_reconciliation.xlsx",
        metadata={
            **audit_metadata(config.company_name, "Stock to GL Reconciliation", config.output_currency),
            "financial_input_policy": result.financial_input_policy,
            "record_identity_policy": result.record_identity_policy,
            "matching_ambiguity_policy": result.matching_ambiguity_policy,
        },
    )
    write_json(
        {
            "financial_input_policy": result.financial_input_policy,
            "record_identity_policy": result.record_identity_policy,
            "matching_ambiguity_policy": result.matching_ambiguity_policy,
            "summary": frame_to_records(result.summary),
            "matched_transactions": frame_to_records(result.matched_transactions),
            "all_exceptions": frame_to_records(result.all_exceptions),
        },
        output_dir,
        "stock_gl_reconciliation",
    )
    _print_frame("Stock-GL Summary", result.summary)
    console.print(f"[green]Stock-GL reconciliation written to:[/green] {workbook_path}")


@reconcile_app.command("workorders")
def reconcile_workorders_command(
    input_path: Annotated[Path, typer.Option("--input", help="Directory containing workshop ERP files.")],
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path(
        "config/reconforge.yml"
    ),
    output_path: Annotated[Path, typer.Option("--output", help="Output directory.")] = Path("output"),
) -> None:
    """Reconcile spare-parts issues, work orders, purchase orders, returns, and invoices."""

    config = load_config(
        _config_option(config_path),
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    datasets = read_required_datasets(
        input_path,
        [
            DatasetName.STOCK_MOVES,
            DatasetName.WORK_ORDERS,
            DatasetName.PURCHASE_ORDERS,
            DatasetName.OLD_PARTS_RETURNS,
            DatasetName.INVOICES,
        ],
    )
    result = reconcile_workorders(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.WORK_ORDERS],
        datasets[DatasetName.PURCHASE_ORDERS],
        datasets[DatasetName.OLD_PARTS_RETURNS],
        datasets[DatasetName.INVOICES],
        config,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    output_dir = ensure_output_dir(output_path)
    frames = workorder_result_frames(result)
    write_report_frames(frames, output_dir, "workorders")
    workbook_metadata = audit_metadata(config.company_name, "Work Order Reconciliation", config.output_currency)
    workbook_metadata["financial_input_policy"] = result.financial_input_policy
    workbook_path = write_excel_workbook(
        frames,
        output_dir / "workorder_reconciliation.xlsx",
        metadata=workbook_metadata,
    )
    write_json(
        {
            "financial_input_policy": result.financial_input_policy,
            "summary": frame_to_records(result.summary),
            "all_exceptions": frame_to_records(result.all_exceptions),
        },
        output_dir,
        "workorder_reconciliation",
    )
    _print_frame("Work-Order Summary", result.summary)
    console.print(f"[green]Work-order reconciliation written to:[/green] {workbook_path}")


@report_app.command("wip-aging")
def wip_aging_command(
    input_path: Annotated[Path, typer.Option("--input", help="Directory containing work_orders.")],
    output_path: Annotated[Path, typer.Option("--output", help="Output directory.")] = Path("output"),
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path(
        "config/reconforge.yml"
    ),
) -> None:
    """Generate WIP aging by work order, customer, equipment, department, and bucket."""

    config = load_config(
        _config_option(config_path),
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    datasets = read_required_datasets(input_path, [DatasetName.WORK_ORDERS])
    wip = generate_wip_aging(datasets[DatasetName.WORK_ORDERS], config)
    summary = aging_summary(wip)
    output_dir = ensure_output_dir(output_path)
    frames = {"wip_aging": wip, "wip_aging_summary": summary}
    write_report_frames(frames, output_dir, "wip")
    workbook_path = write_excel_workbook(
        frames,
        output_dir / "wip_aging.xlsx",
        metadata=audit_metadata(config.company_name, "WIP Aging", config.output_currency),
    )
    write_json({"wip_aging": frame_to_records(wip), "summary": frame_to_records(summary)}, output_dir, "wip_aging")
    _print_frame("WIP Aging Summary", summary)
    console.print(f"[green]WIP aging report written to:[/green] {workbook_path}")


@report_app.command("management-pack")
def management_pack_command(
    input_path: Annotated[Path, typer.Option("--input", help="Directory containing all sample ERP files.")],
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path(
        "config/reconforge.yml"
    ),
    output_path: Annotated[Path, typer.Option("--output", help="Output directory.")] = Path("output"),
) -> None:
    """Generate a complete Excel management pack and companion outputs."""

    config = load_config(
        _config_option(config_path),
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    datasets = read_required_datasets(
        input_path,
        [
            DatasetName.STOCK_MOVES,
            DatasetName.GL_ENTRIES,
            DatasetName.WORK_ORDERS,
            DatasetName.PURCHASE_ORDERS,
            DatasetName.OLD_PARTS_RETURNS,
            DatasetName.INVOICES,
        ],
    )
    stock_result = reconcile_stock_gl(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.GL_ENTRIES],
        config,
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    workorder_result = reconcile_workorders(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.WORK_ORDERS],
        datasets[DatasetName.PURCHASE_ORDERS],
        datasets[DatasetName.OLD_PARTS_RETURNS],
        datasets[DatasetName.INVOICES],
        config,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    wip = generate_wip_aging(datasets[DatasetName.WORK_ORDERS], config)
    artifacts = generate_management_pack(
        input_path, ensure_output_dir(output_path), config, stock_result, workorder_result, wip
    )
    console.print(f"[green]Management pack:[/green] {artifacts.excel_path}")
    console.print(f"[green]JSON summary:[/green] {artifacts.json_path}")
    console.print(f"[green]HTML dashboard report:[/green] {artifacts.html_path}")


@report_app.command("evidence-binder")
def evidence_binder_command(
    input_path: Annotated[Path, typer.Option("--input", help="Generated ReconForge output directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Evidence binder output directory.")] = Path(
        "output/evidence"
    ),
) -> None:
    """Generate audit evidence folders for High and Critical exceptions."""

    try:
        artifacts = generate_evidence_binder(
            input_path,
            output_path,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
    except GeneratedArtifactError as exc:
        console.print("[red]Generated report input failed safety validation.[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Evidence cases generated:[/green] {len(artifacts)}")
    if artifacts:
        _print_frame("Evidence Cases", pd.DataFrame([artifact.model_dump() for artifact in artifacts]))


@report_app.command("client-pack")
def client_pack_command(
    input_path: Annotated[Path, typer.Option("--input", help="Generated ReconForge output directory.")] = Path(
        "output"
    ),
    output_path: Annotated[Path, typer.Option("--output", help="Client handoff pack directory.")] = Path(
        "output/client_pack"
    ),
    redact_names: Annotated[
        bool,
        typer.Option(
            "--redact-names",
            help="Redact customer, supplier, employee, reviewer, and equipment identifiers where practical.",
        ),
    ] = False,
    redact_amounts: Annotated[
        bool, typer.Option("--redact-amounts", help="Bucket or redact monetary values where practical.")
    ] = False,
    exclude_raw_records: Annotated[
        bool, typer.Option("--exclude-raw-records", help="Exclude source-record evidence extracts from the pack.")
    ] = False,
    summary_only: Annotated[
        bool,
        typer.Option(
            "--summary-only", help="Create only generated handoff notes plus the source summary when available."
        ),
    ] = False,
    exclude_evidence: Annotated[
        bool, typer.Option("--exclude-evidence", help="Exclude the evidence folder from the client pack.")
    ] = False,
    include_manifest_checksums: Annotated[
        bool,
        typer.Option(
            "--include-manifest-checksums",
            help="Compatibility request flag; current schema-v2 manifests always include SHA-256 input/output fingerprints.",
        ),
    ] = False,
) -> None:
    """Create a local consultant/client handoff folder from generated outputs."""

    try:
        artifacts = generate_client_pack(
            input_path,
            output_path,
            redact_names=redact_names,
            redact_amounts=redact_amounts,
            exclude_raw_records=exclude_raw_records,
            summary_only=summary_only,
            exclude_evidence=exclude_evidence,
            include_manifest_checksums=include_manifest_checksums,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Client handoff pack:[/green] {artifacts.output_dir}")
    console.print(
        f"Included files: {len(artifacts.included_files)} | Missing optional files: {len(artifacts.missing_optional_files)} | Excluded files: {len(artifacts.excluded_files)}",
    )
    _print_success_paths(artifacts.included_files)


@report_app.command("client-pack-recover")
def client_pack_recover_command(
    output_path: Annotated[
        Path,
        typer.Option("--output", help="Interrupted client handoff pack directory."),
    ],
) -> None:
    """Explicitly recover one integrity-checked interrupted local client-pack publication."""

    try:
        result = recover_client_pack_publication(output_path)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]Client handoff publication recovery:[/green] {result.action} (transaction {result.transaction_id})"
    )


@rules_app.command("validate")
def rules_validate_command(
    pack_path: Annotated[Path, typer.Option("--pack", help="Control pack directory.")],
) -> None:
    """Validate a control pack."""

    pack = load_rule_pack(
        pack_path,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    console.print(f"[green]Control pack valid:[/green] {pack.metadata.pack_id} ({len(pack.rules)} rules)")


def _load_reconciliation_as_code(path: Path) -> ReconciliationAsCodeSpec:
    try:
        return ReconciliationAsCodeSpec.from_file(path)
    except (OSError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@recon_as_code_app.command("validate")
def recon_as_code_validate_command(
    file_path: Annotated[Path, typer.Option("--file", help="Reconciliation-as-Code YAML or JSON file.")],
) -> None:
    """Validate the versioned declarative contract and print its deterministic manifest."""

    spec = _load_reconciliation_as_code(file_path)
    typer.echo(json.dumps(spec.manifest(), ensure_ascii=False, indent=2, sort_keys=True))


@recon_as_code_app.command("lint")
def recon_as_code_lint_command(
    file_path: Annotated[Path, typer.Option("--file", help="Reconciliation-as-Code YAML or JSON file.")],
) -> None:
    """Run fail-closed semantic lint checks without executing any data rule."""

    spec = _load_reconciliation_as_code(file_path)
    findings = spec.lint()
    payload = {
        "reconciliation_id": spec.reconciliation_id,
        "content_sha256": spec.content_digest(),
        "error_count": sum(1 for finding in findings if finding["severity"] == "error"),
        "warning_count": sum(1 for finding in findings if finding["severity"] == "warning"),
        "findings": findings,
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if payload["error_count"]:
        raise typer.Exit(code=1)


@recon_as_code_app.command("test")
def recon_as_code_test_command(
    file_path: Annotated[Path, typer.Option("--file", help="Reconciliation-as-Code YAML or JSON file.")],
) -> None:
    """Run embedded synthetic fixtures through registered deterministic matching adapters."""

    spec = _load_reconciliation_as_code(file_path)
    try:
        payload = spec.run_embedded_tests()
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if not payload["all_passed"]:
        raise typer.Exit(code=1)


@recon_as_code_app.command("simulate")
def recon_as_code_simulate_command(
    file_path: Annotated[Path, typer.Option("--file", help="Reconciliation-as-Code YAML or JSON file.")],
) -> None:
    """Produce a no-side-effect execution plan and matching-fixture outcomes."""

    spec = _load_reconciliation_as_code(file_path)
    try:
        test_run = spec.run_embedded_tests()
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {"plan": spec.simulation_plan(), "test_run": test_run},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


@recon_as_code_app.command("diff")
def recon_as_code_diff_command(
    left_path: Annotated[Path, typer.Option("--left", help="Baseline Reconciliation-as-Code file.")],
    right_path: Annotated[Path, typer.Option("--right", help="Candidate Reconciliation-as-Code file.")],
) -> None:
    """Compare two validated contracts using canonical structural paths."""

    left = _load_reconciliation_as_code(left_path)
    right = _load_reconciliation_as_code(right_path)
    changes = left.diff(right)
    typer.echo(
        json.dumps(
            {
                "left_content_sha256": left.content_digest(),
                "right_content_sha256": right.content_digest(),
                "change_count": len(changes),
                "changes": changes,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


@recon_as_code_app.command("explain")
def recon_as_code_explain_command(
    file_path: Annotated[Path, typer.Option("--file", help="Reconciliation-as-Code YAML or JSON file.")],
) -> None:
    """Explain the validated contract, human-governance boundary, and lint state."""

    spec = _load_reconciliation_as_code(file_path)
    findings = spec.lint()
    typer.echo(
        json.dumps(
            {
                "manifest": spec.manifest(),
                "simulation_plan": spec.simulation_plan(),
                "lint_findings": findings,
                "financial_decision_boundary": "Matching outputs require the declared human approval workflow.",
                "arbitrary_code_execution": "forbidden",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


@recon_as_code_app.command("rollback")
def recon_as_code_rollback_command(
    current_path: Annotated[Path, typer.Option("--current", help="Currently active validated contract.")],
    target_path: Annotated[Path, typer.Option("--to", help="Previously approved validated contract.")],
    output_path: Annotated[Path, typer.Option("--output", help="Rollback output YAML or JSON file.")],
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Explicitly allow atomic replacement of an existing regular output file."),
    ] = False,
) -> None:
    """Atomically restore a previously validated contract without executing it."""

    current = _load_reconciliation_as_code(current_path)
    target = _load_reconciliation_as_code(target_path)
    try:
        written = target.write_file(output_path, overwrite=overwrite)
    except (OSError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "action": "reconciliation-as-code-rollback",
                "from_content_sha256": current.content_digest(),
                "to_content_sha256": target.content_digest(),
                "change_count": len(current.diff(target)),
                "output": str(written),
                "executed": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


@mappings_app.command("validate")
def mappings_validate_command(
    pack_path: Annotated[Path, typer.Option("--pack", help="ERP mapping control-pack directory.")],
) -> None:
    """Validate an ERP mapping profile and its control-pack files."""

    result = validate_mapping_pack(pack_path)
    table = Table(title=f"Mapping Profile Validation: {result.pack_path}")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for check in result.checks:
        style = "green" if check.passed else "red"
        table.add_row(check.name, f"[{style}]{check.status}[/{style}]", check.detail)
    console.print(table)
    passed = sum(1 for check in result.checks if check.passed)
    failed = len(result.checks) - passed
    summary_style = "green" if result.passed else "red"
    console.print(f"[{summary_style}]Summary: {passed} passed, {failed} failed[/{summary_style}]")
    if not result.passed:
        raise typer.Exit(code=1)


def _run_mapping_inspection(input_path: Path, pack_path: Path, output_path: Path) -> None:
    try:
        result = inspect_mapping_inputs(input_path, pack_path, output_path)
    except (OSError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    summary = result.summary
    table = Table(title=f"Mapping Inspection: {result.profile_id}")
    table.add_column("Metric")
    table.add_column("Value")
    for key, value in summary.items():
        table.add_row(key.replace("_", " "), str(value))
    console.print(table)
    _print_success_paths([result.report_markdown_path, result.report_json_path])


@mappings_app.command("inspect")
def mappings_inspect_command(
    input_path: Annotated[Path, typer.Option("--input", help="Folder containing local CSV/XLSX ERP exports.")],
    pack_path: Annotated[Path, typer.Option("--pack", help="ERP mapping control-pack directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Mapping inspection report directory.")] = Path(
        "output/mapping_wizard"
    ),
) -> None:
    """Inspect local export headers against an ERP mapping profile."""

    _run_mapping_inspection(input_path, pack_path, output_path)


@mappings_app.command("wizard")
def mappings_wizard_command(
    input_path: Annotated[Path, typer.Option("--input", help="Folder containing local CSV/XLSX ERP exports.")],
    pack_path: Annotated[Path, typer.Option("--pack", help="ERP mapping control-pack directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Mapping inspection report directory.")] = Path(
        "output/mapping_wizard"
    ),
) -> None:
    """Generate a draft local mapping report for ERP exports."""

    _run_mapping_inspection(input_path, pack_path, output_path)


@mappings_app.command("profile-template")
def mappings_profile_template_command(
    output_path: Annotated[Path, typer.Option("--output", help="Profile template output directory.")] = Path(
        "output/profile_template"
    ),
) -> None:
    """Generate a local generic CSV mapping profile template."""

    artifacts = write_profile_template(output_path)
    _print_success_paths([artifacts.mapping_template_path, artifacts.guide_path])


@rules_app.command("list")
def rules_list_command(
    pack_path: Annotated[Path, typer.Option("--pack", help="Control pack directory.")],
) -> None:
    """List rules in a control pack."""

    pack = load_rule_pack(
        pack_path,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    frame = pd.DataFrame(
        [
            {
                "rule_id": rule.rule_id,
                "rule_name": rule.rule_name,
                "severity": rule.severity,
                "entity_type": rule.entity_type,
                "source_file": rule.source_file,
                "risk_impact": rule.risk_impact,
            }
            for rule in pack.rules
        ],
    )
    _print_frame(f"Rules: {pack.metadata.name}", frame, max_rows=100)


@rules_app.command("run")
def rules_run_command(
    input_path: Annotated[Path, typer.Option("--input", help="Directory containing ERP input files.")],
    pack_path: Annotated[Path, typer.Option("--pack", help="Control pack directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Rule output directory.")] = Path("output/rules"),
) -> None:
    """Run a control pack against ERP exports."""

    execution = execute_rule_pack(
        input_path,
        pack_path,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    paths = write_rule_execution(execution, output_path)
    console.print(f"[green]Rule results:[/green] {len(execution.results)} triggered controls")
    _print_success_paths(paths)


@rules_app.command("explain")
def rules_explain_command(
    pack_path: Annotated[Path, typer.Option("--pack", help="Control pack directory.")],
    rule_id: Annotated[str, typer.Option("--rule", help="Rule ID to explain.")],
) -> None:
    """Explain a control-pack rule in deterministic plain English."""

    try:
        console.print(
            explain_rule(
                str(pack_path),
                rule_id,
                financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
            )
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@app.command("anonymize")
def anonymize_command(
    input_path: Annotated[Path, typer.Option("--input", help="Input ERP export directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Anonymized output directory.")],
    mask_amounts: Annotated[bool, typer.Option("--mask-amounts", help="Mask monetary amounts.")] = False,
    amount_noise_percent: Annotated[
        str,
        typer.Option("--amount-noise-percent", help="Exact maximum percentage noise for masked amounts."),
    ] = "15",
    seed: Annotated[int, typer.Option("--seed", help="Deterministic anonymization seed.")] = 42,
    preserve_dates: Annotated[bool, typer.Option("--preserve-dates", help="Keep dates unchanged.")] = False,
    date_shift_days: Annotated[int, typer.Option("--date-shift-days", help="Shift dates by this many days.")] = 0,
    profile: Annotated[
        str, typer.Option("--profile", help="Anonymization profile: consulting-safe or public-demo.")
    ] = "consulting-safe",
    private_mapping_path: Annotated[
        Path | None,
        typer.Option(
            "--private-map-output",
            help="Explicit private original-to-mask CSV path outside both input and anonymized output directories.",
        ),
    ] = None,
) -> None:
    """Anonymize ERP exports while preserving referential integrity."""

    try:
        paths = anonymize_directory(
            input_path,
            output_path,
            mask_amounts=mask_amounts,
            amount_noise_percent=amount_noise_percent,
            seed=seed,
            preserve_dates=preserve_dates,
            date_shift_days=date_shift_days,
            profile=profile,
            private_mapping_path=private_mapping_path,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Anonymized files:[/green] {len(paths)}")
    _print_success_paths(paths)


@generate_app.command("synthetic")
def generate_synthetic_command(
    rows: Annotated[int, typer.Option("--rows", help="Number of stock movement rows to generate.", min=1)] = 1000,
    output_path: Annotated[Path, typer.Option("--output", help="Synthetic output directory.")] = Path(
        "benchmarks/small_1k"
    ),
    exception_rate: Annotated[
        str, typer.Option("--exception-rate", help="Approximate exception rate as exact decimal text.")
    ] = "0.15",
    critical_rate: Annotated[
        str, typer.Option("--critical-rate", help="Approximate critical exception rate as exact decimal text.")
    ] = "0.05",
    seed: Annotated[int, typer.Option("--seed", help="Deterministic generation seed.")] = 42,
    industry: Annotated[
        str, typer.Option("--industry", help="Industry profile: workshop, manufacturing, fleet, dealership, service.")
    ] = "workshop",
    currency: Annotated[
        str, typer.Option("--currency", help="Output currency code for synthetic monetary rows.")
    ] = "USD",
) -> None:
    """Generate synthetic ERP CSV exports matching ReconForge schema."""

    try:
        paths = generate_synthetic_dataset(
            rows,
            output_path,
            exception_rate=exception_rate,
            critical_rate=critical_rate,
            seed=seed,
            industry=industry,
            currency=currency,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Synthetic dataset generated:[/green] {output_path}")
    _print_success_paths(paths)


@app.command("benchmark")
def benchmark_command(
    input_path: Annotated[Path, typer.Option("--input", help="Input dataset directory.")],
    engine: Annotated[str, typer.Option("--engine", help="Benchmark engine: pandas or duckdb.")] = "pandas",
    output_path: Annotated[Path, typer.Option("--output", help="Benchmark output directory.")] = Path(
        "output/benchmark"
    ),
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path(
        "config/reconforge.yml"
    ),
) -> None:
    """Benchmark reconciliation runtime and output metrics."""

    try:
        metrics = run_benchmark(input_path, output_path, engine_name=engine, config_path=config_path)
    except (ValueError, RuntimeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    _print_frame("Benchmark", pd.DataFrame([metrics.to_dict()]))


@app.command("benchmark-reconciliation")
def benchmark_reconciliation_command(
    records: Annotated[
        int, typer.Option("--records", min=2, max=2_000_000, help="Synthetic records across both sides.")
    ] = 10_000,
    partitions: Annotated[
        int, typer.Option("--partitions", min=0, max=100_000, help="Hard-key partitions; 0 selects a bounded default.")
    ] = 0,
    partition_max_records: Annotated[int, typer.Option("--partition-max-records", min=1, max=100_000)] = 10_000,
    seed: Annotated[int, typer.Option("--seed", help="Synthetic data seed.")] = 7,
    amount_fractional_digits: Annotated[
        int,
        typer.Option("--amount-fractional-digits", min=0, max=18, help="Synthetic record decimals per amount field."),
    ] = 2,
    streaming: Annotated[
        bool, typer.Option("--streaming", help="Generate and match one synthetic partition at a time.")
    ] = False,
    output_path: Annotated[Path, typer.Option("--output", help="Benchmark output directory.")] = Path(
        "output/reconciliation-benchmark"
    ),
) -> None:
    """Benchmark the deterministic partitioned execution adapter."""

    try:
        benchmark = (
            run_reconciliation_execution_streaming_benchmark if streaming else run_reconciliation_execution_benchmark
        )
        metrics = benchmark(
            records,
            partition_count=partitions or None,
            partition_max_records=partition_max_records,
            seed=seed,
            amount_fractional_digits=amount_fractional_digits,
            output_dir=output_path,
        )
    except (ValueError, RuntimeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    _print_frame("Reconciliation execution benchmark", pd.DataFrame([metrics.to_dict()]))


@explain_app.command("exception")
def explain_exception_command(
    input_path: Annotated[Path, typer.Option("--input", help="Local JSON exception file.")],
    exception_id: Annotated[str, typer.Option("--exception-id", help="Exception ID, rule ID, move ID, or entry ID.")],
) -> None:
    """Explain an exception without requiring an AI API."""

    try:
        console.print(explain_exception_file(input_path, exception_id))
    except (OSError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@review_app.command("list")
def review_list_command(
    input_path: Annotated[Path, typer.Option("--input", help="Generated ReconForge output directory.")] = Path(
        "output"
    ),
) -> None:
    """List local exceptions with review status."""

    state_path = input_path / "review_state.json"
    try:
        exceptions = collect_exception_frame(
            input_path,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
        merged = merge_review_state_with_exceptions(exceptions, load_review_state(state_path))
    except GeneratedArtifactError as exc:
        console.print("[red]Generated report input failed safety validation.[/red]")
        raise typer.Exit(code=1) from exc
    if merged.empty:
        console.print("[yellow]No generated exceptions found.[/yellow]")
        return
    columns = [
        "exception_id",
        "status",
        "reviewer",
        "updated_at",
        "severity",
        "exception_type",
        "amount_impact",
        "source_file",
    ]
    visible = merged[[column for column in columns if column in merged.columns]]
    _print_frame("Exception Review State", visible, max_rows=100)
    if "status" in merged.columns:
        counts = merged["status"].astype(str).value_counts().to_dict()
        summary = " | ".join(f"{status}: {count}" for status, count in counts.items())
        console.print(f"[dim]Review statuses:[/dim] {summary}")


@review_app.command("set-status")
def review_set_status_command(
    exception_id: Annotated[str, typer.Option("--exception-id", help="Exception ID to update.")],
    status: Annotated[str, typer.Option("--status", help=f"Status: {', '.join(ALLOWED_STATUSES)}")],
    input_path: Annotated[Path, typer.Option("--input", help="Generated ReconForge output directory.")] = Path(
        "output"
    ),
    reviewer: Annotated[str, typer.Option("--reviewer", help="Reviewer name or initials.")] = "",
    note: Annotated[str, typer.Option("--note", help="Reviewer note.")] = "",
    decision_reason: Annotated[str, typer.Option("--decision-reason", help="Decision reason.")] = "",
    accepted_risk_reason: Annotated[str, typer.Option("--accepted-risk-reason", help="Accepted-risk reason.")] = "",
    escalation_owner: Annotated[str, typer.Option("--escalation-owner", help="Escalation owner.")] = "",
    prepared_by: Annotated[
        str, typer.Option("--prepared-by", help="Preparer name or role for workflow metadata.")
    ] = "",
    prepared_at: Annotated[str, typer.Option("--prepared-at", help="Optional prepared timestamp or date.")] = "",
    reviewed_by: Annotated[
        str, typer.Option("--reviewed-by", help="Reviewer name or role for workflow metadata.")
    ] = "",
    reviewed_at: Annotated[str, typer.Option("--reviewed-at", help="Optional reviewed timestamp or date.")] = "",
    certification_status: Annotated[
        str, typer.Option("--certification-status", help="Workflow certification status metadata.")
    ] = "",
    certification_note: Annotated[str, typer.Option("--certification-note", help="Workflow certification note.")] = "",
) -> None:
    """Set local review status for one exception."""

    state_path = input_path / "review_state.json"
    try:
        state = load_review_state(state_path)
        entry = update_review_status(
            exception_id,
            status,
            state,
            reviewer=reviewer,
            note=note,
            decision_reason=decision_reason,
            accepted_risk_reason=accepted_risk_reason,
            escalation_owner=escalation_owner,
            prepared_by=prepared_by,
            prepared_at=prepared_at,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at,
            certification_status=certification_status,
            certification_note=certification_note,
        )
    except GeneratedArtifactError as exc:
        console.print("[red]Review state failed safety validation.[/red]")
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    save_review_state(state_path, state)
    console.print(
        f"[green]Review updated:[/green] {entry['exception_id']} | {entry['status']} | {state_path}",
    )


@review_app.command("export")
def review_export_command(
    input_path: Annotated[Path, typer.Option("--input", help="Generated ReconForge output directory.")] = Path(
        "output"
    ),
    output_path: Annotated[Path, typer.Option("--output", help="Review register workbook path.")] = Path(
        "output/review_register.xlsx"
    ),
) -> None:
    """Export exception review state as an Excel register."""

    try:
        path = export_review_register(
            input_path,
            output_path,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
    except GeneratedArtifactError as exc:
        console.print("[red]Generated report input failed safety validation.[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Review register written:[/green] {path}")


@close_app.command("init")
def close_init_command(
    output_path: Annotated[Path, typer.Option("--output", help="Close checklist output directory.")] = Path(
        "output/close"
    ),
    template_path: Annotated[
        Path | None, typer.Option("--template", help="Optional local JSON/YAML checklist template.")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing close checklist.")] = False,
) -> None:
    """Create a local close checklist JSON file."""

    try:
        path = write_close_checklist(output_path, template_path=template_path, force=force)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Close checklist:[/green] {path}")


@close_app.command("list")
def close_list_command(
    input_path: Annotated[Path, typer.Option("--input", help="Close checklist directory or JSON file.")] = Path(
        "output/close"
    ),
) -> None:
    """List local close checklist tasks."""

    try:
        checklist = load_close_checklist(input_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    tasks = close_tasks_frame(checklist)
    if tasks.empty:
        console.print("[yellow]No close checklist tasks found.[/yellow]")
        return
    _print_frame(
        "Close Checklist",
        tasks[["task_id", "status", "owner", "due_date", "category", "task_name", "note"]],
        max_rows=100,
    )
    summary = close_summary_frame(checklist)
    completion = summary[summary["metric"].eq("completion_rate_pct")]
    if not completion.empty:
        console.print(f"[dim]Completion:[/dim] {completion.iloc[0]['value']}%")


@close_app.command("set-status")
def close_set_status_command(
    task_id: Annotated[str, typer.Option("--task-id", help="Close checklist task ID.")],
    status: Annotated[str, typer.Option("--status", help=f"Status: {', '.join(ALLOWED_CLOSE_STATUSES)}")],
    input_path: Annotated[Path, typer.Option("--input", help="Close checklist directory or JSON file.")] = Path(
        "output/close"
    ),
    owner: Annotated[str, typer.Option("--owner", help="Plain-text owner name or role.")] = "",
    note: Annotated[str, typer.Option("--note", help="Local workflow note.")] = "",
    due_date: Annotated[str, typer.Option("--due-date", help="Optional due date text.")] = "",
) -> None:
    """Update one local close checklist task."""

    try:
        task = update_close_task_status(
            input_path, task_id=task_id, status=status, owner=owner, note=note, due_date=due_date
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Close task updated:[/green] {task['task_id']} | {task['status']}")


@close_app.command("report")
def close_report_command(
    input_path: Annotated[Path, typer.Option("--input", help="Close checklist directory or JSON file.")] = Path(
        "output/close"
    ),
    output_path: Annotated[Path, typer.Option("--output", help="Close report output directory.")] = Path(
        "output/close_report"
    ),
) -> None:
    """Export a local close checklist report."""

    try:
        artifacts = export_close_report(input_path, output_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    _print_success_paths(
        [
            artifacts.html_path,
            artifacts.workbook_path,
            artifacts.csv_path,
            artifacts.markdown_path,
            artifacts.json_path,
        ],
    )


@analyze_app.command("variance")
def analyze_variance_command(
    current_path: Annotated[Path, typer.Option("--current", help="Current generated ReconForge output folder.")],
    previous_path: Annotated[Path, typer.Option("--previous", help="Previous generated ReconForge output folder.")],
    output_path: Annotated[Path, typer.Option("--output", help="Variance output directory.")] = Path("output/variance"),
    amount_threshold: Annotated[
        str, typer.Option("--amount-threshold", help="Exact absolute amount threshold for flags.")
    ] = "0",
    percent_threshold: Annotated[
        str, typer.Option("--percent-threshold", help="Exact percentage threshold for flags.")
    ] = "10",
) -> None:
    """Compare two local summary output folders."""

    try:
        artifacts = analyze_variance(
            current_path,
            previous_path,
            output_path,
            amount_threshold=amount_threshold,
            percent_threshold=percent_threshold,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    _print_success_paths(
        [
            artifacts.workbook_path,
            artifacts.csv_path,
            artifacts.json_path,
            artifacts.html_path,
            artifacts.markdown_path,
        ],
    )


@controls_app.command("matrix")
def controls_matrix_command(
    pack_path: Annotated[Path, typer.Option("--pack", help="Control pack directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Control matrix output directory.")] = Path(
        "output/control_matrix"
    ),
) -> None:
    """Generate a local control matrix from a rule pack."""

    try:
        artifacts = export_control_matrix(
            pack_path,
            output_path,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    _print_success_paths([artifacts.workbook_path, artifacts.csv_path, artifacts.json_path, artifacts.markdown_path])


@compare_app.command("periods", context_settings={"allow_extra_args": True})
def compare_periods_command(
    ctx: typer.Context,
    inputs: Annotated[
        list[Path], typer.Option("--inputs", help="Generated output folders to compare, in period order.")
    ],
    output_path: Annotated[Path, typer.Option("--output", help="Period comparison output directory.")] = Path(
        "output/period_comparison"
    ),
) -> None:
    """Compare exception outputs from two or more generated periods."""

    period_inputs = [*inputs, *(Path(value) for value in ctx.args)]
    try:
        artifacts = compare_period_outputs(
            period_inputs,
            output_path,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Period comparison:[/green] {output_path}")
    _print_success_paths([artifacts.workbook_path, artifacts.html_path, artifacts.json_path, artifacts.markdown_path])


@demo_app.command("run")
def demo_run_command(
    output_path: Annotated[Path, typer.Option("--output", help="Demo output directory.")] = Path("output/demo"),
    input_path: Annotated[Path, typer.Option("--input", help="Sample ERP export directory.")] = Path(
        "examples/sample_data"
    ),
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path(
        "config/reconforge.yml"
    ),
    rules_pack: Annotated[Path, typer.Option("--rules-pack", help="Control pack to run during the demo.")] = Path(
        "control-packs/audit-basic"
    ),
) -> None:
    """Run the local 10-minute sample workflow end to end."""

    issues = validate_input_directory(input_path)
    issue_frame = issues_to_frame(issues)
    error_count = int(issue_frame["severity"].astype(str).eq("error").sum()) if not issue_frame.empty else 0
    if error_count:
        _print_frame("Demo Data Validation Issues", issue_frame)
        console.print("[red]Demo stopped because sample data has validation errors.[/red]")
        raise typer.Exit(code=1)

    config = load_config(
        _config_option(config_path),
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    datasets = read_required_datasets(
        input_path,
        [
            DatasetName.STOCK_MOVES,
            DatasetName.GL_ENTRIES,
            DatasetName.WORK_ORDERS,
            DatasetName.PURCHASE_ORDERS,
            DatasetName.OLD_PARTS_RETURNS,
            DatasetName.INVOICES,
        ],
    )
    output_dir = ensure_output_dir(output_path)
    stock_result = reconcile_stock_gl(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.GL_ENTRIES],
        config,
        input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    workorder_result = reconcile_workorders(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.WORK_ORDERS],
        datasets[DatasetName.PURCHASE_ORDERS],
        datasets[DatasetName.OLD_PARTS_RETURNS],
        datasets[DatasetName.INVOICES],
        config,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    wip = generate_wip_aging(datasets[DatasetName.WORK_ORDERS], config)

    stock_frames = stock_gl_result_frames(stock_result)
    workorder_frames = workorder_result_frames(workorder_result)
    write_report_frames(stock_frames, output_dir, "stock_gl")
    write_report_frames(workorder_frames, output_dir, "workorders")
    stock_workbook = write_excel_workbook(
        stock_frames,
        output_dir / "stock_gl_reconciliation.xlsx",
        metadata={
            **audit_metadata(config.company_name, "Stock to GL Reconciliation", config.output_currency),
            "financial_input_policy": stock_result.financial_input_policy,
            "record_identity_policy": stock_result.record_identity_policy,
            "matching_ambiguity_policy": stock_result.matching_ambiguity_policy,
        },
    )
    workorder_workbook = write_excel_workbook(
        workorder_frames,
        output_dir / "workorder_reconciliation.xlsx",
        metadata=audit_metadata(config.company_name, "Work Order Reconciliation", config.output_currency),
    )

    rule_execution = execute_rule_pack(
        input_path,
        rules_pack,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    rule_paths = write_rule_execution(rule_execution, output_dir / "rules")
    artifacts = generate_management_pack(input_path, output_dir, config, stock_result, workorder_result, wip)

    state_path = output_dir / "review_state.json"
    state = load_review_state(state_path)
    exceptions = collect_exception_frame(
        output_dir,
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    if not exceptions.empty:
        exception_id = str(exceptions.iloc[0]["exception_id"])
        update_review_status(
            exception_id,
            "Under Review",
            state,
            reviewer="Demo Reviewer",
            note="Initial sample review started from the one-command demo.",
            decision_reason="Validate source posting and operational evidence.",
        )
    save_review_state(state_path, state)
    register_path = export_review_register(
        output_dir,
        output_dir / "review_register.xlsx",
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    evidence_artifacts = generate_evidence_binder(
        output_dir,
        output_dir / "evidence",
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )
    client_pack_artifacts = generate_client_pack(
        output_dir,
        output_dir / "client_pack",
        financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
    )

    paths = [
        artifacts.excel_path,
        output_dir / "executive_report.html",
        output_dir / "dashboard.html",
        artifacts.markdown_path,
        state_path,
        register_path,
        output_dir / "evidence",
        client_pack_artifacts.output_dir,
        stock_workbook,
        workorder_workbook,
        *rule_paths,
    ]
    _print_frame(
        "Demo Workflow",
        pd.DataFrame(
            [
                {
                    "step": "validated_sample_data",
                    "result": f"{len(issue_frame)} validation issues, {error_count} errors",
                },
                {"step": "stock_to_gl_exceptions", "result": len(stock_result.all_exceptions)},
                {"step": "workorder_exceptions", "result": len(workorder_result.all_exceptions)},
                {"step": "rules_triggered", "result": len(rule_paths)},
                {"step": "evidence_cases", "result": len(evidence_artifacts)},
                {"step": "review_state_entries", "result": len(state)},
            ],
        ),
        max_rows=20,
    )
    _print_success_paths(paths)
    console.print("\n[bold]Next steps[/bold]")
    console.print(f"1. Open dashboard: {output_dir / 'dashboard.html'}")
    console.print(f"2. Open executive report: {output_dir / 'executive_report.html'}")
    console.print(f"3. Open management pack: {output_dir / 'management_pack.xlsx'}")
    console.print(f"4. Open evidence binder: {output_dir / 'evidence' / 'index.html'}")
    console.print(f"5. Review client handoff pack: {client_pack_artifacts.output_dir}")
    console.print(f"6. Run Studio: reconforge studio --input {input_path} --output {output_dir}")
    console.print(f"7. Review or export the register: {register_path}")


@demo_app.command("enterprise")
def demo_enterprise_command(
    output_path: Annotated[Path, typer.Option("--output", help="Synthetic enterprise demo output directory.")] = Path(
        "output/enterprise_demo"
    ),
    db_path: Annotated[
        Path | None, typer.Option("--db", help="Optional local SQLite DB path inside the demo output directory.")
    ] = None,
) -> None:
    """Generate a local synthetic enterprise demo package."""

    try:
        result = generate_enterprise_demo(output_path, db_path=db_path)
    except EnterpriseDemoError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    _print_frame(
        "Synthetic Enterprise Demo",
        pd.DataFrame(
            [
                {"artifact": "output_folder", "result": result.output_dir},
                {"artifact": "manifest", "result": result.manifest_path.name},
                {"artifact": "walkthrough", "result": result.walkthrough_path.name},
                {"artifact": "demo_script", "result": result.demo_script_path.name},
                {
                    "artifact": "database",
                    "result": result.db_path.name if result.db_path is not None else "not persisted",
                },
                {"artifact": "synthetic_data_marker", "result": "SYNTHETIC_ENTERPRISE_DEMO_ONLY"},
            ],
        ),
        max_rows=20,
    )
    _print_success_paths(
        [
            result.readme_path,
            result.walkthrough_path,
            result.demo_script_path,
            result.manifest_path,
            result.output_dir / "reports",
            result.output_dir / "sample_evidence",
        ],
    )
    console.print("[green]Synthetic enterprise demo package written.[/green]")
    console.print("All generated data is synthetic and local-first; no external calls were made.")


@demo_app.command("studio-data")
def demo_studio_data_command(
    input_path: Annotated[
        Path,
        typer.Option("--input", help="Generated synthetic enterprise demo directory."),
    ] = Path("output/enterprise_demo"),
    output_path: Annotated[
        Path,
        typer.Option("--output", help="Overview JSON path; related Studio contracts are written beside it."),
    ] = Path("apps/web/public/demo/studio-overview.json"),
) -> None:
    """Build the synthetic-only data bundle used by the modern Studio preview."""

    try:
        bundle = build_studio_demo_bundle(input_path, output_path)
    except StudioDemoBridgeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print("[green]Synthetic Studio data contracts:[/green]")
    for path in bundle.paths:
        console.print(f"- {path}")
    console.print("The contracts contain bounded, allowlisted fields from local synthetic demo outputs only.")


@demo_app.command("showcase")
def demo_showcase_command(
    output_path: Annotated[
        Path,
        typer.Option("--output", help="Synthetic enterprise source package directory."),
    ] = Path("output/showcase/enterprise_demo"),
    studio_output_path: Annotated[
        Path,
        typer.Option(
            "--studio-output",
            help="Studio overview JSON path; related contracts are written beside it.",
        ),
    ] = Path("apps/web/public/demo/studio-overview.json"),
    persist_db: Annotated[
        bool,
        typer.Option(
            "--persist-db/--no-db",
            help="Persist the seeded local SQLite walkthrough database inside the demo package.",
        ),
    ] = False,
) -> None:
    """Generate the complete synthetic enterprise package and modern Studio bundle."""

    db_path = output_path / "reconforge.db" if persist_db else None
    try:
        result = generate_enterprise_demo(output_path, db_path=db_path)
        bundle = build_studio_demo_bundle(result.output_dir, studio_output_path)
    except (EnterpriseDemoError, StudioDemoBridgeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    _print_frame(
        "ReconForge Expert Showcase",
        pd.DataFrame(
            [
                {"layer": "synthetic enterprise package", "result": result.output_dir},
                {"layer": "strict Studio contracts", "result": len(bundle.paths)},
                {"layer": "generated records", "result": sum(result.record_counts.values())},
                {"layer": "local database", "result": result.db_path.name if result.db_path else "not persisted"},
                {"layer": "external calls", "result": "none"},
            ]
        ),
        max_rows=10,
    )
    console.print("[green]Showcase ready.[/green]")
    console.print(f"Enterprise walkthrough: {result.walkthrough_path}")
    console.print(f"Studio overview contract: {bundle.overview_path}")
    console.print("Run the modern UI locally: npm --prefix apps/web run dev")
    console.print("All records are synthetic, local-first, read-only preview data.")


@app.command("dashboard")
def dashboard(
    input_path: Annotated[Path, typer.Option("--input", help="Generated output directory to serve.")] = Path("output"),
    host: Annotated[str, typer.Option("--host", help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Bind port.")] = 8501,
) -> None:
    """Start the local dashboard server for generated reports."""

    if not input_path.exists():
        console.print(f"[red]Output directory does not exist:[/red] {input_path}")
        raise typer.Exit(code=1)
    console.print(f"[green]Starting ReconForge dashboard:[/green] http://{host}:{port}")
    uvicorn.run(create_app(input_path), host=host, port=port, log_level="info")


@app.command("studio")
def studio(
    input_path: Annotated[Path, typer.Option("--input", help="ERP input directory for Studio views.")] = Path(
        "examples/sample_data"
    ),
    output_path: Annotated[
        Path, typer.Option("--output", help="Generated output directory for downloads/evidence.")
    ] = Path("output"),
    db_path: Annotated[Path, typer.Option("--db", help="Local SQLite database path for --require-auth mode.")] = Path(
        "output/reconforge.db"
    ),
    require_auth: Annotated[
        bool, typer.Option("--require-auth", help="Require local Studio login and RBAC checks.")
    ] = False,
    host: Annotated[str, typer.Option("--host", help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Bind port.")] = 8601,
) -> None:
    """Start ReconForge Studio, a local review workspace."""

    if require_auth:
        try:
            status = database_status(_db_option(db_path))
            if status.pending_versions:
                console.print(
                    "[red]ReconForge database has pending migrations. Run 'reconforge db migrate' first.[/red]"
                )
                raise typer.Exit(code=1)
        except DatabaseError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from exc
    console.print(f"[green]Starting ReconForge Studio:[/green] http://{host}:{port}")
    uvicorn.run(
        create_studio_app(input_path, output_path, require_auth=require_auth, db_path=db_path),
        host=host,
        port=port,
        log_level="info",
    )


@app.command("doctor")
def doctor(
    input_path: Annotated[Path, typer.Option("--input", help="Optional sample data directory to inspect.")] = Path(
        "examples/sample_data"
    ),
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path(
        "config/reconforge.yml"
    ),
    output_path: Annotated[Path, typer.Option("--output", help="Output directory to inspect.")] = Path("output"),
) -> None:
    """Check environment, dependencies, sample data, config, and report output path."""

    checks = []
    checks.append(("Python package", "OK", f"ReconForge ERP {__version__}"))
    try:
        config = load_config(
            _config_option(config_path),
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
        )
        checks.append(("Config", "OK", f"{config_path} | {config.company_name}"))
    except ValueError as exc:
        checks.append(("Config", "FAIL", str(exc)))
    checks.append(("Sample data", "OK" if input_path.exists() else "WARN", str(input_path)))
    checks.append(("Output path", "OK", str(ensure_output_dir(output_path))))
    issues = validate_input_directory(input_path) if input_path.exists() else []
    structural_errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    checks.append(
        ("Validation", "OK" if structural_errors == 0 else "FAIL", f"{structural_errors} errors, {warnings} warnings")
    )

    table = Table(title="ReconForge Doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for check, status, detail in checks:
        style = "green" if status == "OK" else "yellow" if status == "WARN" else "red"
        table.add_row(check, f"[{style}]{status}[/{style}]", detail)
    console.print(table)
    if any(status == "FAIL" for _, status, _ in checks):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
