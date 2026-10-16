"""Finite metadata/absence regressions; fake catalogs are not PostgreSQL proof."""

from types import SimpleNamespace

import pytest

from reconforge.infrastructure.postgres_monetary_installation import (
    function_preflight,
    verify_monetary_installation_if_present,
)
from reconforge.infrastructure.postgres_monetary_inventory_native import NATIVE_FUNCTION_SQL as PHYSICAL_SQL
from reconforge.infrastructure.postgres_monetary_inventory_transfer_schema import NATIVE_FUNCTION_SQL as TRANSFER_SQL


class Catalog:
    def __init__(self, profile):
        self.profile = profile
        self.calls = 0

    def execute(self, query):
        assert " AS marker" in query
        self.calls += 1
        return SimpleNamespace(description=[SimpleNamespace(name=key) for key in self.profile], fetchall=lambda: [self.profile])


def test_genuine_absence_is_rechecked_without_executing_legacy_or_new_ddl():
    connection = Catalog({"marker": False, "credit": False, "balance": False, "helpers": False, "relations": 0})
    assert verify_monetary_installation_if_present(connection) is False
    assert verify_monetary_installation_if_present(connection) is False and connection.calls == 2


@pytest.mark.parametrize("field,value", [("marker", True), ("credit", True), ("balance", True), ("helpers", True), ("relations", 1), ("relations", 7)])
def test_partial_namespace_refuses_before_any_original_installer_overwrite(field, value):
    connection = Catalog({**dict.fromkeys(("marker", "credit", "balance", "helpers"), False), "relations": 0, field: value})
    with pytest.raises(ValueError, match="partial"):
        verify_monetary_installation_if_present(connection)
    assert connection.calls == 1


@pytest.mark.parametrize("change", [{"relations": False}, {"relations": "0"}, {"marker": 0}, {"helpers": None}, {"extra": False}])
def test_catalog_evidence_never_coerces_or_ignores_unexpected_keys(change):
    connection = Catalog({"marker": False, "credit": False, "balance": False, "helpers": False, "relations": 0, **change})
    with pytest.raises(ValueError, match="lookup"):
        verify_monetary_installation_if_present(connection)


@pytest.mark.parametrize("declaration", [
    "", "CREATE FUNCTION reconforge.bad(t TEXT) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN RETURN NULL; END $$;",
    "CREATE FUNCTION reconforge.bad(t TEXT DEFAULT NULL) RETURNS JSONB LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN RETURN NULL; END $$;",
    "CREATE FUNCTION reconforge.bad(t TEXT) RETURNS JSONB LANGUAGE plpgsql STABLE SET search_path=public AS $$ BEGIN RETURN NULL; END $$;",
    "CREATE FUNCTION reconforge.bad(t TEXT) RETURNS SETOF JSONB LANGUAGE sql STABLE SET search_path=pg_catalog AS $$ SELECT '{}'::jsonb $$;",
])
def test_unreviewed_new_executable_attributes_fail_closed(declaration):
    with pytest.raises(ValueError):
        function_preflight(declaration)


def test_native_physical_and_transfer_execution_profiles_are_closed_without_default_or_definer_privilege():
    # This qualification covers emitted function membership/metadata only.
    # The mandatory native149 gate executes source/GL/FIFO/restore behavior.
    assertion = function_preflight(PHYSICAL_SQL + TRANSFER_SQL)
    assert assertion.count("Monetary native execution contract drift") == 12
    with pytest.raises(ValueError, match="overloaded"):
        function_preflight(PHYSICAL_SQL + TRANSFER_SQL + PHYSICAL_SQL)


@pytest.mark.parametrize("declaration,catalog_type", [("INTEGER", "int4"), ("BIGINT", "int8"), ("BOOLEAN", "bool")])
def test_result_sql_aliases_bind_the_actual_schema_qualified_catalog_type(declaration, catalog_type):
    assertion = function_preflight("CREATE FUNCTION reconforge.catalog_type() RETURNS " + declaration
        + " LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$ SELECT NULL $$;")
    assert "native.prorettype<>'pg_catalog." + catalog_type + "'::regtype" in assertion
    assert "'pg_catalog." + declaration.lower() + "'::regtype" not in assertion
