"""Live PostgreSQL outbox fencing, recovery, RLS and evidence transactions."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest

from reconforge.benchmark.outbox_recovery import measure_bounded_recovery
from reconforge.infrastructure.outbox_fencing_schema import (
    POSTGRES_OUTBOX_FENCING_SCHEMA_SQL,
    PostgresOutboxFencingMigrationError,
    verify_postgres_outbox_fencing_migration_identity,
)
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
)
from reconforge.infrastructure.postgres_outbox import PostgresOutboxIntegrityError, PostgresOutboxRepository

pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"),
    reason="live PostgreSQL boundary prerequisite; covered by the Amr live acceptance gate",
)


def _database_dsn(value: str, name: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, "/" + name, parts.query, parts.fragment))


@dataclass
class Runtime:
    admin: Any
    boundary: PostgresTenantBoundary


@pytest.fixture(scope="module")
def runtime() -> Iterator[Runtime]:
    import psycopg
    from alembic.config import Config
    from psycopg import sql

    from alembic import command

    database = "amr_outbox_fencing_" + uuid4().hex[:10]
    admin_dsn = os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"]
    app_dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    app_role = os.environ["RECONFORGE_TEST_POSTGRES_APP_USER"]
    previous = os.environ.get("RECONFORGE_POSTGRES_DSN")
    admin = None
    with psycopg.connect(admin_dsn, autocommit=True) as server:
        server.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        try:
            os.environ["RECONFORGE_POSTGRES_DSN"] = _database_dsn(admin_dsn, database)
            configuration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            command.upgrade(configuration, "0102_pg_budget_control")
            admin = psycopg.connect(_database_dsn(admin_dsn, database), autocommit=True)
            admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES('legacy_fencing','Synthetic legacy lease')")
            admin.execute("""INSERT INTO reconforge.outbox_events(
                tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload,status,claimed_at,claimed_by,attempt_count)
                VALUES('legacy_fencing','legacy','test','test','legacy','{}'::jsonb,'Claimed',
                clock_timestamp()+interval '1 hour','reused-worker',3)""")
            admin.execute("""INSERT INTO reconforge.outbox_events(
                tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload,status,published_at,attempt_count)
                VALUES('legacy_fencing','legacy-published','test','test','legacy-published','{}'::jsonb,'Published',
                clock_timestamp(),0)""")
            command.upgrade(configuration, "0103_pg_outbox_fencing")
            admin.execute(sql.SQL("GRANT USAGE ON SCHEMA reconforge TO {}").format(sql.Identifier(app_role)))
            admin.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}").format(sql.Identifier(app_role)))
            admin.execute(
                sql.SQL("REVOKE INSERT,UPDATE,DELETE ON TABLE reconforge.outbox_delivery_evidence FROM {}").format(
                    sql.Identifier(app_role)
                )
            )
            admin.execute(
                sql.SQL("GRANT SELECT ON TABLE reconforge.outbox_delivery_evidence TO {}").format(sql.Identifier(app_role))
            )
            factory = PostgresConnectionFactory(PostgresSettings(dsn=_database_dsn(app_dsn, database), require_tls=False))
            with factory.connect() as connection:
                role = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
                assert role is not None and not role[0] and not role[1]
            yield Runtime(admin, PostgresTenantBoundary(factory))
        finally:
            if admin is not None:
                admin.close()
            if previous is None:
                os.environ.pop("RECONFORGE_POSTGRES_DSN", None)
            else:
                os.environ["RECONFORGE_POSTGRES_DSN"] = previous
            server.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


@pytest.fixture
def tenant(runtime: Runtime) -> str:
    value = "fencing_" + uuid4().hex[:12]
    runtime.admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (value, value))
    return value


@contextmanager
def _repository(runtime: Runtime, tenant: str, **scope: Any) -> Iterator[PostgresOutboxRepository]:
    with runtime.boundary.transaction(tenant, **scope) as connection:
        yield PostgresOutboxRepository(connection)


def _seed(runtime: Runtime, tenant: str, count: int = 1, **scope: Any) -> None:
    with runtime.boundary.transaction(tenant, **scope) as connection:
        for index in range(count):
            connection.execute(
                """INSERT INTO reconforge.outbox_events(
                tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload)
                VALUES(%s,%s,'synthetic.created','synthetic',%s,'{}'::jsonb)""",
                (tenant, f"event-{index}", f"item-{index}"),
            )


def _expire(runtime: Runtime, tenant: str) -> None:
    runtime.admin.execute(
        "UPDATE reconforge.outbox_events SET claimed_at=clock_timestamp()-interval '1 second' WHERE tenant_id=%s AND status='Claimed'",
        (tenant,),
    )


def test_reused_worker_identity_is_fenced_after_crash(runtime: Runtime, tenant: str) -> None:
    _seed(runtime, tenant)
    with _repository(runtime, tenant) as repository:
        old = repository.claim_pending(tenant_id=tenant, worker_id="shared-worker")[0]
    _expire(runtime, tenant)
    with _repository(runtime, tenant) as repository:
        current = repository.claim_pending(tenant_id=tenant, worker_id="shared-worker")[0]
    assert current.lease_generation == old.lease_generation + 1 == 2
    for generation in (None, old.lease_generation):
        with pytest.raises(PostgresOutboxIntegrityError), _repository(runtime, tenant) as repository:
            repository.mark_published(tenant_id=tenant, event_id=old.id, worker_id="shared-worker", lease_generation=generation)
        with pytest.raises(PostgresOutboxIntegrityError), _repository(runtime, tenant) as repository:
            repository.mark_failed(tenant_id=tenant, event_id=old.id, worker_id="shared-worker", error="stale", lease_generation=generation)
    with _repository(runtime, tenant) as repository:
        repository.mark_published(tenant_id=tenant, event_id=current.id, worker_id="shared-worker", lease_generation=current.lease_generation)
        actions = repository.connection.execute(
            """SELECT action FROM reconforge.outbox_delivery_evidence WHERE tenant_id=%s
            ORDER BY lease_generation,CASE action
              WHEN 'claimed' THEN 1 WHEN 'expired' THEN 2 WHEN 'failed' THEN 3
              WHEN 'published' THEN 4 WHEN 'requeued' THEN 5 END""", (tenant,),
        ).fetchall()
        assert [row[0] for row in actions] == ["claimed", "expired", "claimed", "published"]


def test_expired_unreclaimed_worker_cannot_deliver_acknowledge_or_fail(runtime: Runtime, tenant: str) -> None:
    _seed(runtime, tenant)
    with _repository(runtime, tenant) as repository:
        claim = repository.claim_pending(tenant_id=tenant, worker_id="worker")[0]
    _expire(runtime, tenant)
    for operation in ("assert", "publish", "fail"):
        with pytest.raises(PostgresOutboxIntegrityError), _repository(runtime, tenant) as repository:
            values = dict(tenant_id=tenant, event_id=claim.id, worker_id="worker", lease_generation=claim.lease_generation)
            if operation == "assert":
                repository.assert_claim(**values)
            elif operation == "publish":
                repository.mark_published(**values)
            else:
                repository.mark_failed(**values, error="stale")


def test_last_attempt_crash_becomes_bounded_terminal_state(runtime: Runtime, tenant: str) -> None:
    _seed(runtime, tenant, 3)
    with _repository(runtime, tenant) as repository:
        assert len(repository.claim_pending(tenant_id=tenant, worker_id="crashed", limit=3, max_attempts=1)) == 3
    _expire(runtime, tenant)
    with _repository(runtime, tenant) as repository:
        assert repository.recover_expired(tenant_id=tenant, limit=2, max_attempts=1) == 2
        assert len(repository.list_events(tenant_id=tenant, status="dead")) == 2
    with _repository(runtime, tenant) as repository:
        assert repository.recover_expired(tenant_id=tenant, limit=2, max_attempts=1) == 1
        assert repository.recover_expired(tenant_id=tenant, limit=2, max_attempts=1) == 0
        assert repository.claim_pending(tenant_id=tenant, worker_id="next", max_attempts=1) == []
        repository.replay_dead(tenant_id=tenant, event_id="event-0")
        replay = repository.claim_pending(tenant_id=tenant, worker_id="crashed")[0]
        assert replay.lease_generation == 2
        repository.mark_published(tenant_id=tenant, event_id=replay.id, worker_id="crashed", lease_generation=replay.lease_generation)


def test_same_identity_claim_race_has_one_owner(runtime: Runtime, tenant: str) -> None:
    _seed(runtime, tenant)
    barrier = Barrier(2)

    def claim() -> list[Any]:
        with _repository(runtime, tenant) as repository:
            barrier.wait(timeout=10)
            return repository.claim_pending(tenant_id=tenant, worker_id="shared-worker", limit=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sorted(len(result) for result in results) == [0, 1]


def test_delivery_evidence_is_tenant_and_hierarchy_isolated(runtime: Runtime, tenant: str) -> None:
    scope = dict(workspace_id="workspace-a", organization_id="organization-a", legal_entity_id="entity-a")
    _seed(runtime, tenant, **scope)
    with _repository(runtime, tenant, **scope) as repository:
        claim = repository.claim_pending(tenant_id=tenant, worker_id="worker", **scope)[0]
    for other_scope in ({"workspace_id": "workspace-b"}, {"organization_id": "organization-b"}, {"organization_id": "organization-a", "legal_entity_id": "entity-b"}):
        with _repository(runtime, tenant, **other_scope) as repository:
            assert repository.list_events(tenant_id=tenant, status="all") == []
            assert repository.connection.execute("SELECT * FROM reconforge.outbox_delivery_evidence").fetchall() == []
            assert repository.recover_expired(tenant_id=tenant) == 0
        with pytest.raises(PostgresOutboxIntegrityError), _repository(runtime, tenant, **other_scope) as repository:
            repository.mark_published(tenant_id=tenant, event_id=claim.id, worker_id="worker", lease_generation=claim.lease_generation)
    other_tenant = "isolated_" + uuid4().hex[:10]
    runtime.admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (other_tenant, other_tenant))
    with _repository(runtime, other_tenant) as repository:
        assert repository.connection.execute("SELECT * FROM reconforge.outbox_delivery_evidence").fetchall() == []


@pytest.mark.parametrize("operation", ["claim", "recover", "publish"])
def test_evidence_failure_rolls_back_entire_transition(runtime: Runtime, tenant: str, operation: str) -> None:
    import psycopg

    _seed(runtime, tenant)
    claim = None
    if operation != "claim":
        with _repository(runtime, tenant) as repository:
            claim = repository.claim_pending(tenant_id=tenant, worker_id="worker")[0]
    if operation == "recover":
        _expire(runtime, tenant)
    before = runtime.admin.execute("SELECT * FROM reconforge.outbox_events WHERE tenant_id=%s", (tenant,)).fetchone()
    runtime.admin.execute("""CREATE FUNCTION reconforge.inject_delivery_evidence_failure() RETURNS trigger LANGUAGE plpgsql
        AS $$ BEGIN RAISE EXCEPTION 'synthetic evidence failure'; END $$;
        CREATE TRIGGER inject_delivery_evidence_failure BEFORE INSERT ON reconforge.outbox_delivery_evidence
        FOR EACH ROW EXECUTE FUNCTION reconforge.inject_delivery_evidence_failure()""")
    try:
        with pytest.raises(psycopg.Error), _repository(runtime, tenant) as repository:
            if operation == "claim":
                repository.claim_pending(tenant_id=tenant, worker_id="worker")
            elif operation == "recover":
                repository.recover_expired(tenant_id=tenant, max_attempts=1)
            else:
                assert claim is not None
                repository.mark_published(tenant_id=tenant, event_id=claim.id, worker_id="worker", lease_generation=claim.lease_generation)
        assert runtime.admin.execute("SELECT * FROM reconforge.outbox_events WHERE tenant_id=%s", (tenant,)).fetchone() == before
    finally:
        runtime.admin.execute("DROP TRIGGER inject_delivery_evidence_failure ON reconforge.outbox_delivery_evidence; DROP FUNCTION reconforge.inject_delivery_evidence_failure()")


def test_evidence_immutable_and_fencing_install_repeatable(runtime: Runtime, tenant: str) -> None:
    import psycopg

    _seed(runtime, tenant)
    with _repository(runtime, tenant) as repository:
        repository.claim_pending(tenant_id=tenant, worker_id="worker")
    for statement in (
        "UPDATE reconforge.outbox_events SET lease_generation=0 WHERE tenant_id=%s",
        "UPDATE reconforge.outbox_delivery_evidence SET worker_id='forged' WHERE tenant_id=%s",
        "DELETE FROM reconforge.outbox_delivery_evidence WHERE tenant_id=%s",
    ):
        with pytest.raises(psycopg.Error), _repository(runtime, tenant) as repository:
            repository.connection.execute(statement, (tenant,))
    runtime.admin.execute(POSTGRES_OUTBOX_FENCING_SCHEMA_SQL)
    assert runtime.admin.execute("SELECT lease_generation FROM reconforge.outbox_events WHERE tenant_id=%s", (tenant,)).fetchone()[0] == 1


def test_app_role_cannot_watermark_or_bypass_delivery_state(runtime: Runtime, tenant: str) -> None:
    import psycopg

    with pytest.raises(PostgresOutboxFencingMigrationError), _repository(runtime, tenant) as repository:
        verify_postgres_outbox_fencing_migration_identity(repository.connection)
    with pytest.raises(psycopg.Error, match="requires a role that bypasses forced row security"), _repository(
        runtime, tenant
    ) as repository:
        repository.connection.execute(POSTGRES_OUTBOX_FENCING_SCHEMA_SQL)
    with pytest.raises(psycopg.Error, match="initial generation"), _repository(runtime, tenant) as repository:
        repository.connection.execute(
            """INSERT INTO reconforge.outbox_events(
            tenant_id,event_id,event_type,aggregate_type,aggregate_id,payload,
            lease_generation,lease_generation_floor)
            VALUES(%s,'unfenced','test','test','unfenced','{}'::jsonb,0,2)""",
            (tenant,),
        )
    _seed(runtime, tenant)
    with pytest.raises(psycopg.Error, match="live claimed generation"), _repository(runtime, tenant) as repository:
        repository.connection.execute(
            """UPDATE reconforge.outbox_events
            SET status='Published',published_at=clock_timestamp(),claimed_at=NULL,claimed_by=NULL,last_error=NULL
            WHERE tenant_id=%s AND event_id='event-0'""",
            (tenant,),
        )
    with _repository(runtime, tenant) as repository:
        claim = repository.claim_pending(tenant_id=tenant, worker_id="worker")[0]
        repository.mark_published(
            tenant_id=tenant,
            event_id=claim.id,
            worker_id="worker",
            lease_generation=claim.lease_generation,
        )


def test_shared_runtime_role_can_form_a_structurally_valid_delivery_transition(runtime: Runtime, tenant: str) -> None:
    """Direct parent DML remains inside the documented shared-runtime trust boundary."""

    _seed(runtime, tenant)
    with _repository(runtime, tenant) as repository:
        repository.connection.execute(
            """UPDATE reconforge.outbox_events
            SET status='Claimed',lease_generation=lease_generation+1,attempt_count=attempt_count+1,
                claimed_at=clock_timestamp()+interval '1 hour',claimed_by='raw-runtime-worker'
            WHERE tenant_id=%s AND event_id='event-0'""",
            (tenant,),
        )
        repository.connection.execute(
            """UPDATE reconforge.outbox_events
            SET status='Published',claimed_at=NULL,claimed_by=NULL,published_at=clock_timestamp(),last_error=NULL
            WHERE tenant_id=%s AND event_id='event-0'""",
            (tenant,),
        )
        state = repository.connection.execute(
            "SELECT status,lease_generation FROM reconforge.outbox_events WHERE tenant_id=%s AND event_id='event-0'",
            (tenant,),
        ).fetchone()
        evidence = repository.connection.execute(
            "SELECT action,worker_id FROM reconforge.outbox_delivery_evidence "
            "WHERE tenant_id=%s AND event_id='event-0' ORDER BY occurred_at,action",
            (tenant,),
        ).fetchall()
        assert state is not None and tuple(state) == ("Published", 1)
        assert [tuple(row) for row in evidence] == [
            ("claimed", "raw-runtime-worker"),
            ("published", "raw-runtime-worker"),
        ]


def test_evidence_admission_rejects_app_forgery_and_hierarchy_mismatch(runtime: Runtime, tenant: str) -> None:
    import psycopg

    scope = dict(workspace_id="workspace-a", organization_id="organization-a", legal_entity_id="entity-a")
    _seed(runtime, tenant, **scope)
    with _repository(runtime, tenant, **scope) as repository:
        claim = repository.claim_pending(tenant_id=tenant, worker_id="worker", **scope)[0]
    with pytest.raises(psycopg.Error, match="permission denied"), _repository(
        runtime, tenant, **scope
    ) as repository:
        repository.connection.execute(
            """INSERT INTO reconforge.outbox_delivery_evidence(
            tenant_id,event_id,workspace_id,organization_id,legal_entity_id,
            lease_generation,action,worker_id,attempts)
            VALUES(%s,%s,%s,%s,%s,%s,'published','forged',%s)""",
            (
                tenant,
                claim.id,
                scope["workspace_id"],
                scope["organization_id"],
                scope["legal_entity_id"],
                claim.lease_generation,
                claim.attempt_count,
            ),
        )

    runtime.admin.execute(
        """CREATE FUNCTION reconforge.inject_mismatched_outbox_evidence() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = reconforge, pg_catalog AS $$
        BEGIN
          INSERT INTO reconforge.outbox_delivery_evidence(
            tenant_id,event_id,workspace_id,organization_id,legal_entity_id,
            lease_generation,action,worker_id,attempts)
          VALUES(NEW.tenant_id,NEW.event_id,'wrong-workspace',NEW.organization_id,NEW.legal_entity_id,
                 NEW.lease_generation,'failed','forged',NEW.attempt_count);
          RETURN NEW;
        END $$;
        CREATE TRIGGER zz_inject_mismatched_outbox_evidence AFTER UPDATE ON reconforge.outbox_events
        FOR EACH ROW WHEN (OLD.status='Pending' AND NEW.status='Claimed')
        EXECUTE FUNCTION reconforge.inject_mismatched_outbox_evidence()"""
    )
    second_tenant = "hierarchy_" + uuid4().hex[:10]
    runtime.admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,%s)", (second_tenant, second_tenant))
    _seed(runtime, second_tenant, **scope)
    try:
        with pytest.raises(psycopg.Error, match="parent binding"), _repository(runtime, second_tenant, **scope) as repository:
            repository.claim_pending(tenant_id=second_tenant, worker_id="worker", **scope)
    finally:
        runtime.admin.execute("DROP TRIGGER zz_inject_mismatched_outbox_evidence ON reconforge.outbox_events")
        runtime.admin.execute("DROP FUNCTION reconforge.inject_mismatched_outbox_evidence()")


def test_storage_verifier_rejects_retained_post_floor_evidence_gap(runtime: Runtime, tenant: str) -> None:
    _seed(runtime, tenant)
    runtime.admin.execute("DROP TRIGGER outbox_delivery_evidence_admission ON reconforge.outbox_delivery_evidence")
    runtime.admin.execute(
        """INSERT INTO reconforge.outbox_delivery_evidence(
        tenant_id,event_id,lease_generation,action,worker_id,attempts)
        VALUES(%s,'event-0',1,'claimed','forged',0)""",
        (tenant,),
    )
    runtime.admin.execute(POSTGRES_OUTBOX_FENCING_SCHEMA_SQL)
    with pytest.raises(PostgresOutboxIntegrityError, match="Retained outbox delivery evidence is invalid"), _repository(
        runtime, tenant
    ) as repository:
        repository.list_events(tenant_id=tenant)


def test_populated_upgrade_fences_ambiguous_preupgrade_identity(runtime: Runtime) -> None:
    tenant = "legacy_fencing"
    with _repository(runtime, tenant) as repository:
        events = {event.id: event for event in repository.list_events(tenant_id=tenant, status="all")}
        legacy = events["legacy"]
        assert legacy.lease_generation == legacy.lease_generation_floor == 2 and legacy.attempt_count == 3
        assert events["legacy-published"].lease_generation == events["legacy-published"].lease_generation_floor == 2
        with pytest.raises(PostgresOutboxIntegrityError):
            repository.assert_claim(tenant_id=tenant, event_id="legacy", worker_id="reused-worker", lease_generation=2)
        with pytest.raises(PostgresOutboxIntegrityError):
            repository.mark_published(
                tenant_id=tenant, event_id="legacy", worker_id="reused-worker", lease_generation=2
            )
        with pytest.raises(PostgresOutboxIntegrityError):
            repository.mark_failed(
                tenant_id=tenant,
                event_id="legacy",
                worker_id="reused-worker",
                error="legacy",
                lease_generation=2,
            )
    with pytest.raises(PostgresOutboxIntegrityError), _repository(runtime, tenant) as repository:
        repository.mark_published(tenant_id=tenant, event_id="legacy", worker_id="reused-worker")
    _expire(runtime, tenant)
    with _repository(runtime, tenant) as repository:
        recovered = repository.claim_pending(tenant_id=tenant, worker_id="reused-worker")[0]
        assert recovered.lease_generation == 3 and recovered.attempt_count == 4
    with pytest.raises(PostgresOutboxIntegrityError), _repository(runtime, tenant) as repository:
        repository.mark_published(tenant_id=tenant, event_id="legacy", worker_id="reused-worker")
    with _repository(runtime, tenant) as repository:
        repository.mark_published(tenant_id=tenant, event_id="legacy", worker_id="reused-worker", lease_generation=3)


def test_bounded_recovery_profile_1000_expired_events(runtime: Runtime, tenant: str, record_property: Any) -> None:
    _seed(runtime, tenant, 1000)
    with _repository(runtime, tenant) as repository:
        assert len(repository.claim_pending(tenant_id=tenant, worker_id="crashed", limit=1000, max_attempts=1)) == 1000
    _expire(runtime, tenant)
    runtime.admin.execute("ANALYZE reconforge.outbox_events")
    with _repository(runtime, tenant) as repository:
        plan = repository.connection.execute(
            """EXPLAIN (FORMAT JSON) SELECT event_id FROM reconforge.outbox_events
            WHERE tenant_id=%s AND status='Claimed' AND claimed_at<=statement_timestamp()
            ORDER BY claimed_at,created_at,event_id LIMIT 100""", (tenant,),
        ).fetchone()[0]

    def recover(limit: int) -> int:
        with _repository(runtime, tenant) as repository:
            return repository.recover_expired(tenant_id=tenant, limit=limit, max_attempts=1)

    result = measure_bounded_recovery(backend="postgresql", events=1000, batch_limit=100, recover=recover)
    assert result.calls == 11 and result.recovered == 1000 and result.largest_batch == 100
    with _repository(runtime, tenant) as repository:
        assert len(repository.list_events(tenant_id=tenant, status="dead", limit=1000)) == 1000
        assert repository.connection.execute("SELECT COUNT(*) FROM reconforge.outbox_delivery_evidence WHERE tenant_id=%s", (tenant,)).fetchone()[0] == 2000
    record_property("amr_recovery", result.to_dict())
    record_property("amr_recovery_query_plan", plan)
