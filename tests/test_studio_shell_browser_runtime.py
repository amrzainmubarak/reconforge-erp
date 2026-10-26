"""Disposable real PostgreSQL/TLS main-App runtime for Studio shell acceptance."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_enterprise_finance_bridge import PostgresEnterpriseFinanceBridge
from reconforge.infrastructure.postgres_identity import PostgresIdentityRepository
from tests import test_release_product_browser_runtime as product_runtime
from tests.test_postgres_enterprise_finance_bridge import prepare, source

OUT = Path(os.environ.get("RECONFORGE_STUDIO_SHELL_OUT", "output/assurance-20261026/studio-shell"))
RESTRICTED_USER = "synthetic-reviewer-with-a-deliberately-long-user-name"
original_seed = product_runtime.seed


def seed(runtime: Any) -> dict[str, str]:
    """Use native owners to retain actual posted balances and a limited identity."""
    fixture = original_seed(runtime)
    identifier = source(runtime, "ProjectMilestone")
    plan = prepare(runtime, "ProjectMilestone", identifier)
    with runtime.actor("checker", private=False) as (connection, _repository, actor):
        PostgresEnterpriseFinanceBridge(connection, runtime.base.tenant).review(
            plan["binding_id"], expected_source_digest=plan["source_digest"], command_id="shell-review", actor=actor
        )
    with runtime.actor("poster", private=False) as (connection, _repository, actor):
        posted = PostgresEnterpriseFinanceBridge(connection, runtime.base.tenant).post(
            plan["binding_id"], expected_source_digest=plan["source_digest"], command_id="shell-post", actor=actor
        )
        assert posted["phase"] == "Posted"
    with PostgresTenantBoundary(runtime.base.factory).transaction(runtime.base.tenant) as connection:
        identity = PostgresIdentityRepository(connection)
        identity.create_role(tenant_id=runtime.base.tenant, role_name="shell-restricted")
        identity.create_permission(tenant_id=runtime.base.tenant, permission_name="notifications.read")
        identity.grant_permission(tenant_id=runtime.base.tenant, role_name="shell-restricted", permission_name="notifications.read")
        identity.create_user(tenant_id=runtime.base.tenant, user_id="shell-restricted-user", username=RESTRICTED_USER,
                             password=runtime.base.password, role_name="shell-restricted")
    fixture["restricted_username"] = RESTRICTED_USER
    return fixture


if __name__ == "__main__":
    product_runtime.OUT = OUT
    product_runtime.seed = seed
    product_runtime.main()
