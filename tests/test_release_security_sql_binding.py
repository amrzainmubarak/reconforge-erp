"""Adversarial binding regressions for the five reviewed Bandit SQL sites.

PostgreSQL capture tests prove statement/value separation, not database isolation.
The SQLite case executes the hostile filters against a real populated database.
"""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from reconforge.infrastructure.postgres_manufacturing_capacity import PostgresManufacturingCapacityRepository
from reconforge.infrastructure.postgres_mps import PostgresMPSRepository
from reconforge.infrastructure.postgres_reconciliation import PostgresReconciliationRepository
from reconforge.infrastructure.sqlite_manufacturing_capacity import SqliteManufacturingCapacityRepository

HOSTILE = "x' OR 1=1; DROP TABLE capacity_slot_reservations; --"


@pytest.mark.parametrize("active_only", [False, True])
@pytest.mark.parametrize("for_update", [False, True])
def test_postgres_capacity_filters_cannot_become_sql(active_only: bool, for_update: bool) -> None:
    connection = MagicMock()
    connection.transaction.side_effect = nullcontext
    connection.execute.return_value.fetchall.return_value = []
    repo = SimpleNamespace(connection=connection, tenant_id="tenant_a", _scope=lambda: None)
    assert PostgresManufacturingCapacityRepository.list_reservations(
        repo, workspace_id=HOSTILE, workcenter_id=HOSTILE, scheduled_date=HOSTILE,
        active_only=active_only, for_update=for_update,
    ) == []
    sql, params = connection.execute.call_args.args
    assert HOSTILE not in sql
    assert params == ("tenant_a", HOSTILE, HOSTILE, HOSTILE)
    assert sql.count("%s") == len(params)
    assert ("status = 'BOOKED'" in sql) is active_only
    assert sql.strip().endswith("FOR UPDATE") is for_update


@pytest.mark.parametrize("filtered", [False, True])
def test_postgres_mps_filters_cannot_become_sql(filtered: bool) -> None:
    connection = MagicMock()
    connection.transaction.side_effect = nullcontext
    connection.execute.return_value.fetchall.return_value = []
    repo = SimpleNamespace(connection=connection, tenant_id="tenant_a", _scope=lambda: None)
    assert PostgresMPSRepository.list_requisitions(
        repo, workspace_id=HOSTILE, plan_id=HOSTILE if filtered else None,
        item_id=HOSTILE if filtered else None,
    ) == []
    sql, params = connection.execute.call_args.args
    assert HOSTILE not in sql
    expected = ("tenant_a", HOSTILE, HOSTILE, HOSTILE) if filtered else ("tenant_a", HOSTILE)
    assert params == expected
    assert sql.count("%s") == len(params)


def test_sqlite_hostile_filters_do_not_return_another_workspace_or_mutate_schema() -> None:
    import sqlite3

    with sqlite3.connect(":memory:") as connection:
        repo = SqliteManufacturingCapacityRepository(connection)
        connection.execute(
            "INSERT INTO capacity_slot_reservations "
            "(id,workspace_id,reservation_id,workcenter_id,work_order_id,operation_sequence,"
            "scheduled_date,duration_minutes,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            ("row-a", "workspace_a", "reservation_a", "workcenter_a", "order_a", 1, "2026-10-25", 30, "now"),
        )
        assert repo.list_reservations(workspace_id=HOSTILE) == []
        assert repo.list_reservations(workspace_id="workspace_a", workcenter_id=HOSTILE) == []
        assert repo.list_reservations(workspace_id="workspace_a", scheduled_date=HOSTILE) == []
        assert len(repo.list_reservations(workspace_id="workspace_a")) == 1
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


@pytest.mark.parametrize("kind", ["results", "exceptions"])
@pytest.mark.parametrize("batch_size", [1, 3])
def test_reconciliation_batches_bind_hostile_text(kind: str, batch_size: int, monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    connection.execute.return_value.fetchall.return_value = []
    repo = PostgresReconciliationRepository(connection)
    monkeypatch.setattr(PostgresReconciliationRepository, "_run_row", lambda *args, **kwargs: {"status": "Running"})
    if kind == "results":
        connection.execute.return_value.fetchall.side_effect = [[("source-a",)], [], []]
        items = [dict(left_id="source-a", match_type="exact", confidence="1", explanation=HOSTILE,
                      amount_difference="0", status="Matched", lineage={"raw": HOSTILE})] * batch_size
        repo.append_results_batch(tenant_id="tenant_a", run_id="run-a", items=items)
    else:
        items = [dict(exception_type="missing", source_side="Left", source_id=f"source-{index}", title=HOSTILE,
                      explanation=HOSTILE, severity="High", risk_score="1", reason_code="missing",
                      evidence={"raw": HOSTILE}) for index in range(batch_size)]

        def exception_execute(sql: str, params: tuple[object, ...] | None = None) -> MagicMock:
            cursor = MagicMock()
            if "INSERT INTO reconforge.reconciliation_exceptions" in sql:
                assert params is not None
                returned = []
                for index in range(batch_size):
                    value = params[index * 13 : (index + 1) * 13]
                    returned.append((*value[:10], "Open", *value[10:], "synthetic", "synthetic"))
                cursor.fetchall.return_value = returned
            elif "WITH expected" in sql:
                cursor.fetchone.return_value = (False,)
            return cursor

        connection.execute.side_effect = exception_execute
        repo.append_exceptions_batch(tenant_id="tenant_a", run_id="run-a", items=items)
    inserts = [call.args for call in connection.execute.call_args_list
               if call.args[0].lstrip().startswith("INSERT INTO reconforge.reconciliation_")]
    assert len(inserts) == 1
    sql, params = inserts[0]
    assert HOSTILE not in sql
    assert HOSTILE in params
    assert sql.count("%s") == len(params) == 13 * batch_size
    assert "ON CONFLICT (tenant_id, id) DO NOTHING" in sql
    if kind == "exceptions":
        checks = [call.args for call in connection.execute.call_args_list if "WITH expected" in call.args[0]]
        assert len(checks) == 1
        check_sql, check_params = checks[0]
        assert HOSTILE not in check_sql and HOSTILE in check_params
        assert check_sql.count("%s") == len(check_params) == 12 * batch_size + 1
