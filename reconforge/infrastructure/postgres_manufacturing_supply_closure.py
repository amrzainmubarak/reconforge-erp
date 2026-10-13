"""Keep complete MSP closure while removing repeated native delegation.

This is an additive, root-migration-owned function replacement. It leaves the
original 0142 installation, evidence validator, tables, triggers, caller scope,
locks and financial source bytes intact. No closure result survives an invocation.
"""
from __future__ import annotations

from typing import Any

from reconforge.infrastructure.postgres_manufacturing_supply_plan_schema import OWNER_SQL


def _original_function(name: str) -> str:
    marker = f"CREATE FUNCTION reconforge.{name}("
    if OWNER_SQL.count(marker) != 1:
        raise RuntimeError("Original MSP closure definition must remain unique")
    original = marker + OWNER_SQL.split(marker, 1)[1].split("END $msp$;", 1)[0] + "END $msp$;"
    return original.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def _replace_once(source: str, original: str, replacement: str) -> str:
    if source.count(original) != 1:
        raise RuntimeError("Original MSP closure delegation needs renewed qualification")
    return source.replace(original, replacement, 1)


ORIGINAL_CLOSE_SQL = _original_function("msp_close")
ORIGINAL_PURCHASE_SQL = _original_function("msp_purchase_close")

_PER_REQUIREMENT_PROCUREMENT = (
    " FOR c IN SELECT DISTINCT requisition_id FROM reconforge.manufacturing_supply_procurement_claims "
    "WHERE tenant_id=t AND requirement_id=r.id LOOP\n"
    " PERFORM reconforge.msp_procurement_close(t,c.requisition_id);END LOOP;"
)
_PER_PLAN_PROCUREMENT = (
    " FOR c IN SELECT DISTINCT requisition_id FROM reconforge.manufacturing_supply_procurement_claims "
    "WHERE tenant_id=t AND plan_id=i LOOP\n"
    " PERFORM reconforge.msp_procurement_close(t,c.requisition_id);END LOOP;\n"
)
_AFTER_REQUIREMENTS = (
    " PERFORM reconforge.msp_assert(p.phase<>3 OR NOT EXISTS(SELECT 1 "
    "FROM reconforge.manufacturing_supply_stock_claims"
)
_CAPACITY_AND_FIFO = (
    " PERFORM reconforge.inventory_quantity_check_capacity(t,p.workspace_id,p.legal_entity_id,r.item_id,r.location_id);\n"
    " PERFORM reconforge.inventory_quantity_free_fifo(t,p.workspace_id,p.legal_entity_id,r.item_id);"
)

CLOSE_SQL = _replace_once(ORIGINAL_CLOSE_SQL, _PER_REQUIREMENT_PROCUREMENT, "")
CLOSE_SQL = _replace_once(CLOSE_SQL, _AFTER_REQUIREMENTS, _PER_PLAN_PROCUREMENT + _AFTER_REQUIREMENTS)
CLOSE_SQL = _replace_once(CLOSE_SQL, _CAPACITY_AND_FIFO, _CAPACITY_AND_FIFO.split("\n", 1)[0])
PURCHASE_SQL = _replace_once(
    ORIGINAL_PURCHASE_SQL,
    "PERFORM reconforge.pp_verify_order(t,i);PERFORM reconforge.pc_close(t,i);",
    "PERFORM reconforge.pp_verify_order(t,i);",
)

# Pin reviewed native bodies and execution metadata. A retained call in a comment
# or behind an early return cannot qualify a changed delegate. The BPC1 prefix
# enforced by the original purchase closure selects the reviewed budget branch.
_DELEGATION_SQL = r"""
DO $msp$ BEGIN
 PERFORM reconforge.msp_assert(EXISTS(SELECT 1 FROM pg_proc f JOIN pg_language l ON l.oid=f.prolang
  WHERE f.oid='reconforge.pp_verify_order(text,text)'::regprocedure AND l.lanname='plpgsql'
  AND f.prokind='f' AND f.prorettype='void'::regtype AND NOT f.proretset AND NOT f.prosecdef AND NOT f.proleakproof
  AND f.provolatile='v' AND f.proparallel='u' AND f.proargnames=ARRAY['t','i']::text[]
  AND f.proconfig=ARRAY['search_path=pg_catalog']::text[]
  AND encode(sha256(convert_to(f.prosrc,'UTF8')),'hex')='98eaa4b72669f4b8d851106dd918464133a235d662020a12c8cf017d78ce194e'),
  'MSP purchasing closure requires the native budget commitment delegate');
 PERFORM reconforge.msp_assert(EXISTS(SELECT 1 FROM pg_proc f JOIN pg_language l ON l.oid=f.prolang
  WHERE f.oid='reconforge.inventory_quantity_check_capacity(text,text,text,text,text)'::regprocedure AND l.lanname='plpgsql'
  AND f.prokind='f' AND f.prorettype='void'::regtype AND NOT f.proretset AND NOT f.prosecdef AND NOT f.proleakproof
  AND f.provolatile='s' AND f.proparallel='u' AND f.proargnames=ARRAY['t','w','e','i','l']::text[]
  AND f.proconfig=ARRAY['search_path=pg_catalog']::text[]
  AND encode(sha256(convert_to(f.prosrc,'UTF8')),'hex')='8da223f6c900503bde83d9861f0fd5c166270c82d19051423b9649cef9f4f9a0'),
  'MSP capacity closure requires the native exact FIFO delegate');
END $msp$;
"""

UPGRADE_SQL = _DELEGATION_SQL + CLOSE_SQL + "\n" + PURCHASE_SQL
DOWNGRADE_SQL = ORIGINAL_CLOSE_SQL + "\n" + ORIGINAL_PURCHASE_SQL


def install_postgres_manufacturing_supply_closure(connection: Any) -> None:
    """Replace the two owned functions; root alone owns ordered migration adoption."""
    connection.execute(UPGRADE_SQL)
