"""Persist distinct synthetic principal IDs and usernames for real ERP sign-in."""

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_inventory_receipt_posting import ReceiptRuntime


def seed_erp_browser_principals(runtime: ReceiptRuntime) -> None:
    with PostgresTenantBoundary(runtime.factory).transaction(runtime.tenant) as connection:
        identities = PostgresIdentityRepository(connection)
        authority = PostgresScopeAuthorityRepository(connection)
        for function in ("maker", "checker", "poster"):
            principal_id, username = f"erp-{function}", f"browser-{function}"
            identities.create_user(
                tenant_id=runtime.tenant, user_id=principal_id, username=username,
                password=runtime.password, role_name="receipt-operator",
            )
            for kind, identifier in (("workspace", "work"), ("organization", "org"), ("legal_entity", "entity")):
                authority.grant(
                    tenant_id=runtime.tenant, grant_id=f"{principal_id}-{identifier}",
                    principal_type="user", principal_id=principal_id, scope_type=kind,
                    scope_id=identifier, actor_id=principal_id,
                )
