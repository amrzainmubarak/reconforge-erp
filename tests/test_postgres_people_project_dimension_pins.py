"""Native FK custody preserves limited Finance metadata without HC reads."""


import pytest

from reconforge.infrastructure.postgres import PostgresTenantBoundary
from reconforge.infrastructure.postgres_finance_core import PostgresFinanceCoreRepository
from tests.test_postgres_people_project_payroll import (  # noqa: F401
    PeopleRuntime,
    approved_time,
    people,
    personnel_database,
    receipt_database,
)


def test_native_project_pins_preserve_metadata_updates_without_hc_select(people: PeopleRuntime,  # noqa: F811
        personnel_database: tuple[str, str, str]) -> None:  # noqa: F811
    import psycopg
    from psycopg import sql
    approved_time(people)
    ordinary = psycopg.conninfo.conninfo_to_dict(personnel_database[1])["user"]
    with psycopg.connect(personnel_database[0]) as admin:
        admin.execute(sql.SQL("REVOKE SELECT ON reconforge.hc_projects FROM {}").format(sql.Identifier(ordinary)))
    try:
        with PostgresTenantBoundary(people.base.factory).transaction(people.base.tenant, workspace_id="work", organization_id="org") as connection:
            with pytest.raises(Exception) as denied, connection.transaction():
                connection.execute("SELECT id FROM reconforge.hc_projects")
            assert denied.value.sqlstate == "42501"
            result = PostgresFinanceCoreRepository(connection, people.base.tenant).upsert_dimension(dimension_code="PROJECT",
                name="Safe renamed native Project", dimension_type="Project", workspace="work", organization_code="ORG")
            assert result["name"] == "Safe renamed native Project"
            connection.execute("UPDATE reconforge.finance_dimension_values SET name='Safe renamed value' WHERE tenant_id=%s AND value_code='P1'", (people.base.tenant,))
        with people.actor("maker") as (connection, _, _):
            assert connection.execute("SELECT count(*) amount FROM reconforge.hc_projects WHERE tenant_id=%s", (people.base.tenant,)).fetchone()["amount"] == 2
    finally:
        with psycopg.connect(personnel_database[0]) as admin:
            admin.execute(sql.SQL("GRANT SELECT ON reconforge.hc_projects TO {}").format(sql.Identifier(ordinary)))


@pytest.mark.parametrize("statement", [
    "UPDATE reconforge.finance_dimensions SET dimension_code='ALTERED' WHERE tenant_id=%s",
    "UPDATE reconforge.finance_dimensions SET dimension_type='Cost Center' WHERE tenant_id=%s",
    "UPDATE reconforge.finance_dimensions SET required_on_entries=TRUE WHERE tenant_id=%s",
    "UPDATE reconforge.finance_dimensions SET active=FALSE WHERE tenant_id=%s",
    "UPDATE reconforge.finance_dimensions SET organization_code='' WHERE tenant_id=%s",
    "UPDATE reconforge.finance_dimension_values SET value_code='ALTERED' WHERE tenant_id=%s AND value_code='P1'",
    "UPDATE reconforge.finance_dimension_values SET active=FALSE WHERE tenant_id=%s AND value_code='P1'",
])
def test_native_structural_project_pins_refuse_identity_policy_mutation_with_hc_rows_hidden(people: PeopleRuntime,  # noqa: F811
        personnel_database: tuple[str, str, str], statement: str) -> None:  # noqa: F811
    import psycopg
    from psycopg import sql
    approved_time(people)
    ordinary = psycopg.conninfo.conninfo_to_dict(personnel_database[1])["user"]
    with psycopg.connect(personnel_database[0]) as admin:
        admin.execute(sql.SQL("CREATE POLICY hc_test_hidden ON reconforge.hc_projects AS RESTRICTIVE USING(current_user <> {})").format(sql.Literal(ordinary)))
    try:
        with PostgresTenantBoundary(people.base.factory).transaction(people.base.tenant, workspace_id="work", organization_id="org") as connection:
            assert connection.execute("SELECT count(*) amount FROM reconforge.hc_projects").fetchone()[0] == 0
            with pytest.raises(Exception) as refused, connection.transaction():
                connection.execute(statement, (people.base.tenant,))
            # Existing native identity checks may reject before the new FK;
            # category/required/active changes reach its structural check.
            assert refused.value.sqlstate == ("23514" if "dimension_code=" in statement or "organization_code=" in statement or "value_code='ALTERED'" in statement else "23503")
        with people.actor("maker") as (connection, _, _):
            connection.execute("SELECT reconforge.hc_input_close(%s,'hc_projects',id) FROM reconforge.hc_projects WHERE tenant_id=%s", (people.base.tenant, people.base.tenant))
    finally:
        with psycopg.connect(personnel_database[0]) as admin:
            admin.execute("DROP POLICY hc_test_hidden ON reconforge.hc_projects")


def test_unreferenced_native_dimensions_can_change_required_policy_and_category(people: PeopleRuntime) -> None:  # noqa: F811
    with PostgresTenantBoundary(people.base.factory).transaction(people.base.tenant, workspace_id="work", organization_id="org") as connection:
        finance = PostgresFinanceCoreRepository(connection, people.base.tenant)
        finance.upsert_dimension(dimension_code="UNUSED", name="Unreferenced", dimension_type="Project", workspace="work", organization_code="ORG")
        finance.upsert_dimension(dimension_code="UNUSED", name="Changed", dimension_type="Cost Center", required_on_entries=True,
            workspace="work", organization_code="ORG")
        assert connection.execute("SELECT required_on_entries FROM reconforge.finance_dimensions WHERE tenant_id=%s AND dimension_code='UNUSED'", (people.base.tenant,)).fetchone()[0] is True


def test_direct_sql_project_cannot_capture_a_different_native_organization_under_broad_aliases(people: PeopleRuntime,  # noqa: F811
        personnel_database: tuple[str, str, str]) -> None:  # noqa: F811
    from uuid import uuid4

    import psycopg
    with psycopg.connect(personnel_database[0]) as admin:
        admin.execute("INSERT INTO reconforge.organizations(tenant_id,id,organization_code,name,base_currency,application_workspace_id) VALUES(%s,'foreign-org','FOREIGN','Synthetic foreign organization','USD','work')", (people.base.tenant,))
    with PostgresTenantBoundary(people.base.factory).transaction(people.base.tenant, workspace_id="work") as connection:
        finance = PostgresFinanceCoreRepository(connection, people.base.tenant)
        dimension = finance.upsert_dimension(dimension_code="FOREIGN_PROJECT", name="Foreign scoped project", dimension_type="Project", workspace="work", organization_code="FOREIGN")["id"]
        value = finance.upsert_dimension_value(dimension_code="FOREIGN_PROJECT", value_code="X", name="Foreign original", workspace="work")["id"]
        with pytest.raises(Exception) as refused, connection.transaction():
            connection.execute("""INSERT INTO reconforge.hc_projects(tenant_id,id,workspace_id,organization_id,legal_entity_id,project_code,
                dimension_id,value_id,dimension_code,value_code,preparer_id,request_digest,audit_id,outbox_id)
                VALUES(%s,%s,'work','org','entity','FOREIGN',%s,%s,'FOREIGN_PROJECT','X','maker',%s,'SYNTHETIC','SYNTHETIC')""",
                (people.base.tenant, "HCP-"+uuid4().hex, dimension, value, "0"*64))
        assert refused.value.sqlstate == "23514"
        assert "source organization" in str(refused.value)
        assert connection.execute("SELECT count(*) FROM reconforge.hc_projects WHERE tenant_id=%s", (people.base.tenant,)).fetchone()[0] == 0
