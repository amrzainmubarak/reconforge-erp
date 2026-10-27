"""Disposable native PostgreSQL/TLS runtime for the three repaired product views.

All identities, business records, policies and routes are real. The imported
fixtures create a unique database and use restricted PostgreSQL roles; no API
response is mocked. Passwords are generated synthetic test credentials only.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from reconforge.api import create_api_app
from reconforge.domain.crm_contracts import CustomerQuotation, Opportunity, QuotationLineItem, convert_quote_to_contract
from reconforge.domain.hcm_leave import LeaveEntitlementBalance
from reconforge.domain.people_project_payroll import EmployeeRegistration, PeopleScope
from reconforge.domain.project_milestone_billing import ProjectMilestone
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_crm_contracts import PostgresCRMContractsRepository
from reconforge.infrastructure.postgres_hcm_leave import PostgresHCMLeaveRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_project_milestone_billing import PostgresProjectMilestoneBillingRepository
from tests.https_runtime import create_localhost_certificate
from tests.test_postgres_enterprise_finance_bridge import bridge_runtime
from tests.test_postgres_inventory_receipt_posting import receipt_database
from tests.test_postgres_people_project_payroll import people, personnel_database

OUT = Path(os.environ.get("RECONFORGE_RELEASE_PRODUCT_OUT", "output/release-blocker-20261025/agent-c"))


def seed(runtime: Any) -> dict[str, str]:
    with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        for permission in ("sales.manage", "sales.approve", "people_project_payroll.personnel", "people_project_payroll.manage", "people_project_payroll.approve_time"):
            identity.create_permission(tenant_id=runtime.base.tenant, permission_name=permission)
            identity.grant_permission(tenant_id=runtime.base.tenant, role_name="receipt-operator", permission_name=permission)
    with runtime.actor("maker") as (connection, repository, actor):
        employee = repository.register_employee(EmployeeRegistration(PeopleScope("work", "org", "entity", "ORG", "ENTITY"), "SYN-BROWSER", "Synthetic employee", "maker"), command_id="browser-employee", actor=actor)
    with runtime.actor("maker", private=False) as (connection, _repository, actor):
        leave = PostgresHCMLeaveRepository(connection, runtime.base.tenant)
        leave.save_balance("work", LeaveEntitlementBalance(employee["id"], "Annual", 21, 21, 0))
        crm = PostgresCRMContractsRepository(connection, runtime.base.tenant)
        crm.save_opportunity(Opportunity("OP-BROWSER", "work", "org", "CUSTOMER", "Synthetic browser opportunity", "qualified", "2026-12-31", "USD", 9001, 5000))
        quote = CustomerQuotation("Q-BROWSER", "OP-BROWSER", "work", "CUSTOMER", "USD", "2026-12-31", actor.user_id, "submitted", (QuotationLineItem(1, "SERVICE", "Synthetic service", 1, 9001),))
        crm.save_quotation(quote, author_user_id=actor.user_id)
        contract_quote = CustomerQuotation("Q-CONTRACT", "OP-BROWSER", "work", "CUSTOMER", "USD", "2026-12-31", actor.user_id, "submitted", quote.lines)
        crm.save_quotation(contract_quote, author_user_id=actor.user_id)
        approved = contract_quote.approve("checker", "sales_rep")
        crm.save_quotation(approved)
        crm.save_contract(convert_quote_to_contract(approved, contract_id="C-BROWSER", organization_id="org", start_date="2026-10-01", end_date="2026-12-31", billing_frequency="monthly", as_of_date="2026-10-25"))
        PostgresProjectMilestoneBillingRepository(connection, runtime.base.tenant).save_milestone(ProjectMilestone("work", "MS-BROWSER", "PROJECT", "CONTRACT-LINE", "Synthetic browser deliverable", 3001, "USD", "2026-10-25"), actor_label=actor.username, origin=runtime.scope)
    return {"tenant": runtime.base.tenant, "employee_id": employee["id"], "workspace": "work", "organization": "org", "entity": "entity"}


def install_browser_fixture_endpoint(app: FastAPI, fixture: dict[str, str], key: str) -> None:
    """Expose synthetic identifiers only to the local test client, in memory."""
    allowed = {"tenant", "employee_id", "workspace", "organization", "entity", "restricted_username"}
    if not fixture.keys() <= allowed:
        raise ValueError("browser fixture contains unexpected fields")
    if len(key) != 64 or any(ch not in "0123456789abcdef" for ch in key):
        raise ValueError("invalid browser fixture key")
    metadata = fixture.copy()

    async def get_fixture(request: Request) -> JSONResponse:
        candidate = request.headers.get("x-reconforge-fixture-key", "").encode("utf-8")
        if not secrets.compare_digest(candidate, key.encode("ascii")):
            return JSONResponse({"detail": "Forbidden"}, status_code=403, headers={"Cache-Control": "no-store"})
        return JSONResponse(metadata, headers={"Cache-Control": "no-store"})

    app.add_api_route("/__test/browser-fixture", get_fixture, methods=["GET"], include_in_schema=False)
    # The Studio's catch-all static mount was registered during app creation.
    # Place this test-only endpoint ahead of it without changing production routes.
    app.router.routes.insert(0, app.router.routes.pop())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if not all(os.environ.get(key) for key in ("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", "RECONFORGE_TEST_POSTGRES_DSN", "RECONFORGE_TEST_POSTGRES_APP_USER")):
        settings = json.loads(Path("output/blocker-closure-20261025/postgres/setup.json").read_text())
        os.environ.update(RECONFORGE_TEST_POSTGRES_ADMIN_DSN=settings["admin_dsn"], RECONFORGE_TEST_POSTGRES_DSN=settings["app_dsn"], RECONFORGE_TEST_POSTGRES_APP_USER=settings["app_user"])
    database = receipt_database.__wrapped__()
    native = next(database)
    personnel = personnel_database.__wrapped__(native)
    try:
        private = next(personnel)
        password = os.environ.get("RECONFORGE_RELEASE_PRODUCT_TEST_PASSWORD")
        if not password or not password.startswith("Synthetic-browser-") or len(password) < 50:
            raise RuntimeError("a fresh synthetic browser test password is required")
        runtime = bridge_runtime.__wrapped__(people.__wrapped__(private, test_password=password))
        fixture = seed(runtime)
        with tempfile.TemporaryDirectory(prefix="reconforge-release-product-tls-") as raw:
            directory = Path(raw)
            certificate, key = create_localhost_certificate(directory)
            app = create_api_app(directory / "unused-local.db", tenant_db_root=directory / "tenants", postgres_dsn=native[1], postgres_personnel_dsn=private[2], postgres_require_tls=False, web_root=OUT / "web", allowed_hosts=("localhost",), secure_transport=True)
            install_browser_fixture_endpoint(app, fixture, os.environ.get("RECONFORGE_RELEASE_PRODUCT_FIXTURE_KEY", ""))
            uvicorn.run(app, host="127.0.0.1", port=args.port, ssl_certfile=str(certificate), ssl_keyfile=str(key), log_level="warning")
    finally:
        with suppress(StopIteration):
            next(personnel)
        with suppress(StopIteration):
            next(database)


if __name__ == "__main__":
    main()
