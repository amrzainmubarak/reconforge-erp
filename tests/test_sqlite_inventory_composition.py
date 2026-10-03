"""Real SQLite ownership, late evidence faults and caller-work conservation."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from reconforge import platform
from reconforge.audit import verify_audit_events
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.infrastructure.sqlite_inventory_core import SQLiteInventoryCoreRepository
from reconforge.infrastructure.sqlite_inventory_unit_of_work import SQLiteInventoryUnitOfWork
from reconforge.infrastructure.sqlite_inventory_valuation import SQLiteInventoryValuationRepositoryAdapter
from reconforge.infrastructure.sqlite_inventory_valuation_repository import SQLiteInventoryValuationRepository
from reconforge.platform.common import commit_audited
from tests.test_inventory_valuation import _movement, _seed, _valuation_document

PlatformError = platform.PlatformError


@pytest.fixture
def store(tmp_path: Path):
    path = tmp_path / "composition.db"
    run_migrations(path)
    with closing(connect(path, require_exists=True)) as connection:
        _, _, period = _seed(connection)
        connection.execute("CREATE TABLE composition_probe(value TEXT NOT NULL)")
        connection.commit()
        yield path, connection, period


def counts(connection):
    return tuple(connection.execute(
        "SELECT (SELECT count(*) FROM inventory_movements),"
        "(SELECT count(*) FROM inventory_movement_lines),"
        "(SELECT count(*) FROM inventory_valuation_documents),"
        "(SELECT count(*) FROM inventory_valuation_lines),"
        "(SELECT count(*) FROM inventory_cost_layers),"
        "(SELECT count(*) FROM ledger_entries),"
        "(SELECT count(*) FROM ledger_lines),"
        "(SELECT count(*) FROM audit_events),"
        "(SELECT count(*) FROM outbox_events),"
        "(SELECT count(*) FROM composition_probe)"
    ).fetchone())


def receipt(core, valuation, period, *, number="RCV-BOUND"):
    movement = _movement(core, period, number=number, movement_type="Receipt", movement_date="2026-07-01", quantity="10")
    document = _valuation_document(valuation, movement, number="VAL-" + number, total_cost="120.00")
    return valuation.approve_document(document["id"], reason="Independent synthetic review", actor_label="checker")


def test_explicit_owner_commits_multiple_children_and_all_evidence_once(store):
    path, connection, period = store
    before = counts(connection)
    with SQLiteInventoryUnitOfWork(connection) as owner:
        connection.execute("INSERT INTO composition_probe VALUES('owner work')")
        core, valuation = owner.core(), owner.valuation()
        core.upsert_uom(uom_code="BOX", name="Synthetic box")
        document = receipt(core, valuation, period)
        assert document["status"] == "Approved"
        assert connection.execute("SELECT status FROM ledger_entries").fetchone()[0] == "Draft"
        assert connection.execute("SELECT remaining_quantity_scaled,remaining_value_minor FROM inventory_cost_layers").fetchone()[:] == (10000, 12000)
        assert connection.in_transaction
        with closing(connect(path, require_exists=True)) as observer:
            assert counts(observer) == before
    with closing(connect(path, require_exists=True)) as observer:
        after = counts(observer)
        assert after[:7] == (1, 1, 1, 1, 1, 1, 2)
        assert after[7] > before[7] and after[8] > before[8] and after[9] == 1
        assert verify_audit_events(observer).ok


def test_later_owner_failure_rolls_back_movement_fifo_draft_and_evidence(store):
    path, connection, period = store
    before = counts(connection)
    with pytest.raises(RuntimeError, match="later owner"), SQLiteInventoryUnitOfWork(connection) as owner:
        connection.execute("INSERT INTO composition_probe VALUES('pending')")
        receipt(owner.core(), owner.valuation(), period)
        raise RuntimeError("later owner failure")
    assert not connection.in_transaction
    with closing(connect(path, require_exists=True)) as observer:
        assert counts(observer) == before
        assert verify_audit_events(observer).ok


@pytest.mark.parametrize("table,condition", [
    ("audit_events", "NEW.action='inventory_valuation_approved'"),
    ("outbox_events", "NEW.event_type='inventory.valuation.approved'"),
])
def test_caught_late_evidence_failure_poisoned_owner_cannot_commit_prior_children(store, table, condition):
    path, connection, period = store
    before = counts(connection)
    # Table and predicate are a closed test-owned pair, never external input.
    connection.execute(f"CREATE TRIGGER composition_fault BEFORE INSERT ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT,'synthetic late evidence failure'); END")
    with pytest.raises(PlatformError, match="failed bound operation"), SQLiteInventoryUnitOfWork(connection) as owner:
        connection.execute("INSERT INTO composition_probe VALUES('pending')")
        core, valuation = owner.core(), owner.valuation()
        with pytest.raises(PlatformError):
            receipt(core, valuation, period)
        assert owner.rollback_only and connection.in_transaction
        assert connection.execute("SELECT count(*) FROM composition_probe").fetchone()[0] == 1
        with pytest.raises(PlatformError, match="active inventory unit"):
            core.list_uoms()
        with closing(connect(path, require_exists=True)) as observer:
            assert counts(observer) == before
    with closing(connect(path, require_exists=True)) as observer:
        assert counts(observer) == before
        assert verify_audit_events(observer).ok
    connection.execute("DROP TRIGGER composition_fault")
    with SQLiteInventoryUnitOfWork(connection) as owner:
        receipt(owner.core(), owner.valuation(), period)
    assert connection.execute("SELECT count(*) FROM inventory_cost_layers").fetchone()[0] == 1


def test_failed_validation_before_sql_marks_owner_rollback_only(store):
    _, connection, _ = store
    with pytest.raises(PlatformError, match="failed bound operation"), SQLiteInventoryUnitOfWork(connection) as owner:
        connection.execute("INSERT INTO composition_probe VALUES('pending')")
        with pytest.raises(PlatformError):
            owner.core().upsert_uom(uom_code="BAD", name="Invalid", decimal_places=7)
        assert owner.rollback_only
    assert connection.execute("SELECT count(*) FROM composition_probe").fetchone()[0] == 0


@pytest.mark.parametrize("operation", ["master", "movement", "valuation"])
def test_unbound_write_refuses_to_commit_or_rollback_pending_caller_work(store, operation):
    _, connection, period = store
    core = SQLiteInventoryCoreRepository(connection)
    valuation = SQLiteInventoryValuationRepositoryAdapter(connection)
    connection.execute("INSERT INTO composition_probe VALUES('caller')")
    with pytest.raises(PlatformError, match="explicit inventory unit"):
        if operation == "master":
            core.upsert_uom(uom_code="BOX", name="Box")
        elif operation == "movement":
            core.create_movement(movement_number="RCV", movement_type="Receipt", organization_code="SYN", entity_code="EG01", period_id=period["id"], movement_date="2026-07-01", description="Synthetic", lines=[{"item_code": "MAT-01", "quantity": "1", "to_location": "MAIN/STOCK"}])
        else:
            valuation.create_document(valuation_number="VAL", movement_id="missing", policy_code="FIFO")
    assert connection.in_transaction
    assert connection.execute("SELECT value FROM composition_probe").fetchone()[0] == "caller"
    connection.rollback()


def test_owner_refuses_unrelated_pending_work_and_wrong_or_expired_binding(store):
    path, connection, _ = store
    connection.execute("INSERT INTO composition_probe VALUES('caller')")
    with pytest.raises(PlatformError, match="pending caller work"), SQLiteInventoryUnitOfWork(connection):
        pass
    assert connection.in_transaction
    assert connection.execute("SELECT count(*) FROM composition_probe").fetchone()[0] == 1
    connection.rollback()
    owner = SQLiteInventoryUnitOfWork(connection)
    with pytest.raises(PlatformError, match="active inventory unit"):
        SQLiteInventoryCoreRepository(connection, unit_of_work=owner)
    with owner:
        core = owner.core()
        with closing(connect(path, require_exists=True)) as other, pytest.raises(PlatformError, match="own this connection"):
            SQLiteInventoryCoreRepository(other, unit_of_work=owner)
    with pytest.raises(PlatformError, match="active inventory unit"):
        core.list_uoms()


def test_constructor_reads_workspace_and_master_helpers_do_not_finalize_owner(store):
    path, connection, _ = store
    before = counts(connection)
    with pytest.raises(RuntimeError), SQLiteInventoryUnitOfWork(connection) as owner:
        connection.execute("INSERT INTO composition_probe VALUES('caller')")
        core = owner.core()
        owner.valuation().summary()
        core.upsert_uom(uom_code="BOX", name="Box", workspace="new-owned-workspace")
        assert core.list_uoms(workspace="new-owned-workspace")
        assert connection.in_transaction
        with closing(connect(path, require_exists=True)) as observer:
            assert counts(observer) == before
            assert observer.execute("SELECT count(*) FROM workspaces WHERE name='new-owned-workspace'").fetchone()[0] == 0
        raise RuntimeError("owner rollback")
    assert connection.execute("SELECT count(*) FROM workspaces WHERE name='new-owned-workspace'").fetchone()[0] == 0


def test_bound_valuation_refuses_unbound_custom_persistence_repository(store):
    path, connection, _ = store
    before = counts(connection)
    with pytest.raises(PlatformError, match="failed bound operation"), SQLiteInventoryUnitOfWork(connection) as owner:
        owner.core().upsert_uom(uom_code="BEFORE-REJECT", name="Pending synthetic unit")
        with pytest.raises(PlatformError, match="bound valuation persistence"):
            SQLiteInventoryValuationRepositoryAdapter(connection, repository=SQLiteInventoryValuationRepository(connection), unit_of_work=owner)
        assert owner.rollback_only
        assert connection.in_transaction
        assert connection.execute("SELECT count(*) FROM units_of_measure WHERE uom_code='BEFORE-REJECT'").fetchone()[0] == 1
        with closing(connect(path, require_exists=True)) as observer:
            assert counts(observer) == before
            assert observer.execute("SELECT count(*) FROM units_of_measure WHERE uom_code='BEFORE-REJECT'").fetchone()[0] == 0
    assert not connection.in_transaction
    with closing(connect(path, require_exists=True)) as observer:
        assert counts(observer) == before
        assert observer.execute("SELECT count(*) FROM units_of_measure WHERE uom_code='BEFORE-REJECT'").fetchone()[0] == 0


def test_commit_audited_participant_requires_transaction_and_preserves_caller_rollback(store):
    path, connection, _ = store
    before = counts(connection)
    arguments = {"actor_label": "synthetic", "object_type": "composition", "object_id": "owned", "action": "checked", "emit_outbox": True}
    with pytest.raises(PlatformError, match="active caller transaction"):
        commit_audited(connection, autocommit=False, **arguments)
    connection.execute("INSERT INTO composition_probe VALUES('pending')")
    commit_audited(connection, autocommit=False, **arguments)
    assert connection.in_transaction
    with closing(connect(path, require_exists=True)) as observer:
        assert counts(observer) == before
    connection.rollback()
    assert counts(connection) == before
    connection.execute("INSERT INTO composition_probe VALUES('standalone')")
    commit_audited(connection, **arguments)
    assert not connection.in_transaction
    with closing(connect(path, require_exists=True)) as observer:
        assert counts(observer)[9] == 1


@pytest.mark.parametrize("table,condition", [
    ("audit_events", "NEW.action='inventory_movement_posted'"),
    ("outbox_events", "NEW.event_type='inventory_movement_posted'"),
    ("units_of_measure", "NEW.uom_code='FAIL'"),
])
def test_core_failure_never_rolls_back_caller_before_owner_exit(store, table, condition):
    path, connection, period = store
    before = counts(connection)
    connection.execute(f"CREATE TRIGGER composition_fault BEFORE INSERT ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    with pytest.raises(PlatformError, match="failed bound operation"), SQLiteInventoryUnitOfWork(connection) as owner:
        connection.execute("INSERT INTO composition_probe VALUES('pending')")
        core = owner.core()
        with pytest.raises(PlatformError):
            if table == "units_of_measure":
                core.upsert_uom(uom_code="FAIL", name="Synthetic")
            else:
                _movement(core, period, number="FAIL", movement_type="Receipt", movement_date="2026-07-01", quantity="1")
        assert connection.in_transaction and owner.rollback_only
        assert connection.execute("SELECT value FROM composition_probe").fetchone()[0] == "pending"
    with closing(connect(path, require_exists=True)) as observer:
        assert counts(observer) == before


def test_deferred_commit_failure_rolls_back_all_children(store):
    path, connection, period = store
    connection.execute("CREATE TABLE composition_parent(id INTEGER PRIMARY KEY)")
    connection.execute("CREATE TABLE composition_child(parent_id INTEGER REFERENCES composition_parent(id) DEFERRABLE INITIALLY DEFERRED)")
    before = counts(connection)
    with pytest.raises(sqlite3.IntegrityError), SQLiteInventoryUnitOfWork(connection) as owner:
        receipt(owner.core(), owner.valuation(), period)
        connection.execute("INSERT INTO composition_child VALUES(404)")
    assert not owner.active and not connection.in_transaction
    with closing(connect(path, require_exists=True)) as observer:
        assert counts(observer) == before
        assert observer.execute("SELECT count(*) FROM composition_child").fetchone()[0] == 0


def test_actual_local_user_permission_audit_and_reads_participate(store):
    path, connection, _ = store
    auth = LocalAuthService(connection)
    auth.init_admin(username="composition-admin", password="Synthetic-Password-2026!")
    auth.create_user(username="composition-reader", password="Synthetic-Password-2026!", role="auditor-readonly")
    before = counts(connection)
    with pytest.raises(PlatformError, match="failed bound operation"), SQLiteInventoryUnitOfWork(connection) as owner:
        connection.execute("INSERT INTO composition_probe VALUES('pending')")
        core = owner.core()
        assert core.list_uoms(actor_label="composition-admin")
        core.upsert_uom(uom_code="AUTH", name="Authorized", actor_label="composition-admin")
        owner.valuation().summary(actor_label="composition-admin")
        assert connection.in_transaction
        with closing(connect(path, require_exists=True)) as observer:
            assert counts(observer) == before
        with pytest.raises(PlatformError, match="Permission denied"):
            core.upsert_uom(uom_code="DENIED", name="Forbidden", actor_label="composition-reader")
        assert owner.rollback_only and connection.in_transaction
    with closing(connect(path, require_exists=True)) as observer:
        assert counts(observer) == before
        assert verify_audit_events(observer).ok


def test_unbound_constructor_and_reads_preserve_existing_caller_work(store):
    path, connection, _ = store
    connection.execute("INSERT INTO composition_probe VALUES('pending')")
    assert SQLiteInventoryCoreRepository(connection).list_uoms()
    SQLiteInventoryValuationRepositoryAdapter(connection).summary()
    assert connection.in_transaction
    with closing(connect(path, require_exists=True)) as observer:
        assert observer.execute("SELECT count(*) FROM composition_probe").fetchone()[0] == 0
    connection.rollback()


@pytest.mark.parametrize("table", ["audit_events", "outbox_events"])
def test_append_only_common_failure_does_not_finalize_caller_transaction(store, table):
    path, connection, _ = store
    before = counts(connection)
    connection.execute(f"CREATE TRIGGER composition_fault BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'synthetic evidence failure'); END")
    connection.execute("INSERT INTO composition_probe VALUES('pending')")
    with pytest.raises(PlatformError):
        commit_audited(connection, actor_label="synthetic", object_type="probe", object_id="pending", action="checked", emit_outbox=True, autocommit=False)
    assert connection.in_transaction
    assert connection.execute("SELECT value FROM composition_probe").fetchone()[0] == "pending"
    connection.rollback()
    with closing(connect(path, require_exists=True)) as observer:
        assert counts(observer) == before


def test_public_owner_import_and_factories_work_without_preloaded_platform(store):
    path, _, _ = store
    script = """
from reconforge.infrastructure.sqlite_inventory_unit_of_work import SQLiteInventoryUnitOfWork
from reconforge.db import connect
from contextlib import closing
import sys
with closing(connect(sys.argv[1], require_exists=True)) as connection:
    with SQLiteInventoryUnitOfWork(connection) as owner:
        assert owner.core().list_uoms()
        owner.valuation().summary()
    assert not connection.in_transaction
"""
    completed = subprocess.run([sys.executable, "-c", script, str(path)], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30, check=False)
    assert completed.returncode == 0, completed.stderr
