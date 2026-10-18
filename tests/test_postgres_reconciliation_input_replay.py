"""Canonical input replay preserves exact amounts and every source field."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext
from typing import Any

import pytest

from reconforge.infrastructure.postgres_reconciliation import (
    PostgresReconciliationIntegrityError,
    PostgresReconciliationRepository,
    PostgresReconciliationValidationError,
)


class _ReplayConnection:
    def __init__(self, row: dict[str, Any], *, run: dict[str, Any] | None = None, existing: bool = True, isolation: str = "read committed") -> None:
        self.row = row
        self.run = run or {"id": "run-a", "status": "Running", "execution_status": "Queued", "execution_attempt": 0, "cancel_requested": False}
        self.existing = existing
        self.isolation = isolation
        self.statements: list[str] = []

    def execute(self, sql: str, _parameters: object = None) -> Any:
        self.statements.append(sql)
        if sql == "SHOW transaction_isolation":
            row = (self.isolation,)
        elif "INSERT INTO reconforge.reconciliation_inputs" in sql:
            row = None if self.existing else self.row
        elif "FROM reconforge.reconciliation_runs" in sql:
            row = self.run
        elif "FROM reconforge.reconciliation_inputs" in sql:
            row = self.row if self.existing else None
        else:
            pytest.fail("Unexpected SQL in replay guard")
        return type("Cursor", (), {"fetchone": lambda _self: row})()


def _payload() -> dict[str, Any]:
    return {
        "tenant_id": "tenant-a", "run_id": "run-a", "side": "Left", "source_id": "L-1",
        "record_hash": "unchanged-fingerprint", "amount": "10", "amount_original": "10.00",
        "currency_code": "USD", "date_original": "2000-01-01", "date_value": "2000-01-01",
        "reference_original": "Reference 1", "reference_normalized": "REFERENCE1",
        "attributes": {"nested": {"a": 1, "b": "source"}}, "valid": True, "allowed_uses": 1,
    }


def _stored() -> dict[str, Any]:
    row = _payload()
    row["amount_decimal"] = row.pop("amount")
    row["attributes_json"] = row.pop("attributes")
    row["date_value"] = date(2000, 1, 1)
    row["created_at"] = "2000-01-01T00:00:00Z"
    return row


@pytest.mark.parametrize("amount", ["10", "10.0", "10.000000000000000000"])
def test_input_replay_accepts_equivalent_database_numeric_scales(amount: str) -> None:
    row = {**_stored(), "amount_decimal": Decimal("10.000000000000000000")}
    row["attributes_json"] = '{"nested": {"b": "source", "a": 1}}'
    connection = _ReplayConnection(row)
    result = PostgresReconciliationRepository(connection).register_input(**{**_payload(), "amount": amount})
    assert result["amount_decimal"] == Decimal(10)
    assert not any("UPDATE " in query or "DELETE " in query for query in connection.statements)


def test_input_replay_compares_huge_decimal_values_without_ambient_rounding() -> None:
    value = "99999999999999999999.123456789012345678"
    with localcontext() as context:
        context.prec = 2
        repository = PostgresReconciliationRepository(_ReplayConnection({**_stored(), "amount_decimal": Decimal(value)}))
        repository.register_input(**{**_payload(), "amount": value})
        with pytest.raises(PostgresReconciliationIntegrityError):
            repository.register_input(**{**_payload(), "amount": "99999999999999999999.123456789012345679"})


@pytest.mark.parametrize("changed", [
    {"amount": "10.01"}, {"amount": None}, {"amount_original": "10.0"},
    {"currency_code": "EUR"}, {"date_value": "2000-01-02"}, {"date_original": "01/01/2000"},
    {"reference_original": "different"}, {"reference_normalized": "DIFFERENT"},
    {"attributes": {"nested": {"a": 2, "b": "source"}}},
    {"attributes": {"nested": {"a": True, "b": "source"}}},
    {"valid": False}, {"allowed_uses": 2}, {"record_hash": "changed-fingerprint"},
])
def test_unchanged_fingerprint_cannot_hide_different_canonical_input(changed: dict[str, Any]) -> None:
    repository = PostgresReconciliationRepository(_ReplayConnection(_stored()))
    with pytest.raises(PostgresReconciliationIntegrityError):
        repository.register_input(**{**_payload(), **changed})


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_nonfinite_persisted_replay_amount_is_rejected(value: Decimal) -> None:
    repository = PostgresReconciliationRepository(_ReplayConnection({**_stored(), "amount_decimal": value}))
    with pytest.raises((PostgresReconciliationValidationError, PostgresReconciliationIntegrityError)):
        repository.register_input(**_payload())


def test_missing_amount_replay_preserves_null_and_rejects_zero() -> None:
    repository = PostgresReconciliationRepository(_ReplayConnection({**_stored(), "amount_decimal": None}))
    assert repository.register_input(**{**_payload(), "amount": None})["amount_decimal"] is None
    with pytest.raises(PostgresReconciliationIntegrityError):
        repository.register_input(**{**_payload(), "amount": "0"})


SEALED_RUNS = [
    {"status": "Complete", "execution_status": "Complete", "execution_attempt": 1},
    {"status": "Running", "execution_status": "Running", "execution_attempt": 1},
    {"status": "Running", "execution_status": "Failed", "execution_attempt": 1},
    {"status": "Failed", "execution_status": "Failed", "execution_attempt": 1},
    {"status": "Running", "execution_status": "Cancelled", "execution_attempt": 0},
    {"status": "Running", "execution_status": "Queued", "execution_attempt": 1},
    {"status": "Running", "execution_status": "Queued", "execution_attempt": 0, "cancel_requested": True},
    {"status": "Running", "execution_status": "Pending", "execution_attempt": 0},
]


@pytest.mark.parametrize("run", SEALED_RUNS)
def test_new_input_is_rejected_after_run_leaves_initial_editable_state(run: dict[str, Any]) -> None:
    connection = _ReplayConnection(_stored(), run={"id": "run-a", **run}, existing=False)
    with pytest.raises(PostgresReconciliationIntegrityError, match="sealed"):
        PostgresReconciliationRepository(connection).register_input(**_payload())
    assert not any("INSERT INTO" in query for query in connection.statements)
    assert "FOR UPDATE" in connection.statements[0]


@pytest.mark.parametrize("run", SEALED_RUNS)
def test_exact_replay_of_sealed_input_performs_no_write(run: dict[str, Any]) -> None:
    connection = _ReplayConnection(_stored(), run={"id": "run-a", **run})
    assert PostgresReconciliationRepository(connection).register_input(**_payload())["source_id"] == "L-1"
    assert not any("INSERT INTO" in query or "UPDATE reconforge" in query for query in connection.statements)


def test_initial_queued_run_still_accepts_new_inputs_under_the_run_lock() -> None:
    connection = _ReplayConnection(_stored(), existing=False)
    assert PostgresReconciliationRepository(connection).register_input(**_payload())["source_id"] == "L-1"
    assert "FOR UPDATE" in connection.statements[0]
    assert any("INSERT INTO" in query for query in connection.statements[1:])


@pytest.mark.parametrize("isolation", ["repeatable read", "serializable", "read uncommitted", "unknown"])
def test_snapshot_isolation_cannot_admit_new_input_or_claim(isolation: str) -> None:
    connection = _ReplayConnection(_stored(), existing=False, isolation=isolation)
    repository = PostgresReconciliationRepository(connection)
    with pytest.raises(PostgresReconciliationValidationError, match="READ COMMITTED"):
        repository.register_input(**_payload())
    assert not any("INSERT INTO" in query for query in connection.statements)
    connection.statements.clear()
    with pytest.raises(PostgresReconciliationValidationError, match="READ COMMITTED"):
        repository.claim_run(tenant_id="tenant-a", run_id="run-a", worker_id="worker-a")
    assert connection.statements == ["SHOW transaction_isolation"]


@pytest.mark.parametrize("sealed", [False, True])
def test_snapshot_isolation_exact_replay_is_read_only(sealed: bool) -> None:
    run = {"id": "run-a", **SEALED_RUNS[0]} if sealed else None
    connection = _ReplayConnection(_stored(), run=run, isolation="repeatable read")
    PostgresReconciliationRepository(connection).register_input(**_payload())
    assert not any("INSERT INTO" in query for query in connection.statements)
