"""Actual transaction ownership, acknowledgement replay and review races."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from queue import Queue
from typing import Any

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres import set_local_tenant_scope
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.infrastructure.postgres_master_data import PostgresMasterDataRepository
from reconforge.platform.common import PlatformError, server_principal_context
from tests.test_postgres_finance_posting import (
    CHECKER,
    MAKER,
    SCOPE,
    finance_database,
    isolated_postgres_migration_dsn,
    posting_database,
    principal,
    reviewed,
)
from tests.test_postgres_finance_scope import _entry, _wait_for_lock

__all__ = ["finance_database", "isolated_postgres_migration_dsn", "posting_database"]


@pytest.mark.parametrize("same_command", [True, False])
def test_live_concurrent_post_has_one_effect(posting_database: dict[str, Any], same_command: bool) -> None:
    db = posting_database
    entry_id, digest = reviewed(db)
    backends: Queue[int] = Queue()

    def post(connection: Any, key: str) -> dict[str, Any]:
        return PostgresFinancePostingRepository(connection, "finance_scope").post(
            entry_id, command_id=key, expected_validation_digest=digest, reason="Concurrent command", actor=CHECKER
        )

    def second() -> dict[str, Any] | str:
        try:
            with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
                connection.execute("SET LOCAL statement_timeout='10s'")
                backends.put(connection.execute("SELECT pg_backend_pid()").fetchone()[0])
                return post(connection, "first" if same_command else "second")
        except FinancePostingError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=1) as executor:
        with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
            first = post(connection, "first")
            future = executor.submit(second)
            _wait_for_lock(db["admin"], backends.get(timeout=10))
        assert future.result(timeout=15) == (first if same_command else "posting_source_conflict")
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        for table in ("finance_posting_effects", "finance_posting_commands"):
            assert connection.execute(f"SELECT count(*) FROM reconforge.{table}").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT count(*) FROM reconforge.domain_audit_events WHERE action='finance_entry_posted'"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM reconforge.outbox_events WHERE event_type='finance_entry_posted'"
            ).fetchone()[0]
            == 1
        )


def test_live_outer_rollback_owns_successful_post(posting_database: dict[str, Any]) -> None:
    db = posting_database
    entry_id, digest = reviewed(db)
    with (
        pytest.raises(RuntimeError, match="Outer operation failed"),
        db["boundary"].transaction("finance_scope", **SCOPE) as connection,
    ):
        PostgresFinancePostingRepository(connection, "finance_scope").post(
            entry_id, command_id="outer", expected_validation_digest=digest, reason="Synthetic", actor=CHECKER
        )
        raise RuntimeError("Outer operation failed")
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_commands").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT count(*) FROM reconforge.domain_audit_events WHERE action='finance_entry_posted'"
            ).fetchone()[0]
            == 0
        )


def test_live_stale_repeatable_read_child_cannot_modify_new_review_seal(posting_database: dict[str, Any]) -> None:
    import psycopg

    db = posting_database
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection, server_principal_context(principal(MAKER)):
        entry = _entry(PostgresFinanceCoreRepository(connection, "finance_scope"), "STALE-REVIEW")
    with closing(db["factory"].connect()) as stale, stale.transaction():
        stale.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        set_local_tenant_scope(stale, "finance_scope", **SCOPE)
        assert (
            stale.execute(
                "SELECT validation_digest FROM reconforge.finance_entries WHERE id=%s", (entry["id"],)
            ).fetchone()[0]
            is None
        )
        with (
            db["boundary"].transaction("finance_scope", **SCOPE) as connection,
            server_principal_context(principal(CHECKER)),
        ):
            PostgresFinanceCoreRepository(connection, "finance_scope").validate_entry(
                entry["id"], reason="Fresh review", actor_label="checker"
            )
        with pytest.raises(psycopg.errors.SerializationFailure), stale.transaction():
            stale.execute(
                "UPDATE reconforge.finance_entry_lines SET description='Stale alteration' WHERE entry_id=%s",
                (entry["id"],),
            )


@pytest.mark.parametrize("review_first", [True, False])
def test_live_review_and_child_write_serialize(posting_database: dict[str, Any], review_first: bool) -> None:
    import psycopg

    db = posting_database
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection, server_principal_context(principal(MAKER)):
        entry = _entry(PostgresFinanceCoreRepository(connection, "finance_scope"), "REVIEW-RACE")
    backends: Queue[int] = Queue()

    def review(connection: Any) -> None:
        with server_principal_context(principal(CHECKER)):
            PostgresFinanceCoreRepository(connection, "finance_scope").validate_entry(
                entry["id"], reason="Independent raced review", actor_label="checker"
            )

    def change(connection: Any) -> None:
        connection.execute(
            "UPDATE reconforge.finance_entry_lines SET description='Updated before review' WHERE entry_id=%s",
            (entry["id"],),
        )

    def second() -> str:
        try:
            with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
                connection.execute("SET LOCAL statement_timeout='10s'")
                backends.put(connection.execute("SELECT pg_backend_pid()").fetchone()[0])
                (change if review_first else review)(connection)
            return "accepted"
        except psycopg.errors.CheckViolation:
            return "immutable"

    with ThreadPoolExecutor(max_workers=1) as executor:
        with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
            (review if review_first else change)(connection)
            future = executor.submit(second)
            _wait_for_lock(db["admin"], backends.get(timeout=10))
        assert future.result(timeout=15) == ("immutable" if review_first else "accepted")
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        preview = PostgresFinancePostingRepository(connection, "finance_scope").preview(entry["id"], actor=CHECKER)
        assert preview["validation_digest"] == preview["current_content_digest"]


def test_live_posting_downgrade_preserves_legacy_and_refuses_new_provenance(posting_database: dict[str, Any]) -> None:
    import psycopg

    from alembic import command

    db = posting_database
    command.downgrade(db["config"], "0097_pg_reconciliation_seal")
    command.upgrade(db["config"], "0098_pg_finance_posting")
    with psycopg.connect(db["admin"], autocommit=True) as admin:
        role = psycopg.conninfo.conninfo_to_dict(__import__("os").environ["RECONFORGE_TEST_POSTGRES_DSN"])["user"]
        admin.execute(
            psycopg.sql.SQL(
                "GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.finance_posting_effects,reconforge.finance_posting_commands TO {}"
            ).format(psycopg.sql.Identifier(role))
        )
        assert (
            admin.execute(
                "SELECT count(*) FROM reconforge.finance_entries WHERE preparer_actor_id IS NULL AND validation_digest IS NULL"
            ).fetchone()[0]
            == 4
        )
    entry_id, digest = reviewed(db)
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        PostgresFinancePostingRepository(connection, "finance_scope").post(
            entry_id,
            command_id="retained-on-downgrade",
            expected_validation_digest=digest,
            reason="Must retain committed effect",
            actor=CHECKER,
        )
    with pytest.raises(Exception, match="Refusing to discard"):
        command.downgrade(db["config"], "0097_pg_reconciliation_seal")
    with psycopg.connect(db["admin"], autocommit=True) as admin:
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0098_pg_finance_posting"


@pytest.mark.parametrize("review_first", [True, False])
def test_live_independent_review_cannot_race_period_close(posting_database: dict[str, Any], review_first: bool) -> None:
    db = posting_database
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection, server_principal_context(principal(MAKER)):
        entry = _entry(PostgresFinanceCoreRepository(connection, "finance_scope"), "PERIOD-REVIEW-RACE")
    backends: Queue[int] = Queue()

    def review(connection: Any) -> None:
        with server_principal_context(principal(CHECKER)):
            PostgresFinanceCoreRepository(connection, "finance_scope").validate_entry(
                entry["id"], reason="Independent review", actor_label="checker"
            )

    def close(connection: Any) -> None:
        masters = PostgresMasterDataRepository(connection)
        masters.set_period_status(tenant_id="finance_scope", period_id="period", status="Soft Closed")
        masters.set_period_status(tenant_id="finance_scope", period_id="period", status="Closed")

    def second() -> str:
        try:
            with db["boundary"].transaction(
                "finance_scope", **({"workspace_id": "shared"} if review_first else SCOPE)
            ) as connection:
                connection.execute("SET LOCAL statement_timeout='10s'")
                backends.put(connection.execute("SELECT pg_backend_pid()").fetchone()[0])
                (close if review_first else review)(connection)
            return "accepted"
        except PlatformError as exc:
            assert "Open" in str(exc)
            return "period_closed"

    with ThreadPoolExecutor(max_workers=1) as executor:
        with db["boundary"].transaction(
            "finance_scope", **(SCOPE if review_first else {"workspace_id": "shared"})
        ) as connection:
            (review if review_first else close)(connection)
            future = executor.submit(second)
            _wait_for_lock(db["admin"], backends.get(timeout=10))
        assert future.result(timeout=15) == ("accepted" if review_first else "period_closed")
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        row = connection.execute(
            "SELECT status,validation_digest FROM reconforge.finance_entries WHERE id=%s", (entry["id"],)
        ).fetchone()
        assert row[0] == ("Validated" if review_first else "Draft")
        assert (row[1] is not None) == review_first


@pytest.mark.parametrize("column", ["validator_actor_id", "validation_contract_version", "reverses_posting_id"])
def test_live_downgrade_refuses_partial_operator_provenance(posting_database: dict[str, Any], column: str) -> None:
    """Simulate a partial out-of-band restore; downgrade must not erase it."""
    import psycopg

    from alembic import command

    db = posting_database
    with psycopg.connect(db["admin"]) as admin:
        # Deliberate owner-only fault injection in this disposable database.
        admin.execute("SET LOCAL session_replication_role=replica")
        admin.execute(
            psycopg.sql.SQL(
                "UPDATE reconforge.finance_entries SET {}='retained-partial-provenance' WHERE id=%s"
            ).format(psycopg.sql.Identifier(column)),
            (db["entries"]["A1"],),
        )
    with pytest.raises(Exception, match="Refusing to discard"):
        command.downgrade(db["config"], "0097_pg_reconciliation_seal")
    with psycopg.connect(db["admin"]) as admin:
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0098_pg_finance_posting"
        assert (
            admin.execute(
                psycopg.sql.SQL("SELECT {} FROM reconforge.finance_entries WHERE id=%s").format(
                    psycopg.sql.Identifier(column)
                ),
                (db["entries"]["A1"],),
            ).fetchone()[0]
            == "retained-partial-provenance"
        )
