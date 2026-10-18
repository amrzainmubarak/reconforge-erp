"""Versioned execution plans for three unchanged native financial queries.

Only query preparation and canonical recursion change. No row, authorization
result or source proof is cached. The original definitions remain the rollback
contract, including their strictness, volatility, invoker context and ABI.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from reconforge.infrastructure.postgres_finance_posting import records
from reconforge.infrastructure.postgres_financial_reporting_schema import UPGRADE_SQL as FINANCIAL_SQL
from reconforge.infrastructure.postgres_inventory_receipt_posting_schema import (
    POSTGRES_INVENTORY_RECEIPT_POSTING_SCHEMA_SQL as RECEIPT_SQL,
)
from reconforge.infrastructure.postgres_monetary_customer_returns_schema import CANONICAL_SQL

REVISION = "0150_pg_native_query_plans"


def _definition(source: str, name: str, delimiter: str) -> str:
    matches = re.findall(r"CREATE(?: OR REPLACE)? FUNCTION reconforge\." + re.escape(name)
                         + r"\(.*?" + re.escape(delimiter) + ";", source, re.S)
    if len(matches) != 1:
        raise ValueError("One exact retained native query definition is required.")
    return matches[0]


def _body(definition: str) -> tuple[str, str]:
    match = re.search(r"\bAS\s+(\$[a-z0-9_]*\$)", definition, re.I)
    if match is None:
        raise ValueError("A closed native query delimiter is required.")
    delimiter = match[1]
    parts = definition.split(delimiter)
    if len(parts) != 3 or parts[-1] != ";":
        raise ValueError("The native query definition is not closed.")
    return delimiter, parts[1]


def _planned_query(definition: str) -> str:
    delimiter, query = _body(definition)
    if definition.count("LANGUAGE sql STABLE") != 1 or not query.strip().startswith("SELECT ") or ";" in query:
        raise ValueError("One retained read-only scalar query is required.")
    return definition.replace("LANGUAGE sql STABLE", "LANGUAGE plpgsql STABLE", 1).replace(
        delimiter + query + delimiter, delimiter + "BEGIN RETURN (" + query.strip() + "); END" + delimiter, 1)


ORIGINAL_FUNCTIONS = {
    "irp_scope": _definition(RECEIPT_SQL, "irp_scope", "$irp$"),
    "irp_canonical": _definition(RECEIPT_SQL, "irp_canonical", "$irp$"),
    "fr_snapshot": _definition(FINANCIAL_SQL, "fr_snapshot", "$fr$"),
}
_canonical = _definition(CANONICAL_SQL, "monetary_canonical", "$mr149$")
UPGRADED_FUNCTIONS = {
    "irp_scope": _planned_query(ORIGINAL_FUNCTIONS["irp_scope"]),
    "irp_canonical": _canonical.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
        .replace("reconforge.monetary_canonical", "reconforge.irp_canonical")
        .replace("LANGUAGE plpgsql IMMUTABLE", "LANGUAGE plpgsql IMMUTABLE STRICT", 1),
    "fr_snapshot": _planned_query(ORIGINAL_FUNCTIONS["fr_snapshot"]),
}
_PROFILES = {
    "irp_scope": ("text,text,text,text", "bool", "s", False, ("t", "w", "o", "e")),
    "irp_canonical": ("jsonb", "text", "i", True, ("value",)),
    "fr_snapshot": ("text,text,text,text", "jsonb", "s", False, ("t", "i", "o", "l")),
}


def preflight(mode: Literal["original", "optimized", "financial_reinstall"]) -> str:
    """Refuse unknown bodies or execution attributes before reversible DDL."""
    if mode not in {"original", "optimized", "financial_reinstall"}:
        raise ValueError("Unknown native query-plan profile.")
    checks = []
    for name, (arguments, returns, volatility, strict, argnames) in _PROFILES.items():
        original = mode == "original" or mode == "financial_reinstall" and name == "fr_snapshot"
        definition = (ORIGINAL_FUNCTIONS if original else UPGRADED_FUNCTIONS)[name]
        _, body = _body(definition)
        values = {
            "NAME": name, "SIGNATURE": name + "(" + arguments + ")", "RETURNS": returns,
            "LANGUAGE": "sql" if original else "plpgsql", "VOLATILITY": volatility,
            "STRICT": "true" if strict else "false",
            "ARGNAMES": "ARRAY[" + ",".join("'" + arg + "'" for arg in argnames) + "]::text[]",
            "HASH": hashlib.sha256(body.encode()).hexdigest(),
        }
        check = r""" SELECT * INTO native FROM pg_catalog.pg_proc
 WHERE oid=pg_catalog.to_regprocedure('reconforge.@@SIGNATURE@@');
 IF native.oid IS NULL OR native.prosecdef OR native.proretset OR native.proleakproof
 OR native.proisstrict IS DISTINCT FROM @@STRICT@@ OR native.prokind<>'f' OR native.proparallel<>'u'
 OR native.provariadic<>0 OR native.pronargdefaults<>0 OR native.proargmodes IS NOT NULL
 OR native.proallargtypes IS NOT NULL OR native.procost<>100 OR native.prorows<>0
 OR native.proargnames IS DISTINCT FROM @@ARGNAMES@@ OR native.prorettype<>'pg_catalog.@@RETURNS@@'::regtype
 OR native.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='@@LANGUAGE@@')
 OR native.provolatile<>'@@VOLATILITY@@' OR native.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog']::text[]
 OR(SELECT count(*) FROM pg_catalog.pg_proc extra WHERE extra.pronamespace=native.pronamespace AND extra.proname='@@NAME@@')<>1
 OR encode(sha256(convert_to(native.prosrc,'UTF8')),'hex')<>'@@HASH@@' THEN
 RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='native_query_plan_contract',MESSAGE='Native query-plan execution contract drift';
 END IF;
"""
        for key, value in values.items():
            check = check.replace("@@" + key + "@@", value)
        checks.append(check)
    return "DO $nativeplans150$ DECLARE native RECORD;BEGIN\n" + "".join(checks) + "END $nativeplans150$;\n"


UPGRADE_SQL = preflight("original") + "\n".join(UPGRADED_FUNCTIONS.values()) + preflight("optimized")
DOWNGRADE_SQL = preflight("optimized") + "\n".join(ORIGINAL_FUNCTIONS.values()) + preflight("original")


def verify_native_query_plans_if_present(connection: Any) -> bool:
    """Legacy installers preserve a verified150 execution profile, without repair."""
    rows = records(connection.execute("""SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace JOIN pg_catalog.pg_language l ON l.oid=p.prolang
 WHERE n.nspname='reconforge' AND p.proname IN('irp_scope','irp_canonical','fr_snapshot')
 AND l.lanname='plpgsql') AS optimized, to_regclass('alembic_version') IS NOT NULL AS revisions"""))
    if len(rows) != 1 or any(type(rows[0].get(key)) is not bool for key in ("optimized", "revisions")):
        raise ValueError("Invalid native query-plan installation lookup.")
    declared = False
    if rows[0]["revisions"]:
        declared = bool(connection.execute("SELECT 1 FROM alembic_version WHERE version_num=%s", (REVISION,)).fetchone())
    if not rows[0]["optimized"] and not declared:
        return False
    connection.execute(preflight("optimized"))
    return True


def restore_financial_snapshot_after_reinstall(connection: Any) -> None:
    """Only the exact known legacy installer may replace the verified snapshot."""
    connection.execute(preflight("financial_reinstall"))
    connection.execute(UPGRADED_FUNCTIONS["fr_snapshot"])
    connection.execute(preflight("optimized"))
