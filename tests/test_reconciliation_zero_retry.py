"""PostgreSQL NUMERIC scale must not break exact input retries."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_reconciliation import (
    PostgresReconciliationIntegrityError,
    PostgresReconciliationRepository,
    PostgresReconciliationValidationError,
)
from tests.test_postgres_reconciliation import _create_run, _Cursor, _ReconciliationConnection
from tests.test_reconciliation_worker_organization_native import owned_organization_database as _owned_database

owned_organization_database = _owned_database


class _DatabaseScaleConnection(_ReconciliationConnection):
    """Simulate a typed NUMERIC row without imposing string parsing on PostgreSQL."""

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> _Cursor:
        normalized = " ".join(sql.split()).lower()
        if normalized.startswith("select tenant_id, run_id, side, source_id") and "side = %s and source_id = %s" in normalized:
            assert params is not None
            return _Cursor(next((row for row in self.inputs if
                                 (row["tenant_id"], row["run_id"], row["side"], row["source_id"]) == params), None))
        return super().execute(sql, params)


def _register(repository: PostgresReconciliationRepository, amount: object, **changes: object) -> dict[str, Any]:
    data: dict[str, Any] = {
        "tenant_id": "tenant_a", "run_id": "run-a", "side": "Left", "source_id": "source",
        "record_hash": "synthetic-hash", "amount": amount, "currency_code": "USD",
        "attributes": {"source": "synthetic"},
    }
    data.update(changes)
    return repository.register_input(**data)


@pytest.mark.parametrize(("requested", "stored"), [
    ("0", Decimal("0E-18")),
    ("-0", Decimal("-0E-18")),
    ("0.000000000000000001", Decimal("1E-18")),
    ("-0.000000000000000001", Decimal("-1E-18")),
    ("0.0000001", Decimal("1.00000000000E-7")),
    ("1.0", Decimal("1.000000000000000000")),
    ("-99999999999999999999.999999999999999999", Decimal("-99999999999999999999.999999999999999999")),
])
def test_exact_retry_accepts_database_numeric_representation(requested: str, stored: Decimal) -> None:
    connection = _DatabaseScaleConnection()
    repository = PostgresReconciliationRepository(connection)
    _create_run(repository)
    _register(repository, requested)
    connection.inputs[0]["amount_decimal"] = stored
    before = [dict(row) for row in connection.inputs]
    replay = _register(repository, requested)
    assert replay["amount_decimal"] == stored
    assert connection.inputs == before


@pytest.mark.parametrize("amount", ["0E-18", Decimal("0E-18"), "1e-18", "NaN", "Infinity", True, 0.0,
                                    "0.0000000000000000001", "100000000000000000000"])
def test_external_scientific_malformed_and_out_of_range_inputs_remain_rejected(amount: object) -> None:
    connection = _DatabaseScaleConnection()
    repository = PostgresReconciliationRepository(connection)
    _create_run(repository)
    with pytest.raises(PostgresReconciliationValidationError):
        _register(repository, amount)
    assert connection.inputs == []


@pytest.mark.parametrize("stored", [Decimal("NaN"), Decimal("Infinity"), Decimal("0E-19"),
                                    Decimal("1E+100000000"), "0E-18"])
def test_invalid_database_values_fail_closed_without_reformatting_unbounded_values(stored: object) -> None:
    connection = _DatabaseScaleConnection()
    repository = PostgresReconciliationRepository(connection)
    _create_run(repository)
    _register(repository, "0")
    connection.inputs[0]["amount_decimal"] = stored
    with pytest.raises(PostgresReconciliationValidationError):
        _register(repository, "0")


@pytest.mark.parametrize("changes", [
    {"amount": "0.000000000000000001"},
    {"currency_code": "EUR"},
    {"record_hash": "changed-hash"},
    {"attributes": {"source": "changed"}},
])
def test_scaled_zero_retry_rejects_changed_content(changes: dict[str, object]) -> None:
    connection = _DatabaseScaleConnection()
    repository = PostgresReconciliationRepository(connection)
    _create_run(repository)
    _register(repository, "0")
    connection.inputs[0]["amount_decimal"] = Decimal("0E-18")
    before = [dict(row) for row in connection.inputs]
    changed_amount = changes.get("amount", "0")
    changes = {key: value for key, value in changes.items() if key != "amount"}
    with pytest.raises(PostgresReconciliationIntegrityError, match="different content"):
        _register(repository, changed_amount, **changes)
    assert connection.inputs == before


def test_live_postgres_numeric_retries_before_and_after_claim(owned_organization_database: Any) -> None:
    factory = PostgresConnectionFactory(PostgresSettings(dsn=owned_organization_database.app_dsn, require_tls=False))
    boundary = PostgresTenantBoundary(factory)
    with boundary.transaction("org-tenant", workspace_id="workspace", organization_id="org_a",
                              legal_entity_id="entity_a") as connection:
        repository = PostgresReconciliationRepository(connection)
        repository.create_run(tenant_id="org-tenant", run_id="zero-retry", name="Synthetic",
                              left_source="left", right_source="right", algorithm_version="synthetic-v1",
                              rule={}, input_hash="synthetic", actor_id="maker")
        values = (("zero", "0"), ("tiny", "0.000000000000000001"), ("negative", "-0.000000000000000001"))
        for source, amount in values:
            repository.register_input(tenant_id="org-tenant", run_id="zero-retry", side="Left", source_id=source,
                                      record_hash="synthetic-" + source, amount=amount, currency_code="USD")
        before = repository.list_inputs(tenant_id="org-tenant", run_id="zero-retry")
        zero = next(row for row in before if row["source_id"] == "zero")
        assert zero["amount_decimal"] == Decimal("0E-18")
        assert str(zero["amount_decimal"]) == "0E-18"
        for source, amount in values:
            repository.register_input(tenant_id="org-tenant", run_id="zero-retry", side="Left", source_id=source,
                                      record_hash="synthetic-" + source, amount=amount, currency_code="USD")
        assert repository.list_inputs(tenant_id="org-tenant", run_id="zero-retry") == before
        repository.claim_run(tenant_id="org-tenant", run_id="zero-retry", worker_id="synthetic-worker",
                             workspace_id="workspace", organization_id="org_a", legal_entity_id="entity_a")
        for source, amount in values:
            repository.register_input(tenant_id="org-tenant", run_id="zero-retry", side="Left", source_id=source,
                                      record_hash="synthetic-" + source, amount=amount, currency_code="USD")
        for source, _amount in values:
            repository.append_result(tenant_id="org-tenant", run_id="zero-retry", left_id=source,
                                     match_type="unmatched_left", confidence="0", explanation="Synthetic",
                                     status="Unmatched")
        repository.complete_run(tenant_id="org-tenant", run_id="zero-retry", actor_id="synthetic-worker",
                                worker_id="synthetic-worker")
        for source, amount in values:
            repository.register_input(tenant_id="org-tenant", run_id="zero-retry", side="Left", source_id=source,
                                      record_hash="synthetic-" + source, amount=amount, currency_code="USD")
        with pytest.raises(PostgresReconciliationIntegrityError, match="different content"):
            repository.register_input(tenant_id="org-tenant", run_id="zero-retry", side="Left", source_id="zero",
                                      record_hash="synthetic-zero", amount="0.000000000000000001", currency_code="USD")
        with pytest.raises(PostgresReconciliationValidationError, match="exact decimal"):
            repository.register_input(tenant_id="org-tenant", run_id="zero-retry", side="Left", source_id="zero",
                                      record_hash="synthetic-zero", amount="0E-18", currency_code="USD")
        assert repository.list_inputs(tenant_id="org-tenant", run_id="zero-retry") == before
