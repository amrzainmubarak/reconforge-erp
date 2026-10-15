"""Finite149 dispatch over the exact accepted Stock/FX function bodies.

CREATE OR REPLACE preserves original OIDs, owners, grants and trigger bindings.
Unknown original bodies or execution attributes refuse before replacement.
These exports are components of the atomic149 migration, not an installer for
an incomplete monetary owner. The companion native module supplies the new
financial checks; original branches remain byte-for-byte present.
"""

from __future__ import annotations

import hashlib
import re

from reconforge.infrastructure.postgres_customer_partial_return_zero_stock_hooks import (
    UPGRADED_FUNCTIONS as ZERO_STOCK_FUNCTIONS,
)
from reconforge.infrastructure.postgres_operational_fx_revaluation_schema import ACTOR_SQL, CLOSE_SQL, VALUATION_SQL
from reconforge.infrastructure.postgres_stock_sales_schema import POSTGRES_STOCK_SALES_SCHEMA_SQL


def _definition(name: str, sql: str, delimiter: str) -> str:
    matches = re.findall(r"CREATE(?: OR REPLACE)? FUNCTION reconforge\." + re.escape(name) + r"\(.*?" + re.escape(delimiter) + ";", sql, re.S)
    if len(matches) != 1:
        raise ValueError("Exactly one retained Stock/FX function is required.")
    return matches[0]


ORIGINAL_FUNCTIONS = {
    "stock_sales_admit": _definition("stock_sales_admit", POSTGRES_STOCK_SALES_SCHEMA_SQL, "$$"),
    "stock_sales_protect": _definition("stock_sales_protect", POSTGRES_STOCK_SALES_SCHEMA_SQL, "$$"),
    "stock_sales_close": ZERO_STOCK_FUNCTIONS["stock_sales_close"],
    "stock_sales_public": ZERO_STOCK_FUNCTIONS["stock_sales_public"],
    "fx_close": _definition("fx_close", CLOSE_SQL, "$fx$"),
    "fx_command_actor": _definition("fx_command_actor", ACTOR_SQL, "$fx$"),
    "fx_valuation_equation": _definition("fx_valuation_equation", VALUATION_SQL, "$fx$"),
}
_SIGNATURES = {
    "stock_sales_admit": ("", "trigger", "plpgsql", "v", ()),
    "stock_sales_protect": ("", "trigger", "plpgsql", "v", ()),
    "stock_sales_close": ("text,text", "void", "plpgsql", "v", ("t", "target")),
    "stock_sales_public": ("reconforge.stock_sales_orders", "jsonb", "sql", "s", ("d",)),
    "fx_close": ("text,text", "void", "plpgsql", "v", ("t", "i")),
    "fx_command_actor": ("", "trigger", "plpgsql", "v", ()),
    "fx_valuation_equation": ("text,text", "jsonb", "plpgsql", "v", ("t", "i")),
}


def _body(statement: str) -> tuple[str, str]:
    match = re.search(r"\bAS\s+(\$[a-z0-9_]*\$)", statement, re.I)
    if match is None:
        raise ValueError("A retained explicit function body delimiter is required.")
    delimiter = match[1]
    fragments = statement.split(delimiter)
    if len(fragments) != 3 or fragments[2] != ";":
        raise ValueError("The retained function body is not closed.")
    return delimiter, fragments[1]


def _replace_body(original: str, replacement: str) -> str:
    delimiter, before = _body(original)
    if delimiter in replacement:
        raise ValueError("New dispatch cannot contain the retained delimiter.")
    definition = original.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    return definition.replace(delimiter + before + delimiter, delimiter + replacement + delimiter, 1)


def _prepend(name: str, dispatch: str) -> str:
    original = ORIGINAL_FUNCTIONS[name]
    _, body = _body(original)
    before, marker, after = body.partition("BEGIN\n")
    if not marker or "BEGIN" in before:
        raise ValueError("One initial retained PL/pgSQL BEGIN is required.")
    return _replace_body(original, before + marker + dispatch + after)


_STOCK_TRIGGER_DISPATCH = r""" -- Fixed monetary sources have their own complete native contract.
 IF (TG_TABLE_NAME='stock_sales_orders' AND (
   CASE WHEN TG_OP='INSERT' THEN NULL ELSE to_jsonb(OLD)#>>'{source,schema_version}' END='stock-sales-monetary-order-v2'
   OR CASE WHEN TG_OP='DELETE' THEN NULL ELSE to_jsonb(NEW)#>>'{source,schema_version}' END='stock-sales-monetary-order-v2'))
 OR(TG_TABLE_NAME<>'stock_sales_orders' AND EXISTS(SELECT 1 FROM reconforge.stock_sales_orders fixed
   WHERE fixed.source->>'schema_version'='stock-sales-monetary-order-v2' AND (
    (fixed.tenant_id,fixed.id)=(CASE WHEN TG_OP='INSERT' THEN NULL ELSE to_jsonb(OLD)->>'tenant_id' END,
                               CASE WHEN TG_OP='INSERT' THEN NULL ELSE to_jsonb(OLD)->>'order_id' END)
    OR(fixed.tenant_id,fixed.id)=(CASE WHEN TG_OP='DELETE' THEN NULL ELSE to_jsonb(NEW)->>'tenant_id' END,
                                CASE WHEN TG_OP='DELETE' THEN NULL ELSE to_jsonb(NEW)->>'order_id' END)))) THEN
  PERFORM reconforge.monetary_stock_admit(TG_TABLE_NAME,TG_OP,
   CASE WHEN TG_OP='INSERT' THEN NULL ELSE to_jsonb(OLD) END,
   CASE WHEN TG_OP='DELETE' THEN NULL ELSE to_jsonb(NEW) END);
  IF TG_OP='DELETE' THEN RETURN OLD;END IF;RETURN NEW;
 END IF;
"""

_STOCK_CLOSE_DISPATCH = r""" IF EXISTS(SELECT 1 FROM reconforge.stock_sales_orders fixed WHERE fixed.tenant_id=t AND fixed.id=target
  AND fixed.source->>'schema_version'='stock-sales-monetary-order-v2') THEN
  PERFORM reconforge.monetary_stock_close(t,target);RETURN;
 END IF;
"""

_FX_CLOSE_DISPATCH = r""" IF EXISTS(SELECT 1 FROM reconforge.operational_fx_plans plan JOIN reconforge.operational_fx_sources fixed
  ON(fixed.tenant_id,fixed.id)=(plan.tenant_id,plan.source_id) WHERE plan.tenant_id=t AND plan.id=i
  AND fixed.payload->>'schema_version'='operational-fx-stock-source-v2') THEN
  PERFORM reconforge.monetary_fx_close(t,i);RETURN;
 END IF;
"""

_FX_EQUATION_DISPATCH = _FX_CLOSE_DISPATCH.replace(
    "PERFORM reconforge.monetary_fx_close(t,i);RETURN;", "RETURN reconforge.monetary_fx_valuation_equation(t,i);")

_FX_ACTOR_DISPATCH = r""" IF EXISTS(SELECT 1 FROM reconforge.operational_fx_plans plan JOIN reconforge.operational_fx_sources fixed
  ON(fixed.tenant_id,fixed.id)=(plan.tenant_id,plan.source_id)
  WHERE plan.tenant_id=NEW.tenant_id AND plan.id=NEW.plan_id
  AND fixed.payload->>'schema_version'='operational-fx-stock-source-v2') THEN
  PERFORM reconforge.monetary_fx_command_actor(TG_TABLE_NAME,TG_OP,
   CASE WHEN TG_OP='INSERT' THEN NULL ELSE to_jsonb(OLD) END,
   CASE WHEN TG_OP='DELETE' THEN NULL ELSE to_jsonb(NEW) END);
  IF TG_OP='DELETE' THEN RETURN OLD;END IF;RETURN NEW;
 END IF;
"""

_, _PUBLIC_ORIGINAL_BODY = _body(ORIGINAL_FUNCTIONS["stock_sales_public"])
_PUBLIC_BODY = "".join((
    " SELECT CASE WHEN d.source->>'schema_version'='stock-sales-monetary-order-v2'\n",
    " THEN reconforge.monetary_stock_public(d.tenant_id,d.id) ELSE (\n",
    _PUBLIC_ORIGINAL_BODY.strip().removesuffix(";"), "\n) END ",
))

UPGRADED_FUNCTIONS = {
    "stock_sales_admit": _prepend("stock_sales_admit", _STOCK_TRIGGER_DISPATCH),
    "stock_sales_protect": _prepend("stock_sales_protect", _STOCK_TRIGGER_DISPATCH),
    "stock_sales_close": _prepend("stock_sales_close", _STOCK_CLOSE_DISPATCH),
    "stock_sales_public": _replace_body(ORIGINAL_FUNCTIONS["stock_sales_public"], _PUBLIC_BODY),
    "fx_close": _prepend("fx_close", _FX_CLOSE_DISPATCH),
    "fx_command_actor": _prepend("fx_command_actor", _FX_ACTOR_DISPATCH),
    "fx_valuation_equation": _prepend("fx_valuation_equation", _FX_EQUATION_DISPATCH),
}
if set(UPGRADED_FUNCTIONS) != set(_SIGNATURES) or set(ORIGINAL_FUNCTIONS) != set(_SIGNATURES):
    raise ValueError("The finite Stock/FX dispatch inventory differs.")


def preflight(*, upgraded: bool) -> str:
    """Pin the exact source body and unchanged execution profile before DDL."""
    source = UPGRADED_FUNCTIONS if upgraded else ORIGINAL_FUNCTIONS
    checks = []
    for name, (arguments, returns, language, volatility, names) in _SIGNATURES.items():
        _, body = _body(source[name])
        values = {
            "SIGNATURE": name + "(" + arguments + ")", "RETURNS": returns, "LANGUAGE": language,
            "VOLATILITY": volatility, "BODY_HASH": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "ARGNAMES": "ARRAY[" + ",".join("'" + item + "'" for item in names) + "]::text[]" if names else "NULL::text[]",
        }
        statement = r""" SELECT * INTO native FROM pg_catalog.pg_proc WHERE oid=pg_catalog.to_regprocedure('reconforge.@@SIGNATURE@@');
 IF native.oid IS NULL OR native.prosecdef OR native.proretset OR native.proleakproof OR native.proisstrict
 OR native.prokind<>'f' OR native.proparallel<>'u' OR native.provariadic<>0 OR native.pronargdefaults<>0
 OR native.proargmodes IS NOT NULL OR native.proallargtypes IS NOT NULL OR native.procost<>100 OR native.prorows<>0
 OR native.proargnames IS DISTINCT FROM @@ARGNAMES@@
 OR native.prorettype<>'pg_catalog.@@RETURNS@@'::regtype
 OR native.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='@@LANGUAGE@@')
 OR native.provolatile<>'@@VOLATILITY@@' OR native.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog']::text[]
 OR encode(sha256(convert_to(native.prosrc,'UTF8')),'hex')<>'@@BODY_HASH@@' THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_monetary_owner',
   MESSAGE='Retained Stock/FX execution contract drift';
 END IF;
"""
        for key, value in values.items():
            statement = statement.replace("@@" + key + "@@", value)
        checks.append(statement)
    return "DO $cr149dispatch$ DECLARE native RECORD;BEGIN\n" + "".join(checks) + "END $cr149dispatch$;\n"


UPGRADE_SQL = preflight(upgraded=False) + "\n".join(UPGRADED_FUNCTIONS.values())
DOWNGRADE_SQL = preflight(upgraded=True) + "\n".join(
    value.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1) for value in ORIGINAL_FUNCTIONS.values())
