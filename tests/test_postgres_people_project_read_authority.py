"""Cached human principals do not outlive native workforce read authority."""

from typing import Literal

import pytest

from reconforge.domain.finance_posting import FinancePostingError
from reconforge.infrastructure.postgres_scope_authority import PostgresScopeAuthorityRepository
from tests.test_postgres_people_project_payroll import (  # noqa: F401
    SCOPE,
    PeopleRuntime,
    approved_budget,
    approved_time,
    people,
    personnel_database,
    prepare,
    receipt_database,
)


@pytest.mark.parametrize("read", ["get", "catalog", "master_catalog"])
@pytest.mark.parametrize("revoked", ["scope", "permission"])
def test_cached_human_aggregate_read_refuses_persisted_authority_revocation(people: PeopleRuntime,  # noqa: F811
        read: Literal["get", "catalog", "master_catalog"], revoked: Literal["scope", "permission"]) -> None:
    import psycopg
    plan = prepare(people, approved_time(people), approved_budget(people))
    with people.actor("maker", private=False) as (_, repository, actor):
        with psycopg.connect(people.base.admin_dsn) as admin:
            if revoked == "scope":
                PostgresScopeAuthorityRepository(admin).revoke(tenant_id=people.base.tenant, grant_id="hc-makerlegal_entity", actor_id="poster", reason="Synthetic read authority revocation")
            else:
                admin.execute("UPDATE reconforge.identity_role_permissions SET active=FALSE,lifecycle_version=lifecycle_version+1,revoked_at=now(),revoked_by='poster',revocation_reason_code='access_change' WHERE tenant_id=%s AND permission_name='people_project_payroll.read'", (people.base.tenant,))
        with pytest.raises(FinancePostingError) as refused:
            if read == "get":
                repository.get(plan["id"], actor=actor, sensitive=False)
            else:
                repository.catalog("times" if read == "master_catalog" else "payruns", SCOPE, actor=actor)
        assert "denied" in refused.value.code


@pytest.mark.parametrize("read", ["get", "catalog"])
def test_every_emitted_workforce_financial_read_supplies_exact_source_amount_to_central_policy(people: PeopleRuntime,  # noqa: F811
        read: Literal["get", "catalog"], monkeypatch) -> None:
    from decimal import Decimal

    import reconforge.infrastructure.postgres_operational_finance as native_owner
    from reconforge.auth.policy import evaluate_principal_access
    plan = prepare(people, approved_time(people), approved_budget(people))
    observed = []
    def bounded(principal, **context):
        amount = context.get("amount")
        if context["required_permission"] == "people_project_payroll.read" and amount is not None:
            observed.append(amount)
            return evaluate_principal_access(principal, maximum_amount=Decimal("20.00"), **context)
        return evaluate_principal_access(principal, **context)
    monkeypatch.setattr(native_owner, "evaluate_principal_access", bounded)
    with people.actor("maker", private=False) as (_, repository, actor), pytest.raises(FinancePostingError) as refused:
        if read == "get":
            repository.get(plan["id"], actor=actor, sensitive=False)
        else:
            repository.catalog("payruns", SCOPE, actor=actor)
    assert "denied" in refused.value.code and observed == [Decimal("25.01")]
