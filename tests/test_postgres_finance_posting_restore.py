"""Native populated restore of immutable postings, replay and review provenance."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any
from uuid import uuid4

import pytest

from reconforge.domain.finance_posting import FinancePostingError, canonical_json, digest_payload
from reconforge.infrastructure.postgres import (
    PostgresRuntimePooledConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
)
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository
from reconforge.platform.common import server_principal_context
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
from tests.test_postgres_finance_scope_restore import NativeTool, _history, native_tools

__all__ = ["finance_database", "isolated_postgres_migration_dsn", "posting_database", "native_tools"]


def posting_history(connection: Any) -> dict[str, str]:
    from psycopg import sql

    result = _history(connection)
    for table in ("finance_posting_effects", "finance_posting_commands", "currency_registry_snapshots"):
        rows = connection.execute(sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier("reconforge", table)))
        values = sorted(json.dumps(row[0], sort_keys=True, separators=(",", ":")) for row in rows)
        result[table] = hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
    return result


def verify_native_posting_restore(db: dict[str, Any], native: NativeTool) -> dict[str, Any]:
    """A real pg_dump/pg_restore transport may execute locally or in Docker."""
    import psycopg
    from psycopg import sql

    entry_id, digest = reviewed(db, "RESTORE-POSTING")
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        posting = PostgresFinancePostingRepository(connection, "finance_scope")
        original = posting.post(
            entry_id,
            command_id="restore-original",
            expected_validation_digest=digest,
            reason="Retained native restore",
            actor=CHECKER,
        )
        draft = posting.prepare_reversal(
            original["id"],
            command_id="restore-prepare",
            entry_number="RESTORE-REVERSE",
            period_id="period",
            posting_date="2026-07-29",
            reason="Native restore correction",
            actor=MAKER,
        )
        with server_principal_context(principal(CHECKER)):
            PostgresFinanceCoreRepository(connection, "finance_scope").validate_entry(
                draft["entry_id"], reason="Independent reversal review", actor_label="checker"
            )
        reverse_digest = posting.preview(draft["entry_id"], actor=CHECKER)["validation_digest"]
        reverse = posting.post(
            draft["entry_id"],
            command_id="restore-reversal",
            expected_validation_digest=reverse_digest,
            reason="Reviewed correction",
            actor=CHECKER,
        )
        reverse_preview = posting.preview(draft["entry_id"], actor=CHECKER)
        balance = posting.posted_trial_balance(
            period_id="period", organization_code="ORG_A", entity_code="A1", workspace="shared", actor=CHECKER
        )
        assert balance["balance_totals"] == {"debit_minor": 0, "credit_minor": 0, "balanced": True}
        as_of_args = dict(period_id="period", organization_code="ORG_A", entity_code="A1", workspace="shared", actor=CHECKER)
        as_of_early = posting.posted_balances_as_of(as_of_date="2026-07-28", **as_of_args)
        as_of_final = posting.posted_balances_as_of(as_of_date="2026-07-31", **as_of_args)
        assert as_of_early["totals"]["closing"]["balance_totals"]["debit_minor"] == 10000
        assert as_of_final["totals"]["closing"]["balance_totals"]["debit_minor"] == 0
    params = psycopg.conninfo.conninfo_to_dict(db["admin"])
    restored_name = "reconforge_posting_restore_" + uuid4().hex[:20]
    with psycopg.connect(db["admin"], autocommit=True) as admin:
        before = posting_history(admin)
        revision = admin.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        legacy = admin.execute(
            "SELECT id,preparer_actor_id,validator_actor_id,validation_digest,validation_contract_version,reverses_posting_id FROM reconforge.finance_entries WHERE preparer_actor_id IS NULL ORDER BY id"
        ).fetchall()
        assert len(legacy) == 4
        policies = admin.execute(
            "SELECT tablename,policyname,qual,with_check FROM pg_policies WHERE schemaname='reconforge' AND tablename LIKE 'finance_posting_%' ORDER BY tablename,policyname"
        ).fetchall()
        dump = native("pg_dump", ["--format=custom", "--dbname", params["dbname"]], None)
        assert dump.startswith(b"PGDMP")
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restored_name)))
    factory = None
    try:
        native("pg_restore", ["--exit-on-error", "--no-owner", "--dbname", restored_name], dump)
        restored_admin = psycopg.conninfo.make_conninfo(**{**params, "dbname": restored_name})
        with psycopg.connect(restored_admin) as admin:
            runtime_role = psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_DSN"])["user"]
            assert admin.execute(
                "SELECT has_table_privilege(%s,'reconforge.operational_finance_plans','SELECT'),"
                "has_table_privilege(%s,'reconforge.operational_finance_plans','INSERT'),"
                "has_table_privilege(%s,'reconforge.operational_finance_plans','UPDATE'),"
                "has_table_privilege(%s,'reconforge.operational_finance_plans','DELETE')",
                (runtime_role,) * 4,
            ).fetchone() == (True, False, False, False)
            assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == revision
            assert posting_history(admin) == before
            assert (
                admin.execute(
                    "SELECT id,preparer_actor_id,validator_actor_id,validation_digest,validation_contract_version,reverses_posting_id FROM reconforge.finance_entries WHERE preparer_actor_id IS NULL ORDER BY id"
                ).fetchall()
                == legacy
            )
            assert (
                admin.execute(
                    "SELECT tablename,policyname,qual,with_check FROM pg_policies WHERE schemaname='reconforge' AND tablename LIKE 'finance_posting_%' ORDER BY tablename,policyname"
                ).fetchall()
                == policies
            )
        app = psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_DSN"])
        app["dbname"] = restored_name
        factory = PostgresRuntimePooledConnectionFactory(
            PostgresSettings(dsn=psycopg.conninfo.make_conninfo(**app), require_tls=False)
        )
        boundary = PostgresTenantBoundary(factory)
        with boundary.transaction("finance_scope", **SCOPE) as connection:
            posting = PostgresFinancePostingRepository(connection, "finance_scope")
            assert posting.get_effect(original["id"], actor=CHECKER) == original
            assert posting.get_effect(reverse["id"], actor=CHECKER) == reverse
            assert posting.preview(draft["entry_id"], actor=CHECKER) == reverse_preview
            assert (
                posting.post(
                    entry_id,
                    command_id="restore-original",
                    expected_validation_digest=digest,
                    reason="Retained native restore",
                    actor=CHECKER,
                )
                == original
            )
            assert (
                posting.posted_trial_balance(
                    period_id="period", organization_code="ORG_A", entity_code="A1", workspace="shared", actor=CHECKER
                )
                == balance
            )
            assert posting.posted_balances_as_of(as_of_date="2026-07-28", **as_of_args) == as_of_early
            assert posting.posted_balances_as_of(as_of_date="2026-07-31", **as_of_args) == as_of_final
            for statement in (
                "UPDATE reconforge.finance_entries SET description='changed' WHERE id=%s",
                "DELETE FROM reconforge.finance_entry_lines WHERE entry_id=%s",
                "DELETE FROM reconforge.finance_posting_effects WHERE entry_id=%s",
            ):
                with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
                    connection.execute(statement, (entry_id,))
            for statement in (
                "UPDATE reconforge.finance_entries SET validator_actor_id='wrong-reviewer' WHERE id=%s",
                "UPDATE reconforge.finance_entries SET reverses_posting_id=NULL WHERE id=%s",
                "DELETE FROM reconforge.finance_entries WHERE id=%s",
            ):
                with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
                    connection.execute(statement, (draft["entry_id"],))
            receipt_insert = """INSERT INTO reconforge.finance_posting_commands
             (tenant_id,workspace_id,organization_id,legal_entity_id,command_id,operation,actor_id,request_digest,result_json,created_at)
             VALUES('finance_scope','shared','org_a','entity_a1',%s,'post',%s,%s,%s::jsonb,'2026-10-03T00:00:00Z')"""
            with (
                pytest.raises(psycopg.errors.CheckViolation, match="committed posting effect"),
                connection.transaction(),
            ):
                connection.execute(
                    receipt_insert,
                    (
                        "absent-effect",
                        CHECKER.user_id,
                        "0" * 64,
                        canonical_json({**original, "id": "PST-absent-after-restore"}),
                    ),
                )
            with pytest.raises(RuntimeError, match="Discard synthetic receipt probe"), connection.transaction():
                request_digest = digest_payload(
                    {
                        "operation": "post",
                        "actor_id": CHECKER.user_id,
                        "workspace_id": "shared",
                        "entry_id": draft["entry_id"],
                        "expected_validation_digest": reverse_digest,
                        "reason": "Reviewed correction",
                    }
                )
                connection.execute(
                    receipt_insert, ("wrong-restored-source", CHECKER.user_id, request_digest, canonical_json(original))
                )
                with pytest.raises(FinancePostingError) as error:
                    posting.post(
                        draft["entry_id"],
                        command_id="wrong-restored-source",
                        expected_validation_digest=reverse_digest,
                        reason="Reviewed correction",
                        actor=CHECKER,
                    )
                assert error.value.code == "posting_evidence_invalid"
                raise RuntimeError("Discard synthetic receipt probe")
            with pytest.raises(FinancePostingError, match="legacy provenance"):
                posting.post(
                    db["entries"]["A1"],
                    command_id="legacy-denied",
                    expected_validation_digest=digest,
                    reason="Cannot infer old review",
                    actor=CHECKER,
                )
        with boundary.transaction(
            "finance_scope", organization_id="org_a", workspace_id="shared", legal_entity_id="entity_a2"
        ) as connection:
            assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects").fetchone()[0] == 0
            assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_commands").fetchone()[0] == 0
            with pytest.raises(FinancePostingError):
                PostgresFinancePostingRepository(connection, "finance_scope").get_effect(original["id"], actor=CHECKER)
        for column in ("audit_event_id", "outbox_event_id"):
            # Simulate a restored reference redirected to another valid retained row.
            # Only the synthetic fixture administrator can bypass immutable history.
            update_reference = sql.SQL("UPDATE reconforge.finance_posting_effects SET {}=%s WHERE id=%s").format(
                sql.Identifier(column)
            )
            with psycopg.connect(restored_admin) as admin:
                admin.execute("SET LOCAL session_replication_role=replica")
                admin.execute(update_reference, (reverse[column], original["id"]))
            try:
                with boundary.transaction("finance_scope", **SCOPE) as connection:
                    posting = PostgresFinancePostingRepository(connection, "finance_scope")
                    with pytest.raises(FinancePostingError) as error:
                        posting.get_effect(original["id"], actor=CHECKER)
                    assert error.value.code == "posting_evidence_invalid"
                    with pytest.raises(FinancePostingError) as error:
                        posting.post(
                            entry_id,
                            command_id="restore-original",
                            expected_validation_digest=digest,
                            reason="Retained native restore",
                            actor=CHECKER,
                        )
                    assert error.value.code == "posting_evidence_invalid"
            finally:
                with psycopg.connect(restored_admin) as admin:
                    admin.execute("SET LOCAL session_replication_role=replica")
                    admin.execute(update_reference, (original[column], original["id"]))
        with psycopg.connect(restored_admin) as admin:
            assert posting_history(admin) == before
        with psycopg.connect(db["admin"]) as admin:
            assert posting_history(admin) == before
    finally:
        if factory is not None:
            factory.close()
        with psycopg.connect(db["admin"], autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()",
                (restored_name,),
            )
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(restored_name)))
            assert admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (restored_name,)).fetchone() is None
    return {
        "revision": revision,
        "dump_sha256": hashlib.sha256(dump).hexdigest(),
        "dump_bytes": len(dump),
        "table_digests": before,
        "effects": 2,
        "command_receipts": 3,
        "legacy_null_count": len(legacy),
        "policies_equal": True,
        "exact_replay": True,
        "scoped_denials": True,
        "immutability": True,
        "balance_scope": "selected-period-net-activity",
        "selected_period_net_balance_zero": True,
        "business_date_as_of_reports_preserved": True,
        "as_of_early_report_digest": as_of_early["report_digest"],
        "as_of_final_report_digest": as_of_final["report_digest"],
        "absent_effect_receipt_denied": True,
        "cross_source_receipt_replay_denied": True,
        "review_and_reversal_provenance_retained": True,
        "audit_and_outbox_reference_substitution_denied": True,
        "source_unchanged": True,
        "restored_database_removed": True,
    }


def test_live_populated_posting_native_restore(posting_database: dict[str, Any], native_tools: NativeTool) -> None:
    verify_native_posting_restore(posting_database, native_tools)
