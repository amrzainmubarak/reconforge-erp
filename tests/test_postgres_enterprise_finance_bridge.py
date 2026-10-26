"""Restricted-role source/GL acceptance; independent rows, faults and reversals."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.domain.intercompany_elimination import (
    IntercompanyProfitInStockRule,
    calculate_profit_in_stock_elimination,
)
from reconforge.domain.project_milestone_billing import ProjectMilestone, verify_milestone_completion
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    set_local_tenant_scope,
)
from reconforge.infrastructure.postgres_enterprise_finance_bridge import PostgresEnterpriseFinanceBridge
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_intercompany_elimination import PostgresIntercompanyEliminationRepository
from reconforge.infrastructure.postgres_master_data import PostgresMasterDataRepository
from reconforge.infrastructure.postgres_project_milestone_billing import PostgresProjectMilestoneBillingRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.platform.common import current_server_principal, server_principal_context
from tests.test_postgres_people_project_payroll import (  # noqa: F401
    PeopleRuntime,
    people,
    personnel_database,
    receipt_database,
)

pytestmark = pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"),
    reason="BC-GL-01 requires the mandatory owned PostgreSQL cohort; review2026-10-25")
SCOPE = {"workspace_id": "work", "organization_id": "org", "legal_entity_id": "entity", "organization_code": "ORG", "entity_code": "ENTITY"}


@dataclass
class BridgeRuntime(PeopleRuntime):
    scope: dict[str, str] = field(default_factory=lambda: dict(SCOPE))
    journal: str = "STOCK"

    @contextmanager
    def actor(self, name: str, *, private: bool = True) -> Iterator[tuple[Any, Any, Any]]:
        with super().actor(name, private=private) as (connection, repository, actor):
            principal = current_server_principal()
            assert principal is not None
            set_local_tenant_scope(connection, self.base.tenant, "org", workspace_id="work", legal_entity_id=self.scope["legal_entity_id"])
            with server_principal_context(replace(principal, authorized_legal_entity_ids=frozenset({self.scope["legal_entity_id"]}))):
                yield connection, repository, actor

    def select_currency(self, currency: str, precision: int) -> None:
        # New legal entity from birth; never mutate retained functional currency.
        entity = "entity-" + currency.lower()
        entity_code = "ENTITY-" + currency
        self.journal = "BRIDGE-" + currency
        with PostgresTenantBoundary(self.base.factory).transaction(self.base.tenant) as connection:
            master = PostgresMasterDataRepository(connection)
            master.upsert_currency(tenant_id=self.base.tenant, code=currency, name=currency, minor_units=precision)
            master.upsert_legal_entity(tenant_id=self.base.tenant, organization_id="org", entity_id=entity,
                entity_code=entity_code, name="Synthetic " + currency, currency_code=currency)
            PostgresFinanceCoreRepository(connection, self.base.tenant).upsert_journal(journal_code=self.journal,
                name=self.journal, organization_code="ORG", currency_code=currency, workspace="work")
            for actor in ("maker", "checker", "poster"):
                PostgresScopeAuthorityRepository(connection).grant(tenant_id=self.base.tenant, grant_id="bridge-"+currency+actor,
                    principal_type="user", principal_id=actor, scope_type="legal_entity", scope_id=entity, actor_id=actor)
        self.scope.update(legal_entity_id=entity, entity_code=entity_code)


@pytest.fixture
def bridge_runtime(people: PeopleRuntime) -> BridgeRuntime:  # noqa: F811
    runtime = BridgeRuntime(people.base, people.private)
    with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in {"finance_core." + x for x in ("read", "manage", "validate", "post", "reverse")} | {
                "project_time_billing." + x for x in ("read", "manage", "review", "post")}:
            identity.create_permission(tenant_id=runtime.base.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=runtime.base.tenant, role_name="receipt-operator", permission_name=permission)
        finance = PostgresFinanceCoreRepository(connection, runtime.base.tenant)
        for account, kind in (("ACCOUNTS_RECEIVABLE", "Asset"), ("PROJECT_SERVICE_REVENUE", "Income"), ("COGS_ELIMINATION", "Expense"), ("INVENTORY_VALUATION", "Asset")):
            finance.upsert_account(account_code=account, name=account, account_type=kind, chart_code="DEFAULT", workspace="work")
    return runtime


def source(runtime: BridgeRuntime, kind: str, *, currency: str = "USD") -> str:
    if kind == "ProjectMilestone":
        with runtime.actor("maker", private=False) as (connection, _, actor):
            milestone = ProjectMilestone("work", "MS1", "PROJECT", "CONTRACT-LINE", "Delivery", 3001, currency, "2026-10-25")
            PostgresProjectMilestoneBillingRepository(connection, runtime.base.tenant).save_milestone(milestone, actor_label=actor.username, origin=runtime.scope)
        with runtime.actor("checker", private=False) as (connection, _, actor):
            repo = PostgresProjectMilestoneBillingRepository(connection, runtime.base.tenant)
            verified = verify_milestone_completion(repo.get_milestone("work", "MS1"), actor.username, "2026-10-25T00:00:00Z")
            repo.save_milestone(verified, actor_label=actor.username, origin=runtime.scope)
        return "INV1"
    rule = IntercompanyProfitInStockRule("RULE1", "SELLER", "BUYER", "ITEM", 2500, 12004, 1000, currency)
    elimination = calculate_profit_in_stock_elimination(rule)
    with runtime.actor("maker", private=False) as (connection, _, actor):
        PostgresIntercompanyEliminationRepository(connection, runtime.base.tenant).save_profit_in_stock_elimination("work", rule, elimination, actor_label=actor.username, origin=runtime.scope)
    return elimination.elimination_id


def prepare(runtime: BridgeRuntime, kind: str, source_id: str) -> dict[str, Any]:
    with runtime.actor("maker", private=False) as (connection, _, actor):
        if kind == "ProjectMilestone":
            return PostgresProjectMilestoneBillingRepository(connection, runtime.base.tenant).prepare_financial_invoice(
                "MS1", invoice_id=source_id, customer_code="CUSTOMER", issued_at="2026-10-25T00:00:00Z",
                scope=runtime.scope, period_id="period", posting_date="2026-10-25", journal_code=runtime.journal, command_id="prepare", actor=actor)
        return PostgresEnterpriseFinanceBridge(connection, runtime.base.tenant).prepare(kind, source_id,
            scope=runtime.scope, period_id="period", posting_date="2026-10-25", journal_code=runtime.journal, command_id="prepare", actor=actor)


@pytest.mark.parametrize("kind", ["ProjectMilestone", "ProfitInStock"])
@pytest.mark.parametrize("currency,precision", [("USD", 2), ("JPY", 0), ("KWD", 3)])
def test_native_prepare_review_post_exact_replay_and_full_inverse(bridge_runtime: BridgeRuntime, kind: str, currency: str, precision: int) -> None:
    runtime = bridge_runtime
    if currency != "USD":
        runtime.select_currency(currency, precision)
    identifier = source(runtime, kind, currency=currency)
    plan = prepare(runtime, kind, identifier)
    assert plan["phase"] == "Draft" and plan["amount_minor"] == "3001" and plan["currency_precision"] == precision
    assert prepare(runtime, kind, identifier) == plan
    with runtime.actor("maker", private=False) as (connection, _, actor), pytest.raises(FinancePostingError, match="distinct"):
        PostgresEnterpriseFinanceBridge(connection, runtime.base.tenant).review(plan["binding_id"], expected_source_digest=plan["source_digest"], command_id="self-review", actor=actor)
    with runtime.actor("checker", private=False) as (connection, _, actor):
        bridge = PostgresEnterpriseFinanceBridge(connection, runtime.base.tenant)
        reviewed = bridge.review(plan["binding_id"], expected_source_digest=plan["source_digest"], command_id="review", actor=actor)
        assert reviewed["phase"] == "Reviewed"
        with pytest.raises(FinancePostingError, match="third"):
            bridge.post(plan["binding_id"], expected_source_digest=plan["source_digest"], command_id="self-post", actor=actor)
    with runtime.actor("poster", private=False) as (connection, _, actor):
        bridge = PostgresEnterpriseFinanceBridge(connection, runtime.base.tenant)
        posted = bridge.post(plan["binding_id"], expected_source_digest=plan["source_digest"], command_id="post", actor=actor)
        assert posted["phase"] == "Posted" and posted["effect_id"]
        assert bridge.post(plan["binding_id"], expected_source_digest=plan["source_digest"], command_id="post", actor=actor) == posted
        effect = bridge.posting.get_effect(posted["effect_id"], actor=actor)
        assert sum(int(line["debit_minor"]) for line in effect["snapshot"]["lines"]) == 3001
        assert sum(int(line["credit_minor"]) for line in effect["snapshot"]["lines"]) == 3001
    with runtime.actor("maker", private=False) as (connection, _, actor):
        inverse = PostgresEnterpriseFinanceBridge(connection, runtime.base.tenant).reverse(plan["binding_id"], expected_source_digest=plan["source_digest"], period_id="period", posting_date="2026-10-26", reason="Full correction", command_id="inverse", actor=actor)
    with runtime.actor("checker", private=False) as (connection, _, actor):
        PostgresEnterpriseFinanceBridge(connection, runtime.base.tenant).review(inverse["binding_id"], expected_source_digest=inverse["source_digest"], command_id="inverse-review", actor=actor)
    with runtime.actor("poster", private=False) as (connection, _, actor):
        inverse_posted = PostgresEnterpriseFinanceBridge(connection, runtime.base.tenant).post(inverse["binding_id"], expected_source_digest=inverse["source_digest"], command_id="inverse-post", actor=actor)
        assert inverse_posted["phase"] == "Posted"
        rows = connection.execute("""SELECT l.account_id,sum(l.debit_minor-l.credit_minor) FROM reconforge.finance_entry_lines l
            JOIN reconforge.finance_posting_effects f ON f.tenant_id=l.tenant_id AND f.entry_id=l.entry_id
            WHERE l.tenant_id=%s GROUP BY l.account_id""", (runtime.base.tenant,)).fetchall()
        assert rows and all(int(row[1]) == 0 for row in rows)


def test_source_draft_and_milestone_rollback_on_second_stage_database_failure(bridge_runtime: PeopleRuntime) -> None:
    runtime = bridge_runtime
    identifier = source(runtime, "ProjectMilestone")
    with psycopg.connect(runtime.base.admin_dsn) as admin:
        admin.execute("""CREATE FUNCTION reconforge.bridge_test_abort() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN RAISE EXCEPTION 'synthetic binding persistence failure'; END $$;
          CREATE TRIGGER bridge_test_abort BEFORE INSERT ON reconforge.enterprise_finance_bindings
          FOR EACH ROW EXECUTE FUNCTION reconforge.bridge_test_abort();""")
    try:
        with pytest.raises(Exception, match="synthetic binding"):
            prepare(runtime, "ProjectMilestone", identifier)
        with psycopg.connect(runtime.base.admin_dsn) as admin:
            assert admin.execute("SELECT count(*) FROM reconforge.finance_entries WHERE tenant_id=%s", (runtime.base.tenant,)).fetchone()[0] == 0
            assert admin.execute("SELECT count(*) FROM reconforge.project_milestone_invoices WHERE tenant_id=%s", (runtime.base.tenant,)).fetchone()[0] == 0
            assert admin.execute("SELECT status FROM reconforge.project_milestones WHERE tenant_id=%s", (runtime.base.tenant,)).fetchone()[0] == "verified"
    finally:
        with psycopg.connect(runtime.base.admin_dsn) as admin:
            admin.execute("DROP TRIGGER bridge_test_abort ON reconforge.enterprise_finance_bindings; DROP FUNCTION reconforge.bridge_test_abort()")


def test_generic_posting_cannot_publish_a_source_owned_entry(bridge_runtime: PeopleRuntime) -> None:
    runtime = bridge_runtime
    plan = prepare(runtime, "ProjectMilestone", source(runtime, "ProjectMilestone"))
    with runtime.actor("poster", private=False) as (connection, _, actor), pytest.raises(FinancePostingError, match="source owner"):
        PostgresEnterpriseFinanceBridge(connection, runtime.base.tenant).posting.post(plan["entry_id"], expected_validation_digest=plan["validation_digest"], command_id="generic", reason="Bypass attempt", actor=actor)


def test_prepared_source_and_entry_rows_are_database_immutable_and_scope_isolated(bridge_runtime: PeopleRuntime) -> None:
    runtime = bridge_runtime
    plan = prepare(runtime, "ProjectMilestone", source(runtime, "ProjectMilestone"))
    with runtime.actor("maker", private=False) as (connection, _, actor):
        for statement in ["UPDATE reconforge.project_milestone_invoices SET billed_amount_minor=1 WHERE tenant_id=%s",
                          "UPDATE reconforge.finance_entries SET description='tampered' WHERE tenant_id=%s",
                          "DELETE FROM reconforge.enterprise_finance_bindings WHERE tenant_id=%s"]:
            with pytest.raises(psycopg.Error), connection.transaction():
                connection.execute(statement, (runtime.base.tenant,))
        assert PostgresEnterpriseFinanceBridge(connection, runtime.base.tenant).get(plan["binding_id"], actor=actor)["amount_minor"] == "3001"
        connection.execute("SELECT set_config('app.workspace_id','other',true)")
        assert connection.execute("SELECT count(*) FROM reconforge.enterprise_finance_bindings WHERE tenant_id=%s", (runtime.base.tenant,)).fetchone()[0] == 0
        assert connection.execute("UPDATE reconforge.project_milestone_invoices SET billed_amount_minor=1 WHERE tenant_id=%s", (runtime.base.tenant,)).rowcount == 0


def test_populated_bridge_native_archive_restores_all_tables_and_command_replay(
    bridge_runtime: BridgeRuntime, tmp_path: Path,
) -> None:
    """Whole database recovery, including ACL/RLS, never just exported reports."""
    from psycopg import sql

    runtime = bridge_runtime
    plan = prepare(runtime, "ProjectMilestone", source(runtime, "ProjectMilestone"))
    with runtime.actor("checker", private=False) as (connection, _, actor):
        PostgresEnterpriseFinanceBridge(connection, runtime.base.tenant).review(
            plan["binding_id"], expected_source_digest=plan["source_digest"], command_id="restore-review", actor=actor)
    with runtime.actor("poster", private=False) as (connection, _, actor):
        posted = PostgresEnterpriseFinanceBridge(connection, runtime.base.tenant).post(
            plan["binding_id"], expected_source_digest=plan["source_digest"], command_id="restore-post", actor=actor)

    def snapshot(dsn: str) -> dict[str, Any]:
        with psycopg.connect(dsn) as admin:
            tables = admin.execute("SELECT tablename,rowsecurity FROM pg_tables WHERE schemaname='reconforge' ORDER BY tablename").fetchall()
            rows = {}
            for table, _ in tables:
                rows[table] = [row[0] for row in admin.execute(sql.SQL(
                    "SELECT to_jsonb(t)::text FROM reconforge.{} t ORDER BY to_jsonb(t)::text"
                ).format(sql.Identifier(table))).fetchall()]
            flags = admin.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relnamespace='reconforge'::regnamespace AND relkind='r' ORDER BY relname").fetchall()
            return {"rows": rows, "rls": flags, "head": admin.execute("SELECT version_num FROM alembic_version").fetchone()[0]}

    before = snapshot(runtime.base.admin_dsn)
    assert {"enterprise_finance_bindings", "enterprise_finance_commands", "hcm_leave_requests", "quality_ncrs"} <= before["rows"].keys()
    # The module-scoped database also retains other tests' synthetic tenants.
    # Qualify this workflow's one binding, while restoring/comparing every row.
    own_bindings = [json.loads(row) for row in before["rows"]["enterprise_finance_bindings"]
                    if json.loads(row)["tenant_id"] == runtime.base.tenant]
    assert len(own_bindings) == 1 and own_bindings[0]["id"] == plan["binding_id"]
    dump_tool, restore_tool = shutil.which("pg_dump"), shutil.which("pg_restore")
    assert dump_tool and restore_tool, "Mandatory native PostgreSQL backup/restore tools are required"
    archive = tmp_path / "synthetic-bridge.dump"
    dumped = subprocess.run([dump_tool, "--format=custom", "--no-owner", "--file", str(archive), "--dbname", runtime.base.admin_dsn],
        capture_output=True, timeout=120, check=False)
    assert dumped.returncode == 0, hashlib.sha256(dumped.stderr).hexdigest()
    database = "reconforge_bridge_restore_" + uuid4().hex[:12]
    restored_admin = psycopg.conninfo.make_conninfo(runtime.base.admin_dsn, dbname=database)
    restored_app = psycopg.conninfo.make_conninfo(runtime.base.factory.settings.dsn, dbname=database)
    with psycopg.connect(runtime.base.admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        restored = subprocess.run([restore_tool, "--exit-on-error", "--no-owner", "--dbname", restored_admin, str(archive)],
            capture_output=True, timeout=120, check=False)
        assert restored.returncode == 0, hashlib.sha256(restored.stderr).hexdigest()
        initial_restore = snapshot(restored_admin)
        assert initial_restore == before, [key for key in before["rows"] if initial_restore["rows"][key] != before["rows"][key]]
        recovered = replace(runtime, base=replace(runtime.base, admin_dsn=restored_admin,
            factory=PostgresConnectionFactory(PostgresSettings(dsn=restored_app, require_tls=False))))
        with recovered.actor("poster", private=False) as (connection, _, actor):
            # Password authentication intentionally refreshes identity.updated_at.
            # Verify that exact effect separately, then compare every row across
            # the financial read and idempotent command without exclusions.
            authenticated = snapshot(restored_admin)
            assert [key for key in before["rows"] if authenticated["rows"][key] != before["rows"][key]] == ["identity_users"]
            original_users = {(row["tenant_id"], row["id"]): row for raw in before["rows"]["identity_users"] if (row := json.loads(raw))}
            current_users = {(row["tenant_id"], row["id"]): row for raw in authenticated["rows"]["identity_users"] if (row := json.loads(raw))}
            assert original_users.keys() == current_users.keys()
            actor_key = (runtime.base.tenant, actor.user_id)
            assert [key for key in original_users if original_users[key] != current_users[key]] == [actor_key]
            assert {key: value for key, value in original_users[actor_key].items() if key != "updated_at"} == {
                key: value for key, value in current_users[actor_key].items() if key != "updated_at"}
            role = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=session_user").fetchone()
            assert role[0] is False and role[1] is False
            bridge = PostgresEnterpriseFinanceBridge(connection, recovered.base.tenant)
            assert bridge.get(plan["binding_id"], actor=actor) == posted
            assert bridge.post(plan["binding_id"], expected_source_digest=plan["source_digest"], command_id="restore-post", actor=actor) == posted
        after = snapshot(restored_admin)
        assert after == authenticated, [key for key in before["rows"] if after["rows"][key] != authenticated["rows"][key]]
        print(json.dumps({"restored_tables": len(before["rows"]), "head": before["head"],
            "snapshot_sha256": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}))
    finally:
        with psycopg.connect(runtime.base.admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
