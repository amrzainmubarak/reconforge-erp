"""Canonical synthetic receipt/FIFO/GL masters for the owned real browser gate."""
from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_inventory_receipt_posting import create_receipt_runtime


def seed_receipt_browser(admin_dsn: str, app_dsn: str):
    """Return runtime with synthetic secret in memory; never log or persist credentials."""
    runtime = create_receipt_runtime((admin_dsn, app_dsn))
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identities = PostgresIdentityRepository(connection)
        # Enables existing Administration sign-in/step-up UI and its read surfaces.
        for permission in ("audit.read", "users.manage", "roles.manage", "security.center.read", "security.integrations.manage", "security.retention.manage"):
            identities.create_permission(tenant_id=runtime.tenant, permission_name=permission)
            identities.grant_permission(tenant_id=runtime.tenant, role_name="receipt-operator", permission_name=permission)
        authority = PostgresScopeAuthorityRepository(connection)
        for username in ("maker", "checker", "poster"):
            for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
                authority.grant(tenant_id=runtime.tenant, grant_id=f"browser-{username}-{identifier}", principal_type="user", principal_id=username, scope_type=kind, scope_id=identifier, actor_id=username)
    return runtime
