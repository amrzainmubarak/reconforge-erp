from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from reconforge.api import create_api_app
from reconforge.application.notifications import (
    NotificationApplicationService,
    NotificationChannel,
    NotificationEgressPolicy,
    NotificationRequest,
    NotificationRouteRegistration,
)
from reconforge.auth.federation import FederatedPrincipal
from reconforge.db import run_migrations
from reconforge.infrastructure.postgres import (
    PostgresConnectionFactory,
    PostgresSettings,
    PostgresTenantBoundary,
)
from reconforge.infrastructure.postgres_evidence import (
    POSTGRES_EVIDENCE_SCHEMA_SQL,
    PostgresEvidenceIntegrityError,
    PostgresEvidenceRepository,
)
from reconforge.infrastructure.postgres_federation import PostgresFederationError, PostgresFederationRepository
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_notifications import (
    PostgresNotificationError,
    PostgresNotificationRepository,
    PostgresNotificationResolver,
)
from reconforge.infrastructure.postgres_scim_auth import PostgresSCIMCredentialRepository
from reconforge.infrastructure.postgres_security_governance import (
    POSTGRES_SECURITY_GOVERNANCE_SCHEMA_SQL,
    PostgresSecurityGovernanceRepository,
)
from reconforge.infrastructure.postgres_service_accounts import PostgresServiceAccountRepository


def test_security_governance_schema_is_versioned_append_only_and_forced_rls() -> None:
    assert "retention_version BIGINT NOT NULL DEFAULT 1" in POSTGRES_SECURITY_GOVERNANCE_SCHEMA_SQL
    assert "evidence retention cannot be shortened" in POSTGRES_SECURITY_GOVERNANCE_SCHEMA_SQL
    assert "evidence retention assignments are append-only" in POSTGRES_SECURITY_GOVERNANCE_SCHEMA_SQL
    assert POSTGRES_SECURITY_GOVERNANCE_SCHEMA_SQL.count("FORCE ROW LEVEL SECURITY") == 2
    assert "retention_version BIGINT NOT NULL DEFAULT 1" in POSTGRES_EVIDENCE_SCHEMA_SQL
    assert "Evidence retention cannot be shortened" in POSTGRES_EVIDENCE_SCHEMA_SQL
    assert "Evidence retention cannot be shortened." in Path(
        "reconforge/infrastructure/postgres_evidence.py"
    ).read_text(encoding="utf-8")


def test_security_governance_repository_uses_real_resources_and_static_bounded_sql() -> None:
    source = Path("reconforge/infrastructure/postgres_security_governance.py").read_text(encoding="utf-8")
    for resource in (
        "federation_identity_links",
        "notification_routes",
        "scim_credentials",
        "service_accounts",
        "evidence_registry",
    ):
        assert resource in source
    assert "LIMIT %s" in source
    assert "pg_advisory_xact_lock" in source
    assert "execute(f" not in source
    assert "token_hash" not in source
    assert "external_subject_hash" not in source


def test_security_governance_docs_and_migration_are_packaged() -> None:
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    assert "include docs/adr/0197-govern-real-integrations-and-monotonic-evidence-retention.md" in manifest
    assert "include docs/operations/security-governance.md" in manifest
    assert "recursive-include alembic/versions *.py" in manifest


@pytest.mark.skipif(not os.environ.get("RECONFORGE_TEST_POSTGRES_DSN"), reason="requires live PostgreSQL")
def test_live_security_governance_is_atomic_runtime_enforced_and_tenant_isolated(
    tmp_path: Path, monkeypatch: Any
) -> None:
    pytest.importorskip("psycopg")
    dsn = os.environ["RECONFORGE_TEST_POSTGRES_DSN"]
    admin_dsn = os.environ.get("RECONFORGE_TEST_POSTGRES_ADMIN_DSN", dsn)
    app_user = os.environ.get("RECONFORGE_TEST_POSTGRES_APP_USER", "")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", app_user):
        pytest.fail("RECONFORGE_TEST_POSTGRES_APP_USER must name the non-privileged test role")
    admin_factory = PostgresConnectionFactory(PostgresSettings(dsn=admin_dsn, require_tls=False))
    app_factory = PostgresConnectionFactory(PostgresSettings(dsn=dsn, require_tls=False))
    suffix = uuid4().hex[:10]
    tenant_a = f"security_governance_a_{suffix}"
    tenant_b = f"security_governance_b_{suffix}"
    actor_id = f"actor-{suffix}"
    sibling_id = f"sibling-{suffix}"
    service_id = f"svc-governance-{suffix}"
    workspace_id = f"workspace-{suffix}"
    entity_id = f"entity-{suffix}"
    route_id = f"security-route-{suffix}"
    evidence_id = f"evidence-{suffix}"
    password = "Synthetic-security-governance-password-123!"
    principal = FederatedPrincipal(
        provider_id="corp-oidc",
        issuer="https://id.sensitive.invalid/oidc",
        subject=f"sensitive-external-subject-{suffix}",
        roles=("administrator",),
        assertion_id=f"assertion-{suffix}",
    )
    root = tmp_path / "tenants"
    root.mkdir()
    for tenant in (tenant_a, tenant_b):
        run_migrations(root / f"{tenant}.db")

    admin = admin_factory.connect()
    notification_connection = None
    try:
        with admin.transaction():
            role = admin.execute(
                "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=%s", (app_user,)
            ).fetchone()
            assert role is not None and not bool(role[0]) and not bool(role[1])
            admin.execute(f"GRANT USAGE ON SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA reconforge TO {app_user}")
            admin.execute(f"GRANT USAGE,SELECT,UPDATE ON ALL SEQUENCES IN SCHEMA reconforge TO {app_user}")
            admin.execute(
                "INSERT INTO reconforge.tenants(id,name) VALUES (%s,%s),(%s,%s)",
                (tenant_a, tenant_a, tenant_b, tenant_b),
            )
            admin.execute(
                "INSERT INTO reconforge.domain_workspaces(tenant_id,id,name,local_first_note,created_at) "
                "VALUES(%s,%s,%s,%s,%s)",
                (
                    tenant_a,
                    workspace_id,
                    "Synthetic governance workspace",
                    "Synthetic local-first governance workspace.",
                    datetime.now(UTC).replace(microsecond=0).isoformat(),
                ),
            )

        def provision(tenant: str, user_id: str, username: str) -> None:
            with PostgresTenantBoundary(admin_factory).transaction(tenant) as connection:
                identity = PostgresIdentityRepository(connection)
                for permission in ("reports.read", "security.policy.manage"):
                    identity.create_permission(tenant_id=tenant, permission_name=permission)
                identity.create_role(tenant_id=tenant, role_name="administrator")
                identity.grant_permission(
                    tenant_id=tenant,
                    role_name="administrator",
                    permission_name="security.policy.manage",
                )
                identity.create_user(
                    tenant_id=tenant,
                    user_id=user_id,
                    username=username,
                    password=password,
                    role_name="administrator",
                    display_name="Synthetic Security Administrator",
                    email=f"{username}@sensitive.invalid",
                )

        provision(tenant_a, actor_id, f"actor-{suffix}")
        provision(tenant_b, sibling_id, f"sibling-{suffix}")

        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            service_accounts = PostgresServiceAccountRepository(connection)
            service_accounts.create_account(
                tenant_id=tenant_a,
                account_id=service_id,
                name=f"governance-worker-{suffix}",
                display_name="Synthetic governance worker",
                permissions=frozenset({"reports.read"}),
                actor_id=actor_id,
            )
            service_credential = service_accounts.issue_credential(
                tenant_id=tenant_a,
                account_id=service_id,
                actor_id=actor_id,
                ttl=timedelta(hours=1),
            )
            scim_credential = PostgresSCIMCredentialRepository(connection).issue(
                tenant_id=tenant_a,
                provisioning_domain="corp-idp",
                client_id=f"scim-client-{suffix}",
                actor_id=actor_id,
                ttl=timedelta(hours=1),
            )
            PostgresFederationRepository(connection).link_identity(
                tenant_id=tenant_a,
                principal=principal,
                user_id=actor_id,
                actor_id=actor_id,
            )
            PostgresEvidenceRepository(connection).register(
                tenant_id=tenant_a,
                evidence_id=evidence_id,
                evidence_code=f"GOV-{suffix.upper()}",
                source_name="Synthetic security evidence",
                source_reference="sensitive://evidence/reference",
                checksum_sha256="e" * 64,
                actor_id=actor_id,
            )
        with PostgresTenantBoundary(app_factory).transaction(tenant_b) as connection:
            PostgresServiceAccountRepository(connection).create_account(
                tenant_id=tenant_b,
                account_id=f"svc-sibling-{suffix}",
                name=f"sibling-worker-{suffix}",
                display_name="Synthetic sibling worker",
                permissions=frozenset({"reports.read"}),
                actor_id=sibling_id,
            )

        route = NotificationRouteRegistration(
            tenant_id=tenant_a,
            workspace_id=workspace_id,
            entity_id=entity_id,
            route_id=route_id,
            version=1,
            channel=NotificationChannel.WEBHOOK,
            destination="https://hooks.sensitive.invalid/reconforge",
            secret_ref="vault/sensitive/governance-webhook",
        )
        notification_connection = app_factory.connect()
        notification_service = NotificationApplicationService(
            PostgresNotificationRepository(notification_connection),
            policy=NotificationEgressPolicy(
                enabled=True,
                webhook_urls=frozenset({route.destination}),
            ),
        )
        route_record, route_created = notification_service.register_route(route, actor_id=actor_id)
        assert route_created is True
        request = NotificationRequest(
            tenant_id=tenant_a,
            notification_id=f"notification-{suffix}",
            route_id=route_id,
            route_version=1,
            destination_digest=route.destination_digest,
            workspace_id=workspace_id,
            entity_id=entity_id,
            schedule_id=f"schedule-{suffix}",
            schedule_version=1,
            dispatch_key="f" * 64,
            scheduled_for=datetime.now(UTC).replace(microsecond=0),
            durable_job_id=f"job-{suffix}",
        )
        assert PostgresNotificationResolver(app_factory).resolve(request) == route_record

        client = TestClient(
            create_api_app(
                tmp_path / "control.db",
                tenant_db_root=root,
                postgres_dsn=dsn,
                postgres_require_tls=False,
                cursor_signing_key=b"live-e193-cursor-signing-key-32-bytes",
            )
        )

        def login(tenant: str, username: str) -> dict[str, str]:
            response = client.post(
                "/api/v1/auth/login",
                headers={"X-ReconForge-Tenant": tenant},
                json={"username": username, "password": password},
            )
            assert response.status_code == 200, response.text
            headers = {
                "X-ReconForge-Tenant": tenant,
                "Authorization": f"Bearer {response.json()['access_token']}",
            }
            denied = client.get("/api/v1/admin/security/integrations", headers=headers)
            assert denied.status_code == 403 and denied.json()["error"]["code"] == "step_up_required"
            step_up = client.post("/api/v1/auth/step-up", headers=headers, json={"password": password})
            assert step_up.status_code == 200, step_up.text
            return headers

        actor_headers = login(tenant_a, f"actor-{suffix}")
        sibling_headers = login(tenant_b, f"sibling-{suffix}")
        path = "/api/v1/admin/security/integrations"
        first = client.get(path, params={"limit": 1}, headers=actor_headers)
        assert first.status_code == 200, first.text
        cursor = first.json()["pagination"]["next_cursor"]
        assert cursor
        assert client.get(path, params={"limit": 1, "cursor": cursor}, headers=actor_headers).status_code == 200
        mismatch = client.get(
            path,
            params={"limit": 1, "cursor": cursor, "include_inactive": True},
            headers=actor_headers,
        )
        assert mismatch.status_code == 400 and mismatch.json()["error"]["code"] == "cursor_context_mismatch"
        tamper_index = len(cursor) // 2
        tampered_cursor = cursor[:tamper_index] + ("A" if cursor[tamper_index] != "A" else "B") + cursor[tamper_index + 1 :]
        tampered = client.get(path, params={"cursor": tampered_cursor}, headers=actor_headers)
        assert tampered.status_code == 400

        listed = client.get(path, params={"limit": 200}, headers=actor_headers)
        assert listed.status_code == 200, listed.text
        integrations = {(item["kind"], item["id"]): item for item in listed.json()["integrations"]}
        expected_keys = {
            ("federation_link", f"corp-oidc:{actor_id}"),
            ("notification_route", f"{route_id}:1"),
            ("scim_credential", scim_credential.id),
            ("service_account", service_id),
        }
        assert set(integrations) == expected_keys
        sibling_integrations = client.get(path, headers=sibling_headers).json()["integrations"]
        assert [(item["kind"], item["id"]) for item in sibling_integrations] == [
            ("service_account", f"svc-sibling-{suffix}")
        ]

        serialized = listed.text
        for forbidden in (
            password,
            service_credential.token,
            scim_credential.token,
            route.destination,
            route.secret_ref,
            principal.subject,
            principal.issuer,
            "token_hash",
            "external_subject_hash",
            "secret_ref",
            "destination",
        ):
            assert forbidden.casefold() not in serialized.casefold()

        for kind, integration_id in sorted(expected_keys):
            item = integrations[(kind, integration_id)]
            disabled = client.post(
                f"/api/v1/admin/security/integrations/{kind}/{integration_id}/disable",
                headers=actor_headers,
                json={"expected_state_digest": item["state_digest"], "reason_code": "security_response"},
            )
            assert disabled.status_code == 200, disabled.text
            assert disabled.json()["integration"]["status"] == "disabled"
            assert disabled.json()["transitioned"] is True
            if kind == "service_account":
                assert disabled.json()["revoked_credentials"] == 1

        stale = client.post(
            f"/api/v1/admin/security/integrations/service_account/{service_id}/disable",
            headers=actor_headers,
            json={
                "expected_state_digest": integrations[("service_account", service_id)]["state_digest"],
                "reason_code": "security_response",
            },
        )
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "integration_state_conflict"

        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            assert PostgresServiceAccountRepository(connection).authenticate(
                tenant_id=tenant_a, token=service_credential.token
            ) is None
            assert PostgresSCIMCredentialRepository(connection).authenticate(
                tenant_id=tenant_a, token=scim_credential.token
            ) is None
            with pytest.raises(PostgresFederationError):
                PostgresFederationRepository(connection).complete_login(tenant_id=tenant_a, principal=principal)
        with pytest.raises(PostgresNotificationError):
            PostgresNotificationResolver(app_factory).resolve(request)

        created = client.post(
            "/api/v1/admin/security/retention-policies",
            headers=actor_headers,
            json={
                "name": f"audit-{suffix}",
                "description": "Synthetic restricted evidence policy",
                "data_classification": "restricted",
                "duration_days": 365,
            },
        )
        assert created.status_code == 200, created.text
        policy_id = created.json()["policy"]["id"]
        applied = client.post(
            f"/api/v1/admin/security/retention-policies/{policy_id}/evidence/{evidence_id}",
            headers=actor_headers,
            json={"expected_retention_version": 1, "reason_code": "policy_application"},
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["retention_extended"] is True and applied.json()["retention_version"] == 2
        replay = client.post(
            f"/api/v1/admin/security/retention-policies/{policy_id}/evidence/{evidence_id}",
            headers=actor_headers,
            json={"expected_retention_version": 1, "reason_code": "policy_application"},
        )
        assert replay.status_code == 200 and replay.json()["transitioned"] is False

        updated = client.patch(
            f"/api/v1/admin/security/retention-policies/{policy_id}",
            headers=actor_headers,
            json={
                "expected_lifecycle_version": 1,
                "reason_code": "policy_change",
                "duration_days": 30,
            },
        )
        assert updated.status_code == 200 and updated.json()["policy"]["lifecycle_version"] == 2
        non_shortening = client.post(
            f"/api/v1/admin/security/retention-policies/{policy_id}/evidence/{evidence_id}",
            headers=actor_headers,
            json={"expected_retention_version": 2, "reason_code": "policy_application"},
        )
        assert non_shortening.status_code == 200, non_shortening.text
        assert non_shortening.json()["retention_extended"] is False
        assert non_shortening.json()["retention_version"] == 2

        second_policy = client.post(
            "/api/v1/admin/security/retention-policies",
            headers=actor_headers,
            json={
                "name": f"contract-{suffix}",
                "data_classification": "confidential",
                "duration_days": 90,
            },
        )
        second_policy_id = second_policy.json()["policy"]["id"]
        stale_retention = client.post(
            f"/api/v1/admin/security/retention-policies/{second_policy_id}/evidence/{evidence_id}",
            headers=actor_headers,
            json={"expected_retention_version": 1, "reason_code": "contractual_requirement"},
        )
        assert stale_retention.status_code == 409
        assert stale_retention.json()["error"]["code"] == "retention_version_conflict"
        retired = client.patch(
            f"/api/v1/admin/security/retention-policies/{second_policy_id}",
            headers=actor_headers,
            json={
                "expected_lifecycle_version": 1,
                "reason_code": "policy_change",
                "active": False,
            },
        )
        assert retired.status_code == 200 and retired.json()["policy"]["active"] is False
        inactive = client.post(
            f"/api/v1/admin/security/retention-policies/{second_policy_id}/evidence/{evidence_id}",
            headers=actor_headers,
            json={"expected_retention_version": 2, "reason_code": "contractual_requirement"},
        )
        assert inactive.status_code == 409 and inactive.json()["error"]["code"] == "retention_policy_retired"

        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            evidence = connection.execute(
                "SELECT retention_until,retention_version FROM reconforge.evidence_registry WHERE id=%s",
                (evidence_id,),
            ).fetchone()
            assert evidence is not None and evidence[0] is not None and int(evidence[1]) == 2
            with pytest.raises(PostgresEvidenceIntegrityError, match="cannot be shortened"):
                PostgresEvidenceRepository(connection).register(
                    tenant_id=tenant_a,
                    evidence_id=evidence_id,
                    evidence_code=f"GOV-{suffix.upper()}",
                    source_name="Synthetic security evidence",
                    source_reference="sensitive://evidence/reference",
                    checksum_sha256="e" * 64,
                    actor_id=actor_id,
                    retention_until=datetime.now(UTC).replace(microsecond=0),
                )
        with pytest.raises(Exception, match="[Ee]vidence retention cannot be shortened"), PostgresTenantBoundary(
            app_factory
        ).transaction(tenant_a) as connection:
            connection.execute(
                "UPDATE reconforge.evidence_registry SET retention_until=now(),retention_version=retention_version+1 "
                "WHERE id=%s",
                (evidence_id,),
            )

        import reconforge.infrastructure.postgres_security_governance as repository_module

        original_append = repository_module.PostgresAuditEventRepository.append

        def fail_audit(*args: object, **kwargs: object) -> object:
            raise RuntimeError("synthetic governance audit failure")

        monkeypatch.setattr(repository_module.PostgresAuditEventRepository, "append", fail_audit)
        with pytest.raises(RuntimeError, match="synthetic governance audit failure"), PostgresTenantBoundary(
            app_factory
        ).transaction(tenant_a) as connection:
            PostgresSecurityGovernanceRepository(connection, tenant_a).create_retention_policy(
                actor_user_id=actor_id,
                name=f"rollback-{suffix}",
                description="Rollback",
                data_classification="internal",
                duration_days=30,
                as_of=datetime.now(UTC).replace(microsecond=0),
            )
        monkeypatch.setattr(repository_module.PostgresAuditEventRepository, "append", original_append)
        with PostgresTenantBoundary(app_factory).transaction(tenant_a) as connection:
            assert connection.execute(
                "SELECT 1 FROM reconforge.retention_policies WHERE name=%s", (f"rollback-{suffix}",)
            ).fetchone() is None
            actions = {
                str(row[0])
                for row in connection.execute(
                    "SELECT action FROM reconforge.domain_audit_events WHERE tenant_id=%s",
                    (tenant_a,),
                ).fetchall()
            }
            assert {
                "security.integration.disabled",
                "security.retention_policy.applied",
                "security.retention_policy.created",
                "security.retention_policy.updated",
            } <= actions
            assert connection.execute(
                "SELECT 1 FROM reconforge.service_accounts WHERE tenant_id=%s",
                (tenant_b,),
            ).fetchone() is None

        inactive_integrations = client.get(
            path,
            params={"include_inactive": True, "limit": 200},
            headers=actor_headers,
        )
        assert inactive_integrations.status_code == 200
        assert len(inactive_integrations.json()["integrations"]) == 4
        assert {item["status"] for item in inactive_integrations.json()["integrations"]} == {"disabled"}
        assert client.get(path, headers=actor_headers).json()["integrations"] == []
        client.close()

        from alembic.config import Config

        from alembic import command

        with admin.transaction():
            head_before_guarded_downgrade = admin.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0]
        monkeypatch.setenv("RECONFORGE_POSTGRES_DSN", admin_dsn)
        with pytest.raises(
            Exception,
            match=(
                "refusing to discard (?:governed retention policy|connector write-back intent evidence|"
                "certification evidence bindings)"
            ),
        ):
            command.downgrade(Config(str(Path("alembic.ini").resolve())), "0051_access_policy_lifecycle")
        with admin.transaction():
            # A guarded non-empty downgrade is atomic: it must preserve whatever
            # revision was current before Alembic attempted the downgrade chain.
            assert (
                admin.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                == head_before_guarded_downgrade
            )
            assert admin.execute(
                "SELECT count(*) FROM reconforge.retention_policies WHERE tenant_id=%s", (tenant_a,)
            ).fetchone()[0] == 2
    finally:
        if notification_connection is not None:
            notification_connection.close()
        admin.close()
