from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4

import pytest

from reconforge.benchmark.postgres_grouped_matching_scale import (
    LIMITATIONS,
    PostgresGroupedMatchingScaleProfile,
    PostgresGroupedMatchingScaleResult,
    default_profile,
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


def test_postgres_grouped_matching_scale_artifacts_are_in_source_manifest() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "include reconforge/benchmark/postgres_grouped_matching_scale.py" in manifest
    assert "include tests/test_postgres_grouped_matching_scale.py" in manifest
    assert "include docs/adr/0300-postgres-grouped-matching-bounded-scale-profile.md" in manifest
    assert "include docs/execution/benchmarks/postgres-grouped-matching-64-partitions-v1.md" in manifest
    assert "include docs/execution/benchmarks/postgres-grouped-matching-10k-partitions-v1.md" in manifest
    assert "include docs/execution/benchmarks/postgres-grouped-matching-10k-partitions-v1.json" in manifest
    assert "include docs/adr/0341-postgres-grouped-matching-10k-connection-pool.md" in manifest
    assert "test_live_postgres_grouped_matching_500_partition_scale_profile" in workflow
    assert "test_live_postgres_grouped_matching_10k_partition_scale_profile" in workflow


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
            pool.close()

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
