"""Owned synthetic PostgreSQL cash fixture, shared by HTTP and browser proofs."""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from reconforge.infrastructure.postgres import PostgresConnectionFactory, PostgresSettings, PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_receivables import PostgresReceivablesRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from reconforge.infrastructure.postgres_service_accounts import PostgresServiceAccountRepository
from reconforge.platform.receivables import ReceivableInvoiceLineInput


@dataclass(frozen=True)
class CashRuntime:
    database: str
    admin_dsn: str
    app_dsn: str
    password: str
    service_token: str
    invoice_id: str
    customer_id: str


@contextmanager
def synthetic_cash_runtime(*, target: str = "head", password: str | None = None) -> Iterator[CashRuntime]:
    import psycopg
    from psycopg import sql

    database = "reconforge_cash_" + uuid4().hex[:12]
    admin_url = urlsplit(os.environ["RECONFORGE_TEST_POSTGRES_ADMIN_DSN"])
    admin_dsn = urlunsplit(admin_url._replace(path="/" + database))
    app_dsn = psycopg.conninfo.make_conninfo(os.environ["RECONFORGE_TEST_POSTGRES_DSN"], dbname=database)
    control_dsn = psycopg.conninfo.make_conninfo(admin_dsn, dbname="postgres", connect_timeout=5)
    password = password or "Synthetic-cash-" + uuid4().hex
    with psycopg.connect(control_dsn, autocommit=True) as control:
        assert control.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None
        control.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    try:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", target], cwd=Path(__file__).resolve().parents[1], env={**os.environ, "RECONFORGE_POSTGRES_DSN": admin_dsn}, check=True, timeout=180)
        app_user = psycopg.conninfo.conninfo_to_dict(app_dsn)["user"]
        with psycopg.connect(admin_dsn) as admin:
            for statement in ("GRANT USAGE ON SCHEMA reconforge TO {}", "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {}", "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA reconforge TO {}"):
                admin.execute(sql.SQL(statement).format(sql.Identifier(app_user)))
            for tenant in ("cash-a", "cash-b"):
                admin.execute("INSERT INTO reconforge.tenants(id,name) VALUES(%s,'Synthetic cash')", (tenant,))
                for workspace in ("cash-work", "cash-other"):
                    admin.execute("INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,'Synthetic cash')", (tenant, workspace))
                admin.execute("INSERT INTO reconforge.currencies(tenant_id,code,name,minor_units) VALUES(%s,'USD','US Dollar',2)", (tenant,))
                admin.execute("INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,application_workspace_id) VALUES(%s,'cash-org','CASHORG','Synthetic','USD','cash-work')", (tenant,))
                admin.execute("INSERT INTO reconforge.master_data_workspace_organizations(tenant_id,workspace_id,organization_id) VALUES(%s,'cash-work','cash-org')", (tenant,))
                for entity in ("A", "B"):
                    admin.execute("INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) VALUES(%s,%s,'cash-org',%s,'Synthetic','USD')", (tenant, "cash-entity-" + entity.lower(), entity))
        factory = PostgresConnectionFactory(PostgresSettings(dsn=app_dsn, require_tls=False))
        service_token = invoice_id = customer_id = ""
        for tenant in ("cash-a", "cash-b"):
            with PostgresTenantBoundary(factory).transaction(tenant) as conn:
                identities = PostgresIdentityRepository(conn)
                for permission in ("receivables.manage", "receivables.read", "receivables.approve"):
                    identities.create_permission(tenant_id=tenant, permission_name=permission)
                for role, permissions in (("cashier", ("receivables.manage", "receivables.read")), ("checker", ("receivables.approve", "receivables.read")), ("reader", ("receivables.read",)), ("noaccess", ())):
                    identities.create_role(tenant_id=tenant, role_name=role)
                    for permission in permissions:
                        identities.grant_permission(tenant_id=tenant, role_name=role, permission_name=permission)
                    identities.create_user(tenant_id=tenant, user_id="cash-" + role, username=role, password=password, role_name=role)
                    for scope_type, scope_id in (("workspace", "cash-work"), ("workspace", "cash-other"), ("organization", "cash-org"), ("legal_entity", "cash-entity-a"), ("legal_entity", "cash-entity-b")):
                        PostgresScopeAuthorityRepository(conn).grant(tenant_id=tenant, grant_id=f"grant-{role}-{scope_id}", principal_type="user", principal_id="cash-" + role, scope_type=scope_type, scope_id=scope_id, actor_id="cash-" + role)
                machines = PostgresServiceAccountRepository(conn)
                machines.create_account(tenant_id=tenant, account_id="svc-cash", name="cash-machine", display_name="Synthetic cash machine", permissions={"receivables.manage", "receivables.read"}, actor_id="cash-cashier")
                issued = machines.issue_credential(tenant_id=tenant, account_id="svc-cash", actor_id="cash-cashier", ttl=timedelta(hours=1))
                PostgresScopeAuthorityRepository(conn).grant(tenant_id=tenant, grant_id="grant-service-workspace", principal_type="service_account", principal_id="svc-cash", scope_type="workspace", scope_id="cash-work", actor_id="cash-cashier")
                repo = PostgresReceivablesRepository(conn, tenant)
                for entity in ("A", "B"):
                    customer = repo.upsert_customer(customer_code="CUS-" + entity, name="Synthetic cash customer " + entity, currency_code="USD", credit_limit_minor=10000, workspace="cash-work", organization_code="CASHORG", entity_code=entity)
                    invoice = repo.create_invoice(invoice_number="INV-CASH-" + entity, customer_code="CUS-" + entity, invoice_date="2026-10-03", currency_code="USD", tax_minor=0, lines=[ReceivableInvoiceLineInput("Synthetic receivable", "1", 1376, 1376)], workspace="cash-work", organization_code="CASHORG", entity_code=entity, actor_label="fixture-maker")
                    repo.submit_invoice(str(invoice["id"]), expected_version=1, actor_label="fixture-maker")
                    repo.approve_invoice(str(invoice["id"]), expected_version=2, actor_label="fixture-checker")
                    if tenant == "cash-a" and entity == "A":
                        invoice_id, customer_id = str(invoice["id"]), str(customer["id"])
                if tenant == "cash-a":
                    service_token = issued.token
        yield CashRuntime(database, admin_dsn, app_dsn, password, service_token, invoice_id, customer_id)
    finally:
        with psycopg.connect(control_dsn, autocommit=True) as control:
            control.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))
            assert control.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone() is None
