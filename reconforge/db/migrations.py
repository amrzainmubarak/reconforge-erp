"""SQLite migration runner for local ReconForge databases."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from reconforge.db.connection import DatabaseError, connect, resolve_db_path
from reconforge.db.schema import (
    ACCOUNT_RECONCILIATION_MONEY_MIGRATION_SQL,
    API_SESSIONS_SCHEMA_SQL,
    AUTH_RBAC_SCHEMA_SQL,
    CONSOLIDATION_CLOSE_SCHEMA_SQL,
    DB_BRIDGE_SCHEMA_SQL,
    DURABLE_JOB_EFFECTS_SCHEMA_SQL,
    DURABLE_JOB_LEASES_SCHEMA_SQL,
    DURABLE_JOBS_SCHEMA_SQL,
    EVIDENCE_OBJECT_STORAGE_MIGRATION_SQL,
    FINANCE_CORE_SCHEMA_SQL,
    FINANCE_PLATFORM_SCHEMA_SQL,
    IDEMPOTENCY_RECORDS_SCHEMA_SQL,
    INITIAL_SCHEMA_SQL,
    INVENTORY_CORE_SCHEMA_SQL,
    INVENTORY_PLANNING_SCHEMA_SQL,
    INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL,
    INVENTORY_VALUATION_SCHEMA_SQL,
    JOURNALS_INTERCOMPANY_MONEY_MIGRATION_SQL,
    MASTER_DATA_SCHEMA_SQL,
    MATCHING_MONEY_MIGRATION_SQL,
    OUTBOX_DELIVERY_MIGRATION_SQL,
    OUTBOX_SCHEMA_SQL,
    PAYABLES_SCHEMA_SQL,
    RECEIVABLES_SCHEMA_SQL,
    WORKFLOW_STATE_MACHINE_SCHEMA_SQL,
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
