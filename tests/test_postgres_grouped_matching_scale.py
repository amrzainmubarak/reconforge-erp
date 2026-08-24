from __future__ import annotations

import json
import os
import re
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.benchmark.postgres_grouped_matching_scale import (
    DOMAIN_MODES,
    LIMITATIONS,
    PostgresGroupedMatchingScaleProfile,
    PostgresGroupedMatchingScaleResult,
    _partition_records,
    _rule,
    default_profile,
    domain_diverse_profile,
    run_postgres_grouped_matching_scale_profile,
    ten_k_profile,
    verify_postgres_grouped_matching_scale_result,
)
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresConnectionPool,
    PostgresSettings,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_ledger import POSTGRES_LEDGER_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import POSTGRES_MASTER_DATA_SCHEMA_SQL
from reconforge.infrastructure.postgres_reconciliation import POSTGRES_RECONCILIATION_SCHEMA_SQL
from reconforge.infrastructure.postgres_reconciliation_checkpoints import (
    POSTGRES_RECONCILIATION_CHECKPOINT_SCHEMA_SQL,
)
from reconforge.workers.postgres_grouped_matching import PostgresGroupedMatchingAdapter
from reconforge.workers.postgres_reconciliation import (
    ReconciliationExecutionContext,
    ReconciliationInputPartition,
)


def test_postgres_grouped_matching_scale_profile_is_bounded_and_declares_expected_shape() -> None:
    profile = default_profile()

    assert profile.profile_id == "postgres-grouped-matching/64-partitions-v1"
    assert (profile.workers, profile.runs, profile.partitions_per_run) == (4, 32, 2)
    assert profile.declared_partitions == 64
    assert profile.expected_result_rows == 152
    assert profile.modes == ("one-to-many", "many-to-one", "many-to-many", "portfolio", "fx-many-to-one")
    assert any("not a throughput" in limitation for limitation in LIMITATIONS)


def test_postgres_grouped_matching_scale_profile_rejects_unbounded_mode_changes() -> None:
    with pytest.raises(ValueError, match="retain all declared grouped modes"):
        PostgresGroupedMatchingScaleProfile(
            profile_id="invalid",
            workers=1,
            runs=1,
            modes=("one-to-many",),
        )


def test_postgres_grouped_matching_scale_profile_declares_10k_partition_tier() -> None:
    profile = ten_k_profile()

    assert profile.profile_id == "postgres-grouped-matching/10k-partitions-v1"
    assert (profile.workers, profile.runs, profile.partitions_per_run, profile.batch_size) == (
        16,
        1_000,
        10,
        32,
    )
    assert profile.declared_partitions == 10_000
    assert profile.expected_result_rows == 24_000


def test_postgres_grouped_matching_scale_profile_declares_domain_diverse_10k_record_tier() -> None:
    profile = domain_diverse_profile()

    assert profile.profile_id == "postgres-grouped-matching/10k-domain-diverse-v1"
    assert (profile.workers, profile.runs, profile.partitions_per_run, profile.batch_size) == (
        16,
        250,
        10,
        32,
    )
    assert profile.declared_partitions == 2_500
    assert profile.expected_result_rows == 9_160
    assert profile.modes == DOMAIN_MODES


def test_postgres_grouped_matching_domain_diverse_small_shape_covers_every_mode() -> None:
    profile = PostgresGroupedMatchingScaleProfile(
        profile_id="postgres-grouped-matching/domain-diverse-test-v1",
        workers=4,
        runs=6,
        partitions_per_run=2,
        batch_size=4,
        modes=DOMAIN_MODES,
    )

    assert profile.declared_partitions == 12
    assert profile.expected_result_rows == 44


def test_postgres_grouped_matching_domain_diverse_adapter_projects_every_shape() -> None:
    expected_rows = {
        "domain-one-to-many": 3,
        "domain-many-to-one": 3,
        "domain-many-to-many": 4,
        "domain-portfolio-net": 4,
        "domain-fx-many-to-many": 4,
        "domain-portfolio-partial": 4,
    }
    adapter = PostgresGroupedMatchingAdapter()
    for index, mode in enumerate(DOMAIN_MODES):
        left_inputs: list[dict[str, object]] = []
        right_inputs: list[dict[str, object]] = []
        for side, source_id, amount, currency, fee in _partition_records(mode, index, 0):
            target = left_inputs if side == "Left" else right_inputs
            target.append(
                {
                    "source_id": source_id,
                    "amount_decimal": amount,
                    "currency_code": currency,
                    "attributes_json": {
                        "date": "2026-08-01",
                        "currency": currency,
                        "entity_id": f"domain-entity-{index}",
                        "fee": fee,
                    },
                }
            )
        partition = ReconciliationInputPartition(
            f"domain-partition-{index}",
            tuple(left_inputs),
            tuple(right_inputs),
        )
        context = ReconciliationExecutionContext(
            run={"rule_json": _rule(mode)},
            left_inputs=tuple(left_inputs),
            right_inputs=tuple(right_inputs),
            heartbeat=lambda _progress: {},
            cancellation_requested=lambda: False,
            partition_supplier=lambda partition=partition: (partition,),
        )

        projected = adapter.iter_partition_results(context)[0]
        assert len(projected.results) == expected_rows[mode]
        assert all(row["lineage"]["strategy_result_digest"] for row in projected.results)
        if mode == "domain-portfolio-partial":
            assert {row["status"] for row in projected.results} == {"Ambiguous"}
            assert len(projected.exceptions) == 4
        else:
            assert {row["status"] for row in projected.results} == {"Matched"}
            assert projected.exceptions == ()


def test_postgres_grouped_matching_scale_artifacts_are_in_source_manifest() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "include reconforge/benchmark/postgres_grouped_matching_scale.py" in manifest
    assert "include tests/test_postgres_grouped_matching_scale.py" in manifest
    assert "include docs/adr/0300-postgres-grouped-matching-bounded-scale-profile.md" in manifest
    assert "include docs/execution/benchmarks/postgres-grouped-matching-64-partitions-v1.md" in manifest
    assert "include docs/execution/benchmarks/postgres-grouped-matching-500-current-2026-08-23.md" in manifest
    assert "include docs/adr/0614-local-postgres-grouped-500-runtime-evidence.md" in manifest
    assert "include docs/execution/benchmarks/postgres-grouped-matching-10k-partitions-v1.md" in manifest
    assert "include docs/execution/benchmarks/postgres-grouped-matching-10k-partitions-v1.json" in manifest
    assert "include docs/execution/benchmarks/postgres-grouped-matching-10k-current-2026-08-24.md" in manifest
    assert "include docs/execution/benchmarks/postgres-grouped-matching-10k-current-2026-08-24.json" in manifest
    assert "include docs/adr/0615-local-postgres-grouped-10k-runtime-evidence.md" in manifest
    assert "include docs/execution/benchmarks/postgres-grouped-matching-10k-domain-diverse-current-2026-08-24.md" in manifest
    assert "include docs/execution/benchmarks/postgres-grouped-matching-10k-domain-diverse-current-2026-08-24.json" in manifest
    assert "include docs/adr/0616-local-postgres-grouped-10k-domain-diverse-runtime-evidence.md" in manifest
    assert "include docs/adr/0341-postgres-grouped-matching-10k-connection-pool.md" in manifest
    assert "test_live_postgres_grouped_matching_500_partition_scale_profile" in workflow
    assert "test_live_postgres_grouped_matching_10k_partition_scale_profile" in workflow
    assert "test_live_postgres_grouped_matching_10k_domain_diverse_profile" in workflow


def test_postgres_grouped_matching_domain_diverse_artifact_is_bounded_and_current() -> None:
    artifact = json.loads(
        Path(
            "docs/execution/benchmarks/"
            "postgres-grouped-matching-10k-domain-diverse-current-2026-08-24.json"
        ).read_text(encoding="utf-8")
    )

    assert artifact["schema_version"] == 1
    assert artifact["profile_id"] == "postgres-grouped-matching/10k-domain-diverse-v1"
    assert artifact["completed_runs"] == artifact["runs"] == 250
    assert artifact["completed_partitions"] == artifact["declared_partitions"] == 2_500
    assert artifact["result_rows"] == artifact["expected_result_rows"] == 9_160
    assert artifact["duplicate_result_identities"] == 0
    assert artifact["failed_runs"] == artifact["final_active_runs"] == 0
    assert artifact["environment"]["database"] == "PostgreSQL 16.14"
    assert len(artifact["limitations"]) == 4


def _run_live_postgres_grouped_profile(
    profile: PostgresGroupedMatchingScaleProfile,
    *,
    id_prefix: str,
) -> PostgresGroupedMatchingScaleResult:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("live grouped matching scale test requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")

    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_id = "grouped_scale_" + uuid4().hex[:12]
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
            pytest.skip("live grouped matching scale test requires a non-superuser, non-BYPASSRLS role")

        pool = PostgresConnectionPool(factory, max_size=max(2, min(profile.workers, 16)))
        try:
            result = run_postgres_grouped_matching_scale_profile(
                pool,
                tenant_id,
                profile=profile,
                id_prefix=id_prefix + uuid4().hex[:8],
            )
        finally:
            pool_snapshot_before_close = pool.snapshot
            pool.close()

        assert not pool_snapshot_before_close.closed
        assert pool_snapshot_before_close.leased == 0
        assert 1 <= pool_snapshot_before_close.total <= pool_snapshot_before_close.max_size

        verify_postgres_grouped_matching_scale_result(result, profile=profile)
        return result
    finally:
        # The PostgreSQL financial tables are append-only by policy; the
        # unique synthetic tenant is intentionally retained for auditability.
        admin.close()


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"),
    reason="requires a live PostgreSQL service",
)
def test_live_postgres_grouped_matching_scale_drains_concurrent_runs_without_duplicate_effects() -> None:
    profile = PostgresGroupedMatchingScaleProfile(
        profile_id="postgres-grouped-matching/10-partitions-test-v1",
        workers=2,
        runs=5,
        partitions_per_run=2,
    )
    result = _run_live_postgres_grouped_profile(profile, id_prefix="PG-GROUPED-SCALE-TEST-")

    assert result.completed_runs == 5
    assert result.completed_partitions == 10
    assert result.result_rows == 24
    assert result.duplicate_result_identities == 0
    assert result.failed_runs == 0
    assert result.final_active_runs == 0


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"),
    reason="requires a live PostgreSQL service",
)
def test_live_postgres_grouped_matching_500_partition_scale_profile() -> None:
    profile = PostgresGroupedMatchingScaleProfile(
        profile_id="postgres-grouped-matching/500-partitions-v1",
        workers=16,
        runs=250,
        partitions_per_run=2,
        batch_size=16,
    )
    result = _run_live_postgres_grouped_profile(profile, id_prefix="PG-GROUPED-SCALE-500-")

    assert result.completed_runs == 250
    assert result.completed_partitions == 500
    assert result.result_rows == profile.expected_result_rows
    assert result.duplicate_result_identities == 0
    assert result.failed_runs == 0
    assert result.final_active_runs == 0
    assert result.per_mode_completed == {mode: 50 for mode in profile.modes}


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"),
    reason="requires a live PostgreSQL service",
)
def test_live_postgres_grouped_matching_10k_partition_scale_profile() -> None:
    profile = ten_k_profile()
    result = _run_live_postgres_grouped_profile(profile, id_prefix="PG-GROUPED-SCALE-10K-")

    assert result.completed_runs == 1_000
    assert result.completed_partitions == 10_000
    assert result.result_rows == profile.expected_result_rows
    assert result.duplicate_result_identities == 0
    assert result.failed_runs == 0
    assert result.final_active_runs == 0
    assert result.per_mode_completed == {mode: 200 for mode in profile.modes}


@pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"),
    reason="requires a live PostgreSQL service",
)
def test_live_postgres_grouped_matching_10k_domain_diverse_profile() -> None:
    profile = domain_diverse_profile()
    result = _run_live_postgres_grouped_profile(profile, id_prefix="PG-GROUPED-DOMAIN-10K-")

    assert result.completed_runs == 250
    assert result.completed_partitions == 2_500
    assert result.result_rows == profile.expected_result_rows
    assert result.duplicate_result_identities == 0
    assert result.failed_runs == 0
    assert result.final_active_runs == 0
    base, remainder = divmod(profile.runs, len(DOMAIN_MODES))
    expected_modes = {mode: base + int(index < remainder) for index, mode in enumerate(DOMAIN_MODES)}
    assert result.per_mode_completed == dict(sorted(expected_modes.items()))
    assert result.limitations != LIMITATIONS
