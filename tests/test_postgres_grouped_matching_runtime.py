from __future__ import annotations

import os
import re
from collections.abc import Iterable
from uuid import uuid4

import pytest

from reconforge.application.matching_strategies import MatchingStrategyRequest
from reconforge.infrastructure.carry_forward_strategy import CarryForwardFifoStrategy
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
from reconforge.infrastructure.reversal_matching_strategy import ReversalPairingStrategy
from reconforge.workers.postgres_grouped_matching import PostgresGroupedMatchingAdapter
from reconforge.workers.postgres_reconciliation import (
    PostgresReconciliationWorker,
    PostgresReconciliationWorkerSettings,
    ReconciliationExecutionContext,
    ReconciliationExecutionResult,
    ReconciliationPartitionResult,
    _stable_partition_key,
)
from reconforge.workers.postgres_sequential_matching import PostgresSequentialMatchingAdapter


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
    fx_run_id = "grouped-live-fx-" + uuid4().hex[:16]
    portfolio_run_id = "grouped-live-portfolio-" + uuid4().hex[:16]
    carry_run_id = "sequential-live-carry-" + uuid4().hex[:16]
    reversal_run_id = "sequential-live-reversal-" + uuid4().hex[:16]
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
                    allowed_uses=2,
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
                    allowed_uses=2,
                )
            fx_rule = {
                "partition_fields": ["entity_id"],
                "partition_max_records": 10,
                "grouped_matching_mode": "many-to-one",
                "amount_tolerance": "0",
                "date_window_days": 0,
                "target_currency": "USD",
                "fx_rates": [
                    {
                        "base_currency": "EUR",
                        "quote_currency": "USD",
                        "rate": "0.5",
                        "rate_type": "spot",
                        "source": "synthetic-fx",
                        "effective_at": "2026-08-01",
                    }
                ],
            }
            repository.create_run(
                tenant_id=tenant_a,
                run_id=fx_run_id,
                name="Live FX-aware grouped reconciliation",
                left_source="ledger-fx.csv",
                right_source="bank-fx.csv",
                algorithm_version="bounded-grouped-subset-sum@1.0.0",
                rule=fx_rule,
                input_hash="grouped-fx-live-input",
                actor_id="grouped-live-user",
            )
            for side, source_id, amount, currency in (
                ("Left", "FXL1", "60.00", "USD"),
                ("Left", "FXL2", "40.00", "USD"),
                ("Right", "FXR1", "200.00", "EUR"),
            ):
                repository.register_input(
                    tenant_id=tenant_a,
                    run_id=fx_run_id,
                    side=side,
                    source_id=source_id,
                    record_hash=f"hash-{source_id}",
                    amount=amount,
                    currency_code=currency,
                    attributes={
                        "date": "2026-08-01",
                        "currency": currency,
                        "entity_id": "entity-FX",
                    },
                    allowed_uses=2,
                )
            portfolio_rule = {
                "partition_fields": ["entity_id"],
                "partition_max_records": 10,
                "grouped_matching_mode": "portfolio",
                "amount_tolerance": "0",
                "date_window_days": 0,
                "netting_mode": "net",
                "left_fee_field": "fee",
                "right_fee_field": "fee",
                "allow_partial_settlement": True,
            }
            repository.create_run(
                tenant_id=tenant_a,
                run_id=portfolio_run_id,
                name="Live portfolio partial settlement reconciliation",
                left_source="ledger-portfolio.csv",
                right_source="bank-portfolio.csv",
                algorithm_version="bounded-grouped-subset-sum@1.0.0",
                rule=portfolio_rule,
                input_hash="grouped-portfolio-live-input",
                actor_id="grouped-live-user",
            )
            for side, source_id, amount, fee in (
                ("Left", "PL1", "120.00", "20.00"),
                ("Left", "PL2", "50.00", "0.00"),
                ("Right", "PR1", "80.00", "0.00"),
                ("Right", "PR2", "50.00", "0.00"),
            ):
                repository.register_input(
                    tenant_id=tenant_a,
                    run_id=portfolio_run_id,
                    side=side,
                    source_id=source_id,
                    record_hash=f"hash-{source_id}",
                    amount=amount,
                    currency_code="EUR" if source_id in {"PL2", "PR2"} else "USD",
                    attributes={
                        "date": "2026-08-01",
                        "currency": "EUR" if source_id in {"PL2", "PR2"} else "USD",
                        "entity_id": "entity-portfolio",
                        "fee": fee,
                    },
                    allowed_uses=2,
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
        assert summary.completed == 4
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
            fx_metadata = repository.get_run_metadata(tenant_id=tenant_a, run_id=fx_run_id)
            fx_rows = repository.list_results(tenant_id=tenant_a, run_id=fx_run_id)
            assert fx_metadata["execution_status"] == "Complete"
            assert fx_metadata["result_count"] == 2
            assert fx_metadata["matched_count"] == 2
            assert {(row["left_id"], row["right_id"]) for row in fx_rows} == {
                ("FXL1", "FXR1"),
                ("FXL2", "FXR1"),
            }
            assert all(row["lineage_json"]["mode"] == "many-to-one" for row in fx_rows)
            assert all(row["lineage_json"]["currency"] == "USD" for row in fx_rows)
            fx_decision_digest = fx_rows[0]["lineage_json"]["decision_digest"]
            portfolio_metadata = repository.get_run_metadata(tenant_id=tenant_a, run_id=portfolio_run_id)
            portfolio_rows = repository.list_results(tenant_id=tenant_a, run_id=portfolio_run_id)
            assert portfolio_metadata["execution_status"] == "Complete"
            assert portfolio_metadata["result_count"] == 2
            assert portfolio_metadata["matched_count"] == 2
            assert {(row["left_id"], row["right_id"]) for row in portfolio_rows} == {
                ("PL1", "PR1"),
                ("PL2", "PR2"),
            }
            partial_row = next(row for row in portfolio_rows if row["left_id"] == "PL1")
            assert partial_row["lineage_json"]["mode"] == "portfolio"
            assert partial_row["lineage_json"]["netting_mode"] == "net"
            assert partial_row["lineage_json"]["left_fee_total"] == "20"
            assert partial_row["lineage_json"]["left_net_total"] == "100"
            assert partial_row["lineage_json"]["right_net_total"] == "80"
            assert partial_row["lineage_json"]["settled_amount"] == "80"
            assert partial_row["lineage_json"]["left_residual"] == "20"
            assert partial_row["lineage_json"]["right_residual"] == "0"
            assert partial_row["lineage_json"]["reason_code"] == "GROUP_PORTFOLIO_PARTIAL_SETTLEMENT"
            portfolio_result_digest = partial_row["lineage_json"]["strategy_result_digest"]

        expected = GroupedSubsetSumStrategy().execute(
        MatchingStrategyRequest(
                left_records=({"id": "L1", "amount": "100", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-A",))},),
                right_records=(
                    {"id": "R1", "amount": "40", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-A",))},
                    {"id": "R2", "amount": "60", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-A",))},
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
                    {"id": "ML1", "amount": "30", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-M",))},
                    {"id": "ML2", "amount": "70", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-M",))},
                ),
                right_records=(
                    {"id": "MR1", "amount": "25", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-M",))},
                    {"id": "MR2", "amount": "75", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-M",))},
                ),
                amount_tolerance="0",
                date_window_days=0,
                mode="many-to-many",
            )
        )
        assert many_decision_digest == many_expected.results[0]["decision_digest"]
        fx_expected = GroupedSubsetSumStrategy().execute(
            MatchingStrategyRequest(
                left_records=(
                    {"id": "FXL1", "amount": "60", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-FX",))},
                    {"id": "FXL2", "amount": "40", "date": "2026-08-01", "currency": "USD", "partition": _stable_partition_key(("entity-FX",))},
                ),
                right_records=(
                    {"id": "FXR1", "amount": "200", "date": "2026-08-01", "currency": "EUR", "partition": _stable_partition_key(("entity-FX",))},
                ),
                amount_tolerance="0",
                date_window_days=0,
                mode="many-to-one",
                target_currency="USD",
                fx_rates=(
                    {
                        "base_currency": "EUR",
                        "quote_currency": "USD",
                        "rate": "0.5",
                        "rate_type": "spot",
                        "source": "synthetic-fx",
                        "effective_at": "2026-08-01",
                    },
                ),
            )
        )
        assert fx_decision_digest == fx_expected.results[0]["decision_digest"]
        portfolio_expected = GroupedSubsetSumStrategy().execute(
            MatchingStrategyRequest(
                left_records=(
                    {
                        "id": "PL1",
                        "amount": "120",
                        "fee": "20.00",
                        "date": "2026-08-01",
                        "currency": "USD",
                        "entity_id": "entity-portfolio",
                        "partition": _stable_partition_key(("entity-portfolio",)),
                    },
                    {
                        "id": "PL2",
                        "amount": "50",
                        "fee": "0.00",
                        "date": "2026-08-01",
                        "currency": "EUR",
                        "entity_id": "entity-portfolio",
                        "partition": _stable_partition_key(("entity-portfolio",)),
                    },
                ),
                right_records=(
                    {
                        "id": "PR1",
                        "amount": "80",
                        "fee": "0.00",
                        "date": "2026-08-01",
                        "currency": "USD",
                        "entity_id": "entity-portfolio",
                        "partition": _stable_partition_key(("entity-portfolio",)),
                    },
                    {
                        "id": "PR2",
                        "amount": "50",
                        "fee": "0.00",
                        "date": "2026-08-01",
                        "currency": "EUR",
                        "entity_id": "entity-portfolio",
                        "partition": _stable_partition_key(("entity-portfolio",)),
                    },
                ),
                amount_tolerance="0",
                date_window_days=0,
                mode="portfolio",
                netting_mode="net",
                allow_partial_settlement=True,
            )
        )
        assert portfolio_result_digest == portfolio_expected.decision_digest

        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresReconciliationRepository(connection)
            repository.create_run(
                tenant_id=tenant_a,
                run_id=carry_run_id,
                name="Live carry-forward reconciliation",
                left_source="ledger-carry.csv",
                right_source="bank-carry.csv",
                algorithm_version="bounded-carry-forward-fifo@1.0.0",
                rule={"matching_mode": "carry-forward", "date_window_days": 3, "amount_tolerance": "0"},
                input_hash="sequential-carry-live-input",
                actor_id="sequential-live-user",
            )
            repository.register_input(
                tenant_id=tenant_a,
                run_id=carry_run_id,
                side="Left",
                source_id="O1",
                record_hash="hash-O1",
                amount="100.00",
                currency_code="USD",
                attributes={"date": "2026-08-01", "currency": "USD"},
                allowed_uses=2,
            )
            repository.register_input(
                tenant_id=tenant_a,
                run_id=carry_run_id,
                side="Right",
                source_id="S1",
                record_hash="hash-S1",
                amount="60.00",
                currency_code="USD",
                attributes={"date": "2026-08-02", "currency": "USD"},
            )
            repository.create_run(
                tenant_id=tenant_a,
                run_id=reversal_run_id,
                name="Live reversal pairing reconciliation",
                left_source="ledger-reversal.csv",
                right_source="bank-reversal.csv",
                algorithm_version="bounded-reversal-pairing@1.0.0",
                rule={"matching_mode": "reversal-pairing", "date_window_days": 3, "amount_tolerance": "0"},
                input_hash="sequential-reversal-live-input",
                actor_id="sequential-live-user",
            )
            repository.register_input(
                tenant_id=tenant_a,
                run_id=reversal_run_id,
                side="Left",
                source_id="J1",
                record_hash="hash-J1",
                amount="100.00",
                currency_code="USD",
                attributes={"date": "2026-08-01", "currency": "USD"},
            )
            repository.register_input(
                tenant_id=tenant_a,
                run_id=reversal_run_id,
                side="Right",
                source_id="R1",
                record_hash="hash-R1",
                amount="-100.00",
                currency_code="USD",
                attributes={"date": "2026-08-02", "currency": "USD", "reversal_of": "J1"},
            )

        sequential_worker = PostgresReconciliationWorker(
            factory,
            tenant_supplier=lambda: [tenant_a],
            matcher=PostgresSequentialMatchingAdapter(),
            settings=PostgresReconciliationWorkerSettings(
                worker_id="sequential-live-worker",
                actor_id="sequential-live-worker",
                poll_interval_seconds=0,
            ),
        )
        sequential_summary = sequential_worker.process_once()
        assert sequential_summary.completed == 2
        assert sequential_summary.failed == 0
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresReconciliationRepository(connection)
            carry_metadata = repository.get_run_metadata(tenant_id=tenant_a, run_id=carry_run_id)
            carry_rows = repository.list_results(tenant_id=tenant_a, run_id=carry_run_id)
            assert carry_metadata["execution_status"] == "Complete"
            assert carry_metadata["matched_count"] == 1
            assert {(row["left_id"], row["right_id"], row["status"]) for row in carry_rows} == {
                ("O1", "S1", "Matched"),
                ("O1", "", "Unmatched"),
            }
            carry_matched_row = next(row for row in carry_rows if row["status"] == "Matched")
            assert carry_matched_row["lineage_json"]["strategy_id"] == "bounded-carry-forward-fifo"
            assert carry_matched_row["lineage_json"]["allocation"]["obligation_residual"] == "40"
            reversal_metadata = repository.get_run_metadata(tenant_id=tenant_a, run_id=reversal_run_id)
            reversal_rows = repository.list_results(tenant_id=tenant_a, run_id=reversal_run_id)
            assert reversal_metadata["execution_status"] == "Complete"
            assert reversal_metadata["matched_count"] == 1
            assert len(reversal_rows) == 1
            assert (reversal_rows[0]["left_id"], reversal_rows[0]["right_id"]) == ("J1", "R1")
            assert reversal_rows[0]["lineage_json"]["strategy_id"] == "bounded-reversal-pairing"
            assert reversal_rows[0]["lineage_json"]["pair"]["match_basis"] == "explicit-reversal-link"
            carry_result_digest = carry_matched_row["lineage_json"]["strategy_result_digest"]
            reversal_result_digest = reversal_rows[0]["lineage_json"]["strategy_result_digest"]

        carry_expected = CarryForwardFifoStrategy().execute(
            MatchingStrategyRequest(
                    left_records=({"id": "O1", "amount": "100", "date": "2026-08-01", "currency": "USD", "partition": "default"},),
                    right_records=({"id": "S1", "amount": "60", "date": "2026-08-02", "currency": "USD", "partition": "default"},),
                amount_tolerance="0",
                date_window_days=3,
                mode="carry-forward",
            )
        )
        reversal_expected = ReversalPairingStrategy().execute(
            MatchingStrategyRequest(
                    left_records=({"id": "J1", "amount": "100", "date": "2026-08-01", "currency": "USD", "partition": "default"},),
                    right_records=({"id": "R1", "amount": "-100", "date": "2026-08-02", "currency": "USD", "partition": "default", "reversal_of": "J1"},),
                amount_tolerance="0",
                date_window_days=3,
                mode="reversal-pairing",
            )
        )
        assert carry_result_digest == carry_expected.decision_digest
        assert reversal_result_digest == reversal_expected.decision_digest

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
                    allowed_uses=2,
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
        assert resumed.result_count == 4
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
            assert len(rows) == 4
            assert len({str(row["id"]) for row in rows}) == 4
            assert {(row["left_id"], row["right_id"]) for row in rows} == {
                ("L-A", "R-A1"),
                ("L-A", "R-A2"),
                ("L-B", ""),
                ("", "R-B"),
            }
            assert {str(item["worker_id"]) for item in checkpoints} == {
                "grouped-crash-worker-a",
                "grouped-crash-worker-b",
            }
    finally:
        admin.close()
