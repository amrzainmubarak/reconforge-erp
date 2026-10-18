from __future__ import annotations

import ast
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal, localcontext
from hashlib import sha256
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

import reconforge.db.migration_52_budget_control as migration_52_module
import reconforge.db.migrations as migration_module
from reconforge.audit import verify_audit_events
from reconforge.auth import LocalAuthService
from reconforge.db import connect, run_migrations
from reconforge.db.backup import create_backup, restore_backup
from reconforge.db.exporter import DBBridgeError
from reconforge.db.migration_52_budget_control import SQLITE_BUDGET_CONTROL_UPGRADE_SQL
from reconforge.domain.budget_control import (
    BudgetControlError,
    BudgetDefinition,
    BudgetScope,
    CommitmentAction,
    conservation,
    minor,
)
from reconforge.infrastructure.budget_control_verification import verify_sqlite_budget_storage
from reconforge.infrastructure.sqlite_budget_control import SQLiteBudgetControlRepository
from reconforge.infrastructure.sqlite_budget_control_schema import BUDGET_52_RESTORE_ADMISSION_TRIGGERS
from reconforge.platform.common import ServerPrincipal, server_principal_context
from reconforge.platform.master_data import MasterDataService

PERMISSIONS = frozenset({"budget_control.read", "budget_control.manage", "budget_control.approve"})


@pytest.fixture
def budget_store(tmp_path: Path):
    path = tmp_path / "budget.db"
    run_migrations(path)
    connection = connect(path)
    masters = MasterDataService(connection)
    organization = masters.upsert_organization(organization_code="SYN", name="Synthetic operations")
    entity = masters.upsert_legal_entity(organization_code="SYN", entity_code="EG", name="Synthetic entity", currency_code="EGP")
    period = masters.upsert_period(name="2026-10", start_date="2026-10-01", end_date="2026-10-31")
    auth = LocalAuthService(connection)
    maker = auth.create_user(username="maker", password="Synthetic-Amr-Password-2026!", display_name="Synthetic maker", role="controller")
    checker = auth.create_user(username="checker", password="Synthetic-Amr-Password-2026!", display_name="Synthetic checker", role="controller")
    owner_id = connection.execute("SELECT id FROM roles WHERE name='controller'").fetchone()[0]
    assigned = {
        str(row[0])
        for row in connection.execute("SELECT permission_name FROM role_permissions WHERE role_id=?", (owner_id,))
    }
    assert assigned >= PERMISSIONS
    scope = BudgetScope(str(organization["workspace_id"]), str(organization["id"]), str(entity["id"]))
    principals = [ServerPrincipal(user=user, permissions=PERMISSIONS, step_up_active=True,
        authorized_workspace_ids=frozenset({scope.workspace_id}), authorized_organization_ids=frozenset({scope.organization_id}),
        authorized_legal_entity_ids=frozenset({scope.legal_entity_id})) for user in (maker, checker)]
    yield path, connection, scope, str(period["id"]), principals
    connection.close()


def approved(store, *, amount: int = 10_000, code: str = "OPS"):
    _path, connection, scope, period_id, principals = store
    repo = SQLiteBudgetControlRepository(connection)
    with server_principal_context(principals[0]):
        row = repo.create(scope, BudgetDefinition(code, "Synthetic appropriation", period_id, "EGP", amount), command_id="create-" + code)
        row = repo.transition(scope, row["id"], action="submit", expected_version=1, reason="Synthetic review", command_id="submit-" + code)
    with server_principal_context(principals[1]):
        row = repo.transition(scope, row["id"], action="approve", expected_version=2, reason="Synthetic independent approval", command_id="approve-" + code)
    return repo, row


def action(operation: str, amount: int, source: str = "PO/SYN/1") -> CommitmentAction:
    return CommitmentAction(operation, amount, "2026-10-03", source, "Synthetic budget control")


def test_real_lifecycle_exact_conservation_replay_and_audit(budget_store):
    _path, connection, scope, _period, principals = budget_store
    repo, row = approved(budget_store)
    with server_principal_context(principals[0]):
        reserved = repo.record(scope, row["id"], action("Reserve", 8000), expected_version=3, command_id="reserve")
        assert (reserved["available_minor"], reserved["reserved_minor"], reserved["consumed_minor"]) == ("2000", "8000", "0")
        assert repo.record(scope, row["id"], action("Reserve", 8000), expected_version=3, command_id="reserve") == reserved
        consumed = repo.record(scope, row["id"], action("Consume", 3000), expected_version=4, command_id="consume", commitment_id=reserved["commitment_id"])
        released = repo.record(scope, row["id"], action("Release", 5000), expected_version=5, command_id="release", commitment_id=reserved["commitment_id"])
        assert (consumed["reserved_minor"], consumed["consumed_minor"], released["available_minor"], released["remaining_minor"]) == ("5000", "3000", "7000", "0")
        assert len(repo.get(scope, row["id"])["events"]) == 3
    verify_sqlite_budget_storage(connection)
    assert verify_audit_events(connection).ok
    assert connection.execute("SELECT count(*) FROM budget_commands").fetchone()[0] == 6


def test_registered_budget_migration_rolls_back_all_schema_and_permission_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed migration 52 cannot leave an operationally ambiguous budget schema."""

    path = tmp_path / "atomic-budget.db"
    run_migrations(path, target_version=51)
    migrations = migration_module.MIGRATIONS
    broken = migration_module.Migration(
        version=52,
        name="governed_budget_control",
        sql=SQLITE_BUDGET_CONTROL_UPGRADE_SQL + "\nCREATE TABLE budget_envelopes (id TEXT);",
    )
    monkeypatch.setattr(migration_module, "MIGRATIONS", (*migrations[:51], broken))

    with pytest.raises(migration_module.DatabaseError):
        migration_module.run_migrations(path)

    connection = connect(path, require_exists=True)
    try:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='budget_envelopes'"
        ).fetchone() is None
        assert connection.execute("SELECT version FROM schema_migrations WHERE version=52").fetchone() is None
        assert connection.execute("SELECT 1 FROM permissions WHERE name='budget_control.manage'").fetchone() is None
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 51
    finally:
        connection.close()


def test_registered_budget_migration_schema_is_frozen_as_a_literal() -> None:
    """Fresh local installs cannot read mutable runtime schema text for v52."""

    source = Path(migration_52_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignments = {
        target.id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    literal = assignments.get("SQLITE_BUDGET_CONTROL_UPGRADE_SQL")
    assert isinstance(literal, ast.Constant) and isinstance(literal.value, str)
    assert sha256(SQLITE_BUDGET_CONTROL_UPGRADE_SQL.encode("utf-8")).hexdigest() == (
        "a4d2e02d07d81f983eef9b24952565fbe1885cd79c120d7a2b920b892cb6284e"
    )
    assert "sqlite_budget_control_schema" not in source
    assert migration_module.MIGRATIONS[51] == migration_module.Migration(
        version=52,
        name="governed_budget_control",
        sql=SQLITE_BUDGET_CONTROL_UPGRADE_SQL,
    )


def test_backup_restore_retains_and_reverifies_budget_commitment_evidence(budget_store, tmp_path: Path) -> None:
    path, connection, scope, _period, principals = budget_store
    repository, envelope = approved(budget_store)
    with server_principal_context(principals[0]):
        reserved = repository.record(
            scope,
            envelope["id"],
            action("Reserve", 8_000),
            expected_version=3,
            command_id="backup-reserve",
        )
        repository.record(
            scope,
            envelope["id"],
            action("Consume", 3_000),
            expected_version=4,
            command_id="backup-consume",
            commitment_id=reserved["commitment_id"],
        )
    verify_sqlite_budget_storage(connection)

    backup = create_backup(path, tmp_path / "budget-backup")
    payload = json.loads(backup.backup_path.read_text(encoding="utf-8"))
    assert len(payload["tables"]["budget_envelopes"]) == 1
    assert len(payload["tables"]["budget_commitment_events"]) == 2
    assert len(payload["tables"]["budget_commands"]) == 5

    restored_path = tmp_path / "budget-restored.db"
    restore_backup(restored_path, backup.backup_path)
    with connect(restored_path, require_exists=True) as restored:
        assert set(BUDGET_52_RESTORE_ADMISSION_TRIGGERS) <= {
            str(row["name"])
            for row in restored.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()
        }
        verify_sqlite_budget_storage(restored)
        with server_principal_context(principals[0]):
            recovered = SQLiteBudgetControlRepository(restored).get(scope, envelope["id"])
        assert (recovered["reserved_minor"], recovered["consumed_minor"], recovered["available_minor"]) == (
            "5000",
            "3000",
            "2000",
        )


def test_backup_refuses_tampered_budget_evidence(budget_store, tmp_path: Path) -> None:
    path, connection, scope, _period, principals = budget_store
    _repository, envelope = approved(budget_store)
    connection.execute("DROP TRIGGER budget_command_update_guard")
    connection.execute(
        "UPDATE budget_commands SET result_digest=? WHERE budget_id=?",
        ("0" * 64, envelope["id"]),
    )
    connection.commit()

    with pytest.raises(DBBridgeError, match="Unable to create local DB backup"):
        create_backup(path, tmp_path / "tampered-budget-backup")


def test_stable_identity_self_approval_version_scope_and_capacity(budget_store):
    _path, connection, scope, period_id, principals = budget_store
    repo = SQLiteBudgetControlRepository(connection)
    with server_principal_context(principals[0]):
        row = repo.create(scope, BudgetDefinition("OPS", "Synthetic", period_id, "EGP", 100), command_id="draft")
        repo.transition(scope, row["id"], action="submit", expected_version=1, reason="Review", command_id="submit")
        with pytest.raises(BudgetControlError, match="Independent"):
            repo.transition(scope, row["id"], action="approve", expected_version=2, reason="Self", command_id="self")
    with server_principal_context(principals[1]):
        row = repo.transition(scope, row["id"], action="approve", expected_version=2, reason="Independent", command_id="approve")
        for arguments in ((action("Reserve", 101), 3), (action("Reserve", 50), 2), (replace(action("Reserve", 50), operation_date="2026-11-01"), 3)):
            with pytest.raises(BudgetControlError):
                repo.record(scope, row["id"], arguments[0], expected_version=arguments[1], command_id="bad-" + str(arguments))
        with pytest.raises(BudgetControlError, match="authority"):
            repo.get(replace(scope, workspace_id="other"), row["id"])
    assert connection.execute("SELECT count(*) FROM budget_commitment_events").fetchone()[0] == 0


def test_exact_replay_revalidates_persisted_role_and_enabled_identity(budget_store):
    _path, connection, scope, _period, principals = budget_store
    repo, row = approved(budget_store)
    with server_principal_context(principals[0]):
        repo.record(scope, row["id"], action("Reserve", 5000), expected_version=3, command_id="reserve")
        connection.execute("DELETE FROM user_roles WHERE user_id=?", (principals[0].user.id,))
        connection.commit()
        with pytest.raises(BudgetControlError, match="persisted identity"):
            repo.record(scope, row["id"], action("Reserve", 5000), expected_version=3, command_id="reserve")
    assert connection.execute("SELECT count(*) FROM budget_commitment_events").fetchone()[0] == 1


def test_parallel_self_approval_cannot_displace_independent_reviewer(budget_store):
    path, connection, scope, period_id, principals = budget_store
    repository = SQLiteBudgetControlRepository(connection)
    with server_principal_context(principals[0]):
        row = repository.create(
            scope,
            BudgetDefinition("RACE", "Synthetic approval race", period_id, "EGP", 100),
            command_id="race-draft",
        )
        repository.transition(
            scope,
            row["id"],
            action="submit",
            expected_version=1,
            reason="Synthetic review",
            command_id="race-submit",
        )

    def approve(index: int) -> bool:
        with connect(path) as contender, server_principal_context(principals[index]):
            try:
                SQLiteBudgetControlRepository(contender).transition(
                    scope,
                    row["id"],
                    action="approve",
                    expected_version=2,
                    reason="Concurrent independent review",
                    command_id=f"race-approve-{index}",
                )
                return True
            except BudgetControlError:
                return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(approve, (0, 1)))
    assert outcomes == (False, True)
    with server_principal_context(principals[1]):
        retained = repository.get(scope, row["id"])
    assert retained["status"] == "Approved"
    assert retained["approved_by"] == principals[1].user.id


def test_replay_revalidates_current_immutable_ledger_before_cached_response(budget_store):
    _path, connection, scope, _period, principals = budget_store
    repository, row = approved(budget_store)
    with server_principal_context(principals[0]):
        reserved = repository.record(
            scope,
            row["id"],
            action("Reserve", 5_000),
            expected_version=3,
            command_id="reserve",
        )
        repository.record(
            scope,
            row["id"],
            action("Release", 1_000),
            expected_version=4,
            command_id="release",
            commitment_id=reserved["commitment_id"],
        )
        # The original command still returns its immutable acknowledgement only
        # after the progressed authoritative aggregate verifies.
        assert repository.record(
            scope,
            row["id"],
            action("Reserve", 5_000),
            expected_version=3,
            command_id="reserve",
        ) == reserved

    connection.execute("DROP TRIGGER budget_envelope_update_guard")
    connection.execute("UPDATE budget_envelopes SET reserved_minor=1,row_version=6 WHERE id=?", (row["id"],))
    connection.commit()
    with server_principal_context(principals[0]), pytest.raises(BudgetControlError, match="independent immutable ledger"):
        repository.record(
            scope,
            row["id"],
            action("Reserve", 5_000),
            expected_version=3,
            command_id="reserve",
        )


def test_audit_failure_rolls_back_whole_effect_and_command(budget_store, monkeypatch):
    _path, connection, scope, _period, principals = budget_store
    repo, row = approved(budget_store)
    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic audit failure")
    monkeypatch.setattr("reconforge.infrastructure.sqlite_budget_control.append_audit_event", fail)
    with server_principal_context(principals[0]), pytest.raises(RuntimeError, match="audit failure"):
        repo.record(scope, row["id"], action("Reserve", 5000), expected_version=3, command_id="reserve")
    assert connection.execute("SELECT row_version,reserved_minor FROM budget_envelopes").fetchone()[:] == (3, 0)
    assert connection.execute("SELECT count(*) FROM budget_commands").fetchone()[0] == 3


def test_real_parallel_connections_cannot_oversubscribe(budget_store):
    path, connection, scope, _period, principals = budget_store
    _repo, row = approved(budget_store, amount=100)
    def reserve(index):
        with connect(path) as contender, server_principal_context(principals[0]):
            try:
                SQLiteBudgetControlRepository(contender).record(scope, row["id"], action("Reserve", 70, f"PO/{index}"), expected_version=3, command_id=f"reserve-{index}")
                return True
            except BudgetControlError:
                return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(8))) == 1
    verify_sqlite_budget_storage(connection)
    assert connection.execute("SELECT reserved_minor FROM budget_envelopes").fetchone()[0] == 70


def test_raw_sql_immutability_and_independent_tamper_detection(budget_store):
    _path, connection, scope, _period, principals = budget_store
    repo, row = approved(budget_store)
    with server_principal_context(principals[0]):
        repo.record(scope, row["id"], action("Reserve", 5000), expected_version=3, command_id="reserve")
    for statement in ("UPDATE budget_envelopes SET limit_minor=20000", "UPDATE budget_envelopes SET reserved_minor=0,row_version=row_version+1", "DELETE FROM budget_commitment_events", "DELETE FROM budget_commands"):
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(statement)
        connection.rollback()
    connection.execute("DROP TRIGGER budget_envelope_update_guard")
    connection.execute("UPDATE budget_envelopes SET reserved_minor=1")
    connection.commit()
    with pytest.raises(BudgetControlError, match="independent immutable ledger"):
        verify_sqlite_budget_storage(connection)
    with server_principal_context(principals[0]), pytest.raises(BudgetControlError):
        repo.get(scope, row["id"])


def test_storage_identifier_whitelist_rejects_dynamic_sql_targets(budget_store):
    _path, connection, _scope, _period, _principals = budget_store
    repository = SQLiteBudgetControlRepository(connection)
    with pytest.raises(BudgetControlError, match="storage target"):
        repository._insert("budget_envelopes; DROP TABLE users", {})
    with pytest.raises(BudgetControlError, match="storage columns"):
        repository._insert("budget_envelopes", {"untrusted_column": "synthetic"})


@pytest.mark.parametrize("value", [0, -1, True, 1.5, Decimal("1"), "", "01", "1.0", "NaN", "Infinity", "1e3", 9_000_000_000_000_000_001])
def test_closed_money_boundary(value):
    with pytest.raises(BudgetControlError):
        minor(value)


@given(st.integers(1, 9_000_000_000_000_000_000), st.integers(0, 100), st.integers(0, 100))
def test_conservation_property_without_decimal_context_rounding(limit, left, right):
    reserved = limit * left // 100
    consumed = (limit - reserved) * right // 100
    with localcontext() as context:
        context.prec = 1
        assert conservation(limit, reserved, consumed) + reserved + consumed == limit


def test_huge_commitment_reuse_does_not_overflow_historical_aggregation(budget_store):
    _path, connection, scope, _period, principals = budget_store
    repo, row = approved(budget_store, amount=9_000_000_000_000_000_000)
    with server_principal_context(principals[0]):
        for index in range(3):
            row = repo.record(scope, row["id"], action("Reserve", 9_000_000_000_000_000_000, f"SYN/{index}"), expected_version=row["row_version"], command_id=f"r-{index}")
            row = repo.record(scope, row["id"], action("Release", 9_000_000_000_000_000_000, f"SYN/{index}"), expected_version=row["row_version"], command_id=f"l-{index}", commitment_id=row["commitment_id"])
        assert row["available_minor"] == "9000000000000000000"
    verify_sqlite_budget_storage(connection)
