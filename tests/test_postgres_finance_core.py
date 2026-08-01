from __future__ import annotations

import importlib.util
import inspect
import os
import re
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

from reconforge.application.finance_core import FinanceCoreRepositoryProtocol
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
    install_postgres_rls_schema,
)
from reconforge.infrastructure.postgres_domain import install_postgres_domain_schema
from reconforge.infrastructure.postgres_finance_core import (
    POSTGRES_FINANCE_CORE_SCHEMA_SQL,
    PostgresFinanceCoreRepository,
    install_postgres_finance_core_schema,
)
from reconforge.infrastructure.postgres_master_data import (
    POSTGRES_FISCAL_PERIOD_SCHEMA_SQL,
    POSTGRES_MASTER_DATA_SCHEMA_SQL,
)
from reconforge.platform.common import PlatformError

ROOT = Path(__file__).resolve().parents[1]


def _migration() -> ModuleType:
    path = ROOT / "alembic/versions/0019_postgres_finance_core.py"
    spec = importlib.util.spec_from_file_location("migration_0019", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_finance_core_schema_has_all_aggregate_tables_and_forced_rls() -> None:
    tables = (
        "finance_charts",
        "finance_accounts",
        "finance_dimensions",
        "finance_dimension_values",
        "finance_journals",
        "finance_entries",
        "finance_entry_lines",
        "finance_entry_line_dimensions",
    )
    for table in tables:
        assert f"CREATE TABLE IF NOT EXISTS reconforge.{table}" in POSTGRES_FINANCE_CORE_SCHEMA_SQL
        assert (
            table in POSTGRES_FINANCE_CORE_SCHEMA_SQL.split("FORCE ROW LEVEL SECURITY", 1)[0]
            or table in POSTGRES_FINANCE_CORE_SCHEMA_SQL
        )
    assert "ENABLE ROW LEVEL SECURITY" in POSTGRES_FINANCE_CORE_SCHEMA_SQL
    assert "FORCE ROW LEVEL SECURITY" in POSTGRES_FINANCE_CORE_SCHEMA_SQL
    assert "current_setting(''app.tenant_id'', true)" in POSTGRES_FINANCE_CORE_SCHEMA_SQL


def test_finance_core_schema_enforces_exact_balanced_lifecycle_invariants() -> None:
    assert "total_debit_minor BIGINT" in POSTGRES_FINANCE_CORE_SCHEMA_SQL
    assert "total_credit_minor BIGINT" in POSTGRES_FINANCE_CORE_SCHEMA_SQL
    assert "CHECK (total_debit_minor = total_credit_minor)" in POSTGRES_FINANCE_CORE_SCHEMA_SQL
    assert "CHECK ((debit_minor = 0) <> (credit_minor = 0))" in POSTGRES_FINANCE_CORE_SCHEMA_SQL
    assert "status IN ('Draft','Validated','Voided')" in POSTGRES_FINANCE_CORE_SCHEMA_SQL
    assert "DOUBLE PRECISION" not in POSTGRES_FINANCE_CORE_SCHEMA_SQL
    assert " REAL " not in POSTGRES_FINANCE_CORE_SCHEMA_SQL


def test_finance_core_migration_is_linear_and_downgrade_is_dependency_ordered() -> None:
    migration = _migration()
    assert migration.revision == "0019_postgres_finance_core"
    assert migration.down_revision == "0018_postgres_intercompany"
    source = (ROOT / "alembic/versions/0019_postgres_finance_core.py").read_text(encoding="utf-8")
    positions = [
        source.index(f"DROP TABLE IF EXISTS reconforge.{table}")
        for table in (
            "finance_entry_line_dimensions",
            "finance_entry_lines",
            "finance_entries",
            "finance_journals",
            "finance_dimension_values",
            "finance_dimensions",
            "finance_accounts",
            "finance_charts",
        )
    ]
    assert positions == sorted(positions)


class _Result:
    def __init__(self, *, one: object = None, many: list[object] | None = None) -> None:
        self.one = one
        self.many = many or []

    def fetchone(self) -> object:
        return self.one

    def fetchall(self) -> list[object]:
        return self.many


class _Transaction:
    def __init__(self, connection: _ListConnection) -> None:
        self.connection = connection

    def __enter__(self) -> None:
        self.connection.entered += 1

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self.connection.exited += 1
        self.connection.rolled_back = exc is not None
        return False


class _ListConnection:
    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0
        self.rolled_back = False
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    def execute(self, query: str, parameters: tuple[object, ...] = ()) -> _Result:
        self.queries.append((query, parameters))
        if "FROM reconforge.domain_workspaces" in query:
            return _Result(one={"id": "workspace-a"})
        if "FROM reconforge.finance_charts" in query:
            return _Result(
                many=[
                    {
                        "id": "chart-a",
                        "workspace_id": "workspace-a",
                        "organization_code": "ORG",
                        "chart_code": "DEFAULT",
                        "name": "Default",
                        "description": "",
                        "active": True,
                        "created_at": "2026-07-28T00:00:00Z",
                        "updated_at": "2026-07-28T00:00:00Z",
                    }
                ]
            )
        return _Result()


def test_finance_core_chart_reads_are_tenant_scoped_and_transaction_local() -> None:
    connection = _ListConnection()
    rows = PostgresFinanceCoreRepository(connection, "tenant_a").list_charts(workspace="regulated")
    assert rows[0]["chart_code"] == "DEFAULT"
    assert connection.entered == connection.exited == 1
    assert not connection.rolled_back
    assert any("set_config('app.tenant_id'" in query for query, _ in connection.queries)
    assert any(parameters[:2] == ("tenant_a", "workspace-a") for _, parameters in connection.queries)


def test_finance_core_chart_validation_rejects_before_transaction() -> None:
    connection = _ListConnection()
    repository = PostgresFinanceCoreRepository(connection, "tenant_a")
    try:
        repository.upsert_chart(chart_code="bad code", name="Invalid")
    except PlatformError as exc:
        assert "Chart code" in str(exc)
    else:
        raise AssertionError("invalid chart code was accepted")
    assert connection.entered == 0


def test_implemented_finance_core_signatures_match_the_application_port() -> None:
    for method_name in (
        "upsert_chart",
        "list_charts",
        "upsert_account",
        "list_accounts",
        "upsert_dimension",
        "upsert_dimension_value",
        "list_dimensions",
        "list_dimension_values",
        "upsert_journal",
        "list_journals",
        "create_entry",
        "validate_entry",
        "void_entry",
        "get_entry",
        "list_entries",
        "trial_balance",
        "summary",
        "snapshot",
    ):
        adapter = inspect.signature(getattr(PostgresFinanceCoreRepository, method_name))
        protocol = inspect.signature(getattr(FinanceCoreRepositoryProtocol, method_name))
        assert tuple(adapter.parameters) == tuple(protocol.parameters)
        for name, parameter in adapter.parameters.items():
            assert parameter.kind == protocol.parameters[name].kind
            assert parameter.default == protocol.parameters[name].default


def test_account_hierarchy_and_identity_guards_are_explicit() -> None:
    source = (ROOT / "reconforge/infrastructure/postgres_finance_core.py").read_text(encoding="utf-8")
    assert "An account code cannot be moved between charts" in source
    assert "An account cannot be its own parent" in source
    assert "WITH RECURSIVE descendants" in source
    assert "Account hierarchy must remain acyclic" in source
    assert "finance_entry_lines" in source


def test_dimension_lineage_guards_are_explicit() -> None:
    source = (ROOT / "reconforge/infrastructure/postgres_finance_core.py").read_text(encoding="utf-8")
    assert "Dimensions referenced by ledger-control lines cannot be deactivated" in source
    assert "Dimension values referenced by ledger-control lines cannot be deactivated" in source
    assert "Dimension values require an active dimension" in source
    assert "finance_entry_line_dimensions" in source


def test_journal_reference_and_scope_guards_are_explicit() -> None:
    source = (ROOT / "reconforge/infrastructure/postgres_finance_core.py").read_text(encoding="utf-8")
    assert "Finance journal organization must match its chart of accounts" in source
    assert "Finance journals require an active currency reference" in source
    assert "A referenced finance journal cannot change its chart or currency" in source
    assert "Journals referenced by ledger-control entries cannot be deactivated" in source


def test_entry_lifecycle_uses_exact_money_and_maker_checker_guards() -> None:
    source = (ROOT / "reconforge/infrastructure/postgres_finance_core.py").read_text(encoding="utf-8")
    assert "Money.from_exact" in source
    assert "strict_precision=True" in source
    assert "binary floating-point" in source
    assert "Segregation of duties prevents validating your own ledger-control entry" in source
    assert "Only Draft ledger-control entries can be replaced" in source
    assert "Only Validated ledger-control entries can be voided" in source
    assert "Ledger-control entry changed concurrently; reload and retry" in source


def test_entry_integrity_rechecks_scope_accounts_dimensions_and_balance() -> None:
    source = (ROOT / "reconforge/infrastructure/postgres_finance_core.py").read_text(encoding="utf-8")
    assert "_validate_entry_integrity(entry_id)" in source
    assert "Ledger-control entry contains an inactive or inconsistent finance reference" in source
    assert "Ledger-control entry must contain at least two balanced non-zero lines" in source
    assert "Ledger-control entry contains an inactive or incompatible account" in source
    assert "Ledger-control entry is missing a required accounting dimension" in source
    assert "ledger_entry_draft_saved" in source
    assert "ledger_entry_validated" in source
    assert "ledger_entry_voided" in source


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_postgres_finance_core_lifecycle_exactness_and_rls() -> None:
    psycopg = pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not app_user:
        pytest.skip("requires a non-privileged application role")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER contains unsafe characters")
    factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    tenant_a = "finance_core_a_" + uuid4().hex[:8]
    tenant_b = "finance_core_b_" + uuid4().hex[:8]
    admin = admin_factory.connect()
    try:
        with admin.transaction():
            install_postgres_rls_schema(admin)
            install_postgres_domain_schema(admin)
            admin.execute(POSTGRES_MASTER_DATA_SCHEMA_SQL)
            admin.execute(POSTGRES_FISCAL_PERIOD_SCHEMA_SQL)
            install_postgres_finance_core_schema(admin)
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            tables = (
                "tenants,organizations,currencies,legal_entities,fiscal_periods,domain_workspaces,"
                "domain_audit_ledger_state,domain_audit_events,outbox_events,finance_charts,finance_accounts,"
                "finance_dimensions,finance_dimension_values,finance_journals,finance_entries,"
                "finance_entry_lines,finance_entry_line_dimensions"
            )
            admin.execute(
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON reconforge.{tables.replace(',', ',reconforge.')} TO {app_user}"
            )
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
        for tenant in (tenant_a, tenant_b):
            with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                connection.execute(
                    "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES (%s,%s,'Finance')",
                    (tenant, f"workspace-{tenant}"),
                )
                connection.execute(
                    "INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES (%s,'KWD','Kuwaiti Dinar',3)",
                    (tenant,),
                )
                connection.execute(
                    "INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,active) VALUES (%s,%s,'ORG','Organization','KWD',TRUE)",
                    (tenant, f"org-{tenant}"),
                )
                connection.execute(
                    "INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES (%s,%s,%s,'ENTITY','Entity','KWD')",
                    (tenant, f"entity-{tenant}", f"org-{tenant}"),
                )
                connection.execute(
                    "INSERT INTO reconforge.fiscal_periods(tenant_id,id,name,start_date,end_date,fiscal_year,period_number) VALUES (%s,'period-1','2026-07','2026-07-01','2026-07-31',2026,7)",
                    (tenant,),
                )
        with PostgresTenantBoundary(factory).transaction(tenant_a) as connection:
            repository = PostgresFinanceCoreRepository(connection, tenant_a)
            repository.upsert_chart(chart_code="DEFAULT", name="Default", workspace="Finance", organization_code="ORG")
            repository.upsert_account(
                account_code="CASH", name="Cash", workspace="Finance", account_type="Asset", normal_balance="Debit"
            )
            repository.upsert_account(
                account_code="CAPITAL",
                name="Capital",
                workspace="Finance",
                account_type="Equity",
                normal_balance="Credit",
            )
            repository.upsert_journal(
                journal_code="GENERAL",
                name="General",
                organization_code="ORG",
                currency_code="KWD",
                workspace="Finance",
            )
            draft = repository.create_entry(
                entry_number="JE/1",
                organization_code="ORG",
                entity_code="ENTITY",
                period_id="period-1",
                journal_code="GENERAL",
                posting_date="2026-07-28",
                description="Synthetic",
                workspace="Finance",
                actor_label="maker",
                lines=(
                    {"account_code": "CASH", "debit": "10.125", "credit": "0"},
                    {"account_code": "CAPITAL", "debit": "0", "credit": "10.125"},
                ),
            )
            assert draft["total_debit_minor"] == 10125
            with pytest.raises(PlatformError, match="Segregation of duties"):
                repository.validate_entry(str(draft["id"]), reason="Self approval", actor_label="maker")
            validated = repository.validate_entry(str(draft["id"]), reason="Independent review", actor_label="checker")
            assert validated["status"] == "Validated"
            assert (
                repository.trial_balance(
                    period_id="period-1", organization_code="ORG", entity_code="ENTITY", workspace="Finance"
                )["totals"]["balanced"]
                is True
            )
        with PostgresTenantBoundary(factory).transaction(tenant_b) as connection:
            assert PostgresFinanceCoreRepository(connection, tenant_b).list_entries(workspace="Finance") == []
    finally:
        for tenant in (tenant_a, tenant_b):
            try:
                with PostgresTenantBoundary(factory).transaction(tenant) as connection:
                    connection.execute("DELETE FROM reconforge.tenants WHERE id=%s", (tenant,))
            except psycopg.Error:
                pass
        admin.close()
