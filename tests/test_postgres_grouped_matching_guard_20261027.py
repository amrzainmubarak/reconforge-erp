"""Native worker refuses inexact groups before persisting any partition."""

from __future__ import annotations

import os
from decimal import localcontext

import pytest

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_reconciliation import PostgresReconciliationRepository
from reconforge.workers.postgres_grouped_matching import PostgresGroupedMatchingAdapter
from reconforge.workers.postgres_reconciliation import (
    PostgresReconciliationWorker,
    PostgresReconciliationWorkerSettings,
)
from tests.test_postgres_inventory_receipt_posting import receipt_database  # noqa: F401

pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"),
    reason="Requires PostgreSQL; AMR-EXACT-GROUPED-MATCHING-20261027; review 2026-11-27",
)


def test_grouped_inexact_failure_retains_inputs_and_persists_no_partial_results(
    receipt_database: tuple[str, str],  # noqa: F811
) -> None:
    import psycopg

    admin_dsn, app_dsn = receipt_database
    tenant = "guarded-grouped"
    run_id = "guarded-grouped-run"
    with psycopg.connect(admin_dsn) as admin:
        admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s)", (tenant, "Synthetic grouped tenant"))
    factory = PostgresConnectionFactory(PostgresSettings(dsn=app_dsn, require_tls=False))
    with PostgresTenantBoundary(factory).transaction(tenant) as connection:
        repository = PostgresReconciliationRepository(connection)
        repository.create_run(
            tenant_id=tenant,
            run_id=run_id,
            name="Inexact refusal",
            left_source="left.csv",
            right_source="right.csv",
            algorithm_version="bounded-grouped-subset-sum@1.0.0",
            rule={
                "partition_fields": ["entity_id"],
                "partition_max_records": 10,
                "grouped_matching_mode": "portfolio",
                "amount_tolerance": "0",
                "date_window_days": 0,
            },
            input_hash="synthetic-grouped",
            actor_id="synthetic-user",
        )
        for side, source, amount, entity in (
            ("Left", "good-L", "10.00", "A"),
            ("Right", "good-R", "10.00", "A"),
            ("Left", "bad-L", "1234.56", "Z"),
            ("Right", "bad-R", "1234.57", "Z"),
        ):
            repository.register_input(
                tenant_id=tenant,
                run_id=run_id,
                side=side,
                source_id=source,
                record_hash="hash-" + source,
                amount=amount,
                currency_code="USD",
                attributes={"date": "2026-08-01", "currency": "USD", "entity_id": entity},
            )
        before = {
            (row["side"], row["source_id"], row["amount_decimal"])
            for row in repository.list_inputs(tenant_id=tenant, run_id=run_id)
        }
    worker = PostgresReconciliationWorker(
        factory,
        tenant_supplier=lambda: [tenant],
        matcher=PostgresGroupedMatchingAdapter(),
        settings=PostgresReconciliationWorkerSettings(
            worker_id="guarded-worker",
            actor_id="guarded-worker",
            poll_interval_seconds=0,
            allow_unbound_hosted_policy=True,
        ),
    )
    with localcontext() as context:
        context.prec = 3
        outcome = worker.process_run(tenant_id=tenant, run_id=run_id)
    assert outcome.status == "Failed"
    with PostgresTenantBoundary(factory).transaction(tenant) as connection:
        repository = PostgresReconciliationRepository(connection)
        after = {
            (row["side"], row["source_id"], row["amount_decimal"])
            for row in repository.list_inputs(tenant_id=tenant, run_id=run_id)
        }
        assert before == after
        assert len(after) == 4
        assert repository.list_results(tenant_id=tenant, run_id=run_id) == []
        assert repository.list_checkpoints(tenant_id=tenant, run_id=run_id) == []
        metadata = repository.get_run_metadata(tenant_id=tenant, run_id=run_id)
        assert metadata["execution_status"] == "Failed"
        assert "exact arithmetic" in str(metadata.get("execution_error", ""))
