from __future__ import annotations

import os
import re
from collections.abc import Iterable
from uuid import uuid4

import pytest

from reconforge.application.matching_strategies import MatchingStrategyRequest
from reconforge.infrastructure.grouped_matching_strategy import GroupedSubsetSumStrategy
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_reconciliation import (
    POSTGRES_RECONCILIATION_SCHEMA_SQL,
    PostgresReconciliationBusyError,
    PostgresReconciliationNotFoundError,
    PostgresReconciliationRepository,
)
from reconforge.infrastructure.postgres_reconciliation_checkpoints import (
    POSTGRES_RECONCILIATION_CHECKPOINT_SCHEMA_SQL,
)
from reconforge.workers.postgres_grouped_matching import PostgresGroupedMatchingAdapter
from reconforge.workers.postgres_reconciliation import (
    PostgresReconciliationWorker,
    PostgresReconciliationWorkerSettings,
    ReconciliationExecutionContext,
    ReconciliationExecutionResult,
    ReconciliationPartitionResult,
    _stable_partition_key,
)


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"),
    reason="requires a live PostgreSQL service",
)
def test_live_postgres_grouped_matching_worker_persists_group_lineage_and_is_tenant_scoped() -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("live grouped matching test requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")

    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a = "grouped_live_a"
    tenant_b = "grouped_live_b"
    run_id = "grouped-live-" + uuid4().hex[:16]
    many_run_id = "grouped-live-many-" + uuid4().hex[:16]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            admin.execute(POSTGRES_RECONCILIATION_SCHEMA_SQL)
            admin.execute(POSTGRES_RECONCILIATION_CHECKPOINT_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, reconforge.audit_events, "
                f"reconforge.outbox_events, reconforge.reconciliation_runs, reconforge.reconciliation_inputs, "
                f"reconforge.reconciliation_results, reconforge.reconciliation_exceptions, "
                f"reconforge.reconciliation_execution_checkpoints TO {app_user}"
            )
            admin.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {app_user}")
            for tenant in (tenant_a, tenant_b):
                admin.execute(
                    "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                    (tenant, tenant),
                )

        connection = factory.connect()
        try:
            role = connection.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            ).fetchone()
        finally:
            connection.close()
        if role is None or bool(role[0]) or bool(role[1]):
            pytest.skip("live grouped matching test requires a non-superuser, non-BYPASSRLS application role")

        rule = {
            "partition_fields": ["entity_id"],
            "partition_max_records": 10,
            "grouped_matching_mode": "one-to-many",
            "amount_tolerance": "0",
            "date_window_days": 0,
        }
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresReconciliationRepository(connection)
            repository.create_run(
                tenant_id=tenant_a,
                run_id=run_id,
                name="Live grouped reconciliation",
                left_source="ledger.csv",
                right_source="bank.csv",
                algorithm_version="bounded-grouped-subset-sum@1.0.0",
                rule=rule,
                input_hash="grouped-live-input",
                actor_id="grouped-live-user",
            )
            for side, source_id, amount in (
                ("Left", "L1", "100.00"),
                ("Right", "R1", "40.00"),
                ("Right", "R2", "60.00"),
            ):
                repository.register_input(
                    tenant_id=tenant_a,
                    run_id=run_id,
                    side=side,
                    source_id=source_id,
                    record_hash=f"hash-{source_id}",
                    amount=amount,
                    currency_code="USD",
                    attributes={
                        "date": "2026-08-01",
                        "currency": "USD",
                        "entity_id": "entity-A",
                    },
                )
            many_rule = {
                "partition_fields": ["entity_id"],
                "partition_max_records": 10,
                "grouped_matching_mode": "many-to-many",
                "amount_tolerance": "0",
                "date_window_days": 0,
            }
            repository.create_run(
                tenant_id=tenant_a,
                run_id=many_run_id,
                name="Live true many-to-many reconciliation",
                left_source="ledger-many.csv",
                right_source="bank-many.csv",
                algorithm_version="bounded-grouped-subset-sum@1.0.0",
                rule=many_rule,
                input_hash="grouped-many-live-input",
                actor_id="grouped-live-user",
            )
            for side, source_id, amount in (
                ("Left", "ML1", "30.00"),
                ("Left", "ML2", "70.00"),
                ("Right", "MR1", "25.00"),
                ("Right", "MR2", "75.00"),
            ):
                repository.register_input(
                    tenant_id=tenant_a,
                    run_id=many_run_id,
                    side=side,
                    source_id=source_id,
                    record_hash=f"hash-{source_id}",
                    amount=amount,
                    currency_code="USD",
                    attributes={
                        "date": "2026-08-01",
                        "currency": "USD",
                        "entity_id": "entity-M",
                    },
                )

        worker = PostgresReconciliationWorker(
            factory,
            tenant_supplier=lambda: [tenant_a],
            matcher=PostgresGroupedMatchingAdapter(),
            settings=PostgresReconciliationWorkerSettings(
                worker_id="grouped-live-worker",
                actor_id="grouped-live-worker",
                poll_interval_seconds=0,
            ),
        )
        summary = worker.process_once()
        assert summary.completed == 2
        assert summary.failed == 0

        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresReconciliationRepository(connection)
            metadata = repository.get_run_metadata(tenant_id=tenant_a, run_id=run_id)
            rows = repository.list_results(tenant_id=tenant_a, run_id=run_id)
            checkpoints = repository.list_checkpoints(tenant_id=tenant_a, run_id=run_id)
            assert metadata["execution_status"] == "Complete"
            assert metadata["result_count"] == 2
            assert metadata["matched_count"] == 2
            assert len(checkpoints) == 1
            assert checkpoints[0]["input_count"] == 3
            assert {(row["left_id"], row["right_id"]) for row in rows} == {("L1", "R1"), ("L1", "R2")}
            assert all(row["status"] == "Matched" for row in rows)
            assert all(row["lineage_json"]["strategy_id"] == "bounded-grouped-subset-sum" for row in rows)
            decision_digest = rows[0]["lineage_json"]["decision_digest"]
            many_metadata = repository.get_run_metadata(tenant_id=tenant_a, run_id=many_run_id)
            many_rows = repository.list_results(tenant_id=tenant_a, run_id=many_run_id)
            assert many_metadata["execution_status"] == "Complete"
            assert many_metadata["result_count"] == 4
            assert many_metadata["matched_count"] == 4
            assert {(row["left_id"], row["right_id"]) for row in many_rows} == {
                ("ML1", "MR1"),
                ("ML1", "MR2"),
                ("ML2", "MR1"),
                ("ML2", "MR2"),
            }
            assert all(row["lineage_json"]["mode"] == "many-to-many" for row in many_rows)
            many_decision_digest = many_rows[0]["lineage_json"]["decision_digest"]

        expected = GroupedSubsetSumStrategy().execute(
        MatchingStrategyRequest(
                left_records=({"id": "L1", "amount": "100.00", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-A",))},),
                right_records=(
                    {"id": "R1", "amount": "40.00", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-A",))},
                    {"id": "R2", "amount": "60.00", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-A",))},
                ),
                amount_tolerance="0",
                date_window_days=0,
                mode="one-to-many",
            )
        )
        assert decision_digest == expected.results[0]["decision_digest"]
        many_expected = GroupedSubsetSumStrategy().execute(
            MatchingStrategyRequest(
                left_records=(
                    {"id": "ML1", "amount": "30.00", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-M",))},
                    {"id": "ML2", "amount": "70.00", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-M",))},
                ),
                right_records=(
                    {"id": "MR1", "amount": "25.00", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-M",))},
                    {"id": "MR2", "amount": "75.00", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-M",))},
                ),
                amount_tolerance="0",
                date_window_days=0,
                mode="many-to-many",
            )
        )
        assert many_decision_digest == many_expected.results[0]["decision_digest"]

        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection, pytest.raises(
            PostgresReconciliationNotFoundError
        ):
            PostgresReconciliationRepository(connection).get_run_metadata(tenant_id=tenant_b, run_id=run_id)
    finally:
        admin.close()


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"),
    reason="requires a live PostgreSQL service",
)
def test_live_postgres_grouped_matching_resumes_after_process_crash_without_duplicate_partitions() -> None:
    """Prove an unhandled worker loss resumes only the uncommitted partition."""

    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("live grouped matching crash test requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")

    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_id = "grouped_crash_" + uuid4().hex[:12]
    run_id = "grouped-crash-" + uuid4().hex[:16]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_LEDGER_SCHEMA_SQL)
            admin.execute(POSTGRES_RECONCILIATION_SCHEMA_SQL)
            admin.execute(POSTGRES_RECONCILIATION_CHECKPOINT_SCHEMA_SQL)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON reconforge.tenants, reconforge.audit_events, "
                f"reconforge.outbox_events, reconforge.reconciliation_runs, reconforge.reconciliation_inputs, "
                f"reconforge.reconciliation_results, reconforge.reconciliation_exceptions, "
                f"reconforge.reconciliation_execution_checkpoints TO {app_user}"
            )
            admin.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                (tenant_id, tenant_id),
            )

        connection = factory.connect()
        try:
            role = connection.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            ).fetchone()
        finally:
            connection.close()
        if role is None or bool(role[0]) or bool(role[1]):
            pytest.skip("live grouped matching crash test requires a non-superuser, non-BYPASSRLS role")

        rule = {
            "partition_fields": ["entity_id"],
            "partition_max_records": 10,
            "grouped_matching_mode": "one-to-many",
            "amount_tolerance": "0",
            "date_window_days": 0,
        }
        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            repository = PostgresReconciliationRepository(connection)
            repository.create_run(
                tenant_id=tenant_id,
                run_id=run_id,
                name="Live grouped crash-resume reconciliation",
                left_source="ledger.csv",
                right_source="bank.csv",
                algorithm_version="bounded-grouped-subset-sum@1.0.0",
                rule=rule,
                input_hash="grouped-crash-input",
                actor_id="grouped-crash-user",
            )
            for side, source_id, amount, entity in (
                ("Left", "L-A", "100.00", "entity-A"),
                ("Right", "R-A1", "40.00", "entity-A"),
                ("Right", "R-A2", "60.00", "entity-A"),
                ("Left", "L-B", "10.00", "entity-B"),
                ("Right", "R-B", "10.00", "entity-B"),
            ):
                repository.register_input(
                    tenant_id=tenant_id,
                    run_id=run_id,
                    side=side,
                    source_id=source_id,
                    record_hash=f"hash-{source_id}",
                    amount=amount,
                    currency_code="USD",
                    attributes={
                        "date": "2026-08-01",
                        "currency": "USD",
                        "entity_id": entity,
                    },
                )

        class _SyntheticProcessCrash(BaseException):
            pass

        adapter = PostgresGroupedMatchingAdapter()

        class _CrashAfterFirstPartition:
            def __init__(self) -> None:
                self.crashed = False
                self.seen_by_attempt: list[list[str]] = []

            def iter_partition_results(
                self,
                context: ReconciliationExecutionContext,
                *,
                completed_partition_keys: frozenset[str] = frozenset(),
            ) -> Iterable[ReconciliationPartitionResult]:
                seen: list[str] = []
                self.seen_by_attempt.append(seen)
                for partition in adapter.iter_partition_results(
                    context,
                    completed_partition_keys=completed_partition_keys,
                ):
                    seen.append(partition.partition_key)
                    yield partition
                    if not self.crashed:
                        self.crashed = True
                        raise _SyntheticProcessCrash("synthetic process termination after checkpoint commit")

            def __call__(self, context: ReconciliationExecutionContext) -> ReconciliationExecutionResult:
                return adapter(context)

        matcher = _CrashAfterFirstPartition()
        first_worker = PostgresReconciliationWorker(
            factory,
            tenant_supplier=lambda: [tenant_id],
            matcher=matcher,
            settings=PostgresReconciliationWorkerSettings(
                worker_id="grouped-crash-worker-a",
                actor_id="grouped-crash-worker-a",
                poll_interval_seconds=0,
                lease_seconds=1,
            ),
        )
        with pytest.raises(_SyntheticProcessCrash, match="after checkpoint commit"):
            first_worker.process_run(tenant_id=tenant_id, run_id=run_id)

        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            repository = PostgresReconciliationRepository(connection)
            crashed_metadata = repository.get_run_metadata(tenant_id=tenant_id, run_id=run_id)
            crashed_checkpoints = repository.list_checkpoints(tenant_id=tenant_id, run_id=run_id)
            crashed_results = repository.list_results(tenant_id=tenant_id, run_id=run_id)
            assert crashed_metadata["execution_status"] == "Running"
            assert crashed_metadata["execution_worker_id"] == "grouped-crash-worker-a"
            assert len(crashed_checkpoints) == 1
            assert len(crashed_results) in {1, 2}

        replacement_worker = PostgresReconciliationWorker(
            factory,
            tenant_supplier=lambda: [tenant_id],
            matcher=matcher,
            settings=PostgresReconciliationWorkerSettings(
                worker_id="grouped-crash-worker-b",
                actor_id="grouped-crash-worker-b",
                poll_interval_seconds=0,
                lease_seconds=1,
            ),
        )
        with pytest.raises(PostgresReconciliationBusyError, match="already leased"):
            replacement_worker.process_run(tenant_id=tenant_id, run_id=run_id)

        with admin.transaction():
            admin.execute(
                "UPDATE reconforge.reconciliation_runs "
                "SET execution_lease_until = now() - INTERVAL '1 second' "
                "WHERE tenant_id = %s AND id = %s",
                (tenant_id, run_id),
            )

        resumed = replacement_worker.process_run(tenant_id=tenant_id, run_id=run_id)
        assert resumed.status == "Complete"
        assert resumed.result_count == 3
        assert resumed.exception_count == 0
        assert len(matcher.seen_by_attempt) == 2
        assert all(len(attempt) == 1 for attempt in matcher.seen_by_attempt)
        assert set(matcher.seen_by_attempt[0]).isdisjoint(matcher.seen_by_attempt[1])

        with PostgresTenantBoundary(factory).transaction(tenant_id) as connection:
            repository = PostgresReconciliationRepository(connection)
            metadata = repository.get_run_metadata(tenant_id=tenant_id, run_id=run_id)
            checkpoints = repository.list_checkpoints(tenant_id=tenant_id, run_id=run_id)
            rows = repository.list_results(tenant_id=tenant_id, run_id=run_id)
            assert metadata["execution_status"] == "Complete"
            assert metadata["execution_attempt"] == 2
            assert metadata["execution_worker_id"] is None
            assert len(checkpoints) == 2
            assert len(rows) == 3
            assert len({str(row["id"]) for row in rows}) == 3
            assert {(row["left_id"], row["right_id"]) for row in rows} == {
                ("L-A", "R-A1"),
                ("L-A", "R-A2"),
                ("L-B", "R-B"),
            }
            assert {str(item["worker_id"]) for item in checkpoints} == {
                "grouped-crash-worker-a",
                "grouped-crash-worker-b",
            }
    finally:
        admin.close()
