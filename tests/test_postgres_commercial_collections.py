"""Real individual-invoice partial receipts and immutable cash ownership."""
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from reconforge.domain.commercial_collections import CommercialCollectionPreparation
from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres_commercial_collections import PostgresCommercialCollectionsRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime, receipt_database
from tests.test_postgres_stock_commerce import act, commercial_order, repository
from tests.test_postgres_stock_sales import create_stock_runtime

_ = receipt_database


def invoiced(runtime: ReceiptRuntime) -> tuple[dict[str, Any], str]:
    result = commercial_order(runtime)
    result = act(runtime, result, "open-tranche", "maker", {"line_number": 1, "quantity": "10"})
    tranche = result["lines"][0]["tranches"][0]["id"]
    for operation, who, values in (
        ("approve-tranche", "checker", {}),
        ("prepare-issue", "maker", {"posting_date": "2026-10-09", "period_id": "period", "policy_code": "FIFO"}),
        ("review-issue", "checker", {}), ("deliver", "poster", {}),
        ("prepare-invoice", "maker", {"invoice_number": "PARTIAL-AR", "invoice_date": "2026-10-09", "due_date": "2026-10-31",
            "journal_code": "SALES", "period_id": "period", "receivable_account_code": "AR", "revenue_account_code": "REVENUE"}),
        ("review-invoice", "checker", {}), ("invoice", "poster", {}),
    ):
        result = act(runtime, result, operation, who, {"tranche_id": tranche, **values})
    return result, result["lines"][0]["tranches"][0]["invoice_id"]


def prepare(runtime: ReceiptRuntime, invoice_id: str, amount: int, suffix: str = "FIRST") -> dict[str, Any]:
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCommercialCollectionsRepository(connection, runtime.tenant)
        request = CommercialCollectionPreparation(workspace_id="work", organization_id="org", legal_entity_id="entity",
            organization_code="ORG", entity_code="ENTITY", source_id=invoice_id, journal_code="CASH", period_id="period",
            posting_date="2026-10-10", debit_account_code="CASH", credit_account_code="AR", reason="Actual partial AR collection",
            amount_minor=amount, receipt_number="PARTIAL-CASH-" + suffix)
        result = owner.prepare(request, command_id="prepare-" + suffix, actor=actor)
        assert owner.prepare(request, command_id="prepare-" + suffix, actor=actor) == result
        return result


def phase(runtime: ReceiptRuntime, plan: dict[str, Any], operation: str, who: str, command: str) -> dict[str, Any]:
    with runtime.actor(who) as (connection, _, actor):
        owner = PostgresCommercialCollectionsRepository(connection, runtime.tenant)
        method = getattr(owner, operation)
        args = {"expected_plan_digest": plan["plan_digest"], "command_id": command,
                "reason": "Independent actual " + operation, "actor": actor}
        result = method(plan["id"], **args)
        assert method(plan["id"], **args) == result
        return result


def complete(runtime: ReceiptRuntime, plan: dict[str, Any], suffix: str) -> dict[str, Any]:
    return phase(runtime, phase(runtime, plan, "review", "checker", "review-" + suffix), "post", "poster", "post-" + suffix)


def test_three_partial_receipts_inside_one_invoice_conserve_independent_cash_ar_and_cogs(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    order, invoice_id = invoiced(runtime)
    expected = (10000, 15000, 20000)
    posted = [complete(runtime, prepare(runtime, invoice_id, amount, str(index)), str(index)) for index, amount in enumerate(expected)]
    with runtime.actor("maker") as (connection, _, actor):
        result = repository(connection, runtime).get(order["id"], actor=actor)
        line, tranche = result["lines"][0], result["lines"][0]["tranches"][0]
        assert line["collected_minor"] == "45000"
        assert tranche["invoice_id"] == invoice_id and tranche["invoice_status"] == "Paid"
        assert tranche["collected_minor"] == "45000" and tranche["outstanding_minor"] == "0"
        assert tranche["status"] == "Invoiced" and tranche["pending_collection"] is None
        receipts = connection.execute("SELECT amount_minor FROM reconforge.ar_receipts WHERE tenant_id=%s ORDER BY amount_minor", (runtime.tenant,)).fetchall()
        assert [row["amount_minor"] for row in receipts] == list(expected)
        totals = {row["account_code"]: (int(row["d"]), int(row["c"])) for row in connection.execute(
            """SELECT a.account_code,sum(l.debit_minor) d,sum(l.credit_minor) c FROM reconforge.finance_posting_effects f
            JOIN reconforge.finance_entry_lines l ON l.tenant_id=f.tenant_id AND l.entry_id=f.entry_id
            JOIN reconforge.finance_accounts a ON a.tenant_id=l.tenant_id AND a.id=l.account_id
            WHERE f.tenant_id=%s GROUP BY a.account_code""", (runtime.tenant,)).fetchall()}
        assert totals["CASH"] == (45000, 0) and totals["AR"] == (45000, 45000)
        assert totals["REVENUE"] == (0, 45000) and totals["COGS"] == (12000, 0)
        assert len({row["posting_effect_id"] for row in posted}) == 3
        assert connection.execute("SELECT sum(remaining_quantity_scaled) q FROM reconforge.inventory_cost_layers WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["q"] == 0
    with pytest.raises(FinancePostingError, match="positive residual"):
        prepare(runtime, invoice_id, 1, "EXCESS")


def test_partial_view_pending_claim_overpayment_and_three_person_duties(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    order, invoice_id = invoiced(runtime)
    with pytest.raises(FinancePostingError, match="residual"):
        prepare(runtime, invoice_id, 45001)
    plan = prepare(runtime, invoice_id, 10000)
    with pytest.raises(FinancePostingError, match="pending"):
        prepare(runtime, invoice_id, 5000, "OTHER")
    with pytest.raises(FinancePostingError, match="independent"):
        phase(runtime, plan, "review", "maker", "self-review")
    reviewed = phase(runtime, plan, "review", "checker", "review")
    for who in ("maker", "checker"):
        with pytest.raises(FinancePostingError, match="third authorized human"):
            phase(runtime, reviewed, "post", who, "self-post-" + who)
    phase(runtime, reviewed, "post", "poster", "post")
    with runtime.actor("maker") as (connection, _, actor):
        view = repository(connection, runtime).get(order["id"], actor=actor)
        tranche = view["lines"][0]["tranches"][0]
        assert (tranche["invoice_status"], tranche["collected_minor"], tranche["outstanding_minor"]) == ("PartiallyPaid", "10000", "35000")
    with pytest.raises(FinancePostingError, match="wholly unpaid"):
        act(runtime, order, "prepare-collection", "maker", {"tranche_id": order["lines"][0]["tranches"][0]["id"],
            "receipt_number": "INVALID-FULL", "receipt_date": "2026-10-10", "period_id": "period", "journal_code": "CASH", "cash_account_code": "CASH"})


def test_parallel_lost_ack_post_has_one_receipt_and_effect(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    _, invoice_id = invoiced(runtime)
    plan = phase(runtime, prepare(runtime, invoice_id, 10000), "review", "checker", "review")
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda _: phase(runtime, plan, "post", "poster", "lost-ack-post"), range(3)))
    assert results[0] == results[1] == results[2]
    with runtime.actor("poster") as (connection, _, _actor):
        assert connection.execute("SELECT count(*) n FROM reconforge.commercial_collection_links WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT count(*) n FROM reconforge.ar_receipts WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1


def test_distinct_concurrent_commands_claim_only_one_invoice_residual(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    _, invoice_id = invoiced(runtime)

    def claim(suffix: str) -> dict[str, Any] | str:
        try:
            return prepare(runtime, invoice_id, 30000, suffix)
        except FinancePostingError as failure:
            assert failure.code == "collection_state_conflict"
            return failure.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, ("CONCURRENT-A", "CONCURRENT-B")))
    plans = [result for result in results if isinstance(result, dict)]
    assert len(plans) == 1 and results.count("collection_state_conflict") == 1
    complete(runtime, plans[0], "CONCURRENT")
    with runtime.actor("maker") as (connection, _, _actor):
        assert connection.execute("SELECT count(*) n FROM reconforge.commercial_collection_plans WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 1
        assert connection.execute("SELECT sum(amount_minor) n FROM reconforge.ar_receipt_allocations WHERE tenant_id=%s AND invoice_id=%s", (runtime.tenant, invoice_id)).fetchone()["n"] == 30000


def test_cached_permission_revocation_and_raw_sql_birth_phase_fail_closed(receipt_database: tuple[str, str]) -> None:
    import psycopg

    runtime = create_stock_runtime(receipt_database)
    _, invoice_id = invoiced(runtime)
    plan = prepare(runtime, invoice_id, 10000)
    # The principal retains its authenticated permission snapshot. The command
    # must still read the current persisted grant inside its transaction.
    with pytest.raises(FinancePostingError, match="authorization denied"), runtime.actor("checker") as (connection, _, actor):
        assert "receivables.manage" in actor.permissions
        connection.execute("UPDATE reconforge.identity_role_permissions SET active=false,lifecycle_version=lifecycle_version+1,revoked_at=now(),revoked_by='maker',revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='receivables.manage'", (runtime.tenant,))
        PostgresCommercialCollectionsRepository(connection, runtime.tenant).review(plan["id"], expected_plan_digest=plan["plan_digest"],
            command_id="REVOKED", reason="Cached actor must not bypass revocation", actor=actor)
    with pytest.raises(psycopg.errors.CheckViolation, match="born Prepared"), runtime.actor("maker") as (connection, _, _actor):
        connection.execute("""INSERT INTO reconforge.commercial_collection_plans
            (tenant_id,id,workspace_id,organization_id,legal_entity_id,source_id,entry_id,amount_minor,phase,payload,audit_event_id,outbox_event_id)
            SELECT tenant_id,'CA1-SQL-ILLEGAL-BIRTH',workspace_id,organization_id,legal_entity_id,source_id,entry_id,amount_minor,2,payload,audit_event_id,outbox_event_id
            FROM reconforge.commercial_collection_plans WHERE tenant_id=%s AND id=%s""", (runtime.tenant, plan["id"]))
    with pytest.raises(psycopg.errors.CheckViolation, match="current persisted"), runtime.actor("maker") as (connection, _, _actor):
        connection.execute("UPDATE reconforge.identity_role_permissions SET active=false,lifecycle_version=lifecycle_version+1,revoked_at=now(),revoked_by='maker',revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='receivables.manage'", (runtime.tenant,))
        connection.execute("""INSERT INTO reconforge.commercial_collection_commands
            SELECT tenant_id,workspace_id,organization_id,legal_entity_id,plan_id,operation,'SQL-REVOKED',actor_id,request_digest,request_json,response_json
            FROM reconforge.commercial_collection_commands WHERE tenant_id=%s AND plan_id=%s AND operation='prepare'""", (runtime.tenant, plan["id"]))
    with runtime.actor("maker") as (connection, _, actor):
        assert PostgresCommercialCollectionsRepository(connection, runtime.tenant).get(plan["id"], actor=actor) == plan
        assert connection.execute("SELECT count(*) n FROM reconforge.ar_receipts WHERE tenant_id=%s", (runtime.tenant,)).fetchone()["n"] == 0


def test_prepare_ack_after_full_settlement_requires_current_sales_authority(receipt_database: tuple[str, str]) -> None:
    runtime = create_stock_runtime(receipt_database)
    _, invoice_id = invoiced(runtime)
    plan = prepare(runtime, invoice_id, 45000)
    complete(runtime, plan, "FULL")
    request = CommercialCollectionPreparation(**{key: plan[key] for key in CommercialCollectionPreparation.__dataclass_fields__})
    with runtime.actor("maker") as (connection, _, actor):
        owner = PostgresCommercialCollectionsRepository(connection, runtime.tenant)
        assert owner.prepare(request, command_id="prepare-FIRST", actor=actor) == plan
    with pytest.raises(FinancePostingError, match="authorization denied"), runtime.actor("maker") as (connection, _, actor):
        assert "sales.manage" in actor.permissions
        connection.execute("UPDATE reconforge.identity_role_permissions SET active=false,lifecycle_version=lifecycle_version+1,revoked_at=now(),revoked_by='maker',revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='sales.manage'", (runtime.tenant,))
        PostgresCommercialCollectionsRepository(connection, runtime.tenant).prepare(request, command_id="prepare-FIRST", actor=actor)


def test_known_native_receipt_conflict_preserves_every_scoped_row_and_prepare_replay(receipt_database: tuple[str, str]) -> None:
    from psycopg import sql

    from reconforge.domain.finance_posting import digest_payload
    from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository

    runtime = create_stock_runtime(receipt_database)
    _, invoice_id = invoiced(runtime)
    with runtime.actor("poster") as (connection, _, actor):
        native = PostgresReceivablesRepository(connection, runtime.tenant).post_receipt(
            receipt_number="PARTIAL-CASH-COLLISION", customer_code="CUSTOMER", receipt_date="2026-10-10",
            currency_code="USD", amount_minor=1000, workspace="work", organization_code="ORG", entity_code="ENTITY",
            actor_label=actor.username)
        assert native["allocated_minor"] == 0

    def retained(connection: Any) -> str:
        # Compare every visible tenant row, including drafts, source versions,
        # native receipts, owner commands, audit chain and outbox evidence.
        tables = connection.execute("""SELECT c.table_name FROM information_schema.columns c
            JOIN information_schema.tables t ON (t.table_schema,t.table_name)=(c.table_schema,c.table_name)
            WHERE c.table_schema='reconforge' AND c.column_name='tenant_id' AND t.table_type='BASE TABLE'
            ORDER BY c.table_name""").fetchall()
        snapshot = {}
        for table in tables:
            rows = connection.execute(sql.SQL("SELECT to_jsonb(r) value FROM reconforge.{} r WHERE tenant_id=%s ORDER BY to_jsonb(r)::text")
                .format(sql.Identifier(table["table_name"])), (runtime.tenant,)).fetchall()
            snapshot[table["table_name"]] = [row["value"] for row in rows]
        return digest_payload(snapshot)

    def refused_without_effect(number: str, command: str) -> None:
        request = CommercialCollectionPreparation(workspace_id="work", organization_id="org", legal_entity_id="entity",
            organization_code="ORG", entity_code="ENTITY", source_id=invoice_id, journal_code="CASH", period_id="period",
            posting_date="2026-10-10", debit_account_code="CASH", credit_account_code="AR", reason="Known receipt conflict",
            amount_minor=10000, receipt_number=number)
        with runtime.actor("maker") as (connection, _, actor):
            before = retained(connection)
            with pytest.raises(FinancePostingError) as refusal:
                PostgresCommercialCollectionsRepository(connection, runtime.tenant).prepare(request, command_id=command, actor=actor)
            assert refusal.value.code == "collection_receipt_conflict"  # Native API maps this exact code to HTTP 409.
            assert retained(connection) == before

    refused_without_effect("PARTIAL-CASH-COLLISION", "known-native-conflict")
    plan = prepare(runtime, invoice_id, 10000, "REPLAY-FIRST")
    refused_without_effect(plan["receipt_number"], "known-prepared-name-conflict")
    complete(runtime, plan, "REPLAY-FIRST")
    request = CommercialCollectionPreparation(**{key: plan[key] for key in CommercialCollectionPreparation.__dataclass_fields__})
    with runtime.actor("maker") as (connection, _, actor):
        before = retained(connection)
        assert PostgresCommercialCollectionsRepository(connection, runtime.tenant).prepare(
            request, command_id="prepare-REPLAY-FIRST", actor=actor) == plan
        assert retained(connection) == before
    refused_without_effect(plan["receipt_number"], "known-posted-name-conflict")


def test_sql_unowned_receipt_allocation_and_plan_mutation_are_rejected(receipt_database: tuple[str, str]) -> None:
    import psycopg

    from reconforge.application.receivables import ReceiptAllocationInput
    from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
    runtime = create_stock_runtime(receipt_database)
    _, invoice_id = invoiced(runtime)
    posted = complete(runtime, prepare(runtime, invoice_id, 10000), "first")
    with pytest.raises(psycopg.errors.CheckViolation), runtime.actor("poster") as (connection, _, actor):
        PostgresReceivablesRepository(connection, runtime.tenant).post_receipt(receipt_number="UNOWNED", customer_code="CUSTOMER",
            receipt_date="2026-10-10", currency_code="USD", amount_minor=1000, workspace="work", organization_code="ORG", entity_code="ENTITY",
            allocations=[ReceiptAllocationInput(invoice_id=invoice_id, amount_minor=1000)], actor_label=actor.username)
    with pytest.raises(psycopg.errors.CheckViolation, match="immutable"), runtime.actor("maker") as (connection, _, _actor):
        connection.execute("UPDATE reconforge.commercial_collection_plans SET amount_minor=1 WHERE tenant_id=%s AND id=%s", (runtime.tenant, posted["id"]))
    with runtime.actor("poster") as (connection, _, actor):
        assert PostgresCommercialCollectionsRepository(connection, runtime.tenant).get(posted["id"], actor=actor) == posted


def test_unrelated_worker_evidence_needs_no_collection_table_read_authority(receipt_database: tuple[str, str]) -> None:
    import psycopg
    from psycopg import sql

    from reconforge.infrastructure.postgres_domain import PostgresAuditEventRepository
    from reconforge.infrastructure.postgres_outbox import PostgresOutboxRepository
    from tests.test_postgres_inventory_receipt_posting import create_receipt_runtime

    runtime = create_receipt_runtime(receipt_database)
    app_role = psycopg.conninfo.conninfo_to_dict(receipt_database[1])["user"]
    tables = ("commercial_collection_plans", "commercial_collection_reviews", "commercial_collection_links",
              "commercial_collection_commands")
    with psycopg.connect(runtime.admin_dsn) as admin:
        for table in tables:
            admin.execute(sql.SQL("REVOKE SELECT ON reconforge.{} FROM {}")
                .format(sql.Identifier(table), sql.Identifier(app_role)))
    try:
        with runtime.actor("maker") as (connection, _, actor):
            assert not any(connection.execute("SELECT has_table_privilege(current_user,%s,'SELECT') permitted",
                ("reconforge." + table,)).fetchone()["permitted"] for table in tables)
            audit = PostgresAuditEventRepository(connection, runtime.tenant).append(actor_user_id=actor.user_id,
                actor_label=actor.username, object_type="durable_job", object_id="UNRELATED-JOB",
                action="job_completed", metadata={"schema_version": 1})
            connection.execute("""INSERT INTO reconforge.outbox_events
                (tenant_id,event_id,event_type,aggregate_type,aggregate_id,workspace_id,organization_id,legal_entity_id,payload)
                VALUES(%s,'unrelated-outbox','job_completed','durable_job','UNRELATED-JOB','work','org','entity',
                    jsonb_build_object('audit_event_id',%s::text,'schema_version',1))""", (runtime.tenant, audit.id))
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        with runtime.actor("maker") as (connection, _, _actor):
            outbox = PostgresOutboxRepository(connection)
            claims = outbox.claim_pending(tenant_id=runtime.tenant, worker_id="restricted-worker", limit=100,
                workspace_id="work", organization_id="org", legal_entity_id="entity")
            retained = next(event for event in claims if event.id == "unrelated-outbox")
            outbox.mark_published(tenant_id=runtime.tenant, event_id=retained.id,
                worker_id="restricted-worker", lease_generation=retained.lease_generation)
            connection.execute("SET CONSTRAINTS ALL IMMEDIATE")
        with runtime.actor("maker") as (connection, _, _actor):
            assert connection.execute("SELECT status FROM reconforge.outbox_events WHERE tenant_id=%s AND event_id='unrelated-outbox'",
                (runtime.tenant,)).fetchone()["status"] == "Published"
            assert connection.execute("SELECT 1 FROM reconforge.domain_audit_events WHERE tenant_id=%s AND id=%s",
                (runtime.tenant, audit.id)).fetchone() is not None
        # Restricted workers must still encounter the actual CA owner closure
        # for reserved references. No missing-table privilege is bypassed.
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="commercial_collection_plans"), runtime.actor("maker") as (connection, _, actor):
            PostgresAuditEventRepository(connection, runtime.tenant).append(actor_user_id=actor.user_id,
                actor_label=actor.username, object_type="operational_finance", object_id="CA1-RESTRICTED",
                action="commercial_collection_posted", metadata={})
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="commercial_collection_plans"), runtime.actor("maker") as (connection, _, _actor):
            connection.execute("""INSERT INTO reconforge.outbox_events
                (tenant_id,event_id,event_type,aggregate_type,aggregate_id,workspace_id,organization_id,legal_entity_id,payload)
                VALUES(%s,'CA1-RESTRICTED-OUTBOX','commercial_collection_posted','operational_finance','CA1-RESTRICTED',
                    'work','org','entity','{}'::jsonb)""", (runtime.tenant,))
    finally:
        # Restore only the fixture's existing read grants for subsequent cases.
        with psycopg.connect(runtime.admin_dsn) as admin:
            for table in tables:
                admin.execute(sql.SQL("GRANT SELECT ON reconforge.{} TO {}")
                    .format(sql.Identifier(table), sql.Identifier(app_role)))
