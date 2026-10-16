"""Strict149 verifier for already-installed monetary native ownership.

Legacy installers may not overwrite a newer accepted function body and then
guess how to repair it. A complete149 footprint is verified before their DDL;
an absent footprint retains the original flow, and a partial one fails closed.
No verifier mutates source data or silently repairs an unknown catalog.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from reconforge.infrastructure.postgres_finance_posting import records
from reconforge.infrastructure.postgres_monetary_inventory_shared_hooks import preflight as physical_preflight
from reconforge.infrastructure.postgres_monetary_receivables import MONETARY_SCHEMA_SQL, monetary_return_schema
from reconforge.infrastructure.postgres_monetary_stock_shared_hooks import preflight as stock_preflight

_FUNCTION = re.compile(
    r"CREATE(?: OR REPLACE)? FUNCTION reconforge\.([a-z0-9_]+)\(([^)]*)\)\s+RETURNS\s+([a-zA-Z]+)\s+"
    r"LANGUAGE\s+(plpgsql|sql)([^$]+)AS\s+(\$[a-z0-9_]*\$)(.*?)\6;", re.M | re.S)


def function_preflight(source: str) -> str:
    """Pin the closed emitted native function set, bodies and execution profile."""
    statements = _FUNCTION.findall(source)
    declarations = re.findall(r"CREATE(?: OR REPLACE)? FUNCTION reconforge\.([a-z0-9_]+)\(", source)
    if not statements or [row[0] for row in statements] != declarations or len(declarations) != len(set(declarations)):
        raise ValueError("The monetary native function inventory is incomplete or overloaded.")
    checks = []
    for name, arguments, returns, language, attributes, _delimiter, body in statements:
        pairs = [argument.strip().split() for argument in arguments.split(",")] if arguments.strip() else []
        if any(len(pair) != 2 or re.fullmatch(r"[a-z][a-z0-9_]*", pair[0]) is None
               or pair[1].upper() not in {"TEXT", "JSONB", "INTEGER", "BIGINT", "BOOLEAN", "NUMERIC"} for pair in pairs):
            raise ValueError("Explicit finite native function arguments are required.")
        normalized = " ".join(attributes.split()).upper()
        if normalized not in {policy + "SET SEARCH_PATH=PG_CATALOG" for policy in ("", "IMMUTABLE ", "STABLE ", "VOLATILE ")}:
            raise ValueError("Native monetary functions require their exact invoker execution profile.")
        if returns.lower() not in {"void", "trigger", "integer", "bigint", "text", "numeric", "jsonb", "boolean"}:
            raise ValueError("Unsupported monetary native result type.")
        values = {
            "SIGNATURE": name + "(" + ",".join(pair[1].lower() for pair in pairs) + ")",
            "RETURNS": {"integer": "int4", "bigint": "int8", "boolean": "bool"}.get(returns.lower(), returns.lower()), "LANGUAGE": language,
            "VOLATILITY": "i" if "IMMUTABLE" in normalized else "s" if "STABLE" in normalized else "v",
            "ARGNAMES": "ARRAY[" + ",".join("'" + pair[0] + "'" for pair in pairs) + "]::text[]" if pairs else "NULL::text[]",
            "BODY_HASH": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        }
        statement = r""" SELECT * INTO native FROM pg_catalog.pg_proc WHERE oid=pg_catalog.to_regprocedure('reconforge.@@SIGNATURE@@');
 IF native.oid IS NULL OR native.prosecdef OR native.proretset OR native.proleakproof OR native.proisstrict
 OR native.prokind<>'f' OR native.proparallel<>'u' OR native.provariadic<>0 OR native.pronargdefaults<>0
 OR native.proargmodes IS NOT NULL OR native.proallargtypes IS NOT NULL OR native.procost<>100 OR native.prorows<>0
 OR native.proargnames IS DISTINCT FROM @@ARGNAMES@@ OR native.prorettype<>'pg_catalog.@@RETURNS@@'::regtype
 OR native.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='@@LANGUAGE@@')
 OR native.provolatile<>'@@VOLATILITY@@' OR native.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog']::text[]
 OR(SELECT count(*) FROM pg_catalog.pg_proc extra WHERE extra.pronamespace=native.pronamespace AND extra.proname=native.proname)<>1
 OR encode(sha256(convert_to(native.prosrc,'UTF8')),'hex')<>'@@BODY_HASH@@' THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_monetary_owner',MESSAGE='Monetary native execution contract drift';
 END IF;
"""
        for key, value in values.items():
            statement = statement.replace("@@" + key + "@@", value)
        checks.append(statement)
    return "DO $cr149verify$ DECLARE native RECORD;BEGIN\n" + "".join(checks) + "END $cr149verify$;\n"


def installation_preflight_sql() -> str:
    """Emit the same complete verifier for online installs and offline migrations."""
    from reconforge.infrastructure.postgres_monetary_customer_returns_schema import (
        NATIVE_CATALOG_SQL,
        NATIVE_FUNCTION_SQL,
        NATIVE_TRIGGER_CONTRACTS,
    )

    statements = [function_preflight(NATIVE_FUNCTION_SQL), stock_preflight(upgraded=True), physical_preflight(upgraded=True)]
    statements.append("DO $cr149catalog$ DECLARE profile JSONB;BEGIN SELECT catalog.profile INTO profile FROM ("
        + MONETARY_SCHEMA_SQL + ") catalog; IF profile IS NULL OR (SELECT count(*) FROM jsonb_object_keys(profile))<>18 OR EXISTS("
        "SELECT 1 FROM jsonb_each(profile) flag WHERE flag.value IS DISTINCT FROM 'true'::jsonb) THEN "
        "RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_monetary_owner',"
        "MESSAGE='Monetary native storage or report execution contract drift'; END IF; END $cr149catalog$;\n")
    names: set[tuple[str, str]] = set()
    for table, name, signature, kind, deferred, initially_deferred, enabled in NATIVE_TRIGGER_CONTRACTS:
        if (re.fullmatch(r"[a-z][a-z0-9_]*", table) is None or re.fullmatch(r"[a-z][a-z0-9_]*", name) is None
                or re.fullmatch(r"[a-z][a-z0-9_]*\((?:text(?:,text)*)?\)", signature) is None
                or type(kind) is not int or not 0 < kind < 128 or type(deferred) is not bool
                or type(initially_deferred) is not bool or enabled != "O" or (table, name) in names):
            raise ValueError("The monetary native trigger inventory is malformed or duplicated.")
        names.add((table, name))
        statement = """DO $cr149trigger$ BEGIN IF (SELECT count(*) FROM pg_catalog.pg_trigger trigger
            WHERE trigger.tgrelid=to_regclass('reconforge.@@TABLE@@') AND trigger.tgname='@@NAME@@'
              AND trigger.tgtype::integer=@@KIND@@ AND trigger.tgdeferrable=@@DEFERRED@@
              AND trigger.tginitdeferred=@@INITIAL@@ AND trigger.tgenabled='O'
              AND trigger.tgfoid=to_regprocedure('reconforge.@@SIGNATURE@@') AND NOT trigger.tgisinternal
              AND trigger.tgnargs=0 AND trigger.tgqual IS NULL)<>1 THEN
             RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_monetary_owner',
              MESSAGE='Monetary native trigger binding or execution profile drift';
            END IF; END $cr149trigger$;\n"""
        for key, value in {"TABLE": table, "NAME": name, "SIGNATURE": signature, "KIND": str(kind),
                           "DEFERRED": str(deferred).upper(), "INITIAL": str(initially_deferred).upper()}.items():
            statement = statement.replace("@@" + key + "@@", value)
        statements.append(statement)
    if not names:
        raise ValueError("The monetary native trigger inventory is empty.")
    statements.append(NATIVE_CATALOG_SQL)
    return "\n".join(statements)


def verify_monetary_installation_if_present(connection: Any) -> bool:
    """Return False only for a genuinely absent149 namespace, without caching."""
    rows = records(connection.execute("""SELECT
        to_regprocedure('reconforge.monetary_stock_version()') IS NOT NULL AS marker,
        to_regprocedure('reconforge.monetary_stock_invoice_credit(text,text)') IS NOT NULL AS credit,
        to_regprocedure('reconforge.monetary_stock_invoice_balance(text,text)') IS NOT NULL AS balance,
        EXISTS(SELECT 1 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
         WHERE n.nspname='reconforge' AND left(p.proname,9)='monetary_') AS helpers,
        (SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
         WHERE n.nspname='reconforge' AND c.relname IN('stock_sales_monetary_origins','customer_partial_return_monetary_plans',
          'customer_partial_return_monetary_entries','customer_partial_return_monetary_events','customer_partial_return_monetary_history',
          'customer_partial_return_monetary_restorations','customer_partial_return_monetary_commands')) AS relations"""))
    if len(rows) != 1 or set(rows[0]) != {"marker", "credit", "balance", "helpers", "relations"}:
        raise ValueError("The native monetary installation lookup is incomplete.")
    profile = rows[0]
    if any(type(profile[name]) is not bool for name in ("marker", "credit", "balance", "helpers")) or type(profile["relations"]) is not int:
        raise ValueError("The native monetary installation lookup has invalid types.")
    if not any(profile.values()):
        return False
    if not all(profile[name] for name in ("marker", "credit", "balance", "helpers")) or profile["relations"] != 7:
        raise ValueError("A partial monetary native installation cannot fall back to legacy behavior.")
    if not monetary_return_schema(connection):
        raise ValueError("The installed monetary owner has no verified native storage.")
    connection.execute(installation_preflight_sql())
    return True
