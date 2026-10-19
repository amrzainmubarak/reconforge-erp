"""Tests for PostgreSQL Performance Indexes (Migration 0152)."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Migration modules start with digits and alembic/versions has no __init__.py,
# so load dynamically via importlib.util.spec_from_file_location
_file = ROOT / "alembic" / "versions" / "0152_postgres_performance_indexes.py"
_spec = importlib.util.spec_from_file_location("migration_0152", _file)
assert _spec is not None and _spec.loader is not None
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)

revision = _migration.revision
down_revision = _migration.down_revision
UPGRADE_SQL = _migration.UPGRADE_SQL
DOWNGRADE_SQL = _migration.DOWNGRADE_SQL


def test_migration_0152_metadata_and_reversibility() -> None:
    """Assert migration 0152 has valid alembic revision metadata linked to 0151."""
    assert revision == "0152_pg_performance_indexes"
    assert down_revision == "0151_pg_enterprise_erp_v1_tables"
    assert len(revision) <= 32


def test_migration_0152_ast_syntax_and_sqlalchemy_text() -> None:
    """Verify migration 0152 parses cleanly and uses sa.text()."""
    migration_file = ROOT / "alembic" / "versions" / "0152_postgres_performance_indexes.py"
    assert migration_file.exists()
    tree = ast.parse(migration_file.read_text(encoding="utf-8"))
    assert tree is not None


def test_migration_0152_gl_and_audit_indexes_declared() -> None:
    """Verify GL lines, entries, and audit event indexes are declared."""
    # Finance GL lines (tenant_id, account_id)
    assert "idx_finance_lines_tenant_account" in UPGRADE_SQL
    assert "ON reconforge.finance_entry_lines (tenant_id, account_id)" in UPGRADE_SQL

    # Finance entries (tenant_id, posting_date, entry_number)
    assert "idx_finance_entries_tenant_date" in UPGRADE_SQL
    assert "ON reconforge.finance_entries (tenant_id, posting_date, entry_number)" in UPGRADE_SQL

    # Domain audit events object and created_at
    assert "idx_domain_audit_events_object" in UPGRADE_SQL
    assert "ON reconforge.domain_audit_events (tenant_id, object_type, object_id, sequence)" in UPGRADE_SQL
    assert "idx_domain_audit_events_created" in UPGRADE_SQL
    assert "ON reconforge.domain_audit_events (tenant_id, created_at, id)" in UPGRADE_SQL


def test_migration_0152_partial_queue_indexes_declared() -> None:
    """Verify partial indexes on active durable jobs and pending outbox events."""
    assert "idx_durable_jobs_active_queue" in UPGRADE_SQL
    assert "WHERE status IN ('queued', 'running', 'retrying')" in UPGRADE_SQL
    assert "idx_outbox_events_unprocessed" in UPGRADE_SQL
    assert "WHERE status IN ('Pending', 'Claimed')" in UPGRADE_SQL


def test_migration_0152_erp_v1_secondary_indexes_declared() -> None:
    """Verify secondary indexes for Shop Floor, Projects, MPS, and Intercompany."""
    expected_indexes = [
        ("idx_shop_floor_lots_item_status", "reconforge.shop_floor_lots (tenant_id, workspace_id, item_id, status)"),
        ("idx_shop_floor_genealogy_child", "reconforge.shop_floor_lot_genealogy (tenant_id, workspace_id, child_lot_id, parent_lot_id)"),
        ("idx_shop_floor_dispatches_wo", "reconforge.shop_floor_dispatches (tenant_id, workspace_id, work_order_id)"),
        ("idx_shop_floor_steps_wo_seq", "reconforge.shop_floor_steps (tenant_id, workspace_id, work_order_id, operation_sequence)"),
        ("idx_shop_floor_steps_wc_status", "reconforge.shop_floor_steps (tenant_id, workspace_id, work_center_id, status)"),
        ("idx_project_wbs_tasks_project_status", "reconforge.project_wbs_tasks (tenant_id, workspace_id, project_id, status)"),
        ("idx_project_milestones_project_status", "reconforge.project_milestones (tenant_id, workspace_id, project_id, status)"),
        ("idx_project_time_logs_task_date", "reconforge.project_time_logs (tenant_id, workspace_id, project_id, task_id, log_date)"),
        ("idx_mps_requisitions_plan_item", "reconforge.mps_sourcing_requisitions (tenant_id, workspace_id, plan_id, item_id, status)"),
        ("idx_intercompany_pis_rules_entities", "reconforge.intercompany_profit_in_stock_rules (tenant_id, workspace_id, selling_entity, buying_entity)"),
    ]
    for index_name, table_and_columns in expected_indexes:
        assert index_name in UPGRADE_SQL, f"Missing {index_name} in UPGRADE_SQL"
        assert table_and_columns in UPGRADE_SQL, f"Missing {table_and_columns} in UPGRADE_SQL"
        assert f"DROP INDEX IF EXISTS reconforge.{index_name};" in DOWNGRADE_SQL, f"Missing DROP for {index_name}"


def test_migration_0152_downgrade_drops_all_indexes() -> None:
    """Verify downgrade drops every single created index with IF EXISTS."""
    created_indexes = [
        "idx_finance_lines_tenant_account",
        "idx_finance_entries_tenant_date",
        "idx_domain_audit_events_object",
        "idx_domain_audit_events_created",
        "idx_durable_jobs_active_queue",
        "idx_outbox_events_unprocessed",
        "idx_shop_floor_lots_item_status",
        "idx_shop_floor_genealogy_child",
        "idx_shop_floor_dispatches_wo",
        "idx_shop_floor_steps_wo_seq",
        "idx_shop_floor_steps_wc_status",
        "idx_project_wbs_tasks_project_status",
        "idx_project_milestones_project_status",
        "idx_project_time_logs_task_date",
        "idx_mps_requisitions_plan_item",
        "idx_intercompany_pis_rules_entities",
    ]
    assert len(created_indexes) == 16
    for idx in created_indexes:
        assert f"DROP INDEX IF EXISTS reconforge.{idx};" in DOWNGRADE_SQL
