"""Release regressions through real PostgreSQL authentication and ordinary roles.

Only synthetic, test-owned databases are used. The fixture applies the official
Alembic chain and provisions employees through the canonical personnel service.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Event
from typing import Any

import pytest
from fastapi.testclient import TestClient

from reconforge.domain.hcm_leave import LeaveRequest
from reconforge.domain.people_project_payroll import EmployeeRegistration
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_access_administration import PostgresAccessAdministrationRepository
from reconforge.infrastructure.postgres_hcm_leave import PostgresHCMLeaveRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_people_project_payroll import SCOPE, PeopleRuntime
from tests.test_postgres_people_project_payroll_api import application, sessions

pytest_plugins = ("tests.test_postgres_people_project_payroll",)
pytestmark = pytest.mark.skipif(
    not os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN"), reason="requires owned live PostgreSQL fixture"
)
BASE = "/api/v1/hcm/leave"


@pytest.fixture()
def leave_runtime(people: PeopleRuntime) -> tuple[PeopleRuntime, dict[str, str]]:
    runtime = people
    with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
        identities = PostgresIdentityRepository(connection)
        identities.create_role(tenant_id=runtime.base.tenant, role_name="leave-personal")
        identities.grant_permission(
            tenant_id=runtime.base.tenant, role_name="leave-personal", permission_name="people_project_payroll.personnel"
        )
        for name in ("alice", "bob"):
            identities.create_user(
                tenant_id=runtime.base.tenant, user_id=name, username=name, password=runtime.base.password,
                role_name="leave-personal",
            )
            for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
                PostgresScopeAuthorityRepository(connection).grant(
                    tenant_id=runtime.base.tenant, grant_id="leave-" + name + kind, principal_type="user",
                    principal_id=name, scope_type=kind, scope_id=identifier, actor_id="maker",
                )
    employees = {}
    with runtime.actor("maker") as (_, repository, actor):
        for name in ("alice", "bob"):
            employee = repository.register_employee(
                EmployeeRegistration(SCOPE, name.upper(), "Synthetic " + name, linked_user_id=name),
                command_id="leave-employee-" + name, actor=actor,
            )
            employees[name] = employee["id"]
    return runtime, employees


def login(client: TestClient, runtime: PeopleRuntime, name: str) -> dict[str, str]:
    headers = {
        "X-ReconForge-Tenant": runtime.base.tenant, "X-ReconForge-Workspace": "work",
        "X-ReconForge-Organization": "org", "X-ReconForge-Legal-Entity": "entity",
    }
    response = client.post(
        "/api/v1/auth/login", headers=headers, json={"username": name, "password": runtime.base.password}
    )
    assert response.status_code == 200, response.text
    headers["Authorization"] = "Bearer " + response.json()["access_token"]
    response = client.post("/api/v1/auth/step-up", headers=headers, json={"password": runtime.base.password})
    assert response.status_code == 200, response.text
    return headers


def balance(client: TestClient, headers: dict[str, str], employee: str, available: int = 20) -> None:
    response = client.post(BASE + "/balances", headers=headers, json={
        "employee_id": employee, "leave_type": "Annual", "annual_entitlement_days": 30,
        "accrued_days": available, "consumed_days": 0,
    })
    assert response.status_code == 200, response.text


def submission(employee: str, identifier: str = "LEAVE-1", days: int = 5) -> dict[str, Any]:
    return {
        "request_id": identifier, "employee_id": employee, "leave_type": "Annual",
        "start_date": "2026-12-01", "end_date": "2026-12-05", "requested_days": days,
        "reason": "Synthetic private leave reason",
    }


def state(runtime: PeopleRuntime) -> tuple[Any, Any, Any, Any]:
    import psycopg

    with psycopg.connect(runtime.base.admin_dsn) as connection:
        return (
            connection.execute(
                "SELECT to_jsonb(t) FROM reconforge.hcm_leave_requests t WHERE tenant_id=%s ORDER BY request_id",
                (runtime.base.tenant,),
            ).fetchall(),
            connection.execute(
                "SELECT to_jsonb(t) FROM reconforge.hcm_leave_entitlement_balances t WHERE tenant_id=%s ORDER BY employee_id",
                (runtime.base.tenant,),
            ).fetchall(),
            connection.execute(
                "SELECT count(*) FROM reconforge.finance_posting_effects WHERE tenant_id=%s", (runtime.base.tenant,),
            ).fetchone(),
            connection.execute(
                "SELECT to_jsonb(t) FROM reconforge.domain_audit_events t WHERE tenant_id=%s "
                "AND object_type='hcm.leave' ORDER BY sequence", (runtime.base.tenant,),
            ).fetchall(),
        )


def test_native_employee_linkage_denies_foreign_or_missing_identity_without_effects(
    leave_runtime: tuple[PeopleRuntime, dict[str, str]], tmp_path: Path,
) -> None:
    runtime, employees = leave_runtime
    with TestClient(application(runtime, tmp_path), base_url="https://testserver") as client:
        manager = sessions(client, runtime)["maker"]
        alice = login(client, runtime, "alice")
        balance(client, manager, employees["alice"])
        balance(client, manager, employees["bob"])
        before = state(runtime)
        for employee in (employees["bob"], "HCE-" + "f" * 32):
            response = client.post(BASE + "/requests", headers=alice, json=submission(employee))
            assert response.status_code == 403, response.text
            assert response.json()["error"]["code"] == "leave_employee_forbidden"
            response = client.get(BASE + "/balances/" + employee + "/Annual", headers=alice)
            assert response.status_code == 403, response.text
            assert response.json()["error"]["code"] == "leave_employee_forbidden"
            assert state(runtime) == before
        response = client.post(BASE + "/requests", headers=alice, json=submission(employees["alice"]))
        assert response.status_code == 200, response.text
        assert client.get(BASE + "/balances/" + employees["alice"] + "/Annual", headers=alice).status_code == 200


def test_native_foreign_requests_cannot_be_read_calculated_or_withdrawn(
    leave_runtime: tuple[PeopleRuntime, dict[str, str]], tmp_path: Path,
) -> None:
    runtime, employees = leave_runtime
    with TestClient(application(runtime, tmp_path), base_url="https://testserver") as client:
        manager = sessions(client, runtime)["maker"]
        alice, bob = login(client, runtime, "alice"), login(client, runtime, "bob")
        balance(client, manager, employees["alice"])
        assert client.post(BASE + "/requests", headers=alice, json=submission(employees["alice"])).status_code == 200
        before = state(runtime)
        responses = (
            client.get(BASE + "/requests/LEAVE-1", headers=bob),
            client.post(BASE + "/requests/LEAVE-1/unpaid-deduction", headers=bob, json={"daily_rate_minor": 1000}),
            client.post(BASE + "/requests/LEAVE-1/withdraw", headers=bob),
        )
        assert all(response.status_code == 403 for response in responses), [response.text for response in responses]
        assert all("Synthetic private leave reason" not in response.text for response in responses)
        assert state(runtime) == before
        assert client.get(BASE + "/requests/LEAVE-1", headers=alice).status_code == 200
        assert client.get(BASE + "/requests/LEAVE-1", headers=manager).status_code == 200


def test_native_revoked_permission_and_foreign_scope_cannot_mutate_leave(
    leave_runtime: tuple[PeopleRuntime, dict[str, str]], tmp_path: Path,
) -> None:
    runtime, employees = leave_runtime
    with TestClient(application(runtime, tmp_path), base_url="https://testserver") as client:
        manager = sessions(client, runtime)["maker"]
        alice = login(client, runtime, "alice")
        balance(client, manager, employees["alice"])
        assert client.post(BASE + "/requests", headers=alice, json=submission(employees["alice"])).status_code == 200
        before = state(runtime)
        for changed in ({"X-ReconForge-Workspace": "foreign"}, {"X-ReconForge-Tenant": "foreign"}):
            response = client.post(BASE + "/requests/LEAVE-1/withdraw", headers={**alice, **changed})
            assert response.status_code in (401, 403), response.text
            assert state(runtime) == before
        with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
            identity = PostgresIdentityRepository(connection)
            identity.create_permission(tenant_id=runtime.base.tenant, permission_name="roles.manage")
            identity.grant_permission(
                tenant_id=runtime.base.tenant, role_name="receipt-operator", permission_name="roles.manage",
            )
            role = connection.execute(
                "SELECT id,lifecycle_version FROM reconforge.identity_roles WHERE tenant_id=%s AND name='leave-personal'",
                (runtime.base.tenant,),
            ).fetchone()
            change = PostgresAccessAdministrationRepository(connection, runtime.base.tenant).replace_role_permissions(
                actor_user_id="maker", role_id=role["id"], permissions=(),
                expected_lifecycle_version=role["lifecycle_version"], as_of=datetime.now(UTC).replace(microsecond=0),
            )
            assert change.revoked_sessions >= 1
        response = client.post(BASE + "/requests/LEAVE-1/withdraw", headers=alice)
        assert response.status_code == 401, response.text
        assert state(runtime) == before
        alice = login(client, runtime, "alice")
        response = client.post(BASE + "/requests/LEAVE-1/withdraw", headers=alice)
        assert response.status_code == 403, response.text
        assert state(runtime) == before


def test_native_concurrent_approvals_and_cancellations_conserve_entitlement(
    leave_runtime: tuple[PeopleRuntime, dict[str, str]], tmp_path: Path,
) -> None:
    runtime, employees = leave_runtime
    with TestClient(application(runtime, tmp_path), base_url="https://testserver") as client:
        manager = sessions(client, runtime)["maker"]
        alice = login(client, runtime, "alice")
        balance(client, manager, employees["alice"])
        for identifier in ("LEAVE-1", "LEAVE-2"):
            response = client.post(BASE + "/requests", headers=alice, json=submission(employees["alice"], identifier, 15))
            assert response.status_code == 200, response.text
        start = Barrier(2)

        def approve(identifier: str) -> tuple[str, int]:
            start.wait(timeout=10)
            return identifier, client.post(BASE + "/requests/" + identifier + "/approve", headers=manager).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(approve, ("LEAVE-1", "LEAVE-2")))
        assert sorted(status for _, status in results) == [200, 400], results
        approved = next(identifier for identifier, status in results if status == 200)
        response = client.get(BASE + "/balances/" + employees["alice"] + "/Annual", headers=alice)
        assert response.json()["consumed_days"] == 15
        start = Barrier(2)

        def cancel(_: int) -> int:
            start.wait(timeout=10)
            return client.post(
                BASE + "/requests/" + approved + "/cancel", headers=manager, json={"current_date": "2026-11-01"},
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(cancel, range(2)))
        assert sorted(statuses) == [200, 400], statuses
        response = client.get(BASE + "/balances/" + employees["alice"] + "/Annual", headers=alice)
        assert response.json()["consumed_days"] == 0


@pytest.mark.parametrize("failure", ["balance", "audit"])
def test_native_second_write_failure_rolls_back_request_and_entitlement(
    leave_runtime: tuple[PeopleRuntime, dict[str, str]], tmp_path: Path, failure: str,
) -> None:
    import psycopg
    from psycopg import sql

    runtime, employees = leave_runtime
    with TestClient(application(runtime, tmp_path), base_url="https://testserver", raise_server_exceptions=False) as client:
        manager = sessions(client, runtime)["maker"]
        alice = login(client, runtime, "alice")
        balance(client, manager, employees["alice"])
        assert client.post(BASE + "/requests", headers=alice, json=submission(employees["alice"])).status_code == 200
        before = state(runtime)
        table = "hcm_leave_entitlement_balances" if failure == "balance" else "domain_audit_events"
        with psycopg.connect(runtime.base.admin_dsn) as connection:
            connection.execute("""
                CREATE FUNCTION reconforge.reject_release_leave_balance() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                  IF TG_TABLE_NAME='hcm_leave_entitlement_balances' THEN RAISE EXCEPTION 'Synthetic balance failure'; END IF;
                  IF NEW.object_type='hcm.leave' AND NEW.action='leave_approved' THEN RAISE EXCEPTION 'Synthetic audit failure'; END IF;
                  RETURN NEW;
                END $$;
            """)
            connection.execute(sql.SQL(
                "CREATE TRIGGER release_leave_balance_failure BEFORE INSERT OR UPDATE ON reconforge.{} "
                "FOR EACH ROW EXECUTE FUNCTION reconforge.reject_release_leave_balance()"
            ).format(sql.Identifier(table)))
        try:
            response = client.post(BASE + "/requests/LEAVE-1/approve", headers=manager)
            assert response.status_code >= 400, response.text
            assert state(runtime) == before
        finally:
            with psycopg.connect(runtime.base.admin_dsn) as connection:
                connection.execute(sql.SQL("DROP TRIGGER release_leave_balance_failure ON reconforge.{}").format(sql.Identifier(table)))
                connection.execute("DROP FUNCTION reconforge.reject_release_leave_balance()")


def test_native_canonical_employee_cannot_self_approve_a_forged_legacy_owner(
    leave_runtime: tuple[PeopleRuntime, dict[str, str]], tmp_path: Path,
) -> None:
    runtime, employees = leave_runtime
    with TestClient(application(runtime, tmp_path), base_url="https://testserver") as client:
        manager = sessions(client, runtime)["maker"]
        balance(client, manager, employees["alice"])
        with PostgresTenantBoundary(runtime.base.factory).transaction(
            runtime.base.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity",
        ) as connection:
            PostgresIdentityRepository(connection).grant_permission(
                tenant_id=runtime.base.tenant, role_name="leave-personal", permission_name="people_project_payroll.approve_time",
            )
            PostgresHCMLeaveRepository(connection, runtime.base.tenant).save_request("work", LeaveRequest(
                "LEAVE-1", employees["alice"], "legacy-forged-owner", "Annual", "2026-12-01", "2026-12-05",
                5, "Submitted", "Synthetic legacy owner",
            ))
        alice = login(client, runtime, "alice")
        assert client.post("/api/v1/auth/step-up", headers=alice, json={"password": runtime.base.password}).status_code == 200
        before = state(runtime)
        response = client.post(BASE + "/requests/LEAVE-1/approve", headers=alice)
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "leave_self_approval_prohibited"
        assert state(runtime) == before


def test_native_all_enterprise_route_contracts_deny_empty_authority_without_business_effects(
    leave_runtime: tuple[PeopleRuntime, dict[str, str]], tmp_path: Path,
) -> None:
    import psycopg
    from psycopg import sql

    from reconforge.infrastructure.postgres_enterprise_modules_schema import (
        REGISTERED_MODULE_TABLES,
        RETAINED_ENTERPRISE_TABLES,
    )
    from tests.test_api_authorization_inventory import ENTERPRISE_V1_CONTRACTS

    runtime, _ = leave_runtime
    with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        identity.create_role(tenant_id=runtime.base.tenant, role_name="leave-denied")
        identity.create_user(
            tenant_id=runtime.base.tenant, user_id="no-capability", username="no-capability",
            password=runtime.base.password, role_name="leave-denied",
        )
        for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
            PostgresScopeAuthorityRepository(connection).grant(
                tenant_id=runtime.base.tenant, grant_id="denied-" + kind, principal_type="user",
                principal_id="no-capability", scope_type=kind, scope_id=identifier, actor_id="maker",
            )

    def business_rows() -> dict[str, Any]:
        with psycopg.connect(runtime.base.admin_dsn) as connection:
            return {
                table: connection.execute(sql.SQL(
                    "SELECT to_jsonb(t) FROM reconforge.{} t WHERE tenant_id=%s ORDER BY to_jsonb(t)::text"
                ).format(sql.Identifier(table)), (runtime.base.tenant,)).fetchall()
                for table in (*REGISTERED_MODULE_TABLES, *RETAINED_ENTERPRISE_TABLES, "finance_posting_effects")
            }

    before = business_rows()
    with TestClient(application(runtime, tmp_path), base_url="https://testserver") as client:
        denied = login(client, runtime, "no-capability")
        for contract in ENTERPRISE_V1_CONTRACTS:
            path = re.sub(r"\{[^}]+\}", "synthetic-foreign-id", contract.path)
            response = client.request(contract.method, path, headers=denied, json={})
            assert response.status_code == 403, (contract, response.status_code, response.text)
            assert response.json()["error"]["code"] == "permission_denied", (contract, response.text)
    assert business_rows() == before


def test_native_restricted_role_force_rls_blocks_cross_tenant_and_workspace_sql(
    leave_runtime: tuple[PeopleRuntime, dict[str, str]],
) -> None:
    import psycopg

    runtime, employees = leave_runtime
    with psycopg.connect(runtime.base.admin_dsn) as connection:
        connection.execute("INSERT INTO reconforge.tenants(id,name) VALUES('foreign-tenant','Synthetic foreign tenant')")
        for tenant, workspace in ((runtime.base.tenant, "foreign-work"), ("foreign-tenant", "work")):
            connection.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name) VALUES(%s,%s,'Synthetic foreign workspace')",
                (tenant, workspace),
            )
            connection.execute(
                "INSERT INTO reconforge.hcm_leave_entitlement_balances "
                "(tenant_id,workspace_id,employee_id,leave_type,annual_entitlement_days,accrued_days,consumed_days) "
                "VALUES(%s,%s,%s,'Annual',30,20,0)", (tenant, workspace, employees["alice"]),
            )
    with PostgresTenantBoundary(runtime.base.factory).transaction(
        runtime.base.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity",
    ) as connection:
        assert tuple(connection.execute(
            "SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb FROM pg_roles WHERE rolname=session_user"
        ).fetchone()) == (False, False, False, False)
        flags = connection.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='reconforge.hcm_leave_entitlement_balances'::regclass"
        ).fetchone()
        assert tuple(flags) == (True, True)
        assert PostgresHCMLeaveRepository(connection, runtime.base.tenant).get_balance(
            "foreign-work", employees["alice"], "Annual",
        ) is None
        assert connection.execute("SELECT count(*) FROM reconforge.hcm_leave_entitlement_balances").fetchone()[0] == 0
        assert connection.execute("UPDATE reconforge.hcm_leave_entitlement_balances SET consumed_days=9").rowcount == 0
        assert connection.execute("DELETE FROM reconforge.hcm_leave_entitlement_balances").rowcount == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute(
                "INSERT INTO reconforge.hcm_leave_entitlement_balances "
                "(tenant_id,workspace_id,employee_id,leave_type,annual_entitlement_days,accrued_days,consumed_days) "
                "VALUES(%s,'foreign-work',%s,'Annual',30,20,0)", (runtime.base.tenant, employees["alice"]),
            )


def test_native_committed_revocation_cannot_be_overtaken_by_an_authenticated_waiter(
    leave_runtime: tuple[PeopleRuntime, dict[str, str]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from reconforge.api.routes import hcm_leave as route

    runtime, employees = leave_runtime
    with TestClient(application(runtime, tmp_path), base_url="https://testserver") as client:
        manager = sessions(client, runtime)["maker"]
        alice = login(client, runtime, "alice")
        balance(client, manager, employees["alice"])
        assert client.post(BASE + "/requests", headers=alice, json=submission(employees["alice"])).status_code == 200
        before = state(runtime)
        with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
            identity = PostgresIdentityRepository(connection)
            identity.create_permission(tenant_id=runtime.base.tenant, permission_name="roles.manage")
            identity.grant_permission(tenant_id=runtime.base.tenant, role_name="receipt-operator", permission_name="roles.manage")
        waiting, release = Event(), Event()
        original = route.enterprise_transaction

        @contextmanager
        def gated_transaction(*args: Any, **kwargs: Any) -> Iterator[Any]:
            with original(*args, **kwargs) as business:
                # Pause after actual HTTP policy admission, before the native
                # persisted grant pin. Neither decision nor DB work is mocked.
                waiting.set()
                assert release.wait(timeout=15)
                yield business

        monkeypatch.setattr(route, "enterprise_transaction", gated_transaction)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.post, BASE + "/requests/LEAVE-1/approve", headers=manager)
            try:
                assert waiting.wait(timeout=15)
                with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
                    role = connection.execute(
                        "SELECT id,lifecycle_version FROM reconforge.identity_roles WHERE tenant_id=%s AND name='receipt-operator'",
                        (runtime.base.tenant,),
                    ).fetchone()
                    retained = tuple(row[0] for row in connection.execute(
                        "SELECT permission_name FROM reconforge.identity_role_permissions WHERE tenant_id=%s AND role_id=%s "
                        "AND active AND permission_name<>'people_project_payroll.approve_time' ORDER BY permission_name",
                        (runtime.base.tenant, role["id"]),
                    ))
                    PostgresAccessAdministrationRepository(connection, runtime.base.tenant).replace_role_permissions(
                        actor_user_id="maker", role_id=role["id"], permissions=retained,
                        expected_lifecycle_version=role["lifecycle_version"], as_of=datetime.now(UTC).replace(microsecond=0),
                    )
            finally:
                release.set()
            response = pending.result(timeout=15)
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "permission_denied"
        assert state(runtime) == before


@pytest.mark.parametrize("identity_mode", ["stable", "legacy", "unbound"])
def test_native_leave_identity_survives_rename_without_legacy_alias_selfclaim(
    leave_runtime: tuple[PeopleRuntime, dict[str, str]], tmp_path: Path, identity_mode: str,
) -> None:
    runtime, _ = leave_runtime
    owner_id, original_name = "stable-owner-id", "original-owner"
    with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        identity.create_role(tenant_id=runtime.base.tenant, role_name="rename-owner")
        identity.grant_permission(tenant_id=runtime.base.tenant, role_name="rename-owner", permission_name="people_project_payroll.personnel")
        identity.create_user(tenant_id=runtime.base.tenant, user_id=owner_id, username=original_name, password=runtime.base.password, role_name="rename-owner")
        for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
            PostgresScopeAuthorityRepository(connection).grant(
                tenant_id=runtime.base.tenant, grant_id="rename-" + kind, principal_type="user",
                principal_id=owner_id, scope_type=kind, scope_id=identifier, actor_id="maker",
            )
    with runtime.actor("maker") as (_, repository, actor):
        employee = repository.register_employee(
            EmployeeRegistration(SCOPE, "RENAME-OWNER", "Synthetic rename employee", None if identity_mode == "unbound" else owner_id),
            command_id="rename-employee", actor=actor,
        )["id"]
    with TestClient(application(runtime, tmp_path), base_url="https://testserver") as client:
        manager = sessions(client, runtime)["maker"]
        owner, foreign = login(client, runtime, original_name), login(client, runtime, "bob")
        balance(client, manager, employee)
        if identity_mode == "stable":
            response = client.post(BASE + "/requests", headers=owner, json=submission(employee))
            assert response.status_code == 200, response.text
        else:
            with PostgresTenantBoundary(runtime.base.factory).transaction(
                runtime.base.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity",
            ) as connection:
                PostgresHCMLeaveRepository(connection, runtime.base.tenant).save_request("work", LeaveRequest(
                    "LEAVE-1", employee, original_name, "Annual", "2026-12-01", "2026-12-05", 5,
                    "Submitted", "Synthetic historical identity",
                ))
        with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
            connection.execute("UPDATE reconforge.identity_users SET username='renamed-owner' WHERE tenant_id=%s AND id=%s", (runtime.base.tenant, owner_id))
            connection.execute("UPDATE reconforge.identity_users SET username=%s WHERE tenant_id=%s AND id='bob'", (original_name, runtime.base.tenant))
        before = state(runtime)
        response = client.get(BASE + "/requests/LEAVE-1", headers=owner)
        assert response.status_code == (403 if identity_mode == "unbound" else 200), response.text
        if identity_mode != "unbound":
            assert response.json()["employee_user_id"] == (owner_id if identity_mode == "stable" else original_name)
        denied = client.get(BASE + "/requests/LEAVE-1", headers=foreign)
        assert denied.status_code == 403, denied.text
        assert state(runtime) == before
        with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
            PostgresIdentityRepository(connection).grant_permission(
                tenant_id=runtime.base.tenant, role_name="rename-owner", permission_name="people_project_payroll.approve_time",
            )
        owner = login(client, runtime, "renamed-owner")
        for action in ("approve", "reject"):
            response = client.post(
                BASE + "/requests/LEAVE-1/" + action, headers=owner,
                json={"rejection_reason": "Synthetic self review"} if action == "reject" else None,
            )
            assert response.status_code == (403 if identity_mode == "unbound" else 400), response.text
            assert state(runtime) == before
        if identity_mode != "unbound":
            assert client.post(BASE + "/requests/LEAVE-1/withdraw", headers=owner).status_code == 200


def test_native_leave_hr_authority_cannot_cross_entity_inside_one_workspace(
    leave_runtime: tuple[PeopleRuntime, dict[str, str]], tmp_path: Path,
) -> None:
    import psycopg

    from reconforge.domain.finance_posting import PostingActor
    from reconforge.domain.people_project_payroll import PeopleScope
    from reconforge.infrastructure.postgres_people_project_payroll import PostgresPeopleProjectPayrollRepository
    from reconforge.platform.common import ServerPrincipal, server_principal_context

    runtime, employees = leave_runtime
    with psycopg.connect(runtime.base.admin_dsn) as connection:
        connection.execute(
            "INSERT INTO reconforge.legal_entities(tenant_id,id,organization_id,entity_code,name,currency_code) "
            "VALUES(%s,'entity-b','org','SIBLING','Synthetic sibling entity','USD')", (runtime.base.tenant,),
        )
    with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
        PostgresScopeAuthorityRepository(connection).grant(
            tenant_id=runtime.base.tenant, grant_id="poster-sibling", principal_type="user", principal_id="poster",
            scope_type="legal_entity", scope_id="entity-b", actor_id="maker",
        )
        identity = PostgresIdentityRepository(connection)
        user = identity.authenticate_user(tenant_id=runtime.base.tenant, username="poster", password=runtime.base.password)
        assert user is not None
        permissions = identity.user_permissions(tenant_id=runtime.base.tenant, user_id=user.id)
    with PostgresTenantBoundary(runtime.private).transaction(
        runtime.base.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity-b",
    ) as connection:
        principal = ServerPrincipal(
            user=user, permissions=permissions, step_up_active=True,
            authorized_tenant_ids=frozenset({runtime.base.tenant}), authorized_workspace_ids=frozenset({"work"}),
            authorized_organization_ids=frozenset({"org"}), authorized_legal_entity_ids=frozenset({"entity-b"}),
        )
        with server_principal_context(principal):
            connection.execute("SELECT set_config('app.personnel_actor_id',%s,true)", (user.id,))
            employee = PostgresPeopleProjectPayrollRepository(connection, runtime.base.tenant).register_employee(
                EmployeeRegistration(PeopleScope("work", "org", "entity-b", "ORG", "SIBLING"), "SIBLING-EMP", "Synthetic sibling employee", "alice"),
                command_id="sibling-employee", actor=PostingActor(user.id, user.username, permissions, step_up_active=True),
            )["id"]
            repo = PostgresHCMLeaveRepository(connection, runtime.base.tenant)
            repo.save_balance("work", __import__("reconforge.domain.hcm_leave", fromlist=["LeaveEntitlementBalance"]).LeaveEntitlementBalance(employee, "Annual", 30, 20, 0))
            repo.save_request("work", LeaveRequest("FOREIGN-ENTITY", employee, "alice", "Annual", "2026-12-01", "2026-12-05", 5, "Submitted", "Synthetic sibling private reason"))
    with TestClient(application(runtime, tmp_path), base_url="https://testserver") as client:
        manager = sessions(client, runtime)["maker"]
        balance(client, manager, employees["alice"])
        assert client.get(BASE + "/balances/" + employees["alice"] + "/Annual", headers=manager).status_code == 200
        before = state(runtime)
        denied = client.get(BASE + "/balances/" + employee + "/Annual", headers=manager)
        assert denied.status_code in (403, 404), denied.text
        assert client.get(BASE + "/requests/FOREIGN-ENTITY", headers=manager).status_code == 404
        operations = (
            (BASE + "/balances", {"employee_id": employee, "leave_type": "Annual", "annual_entitlement_days": 30, "accrued_days": 10}),
            (BASE + "/balances/" + employee + "/Annual/rollover", {"max_carryover_days": 0}),
            (BASE + "/balances/" + employee + "/Annual/accrue-prorated", {"service_days": 100, "total_year_days": 365}),
            (BASE + "/requests/FOREIGN-ENTITY/approve", None),
            (BASE + "/requests/FOREIGN-ENTITY/reject", {"rejection_reason": "Synthetic unauthorized review"}),
            (BASE + "/requests/FOREIGN-ENTITY/cancel", {"current_date": "2026-11-01"}),
            (BASE + "/requests/FOREIGN-ENTITY/unpaid-deduction", {"daily_rate_minor": 1000}),
        )
        for path, body in operations:
            response = client.post(path, headers=manager, json=body)
            assert response.status_code in (403, 404), (path, response.text)
            assert state(runtime) == before
    with PostgresTenantBoundary(runtime.base.factory).transaction(
        runtime.base.tenant, workspace_id="work", organization_id="org", legal_entity_id="entity",
    ) as connection:
        assert connection.execute(
            "SELECT count(*) FROM reconforge.hcm_leave_entitlement_balances WHERE employee_id=%s", (employee,),
        ).fetchone()[0] == 0
        assert connection.execute(
            "UPDATE reconforge.hcm_leave_entitlement_balances SET consumed_days=9 WHERE employee_id=%s", (employee,),
        ).rowcount == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute(
                "INSERT INTO reconforge.hcm_leave_entitlement_balances "
                "(tenant_id,workspace_id,employee_id,leave_type,annual_entitlement_days,accrued_days,consumed_days) "
                "VALUES(%s,'work',%s,'Sick',30,20,0)", (runtime.base.tenant, employee),
            )
