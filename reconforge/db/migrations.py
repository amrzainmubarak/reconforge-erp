"""SQLite migration runner for local ReconForge databases."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from reconforge.db.connection import DatabaseError, connect, resolve_db_path
from reconforge.db.migration_52_budget_control import SQLITE_BUDGET_CONTROL_UPGRADE_SQL
from reconforge.db.migration_53_outbox_fencing import (
    SQLITE_OUTBOX_FENCING_UPGRADE_SQL,
    atomic_outbox_fencing_upgrade,
)
from reconforge.db.schema import (
    ACCOUNT_RECONCILIATION_MONEY_MIGRATION_SQL,
    API_SESSIONS_SCHEMA_SQL,
    AUTH_RBAC_SCHEMA_SQL,
    BANK_STATEMENT_CONTROL_SCHEMA_SQL,
    CERTIFICATION_EVIDENCE_MIGRATION_SQL,
    CLOSE_PERIOD_LOCK_EVIDENCE_MIGRATION_SQL,
    CLOSE_PERIOD_SOD_MIGRATION_SQL,
    CONSOLIDATION_CLOSE_SCHEMA_SQL,
    CONSOLIDATION_OWNERSHIP_SCHEMA_SQL,
    CURRENCY_REGISTRY_BINDING_SCHEMA_SQL,
    CURRENCY_REGISTRY_SNAPSHOT_SCHEMA_SQL,
    DB_BRIDGE_SCHEMA_SQL,
    DURABLE_JOB_EFFECTS_SCHEMA_SQL,
    DURABLE_JOB_LEASES_SCHEMA_SQL,
    DURABLE_JOB_ORGANIZATION_MIGRATION_SQL,
    DURABLE_JOB_SCHEDULER_CURSOR_MIGRATION_SQL,
    DURABLE_JOBS_SCHEMA_SQL,
    EVIDENCE_OBJECT_STORAGE_MIGRATION_SQL,
    EVIDENCE_RETENTION_GOVERNANCE_MIGRATION_SQL,
    FINANCE_CORE_SCHEMA_SQL,
    FINANCE_PLATFORM_SCHEMA_SQL,
    IDEMPOTENCY_RECORDS_SCHEMA_SQL,
    INITIAL_SCHEMA_SQL,
    INVENTORY_CORE_SCHEMA_SQL,
    INVENTORY_PLANNING_SCHEMA_SQL,
    INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL,
    INVENTORY_VALUATION_SCHEMA_SQL,
    JOURNALS_INTERCOMPANY_MONEY_MIGRATION_SQL,
    MANUFACTURING_COST_CONTROL_SCHEMA_SQL,
    MASTER_DATA_SCHEMA_SQL,
    MATCHING_MONEY_MIGRATION_SQL,
    OUTBOX_DELIVERY_MIGRATION_SQL,
    OUTBOX_SCHEMA_SQL,
    PAYABLES_SCHEMA_SQL,
    POLICY_DELEGATIONS_SCHEMA_SQL,
    PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL,
    RECEIVABLES_SCHEMA_SQL,
    RETAIL_SETTLEMENT_SCHEMA_SQL,
    WORKFLOW_STATE_MACHINE_SCHEMA_SQL,
    WRITEBACK_APPROVAL_PERMISSION_SQL,
    WRITEBACK_COMPENSATION_PERMISSION_SQL,
    WRITEBACK_DISPATCH_PERMISSION_SQL,
    WRITEBACK_INTENTS_SCHEMA_SQL,
    WRITEBACK_PROPOSAL_IDENTITY_MIGRATION_SQL,
    WRITEBACK_RECONCILIATION_PERMISSION_SQL,
    WRITEBACK_RECOVERY_OBSERVATIONS_SCHEMA_SQL,
)
from reconforge.infrastructure.finance_policy_schema import SQLITE_FINANCE_POLICY_MIGRATION_SQL
from reconforge.infrastructure.notification_inbox_schema import SQLITE_NOTIFICATION_INBOX_SQL
from reconforge.infrastructure.receivables_policy_schema import SQLITE_RECEIVABLES_POLICY_MIGRATION_SQL
from reconforge.infrastructure.sqlite_finance_posting_schema import SQLITE_FINANCE_POSTING_MIGRATION_SQL
from reconforge.infrastructure.sqlite_inventory_receipt_posting_schema import (
    SQLITE_INVENTORY_RECEIPT_MIGRATION_SQL,
    atomic_receipt_upgrade,
)


@dataclass(frozen=True)
class Migration:
    """One local SQLite schema migration."""

    version: int
    name: str
    sql: str


@dataclass(frozen=True)
class MigrationStatus:
    """Result from applying migrations."""

    path: Path
    applied_versions: list[int]
    current_version: int
    latest_version: int


@dataclass(frozen=True)
class DatabaseStatus:
    """Current local database schema state."""

    path: Path
    current_version: int
    latest_version: int
    applied_versions: list[int]
    pending_versions: list[int]


MIGRATIONS = [
    Migration(version=1, name="enterprise_domain_and_audit_foundation", sql=INITIAL_SCHEMA_SQL),
    Migration(version=2, name="local_users_rbac_foundation", sql=AUTH_RBAC_SCHEMA_SQL),
    Migration(version=3, name="workflow_state_machine_foundation", sql=WORKFLOW_STATE_MACHINE_SCHEMA_SQL),
    Migration(version=4, name="local_api_sessions_foundation", sql=API_SESSIONS_SCHEMA_SQL),
    Migration(version=5, name="db_import_export_bridge", sql=DB_BRIDGE_SCHEMA_SQL),
    Migration(version=6, name="finance_platform_workflow_foundations", sql=FINANCE_PLATFORM_SCHEMA_SQL),
    Migration(version=7, name="organization_master_data_foundation", sql=MASTER_DATA_SCHEMA_SQL),
    Migration(version=8, name="finance_core_ledger_control_foundation", sql=FINANCE_CORE_SCHEMA_SQL),
    Migration(version=9, name="inventory_core_movement_foundation", sql=INVENTORY_CORE_SCHEMA_SQL),
    Migration(version=10, name="inventory_count_and_reorder_foundation", sql=INVENTORY_PLANNING_SCHEMA_SQL),
    Migration(version=11, name="inventory_fifo_valuation_foundation", sql=INVENTORY_VALUATION_SCHEMA_SQL),
    Migration(
        version=12,
        name="inventory_fifo_valuation_reversal_foundation",
        sql=INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL,
    ),
    Migration(version=13, name="transactional_outbox_foundation", sql=OUTBOX_SCHEMA_SQL),
    Migration(version=14, name="transactional_outbox_delivery_state", sql=OUTBOX_DELIVERY_MIGRATION_SQL),
    Migration(version=15, name="accounts_payable_three_way_match_foundation", sql=PAYABLES_SCHEMA_SQL),
    Migration(
        version=16, name="account_reconciliation_decimal_money_columns", sql=ACCOUNT_RECONCILIATION_MONEY_MIGRATION_SQL
    ),
    Migration(
        version=17, name="journal_intercompany_decimal_money_columns", sql=JOURNALS_INTERCOMPANY_MONEY_MIGRATION_SQL
    ),
    Migration(version=18, name="matching_decimal_money_columns", sql=MATCHING_MONEY_MIGRATION_SQL),
    Migration(version=19, name="evidence_object_storage_references", sql=EVIDENCE_OBJECT_STORAGE_MIGRATION_SQL),
    Migration(version=20, name="accounts_receivable_credit_control_foundation", sql=RECEIVABLES_SCHEMA_SQL),
    Migration(version=21, name="durable_job_state_machine_foundation", sql=DURABLE_JOBS_SCHEMA_SQL),
    Migration(version=22, name="durable_job_worker_leases", sql=DURABLE_JOB_LEASES_SCHEMA_SQL),
    Migration(version=23, name="durable_job_partition_effects", sql=DURABLE_JOB_EFFECTS_SCHEMA_SQL),
    Migration(version=24, name="generic_idempotency_service", sql=IDEMPOTENCY_RECORDS_SCHEMA_SQL),
    Migration(version=25, name="consolidation_close_lifecycle", sql=CONSOLIDATION_CLOSE_SCHEMA_SQL),
    Migration(version=26, name="consolidation_ownership_masters", sql=CONSOLIDATION_OWNERSHIP_SCHEMA_SQL),
    Migration(version=27, name="policy_delegation_administration", sql=POLICY_DELEGATIONS_SCHEMA_SQL),
    Migration(version=28, name="connector_writeback_intents", sql=WRITEBACK_INTENTS_SCHEMA_SQL),
    Migration(version=29, name="connector_writeback_approval_permission", sql=WRITEBACK_APPROVAL_PERMISSION_SQL),
    Migration(version=30, name="connector_writeback_reconciliation_permission", sql=WRITEBACK_RECONCILIATION_PERMISSION_SQL),
    Migration(version=31, name="connector_writeback_dispatch_permission", sql=WRITEBACK_DISPATCH_PERMISSION_SQL),
    Migration(version=32, name="connector_writeback_compensation_permission", sql=WRITEBACK_COMPENSATION_PERMISSION_SQL),
    Migration(version=33, name="durable_job_organization_scope", sql=DURABLE_JOB_ORGANIZATION_MIGRATION_SQL),
    Migration(
        version=34,
        name="durable_job_scheduler_cursor_coordination",
        sql=DURABLE_JOB_SCHEDULER_CURSOR_MIGRATION_SQL,
    ),
    Migration(version=35, name="retail_settlement_persistence", sql=RETAIL_SETTLEMENT_SCHEMA_SQL),
    Migration(version=36, name="professional_invoice_payment_persistence", sql=PROFESSIONAL_INVOICE_PAYMENT_SCHEMA_SQL),
    Migration(version=37, name="certification_evidence_binding", sql=CERTIFICATION_EVIDENCE_MIGRATION_SQL),
    Migration(version=38, name="manufacturing_cost_control_persistence", sql=MANUFACTURING_COST_CONTROL_SCHEMA_SQL),
    Migration(version=39, name="bank_statement_control_persistence", sql=BANK_STATEMENT_CONTROL_SCHEMA_SQL),
    Migration(version=40, name="currency_registry_workspace_binding", sql=CURRENCY_REGISTRY_BINDING_SCHEMA_SQL),
    Migration(version=41, name="currency_registry_snapshot_store", sql=CURRENCY_REGISTRY_SNAPSHOT_SCHEMA_SQL),
    Migration(version=42, name="connector_writeback_proposal_identity_guard", sql=WRITEBACK_PROPOSAL_IDENTITY_MIGRATION_SQL),
    Migration(
        version=43,
        name="connector_writeback_recovery_observations",
        sql=WRITEBACK_RECOVERY_OBSERVATIONS_SCHEMA_SQL,
    ),
    Migration(version=44, name="close_period_segregation_of_duties", sql=CLOSE_PERIOD_SOD_MIGRATION_SQL),
    Migration(version=45, name="close_period_lock_evidence_immutability", sql=CLOSE_PERIOD_LOCK_EVIDENCE_MIGRATION_SQL),
    Migration(version=46, name="evidence_retention_governance", sql=EVIDENCE_RETENTION_GOVERNANCE_MIGRATION_SQL),
    Migration(version=47, name="finance_currency_policy", sql=SQLITE_FINANCE_POLICY_MIGRATION_SQL),
    Migration(version=48, name="manual_finance_operational_posting", sql=SQLITE_FINANCE_POSTING_MIGRATION_SQL),
    Migration(version=49, name="receivables_retained_monetary_policy", sql=SQLITE_RECEIVABLES_POLICY_MIGRATION_SQL),
    Migration(version=50, name="reviewed_inventory_receipt_posting", sql=SQLITE_INVENTORY_RECEIPT_MIGRATION_SQL),
    Migration(version=51, name="retained_notification_inbox", sql=SQLITE_NOTIFICATION_INBOX_SQL),
    Migration(version=52, name="governed_budget_control", sql=SQLITE_BUDGET_CONTROL_UPGRADE_SQL),
    Migration(version=53, name="outbox_lease_fencing_and_delivery_evidence", sql=SQLITE_OUTBOX_FENCING_UPGRADE_SQL),
]

_MIGRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(_MIGRATION_TABLE_SQL)
    connection.commit()


def _applied_versions(connection: sqlite3.Connection) -> list[int]:
    rows = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return [int(row["version"]) for row in rows]


def _atomic_schema_upgrade(
    connection: sqlite3.Connection,
    *,
    schema_sql: str,
    version: int,
    name: str,
    applied_at: str,
) -> None:
    """Apply one additive schema slice and its migration record as one SQLite transaction."""

    if not schema_sql.strip() or type(version) is not int or version < 1:
        raise sqlite3.DatabaseError("Invalid atomic migration definition.")
    # executescript opens the explicit transaction before any schema statement.
    # A failed trigger, constraint, or permission insert therefore cannot leave a
    # replay-hostile partial migration behind.
    # The migration registry supplies only committed, closed SQL literals; this
    # helper never receives application or user input. # nosec B608
    script = (
        "BEGIN IMMEDIATE;\n"
        + schema_sql  # nosec B608
        + "\nINSERT INTO schema_migrations (version, name, applied_at) VALUES ("  # nosec B608
        + f"{version}, {name!r}, {applied_at!r});\n"
        + f"PRAGMA user_version = {version};\nCOMMIT;"
    )
    try:
        connection.executescript(script)
    except sqlite3.DatabaseError:
        connection.rollback()
        raise


def run_migrations(db_path: Path | str, *, target_version: int | None = None) -> MigrationStatus:
    """Create or migrate a local database, optionally stopping at a supported version."""

    resolved = resolve_db_path(db_path)
    latest_version = MIGRATIONS[-1].version
    selected_target = latest_version if target_version is None else target_version
    if selected_target < 1 or selected_target > latest_version:
        raise DatabaseError(f"Migration target must be between 1 and {latest_version}.")
    connection = connect(resolved, create_parent=True)
    applied_now: list[int] = []
    try:
        _ensure_migration_table(connection)
        already_applied = set(_applied_versions(connection))
        for migration in MIGRATIONS:
            if migration.version > selected_target:
                continue
            if migration.version in already_applied:
                continue
            if migration.version == 50:
                atomic_receipt_upgrade(connection, schema_sql=migration.sql, version=migration.version,
                                       name=migration.name, applied_at=_utc_now())
                applied_now.append(migration.version)
                continue
            if migration.version in {51, 52}:
                _atomic_schema_upgrade(
                    connection,
                    schema_sql=migration.sql,
                    version=migration.version,
                    name=migration.name,
                    applied_at=_utc_now(),
                )
                applied_now.append(migration.version)
                continue
            if migration.version == 53:
                atomic_outbox_fencing_upgrade(
                    connection,
                    schema_sql=migration.sql,
                    version=migration.version,
                    name=migration.name,
                    applied_at=_utc_now(),
                )
                applied_now.append(migration.version)
                continue
            connection.executescript(migration.sql)
            connection.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, _utc_now()),
            )
            connection.execute(f"PRAGMA user_version = {migration.version}")
            connection.commit()
            applied_now.append(migration.version)
        applied = _applied_versions(connection)
        current_version = max(applied, default=0)
    except sqlite3.DatabaseError as exc:
        connection.rollback()
        raise DatabaseError(
            "Unable to migrate ReconForge database. The file may not be a valid local SQLite database."
        ) from exc
    finally:
        connection.close()

    return MigrationStatus(
        path=resolved,
        applied_versions=applied_now,
        current_version=current_version,
        latest_version=latest_version,
    )


def database_status(db_path: Path | str) -> DatabaseStatus:
    """Return schema status for an existing local ReconForge database."""

    resolved = resolve_db_path(db_path)
    connection = connect(resolved, require_exists=True)
    try:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'",
        ).fetchone()
        applied = _applied_versions(connection) if table_exists else []
        current_version = max(applied, default=0)
    except sqlite3.DatabaseError as exc:
        raise DatabaseError(
            "Unable to read ReconForge database. The file may not be a valid local SQLite database."
        ) from exc
    finally:
        connection.close()

    latest = MIGRATIONS[-1].version
    pending = [migration.version for migration in MIGRATIONS if migration.version not in set(applied)]
    return DatabaseStatus(
        path=resolved,
        current_version=current_version,
        latest_version=latest,
        applied_versions=applied,
        pending_versions=pending,
    )
