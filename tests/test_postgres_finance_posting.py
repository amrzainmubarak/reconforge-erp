"""Actual nonowner PostgreSQL posting, replay, reversal and immutable effects."""

from __future__ import annotations

import ast
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from typing import Any

import pytest

from reconforge.auth.models import LocalUser
from reconforge.domain.finance_posting import FinancePostingError, PostingActor, canonical_json, digest_payload
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_finance_posting import PostgresFinancePostingRepository, posting_entry
from reconforge.infrastructure.postgres_finance_posting_schema import POSTGRES_FINANCE_POSTING_SCHEMA_SQL
from reconforge.infrastructure.postgres_master_data import PostgresMasterDataRepository
from reconforge.platform.common import PlatformError, ServerPrincipal, server_principal_context
from tests.test_postgres_finance_scope import _entry, _wait_for_lock, finance_database, isolated_postgres_migration_dsn

__all__ = ["finance_database", "isolated_postgres_migration_dsn"]
PERMISSIONS = frozenset(
    {"finance_core.read", "finance_core.manage", "finance_core.validate", "finance_core.post", "finance_core.reverse"}
)
MAKER = PostingActor("posting-maker", "maker", PERMISSIONS, step_up_active=True)
CHECKER = PostingActor("posting-checker", "checker", PERMISSIONS, step_up_active=True)
SCOPE = {"organization_id": "org_a", "workspace_id": "shared", "legal_entity_id": "entity_a1"}


def principal(actor: PostingActor) -> ServerPrincipal:
    return ServerPrincipal(
        LocalUser(id=actor.user_id, username=actor.username, display_name=actor.username),
        PERMISSIONS,
        step_up_active=True,
    )


@pytest.fixture
def posting_database(finance_database: dict[str, Any]) -> dict[str, Any]:
    import psycopg

    role = psycopg.conninfo.conninfo_to_dict(os.environ["RECONFORGE_TEST_POSTGRES_DSN"])["user"]
    with psycopg.connect(finance_database["admin"], autocommit=True) as admin:
        admin.execute(
            psycopg.sql.SQL(
                "GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.finance_posting_effects,reconforge.finance_posting_commands TO {}"
            ).format(psycopg.sql.Identifier(role))
        )
    return finance_database


def reviewed(db: dict[str, Any], number: str = "MANUAL-POSTING") -> tuple[str, str]:
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        finance = PostgresFinanceCoreRepository(connection, "finance_scope")
        with server_principal_context(principal(MAKER)):
            entry = _entry(finance, number)
        with server_principal_context(principal(CHECKER)):
            finance.validate_entry(entry["id"], reason="Independent synthetic review", actor_label="checker")
        preview = PostgresFinancePostingRepository(connection, "finance_scope").preview(entry["id"], actor=CHECKER)
        assert preview["preparer_actor_id"] == MAKER.user_id
        assert preview["validator_actor_id"] == CHECKER.user_id
        assert preview["validation_digest"] == preview["current_content_digest"]
        return entry["id"], preview["validation_digest"]


def test_posting_migration_is_frozen() -> None:
    tree = ast.parse(Path("alembic/versions/0098_postgres_finance_posting.py").read_text())
    values = {
        target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert values["revision"] == "0098_pg_finance_posting"
    assert values["down_revision"] == "0097_pg_reconciliation_seal"
    assert values["UPGRADE_SQL"] == POSTGRES_FINANCE_POSTING_SCHEMA_SQL


def test_live_posting_exact_replay_reversal_and_posted_only_balance(posting_database: dict[str, Any]) -> None:
    import psycopg

    db = posting_database
    entry_id, digest = reviewed(db)
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        posting = PostgresFinancePostingRepository(connection, "finance_scope")
        effect = posting.post(
            entry_id,
            command_id="post-original",
            expected_validation_digest=digest,
            reason="Explicit synthetic posting",
            actor=CHECKER,
        )
        assert (
            posting.post(
                entry_id,
                command_id="post-original",
                expected_validation_digest=digest,
                reason="Explicit synthetic posting",
                actor=CHECKER,
            )
            == effect
        )
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects").fetchone()[0] == 1
        balance = posting.posted_trial_balance(
            period_id="period", organization_code="ORG_A", entity_code="A1", workspace="shared", actor=CHECKER
        )
        assert balance["totals"] == {"debit_minor": 10000, "credit_minor": 10000, "balanced": True}
        assert balance["balance_totals"] == {"debit_minor": 10000, "credit_minor": 10000, "balanced": True}
        draft = posting.prepare_reversal(
            effect["id"],
            command_id="reverse-original",
            entry_number="FULL-REVERSAL",
            period_id="period",
            posting_date="2026-07-29",
            reason="Explicit correction",
            actor=MAKER,
        )
        assert (
            posting.prepare_reversal(
                effect["id"],
                command_id="reverse-original",
                entry_number="FULL-REVERSAL",
                period_id="period",
                posting_date="2026-07-29",
                reason="Explicit correction",
                actor=MAKER,
            )
            == draft
        )
        with pytest.raises(psycopg.errors.CheckViolation, match="immutable history"), connection.transaction():
            connection.execute("DELETE FROM reconforge.finance_entries WHERE id=%s", (draft["entry_id"],))
        with server_principal_context(principal(CHECKER)):
            PostgresFinanceCoreRepository(connection, "finance_scope").validate_entry(
                draft["entry_id"], reason="Independent reversal review", actor_label="checker"
            )
        reverse_digest = posting.preview(draft["entry_id"], actor=CHECKER)["validation_digest"]
        reverse = posting.post(
            draft["entry_id"],
            command_id="post-reversal",
            expected_validation_digest=reverse_digest,
            reason="Post reviewed reversal",
            actor=CHECKER,
        )
        assert reverse["reverses_effect_id"] == effect["id"]
        assert (
            posting.prepare_reversal(
                effect["id"],
                command_id="reverse-original",
                entry_number="FULL-REVERSAL",
                period_id="period",
                posting_date="2026-07-29",
                reason="Explicit correction",
                actor=MAKER,
            )
            == draft
        )
        revoked = PostingActor(
            CHECKER.user_id, CHECKER.username, PERMISSIONS - {"finance_core.reverse"}, step_up_active=True
        )
        with pytest.raises(FinancePostingError, match="finance_core.reverse"):
            posting.post(
                draft["entry_id"],
                command_id="post-reversal",
                expected_validation_digest=reverse_digest,
                reason="Post reviewed reversal",
                actor=revoked,
            )
        balance = posting.posted_trial_balance(
            period_id="period", organization_code="ORG_A", entity_code="A1", workspace="shared", actor=CHECKER
        )
        assert balance["effect_count"] == 2
        assert balance["totals"] == {"debit_minor": 20000, "credit_minor": 20000, "balanced": True}
        assert balance["balance_totals"] == {"debit_minor": 0, "credit_minor": 0, "balanced": True}
        assert all(row["balance_minor"] == 0 and len(row["postings"]) == 2 for row in balance["accounts"])


def test_live_posting_requires_provenance_independence_and_matching_command(posting_database: dict[str, Any]) -> None:
    db = posting_database
    entry_id, digest = reviewed(db)
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        posting = PostgresFinancePostingRepository(connection, "finance_scope")
        for target, seal, actor, code in (
            (db["entries"]["A1"], digest, CHECKER, "posting_review_unverified"),
            (entry_id, digest, MAKER, "posting_sod_denied"),
            (entry_id, "0" * 64, CHECKER, "posting_review_changed"),
        ):
            with pytest.raises(FinancePostingError) as error:
                posting.post(
                    target, command_id="denied", expected_validation_digest=seal, reason="Synthetic", actor=actor
                )
            assert error.value.code == code
        posting.post(
            entry_id, command_id="accepted", expected_validation_digest=digest, reason="Synthetic", actor=CHECKER
        )
        with pytest.raises(FinancePostingError, match="different content"):
            posting.post(
                entry_id,
                command_id="accepted",
                expected_validation_digest=digest,
                reason="Changed request",
                actor=CHECKER,
            )
        with pytest.raises(FinancePostingError, match="already has"):
            posting.post(
                entry_id, command_id="another", expected_validation_digest=digest, reason="Synthetic", actor=CHECKER
            )


def test_live_posted_raw_mutations_and_sibling_access_are_denied(posting_database: dict[str, Any]) -> None:
    import psycopg

    db = posting_database
    entry_id, digest = reviewed(db)
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        posting = PostgresFinancePostingRepository(connection, "finance_scope")
        effect = posting.post(
            entry_id, command_id="post", expected_validation_digest=digest, reason="Synthetic", actor=CHECKER
        )
        forged = {**effect, "tenant_id": "finance_scope", "id": "PST-forged"}
        forged["snapshot_json"] = {**forged.pop("snapshot"), "unknown": "unreviewed evidence"}
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="exact stored financial content"),
            connection.transaction(),
        ):
            connection.execute(
                "INSERT INTO reconforge.finance_posting_effects SELECT * FROM jsonb_populate_record(NULL::reconforge.finance_posting_effects,%s::jsonb)",
                (canonical_json(forged),),
            )
        for sql in (
            "UPDATE reconforge.finance_entries SET description='changed' WHERE id=%s",
            "DELETE FROM reconforge.finance_entries WHERE id=%s",
            "UPDATE reconforge.finance_entry_lines SET debit_minor=1 WHERE entry_id=%s AND debit_minor>0",
            "DELETE FROM reconforge.finance_entry_lines WHERE entry_id=%s",
            "DELETE FROM reconforge.finance_entry_line_dimensions WHERE entry_line_id IN (SELECT id FROM reconforge.finance_entry_lines WHERE entry_id=%s)",
            "DELETE FROM reconforge.finance_posting_effects WHERE entry_id=%s",
        ):
            with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
                connection.execute(sql, (entry_id,))
        with pytest.raises(Exception, match="immutable"):
            PostgresFinanceCoreRepository(connection, "finance_scope").void_entry(
                entry_id, reason="Cannot void posted effect", actor_label="checker"
            )
    with db["boundary"].transaction(
        "finance_scope", organization_id="org_a", workspace_id="shared", legal_entity_id="entity_a2"
    ) as connection:
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_commands").fetchone()[0] == 0
        with pytest.raises(FinancePostingError, match="authorized scope"):
            PostgresFinancePostingRepository(connection, "finance_scope").get_effect(effect["id"], actor=CHECKER)


def test_live_posting_final_receipt_failure_rolls_back_effect_and_evidence(
    posting_database: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    db = posting_database
    entry_id, digest = reviewed(db)
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        posting = PostgresFinancePostingRepository(connection, "finance_scope")
        before = [
            connection.execute(f"SELECT count(*) FROM reconforge.{table}").fetchone()[0]
            for table in ("domain_audit_events", "outbox_events", "finance_posting_effects", "finance_posting_commands")
        ]

        def refuse(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("Synthetic receipt write failure")

        monkeypatch.setattr(posting, "_receipt", refuse)
        with pytest.raises(RuntimeError, match="Synthetic"):
            posting.post(
                entry_id, command_id="fail", expected_validation_digest=digest, reason="Synthetic", actor=CHECKER
            )
        after = [
            connection.execute(f"SELECT count(*) FROM reconforge.{table}").fetchone()[0]
            for table in ("domain_audit_events", "outbox_events", "finance_posting_effects", "finance_posting_commands")
        ]
        assert after == before


@pytest.mark.parametrize("posting_first", [True, False])
def test_live_period_close_and_post_serialize(posting_database: dict[str, Any], posting_first: bool) -> None:
    db = posting_database
    entry_id, digest = reviewed(db)
    backends: Queue[int] = Queue()

    def close(connection: Any) -> None:
        masters = PostgresMasterDataRepository(connection)
        masters.set_period_status(tenant_id="finance_scope", period_id="period", status="Soft Closed")
        masters.set_period_status(tenant_id="finance_scope", period_id="period", status="Closed")

    def post(connection: Any) -> None:
        PostgresFinancePostingRepository(connection, "finance_scope").post(
            entry_id, command_id="race", expected_validation_digest=digest, reason="Synthetic race", actor=CHECKER
        )

    def second() -> str:
        try:
            with db["boundary"].transaction(
                "finance_scope", **({"workspace_id": "shared"} if posting_first else SCOPE)
            ) as connection:
                connection.execute("SET LOCAL statement_timeout='10s'")
                backends.put(connection.execute("SELECT pg_backend_pid()").fetchone()[0])
                (close if posting_first else post)(connection)
            return "accepted"
        except FinancePostingError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=1) as executor:
        with db["boundary"].transaction(
            "finance_scope", **(SCOPE if posting_first else {"workspace_id": "shared"})
        ) as first:
            (post if posting_first else close)(first)
            future = executor.submit(second)
            _wait_for_lock(db["admin"], backends.get(timeout=10))
        assert future.result(timeout=15) == ("accepted" if posting_first else "posting_period_closed")
    if posting_first:
        with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
            # Acknowledgement recovery replays the committed result even after close.
            post(connection)
            assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects").fetchone()[0] == 1


def test_live_raw_receipt_cannot_claim_an_absent_posting(posting_database: dict[str, Any]) -> None:
    import psycopg

    db = posting_database
    entry_id, digest = reviewed(db)
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        posting = PostgresFinancePostingRepository(connection, "finance_scope")
        with pytest.raises(RuntimeError, match="Rollback template"), connection.transaction():
            template = posting.post(
                entry_id,
                command_id="forged-receipt",
                expected_validation_digest=digest,
                reason="Synthetic forgery probe",
                actor=CHECKER,
            )
            raise RuntimeError("Rollback template")
        assert connection.execute("SELECT count(*) FROM reconforge.finance_posting_effects").fetchone()[0] == 0
        request_digest = digest_payload(
            {
                "operation": "post",
                "actor_id": CHECKER.user_id,
                "workspace_id": "shared",
                "entry_id": entry_id,
                "expected_validation_digest": digest,
                "reason": "Synthetic forgery probe",
            }
        )
        with pytest.raises(psycopg.errors.CheckViolation, match="committed posting effect"), connection.transaction():
            connection.execute(
                """INSERT INTO reconforge.finance_posting_commands
             (tenant_id,workspace_id,organization_id,legal_entity_id,command_id,operation,actor_id,request_digest,result_json,created_at)
             VALUES('finance_scope','shared','org_a','entity_a1','forged-receipt','post',%s,%s,%s::jsonb,'2026-10-03T00:00:00Z')""",
                (CHECKER.user_id, request_digest, canonical_json(template)),
            )


def test_live_raw_receipt_cannot_claim_an_absent_reversal_draft(posting_database: dict[str, Any]) -> None:
    import psycopg

    db = posting_database
    entry_id, digest = reviewed(db)
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        posting = PostgresFinancePostingRepository(connection, "finance_scope")
        original = posting.post(
            entry_id, command_id="original", expected_validation_digest=digest, reason="Synthetic", actor=CHECKER
        )
        with pytest.raises(RuntimeError, match="Rollback template"), connection.transaction():
            template = posting.prepare_reversal(
                original["id"],
                command_id="forged-draft",
                entry_number="FORGED-DRAFT",
                period_id="period",
                posting_date="2026-07-29",
                reason="Synthetic forgery probe",
                actor=MAKER,
            )
            raise RuntimeError("Rollback template")
        with pytest.raises(psycopg.errors.CheckViolation, match="linked reversal draft"), connection.transaction():
            connection.execute(
                """INSERT INTO reconforge.finance_posting_commands
             (tenant_id,workspace_id,organization_id,legal_entity_id,command_id,operation,actor_id,request_digest,result_json,created_at)
             VALUES('finance_scope','shared','org_a','entity_a1','forged-draft','prepare_reversal',%s,%s,%s::jsonb,'2026-10-03T00:00:00Z')""",
                (MAKER.user_id, "0" * 64, canonical_json(template)),
            )


def test_live_replay_cannot_substitute_another_real_source_effect(posting_database: dict[str, Any]) -> None:
    db = posting_database
    first, first_digest = reviewed(db, "FIRST-SOURCE")
    second, second_digest = reviewed(db, "SECOND-SOURCE")
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        posting = PostgresFinancePostingRepository(connection, "finance_scope")
        effect = posting.post(
            first,
            command_id="first-source",
            expected_validation_digest=first_digest,
            reason="Original request",
            actor=CHECKER,
        )
        request_digest = digest_payload(
            {
                "operation": "post",
                "actor_id": CHECKER.user_id,
                "workspace_id": "shared",
                "entry_id": second,
                "expected_validation_digest": second_digest,
                "reason": "Borrowed acknowledgement",
            }
        )
        connection.execute(
            """INSERT INTO reconforge.finance_posting_commands
         (tenant_id,workspace_id,organization_id,legal_entity_id,command_id,operation,actor_id,request_digest,result_json,created_at)
         VALUES('finance_scope','shared','org_a','entity_a1','substituted-source','post',%s,%s,%s::jsonb,'2026-10-03T00:00:00Z')""",
            (CHECKER.user_id, request_digest, canonical_json(effect)),
        )
        with pytest.raises(FinancePostingError) as error:
            posting.post(
                second,
                command_id="substituted-source",
                expected_validation_digest=second_digest,
                reason="Borrowed acknowledgement",
                actor=CHECKER,
            )
        assert error.value.code == "posting_evidence_invalid"
        assert (
            connection.execute(
                "SELECT count(*) FROM reconforge.finance_posting_effects WHERE entry_id=%s", (second,)
            ).fetchone()[0]
            == 0
        )


def test_live_checker_cannot_replace_then_review_and_post_their_own_content(posting_database: dict[str, Any]) -> None:
    db = posting_database
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        finance = PostgresFinanceCoreRepository(connection, "finance_scope")
        posting = PostgresFinancePostingRepository(connection, "finance_scope")
        with server_principal_context(principal(MAKER)):
            original = _entry(finance, "MAKER-CONTENT")
        with pytest.raises(PlatformError, match="captured preparer"), server_principal_context(principal(CHECKER)):
            changed = finance.create_entry(
                entry_number="MAKER-CONTENT",
                organization_code="ORG_A",
                entity_code="A1",
                period_id="period",
                journal_code="J_A",
                posting_date="2026-07-28",
                description="Checker changes financial content",
                workspace="Shared",
                actor_label="checker",
                lines=[
                    {"account_code": "A_CASH", "debit": "200.00", "dimensions": {"D_A": "V", "D_SHARED": "V"}},
                    {"account_code": "A_CAPITAL", "credit": "200.00"},
                ],
            )
            finance.validate_entry(
                changed["id"], reason="Checker reviews their own changed content", actor_label="checker"
            )
            preview = posting.preview(changed["id"], actor=CHECKER)
            assert preview["preparer_actor_id"] == MAKER.user_id
            assert preview["validator_actor_id"] == CHECKER.user_id
            effect = posting.post(
                changed["id"],
                command_id="self-reviewed-content",
                expected_validation_digest=preview["validation_digest"],
                reason="Demonstrate content self-approval",
                actor=CHECKER,
            )
            assert sum(line["debit_minor"] for line in effect["snapshot"]["lines"]) == 20000
        assert finance.get_entry(original["id"])["total_debit_minor"] == 10000


def test_live_only_stable_preparer_can_replace_authenticated_draft(posting_database: dict[str, Any]) -> None:
    db = posting_database
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        finance = PostgresFinanceCoreRepository(connection, "finance_scope")
        with server_principal_context(principal(MAKER)):
            original = _entry(finance, "STABLE-MAKER")
        with pytest.raises(PlatformError, match="captured preparer"):
            _entry(finance, "STABLE-MAKER")
        renamed = PostingActor(MAKER.user_id, "renamed-preparer", PERMISSIONS, step_up_active=True)
        with server_principal_context(principal(renamed)):
            edited = finance.create_entry(
                entry_number="STABLE-MAKER",
                organization_code="ORG_A",
                entity_code="A1",
                period_id="period",
                journal_code="J_A",
                posting_date="2026-07-28",
                description="Same stable preparer after a username change",
                workspace="Shared",
                actor_label=MAKER.user_id,
                lines=[
                    {"account_code": "A_CASH", "debit": "200.00", "dimensions": {"D_A": "V", "D_SHARED": "V"}},
                    {"account_code": "A_CAPITAL", "credit": "200.00"},
                ],
            )
            assert edited["id"] == original["id"] and edited["total_debit_minor"] == 20000
            with pytest.raises(PlatformError, match="Segregation of duties"):
                finance.validate_entry(
                    edited["id"], reason="Renaming must not permit self-review", actor_label=MAKER.user_id
                )
        with server_principal_context(principal(CHECKER)):
            finance.validate_entry(
                edited["id"], reason="Independent review after preparer correction", actor_label="checker"
            )
        posting = PostgresFinancePostingRepository(connection, "finance_scope")
        preview = posting.preview(edited["id"], actor=CHECKER)
        assert preview["preparer_actor_id"] == MAKER.user_id
        effect = posting.post(
            edited["id"],
            command_id="stable-preparer",
            expected_validation_digest=preview["validation_digest"],
            reason="Independent operational posting",
            actor=CHECKER,
        )
        assert sum(line["debit_minor"] for line in effect["snapshot"]["lines"]) == 20000


@pytest.mark.parametrize("column", ["audit_event_id", "outbox_event_id"])
def test_live_posting_read_rejects_wrong_retained_evidence(posting_database: dict[str, Any], column: str) -> None:
    """A partially corrupted restore must not redirect a posting's evidence."""
    import psycopg

    db = posting_database
    first, first_digest = reviewed(db, "FIRST-EVIDENCE")
    second, second_digest = reviewed(db, "SECOND-EVIDENCE")
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        posting = PostgresFinancePostingRepository(connection, "finance_scope")
        first_effect = posting.post(
            first,
            command_id="first-evidence",
            expected_validation_digest=first_digest,
            reason="First source",
            actor=CHECKER,
        )
        second_effect = posting.post(
            second,
            command_id="second-evidence",
            expected_validation_digest=second_digest,
            reason="Second source",
            actor=CHECKER,
        )
    with psycopg.connect(db["admin"]) as admin:
        admin.execute("SET LOCAL session_replication_role=replica")
        admin.execute(
            psycopg.sql.SQL("UPDATE reconforge.finance_posting_effects SET {}=%s WHERE id=%s").format(
                psycopg.sql.Identifier(column)
            ),
            (second_effect[column], first_effect["id"]),
        )
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        posting = PostgresFinancePostingRepository(connection, "finance_scope")
        operations = (
            lambda: posting.get_effect(first_effect["id"], actor=CHECKER),
            lambda: posting.post(
                first,
                command_id="first-evidence",
                expected_validation_digest=first_digest,
                reason="First source",
                actor=CHECKER,
            ),
            lambda: posting.posted_trial_balance(
                period_id="period", organization_code="ORG_A", entity_code="A1", workspace="shared", actor=CHECKER
            ),
        )
        for operation in operations:
            with pytest.raises(FinancePostingError) as error:
                operation()
            assert error.value.code == "posting_evidence_invalid"


def test_live_raw_posting_cannot_borrow_another_effect_evidence(posting_database: dict[str, Any]) -> None:
    import psycopg

    db = posting_database
    first, first_digest = reviewed(db, "REAL-EVIDENCE")
    second, second_digest = reviewed(db, "BORROWED-EVIDENCE")
    with db["boundary"].transaction("finance_scope", **SCOPE) as connection:
        posting = PostgresFinancePostingRepository(connection, "finance_scope")
        original = posting.post(
            first, command_id="real-evidence", expected_validation_digest=first_digest, reason="Real", actor=CHECKER
        )
        with pytest.raises(RuntimeError, match="Discard template"), connection.transaction():
            template = posting.post(
                second,
                command_id="template-evidence",
                expected_validation_digest=second_digest,
                reason="Template",
                actor=CHECKER,
            )
            raise RuntimeError("Discard template")
        entry = posting_entry(connection, "finance_scope", second)
        audit_id, outbox_id = posting._evidence(entry, template["id"], "finance_entry_posted", CHECKER, second_digest)
        template["audit_event_id"], template["outbox_event_id"] = audit_id, outbox_id
        for column in ("audit_event_id", "outbox_event_id"):
            forged = {**template, "tenant_id": "finance_scope", column: original[column]}
            forged["snapshot_json"] = forged.pop("snapshot")
            with (
                pytest.raises(psycopg.errors.CheckViolation, match="exact audit and outbox evidence"),
                connection.transaction(),
            ):
                connection.execute(
                    "INSERT INTO reconforge.finance_posting_effects SELECT * FROM jsonb_populate_record(NULL::reconforge.finance_posting_effects,%s::jsonb)",
                    (canonical_json(forged),),
                )
        assert (
            connection.execute(
                "SELECT count(*) FROM reconforge.finance_posting_effects WHERE entry_id=%s", (second,)
            ).fetchone()[0]
            == 0
        )
