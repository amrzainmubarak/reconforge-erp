"""New financial operations require human governance and explicit grants."""

import pytest

from reconforge.auth.policy import PRIVILEGED_STEP_UP_PERMISSIONS, permission_requires_human
from reconforge.infrastructure.postgres_wave5_permission_schema import permission_upgrade_sql


@pytest.mark.parametrize("permission", [
    "manufacturing_execution.manage", "manufacturing_execution.approve", "manufacturing_execution.post",
    "intercompany_operations.prepare", "intercompany_operations.review", "intercompany_operations.post",
    "procurement_sourcing.manage", "procurement_sourcing.approve", "procurement_sourcing.award",
])
def test_financial_mutations_cannot_be_delegated_to_an_unassured_service_account(permission: str) -> None:
    assert permission_requires_human(permission)
    assert permission in PRIVILEGED_STEP_UP_PERMISSIONS


@pytest.mark.parametrize("module", ["manufacturing_execution", "intercompany_operations", "procurement_sourcing"])
def test_permission_catalog_installation_does_not_grant_existing_roles(module: str) -> None:
    statement = permission_upgrade_sql(module)
    assert "AFTER INSERT ON reconforge.tenants" in statement
    assert "identity_role_permissions" not in statement


def test_permission_sql_identifiers_are_internal_catalog_only() -> None:
    with pytest.raises(KeyError):
        permission_upgrade_sql("manufacturing_execution'; DROP TABLE reconforge.tenants; --")
