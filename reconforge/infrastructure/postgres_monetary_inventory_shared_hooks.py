"""Finite149 physical dispatch preserving the accepted147/148 function bodies.

This component is installed only with the complete monetary native owner. The
existing cost-layer definer keeps its security context, owner, ACL and OID. Its
immutable-history equation gains signed actual CR3 restoration rows; all new
source, phase and financial checks execute through the caller's native owner.
"""

from __future__ import annotations

import hashlib

from reconforge.infrastructure.postgres_customer_partial_return_rounding_schema import WITNESS_SQL
from reconforge.infrastructure.postgres_customer_partial_return_rounding_transfer_hooks import (
    UPGRADED_FUNCTIONS as ROUNDING_TRANSFER_FUNCTIONS,
)
from reconforge.infrastructure.postgres_customer_partial_return_shared_hooks import _HISTORY_ADDITION, _PATCHES
from reconforge.infrastructure.postgres_customer_partial_return_transfer_hooks import (
    UPGRADED_FUNCTIONS as TRANSFER_FUNCTIONS,
)
from reconforge.infrastructure.postgres_customer_partial_return_zero_stock_hooks import ADMISSION_SQL
from reconforge.infrastructure.postgres_customer_partial_return_zero_stock_hooks import (
    UPGRADED_FUNCTIONS as ZERO_STOCK_FUNCTIONS,
)
from reconforge.infrastructure.postgres_inventory_receipt_posting_schema import _HISTORY_SQL
from reconforge.infrastructure.postgres_inventory_valuation_reversal import (
    POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL,
)
from reconforge.infrastructure.postgres_monetary_stock_shared_hooks import _body, _definition, _replace_body


def _replace(value: str, before: str, after: str) -> str:
    if value.count(before) != 1:
        raise ValueError("One exact accepted monetary physical hook anchor is required.")
    return value.replace(before, after, 1)


def _cost_original() -> str:
    value = _definition("inventory_cost_layer_guard", POSTGRES_INVENTORY_VALUATION_REVERSAL_SCHEMA_SQL, "$$")
    for _, anchor, addition in _PATCHES[:2]:
        value = _replace(value, anchor, anchor + addition)
    return value


def _history_original() -> str:
    value = _definition("guard_inventory_receipt_layer_history_complete", _HISTORY_SQL, "$irp$")
    return _replace(value, _PATCHES[2][1], _HISTORY_ADDITION + _PATCHES[2][1])


ORIGINAL_FUNCTIONS = {
    "inventory_cost_layer_guard": _cost_original(),
    "guard_inventory_receipt_layer_history_complete": _history_original(),
    "guard_inventory_receipt_link": ZERO_STOCK_FUNCTIONS["guard_inventory_receipt_link"],
    "customer_partial_return_zero_layer_guard": _definition("customer_partial_return_zero_layer_guard", WITNESS_SQL, "$cr148$"),
    "customer_partial_return_zero_stock_active": _definition("customer_partial_return_zero_stock_active", ADMISSION_SQL, "$cr148zs$"),
    "customer_partial_return_zero_stock_plan": _definition("customer_partial_return_zero_stock_plan", ADMISSION_SQL, "$cr148zs$"),
    "it1_cost_snapshot": ROUNDING_TRANSFER_FUNCTIONS["it1_cost_snapshot"],
    "it1_cost_originals": ROUNDING_TRANSFER_FUNCTIONS["it1_cost_originals"],
    "it1_stock_origins": TRANSFER_FUNCTIONS["it1_stock_origins"],
}
_SIGNATURES = {
    "inventory_cost_layer_guard": ("", "trigger", "v", (), True),
    "guard_inventory_receipt_layer_history_complete": ("", "trigger", "v", (), False),
    "guard_inventory_receipt_link": ("", "trigger", "v", (), False),
    "customer_partial_return_zero_layer_guard": ("", "trigger", "v", (), False),
    "customer_partial_return_zero_stock_active": ("text,text", "jsonb", "v", ("t", "d"), False),
    "customer_partial_return_zero_stock_plan": ("text,text", "void", "s", ("t", "i"), False),
    "it1_cost_snapshot": ("text,text,text,text,text", "jsonb", "s", ("t", "w", "o", "e", "i"), False),
    "it1_cost_originals": ("text,jsonb", "void", "s", ("t", "cost"), False),
    "it1_stock_origins": ("text,text,text,text,text", "void", "v", ("t", "w", "o", "e", "i"), False),
}


def _prepend(name: str, addition: str) -> str:
    original = ORIGINAL_FUNCTIONS[name]
    _, body = _body(original)
    return _replace_body(original, _replace(body, "BEGIN\n", "BEGIN\n" + addition))


def _cost() -> str:
    value = ORIGINAL_FUNCTIONS["inventory_cost_layer_guard"]
    corrections = (
        ("(SELECT COALESCE(SUM(direction::numeric*quantity_scaled),0) FROM reconforge.customer_partial_return_restorations WHERE tenant_id=OLD.tenant_id AND cost_layer_id=OLD.id)",
         "+(SELECT COALESCE(SUM(direction::numeric*quantity_scaled),0) FROM reconforge.customer_partial_return_monetary_restorations WHERE tenant_id=OLD.tenant_id AND cost_layer_id=OLD.id)"),
        ("(SELECT COALESCE(SUM(direction::numeric*value_minor),0) FROM reconforge.customer_partial_return_restorations WHERE tenant_id=OLD.tenant_id AND cost_layer_id=OLD.id)",
         "+(SELECT COALESCE(SUM(direction::numeric*value_minor),0) FROM reconforge.customer_partial_return_monetary_restorations WHERE tenant_id=OLD.tenant_id AND cost_layer_id=OLD.id)"),
    )
    for anchor, addition in corrections:
        value = _replace(value, anchor, anchor + addition)
    return value


def _history() -> str:
    original = ORIGINAL_FUNCTIONS["guard_inventory_receipt_layer_history_complete"]
    addition = _HISTORY_ADDITION.replace("reconforge.customer_partial_return_restorations", "reconforge.customer_partial_return_monetary_restorations")
    return _replace(original, _PATCHES[2][1], addition + _PATCHES[2][1])


def _chronology() -> str:
    original = ORIGINAL_FUNCTIONS["guard_inventory_receipt_link"]
    original = _replace(original,
        "AND NOT reconforge.customer_partial_return_valued_movement(m.tenant_id,m.id))",
        "AND NOT reconforge.customer_partial_return_valued_movement(m.tenant_id,m.id)\n  AND NOT reconforge.monetary_return_valued_movement(m.tenant_id,m.id))")
    return _replace(original,
        "OR(m.status='Posted' AND reconforge.customer_partial_return_valued_movement(m.tenant_id,m.id)))",
        "OR(m.status='Posted' AND(reconforge.customer_partial_return_valued_movement(m.tenant_id,m.id)\n    OR reconforge.monetary_return_valued_movement(m.tenant_id,m.id))))")


_ZERO_LAYER = r""" IF NEW.remaining_quantity_scaled>0 AND NEW.remaining_value_minor=0
 AND reconforge.monetary_return_zero_layer_admitted(NEW.tenant_id,NEW.id,
  CASE WHEN TG_OP='INSERT' THEN NULL ELSE to_jsonb(OLD) END,to_jsonb(NEW),TG_OP) THEN RETURN NEW;END IF;
"""
_ZERO_ACTIVE = r""" IF EXISTS(SELECT 1 FROM reconforge.inventory_valuation_documents dispatch_document
 JOIN reconforge.inventory_movements dispatch_movement ON(dispatch_movement.tenant_id,dispatch_movement.id)=(dispatch_document.tenant_id,dispatch_document.movement_id)
 JOIN reconforge.stock_sales_orders dispatch_stock ON(dispatch_stock.tenant_id,dispatch_stock.id)=(dispatch_movement.tenant_id,dispatch_movement.source_reference)
 WHERE dispatch_document.tenant_id=t AND dispatch_document.id=d AND dispatch_stock.source->>'schema_version'='stock-sales-monetary-order-v2') THEN
  RETURN reconforge.monetary_stock_zero_active(t,d);
 END IF;
"""
_ZERO_PLAN = r""" IF EXISTS(SELECT 1 FROM reconforge.stock_sales_orders dispatch_stock WHERE dispatch_stock.tenant_id=t AND dispatch_stock.id=i
 AND dispatch_stock.source->>'schema_version'='stock-sales-monetary-order-v2') THEN
  PERFORM reconforge.monetary_stock_zero_plan(t,i);RETURN;
 END IF;
"""
_COST_SNAPSHOT = r""" IF EXISTS(SELECT 1 FROM reconforge.customer_partial_return_monetary_restorations dispatch_restoration
 JOIN reconforge.inventory_cost_layers dispatch_layer ON(dispatch_layer.tenant_id,dispatch_layer.id)=(dispatch_restoration.tenant_id,dispatch_restoration.cost_layer_id)
 WHERE dispatch_layer.tenant_id=t AND dispatch_layer.workspace_id=w AND dispatch_layer.legal_entity_id=e AND dispatch_layer.item_id=i)
 OR EXISTS(SELECT 1 FROM reconforge.inventory_cost_layers dispatch_layer
 JOIN reconforge.inventory_layer_consumptions dispatch_consumed ON(dispatch_consumed.tenant_id,dispatch_consumed.cost_layer_id)=(dispatch_layer.tenant_id,dispatch_layer.id)
 JOIN reconforge.inventory_valuation_lines dispatch_detail ON(dispatch_detail.tenant_id,dispatch_detail.id)=(dispatch_consumed.tenant_id,dispatch_consumed.valuation_line_id)
 JOIN reconforge.inventory_valuation_documents dispatch_document ON(dispatch_document.tenant_id,dispatch_document.id)=(dispatch_detail.tenant_id,dispatch_detail.valuation_document_id)
 JOIN reconforge.inventory_movements dispatch_movement ON(dispatch_movement.tenant_id,dispatch_movement.id)=(dispatch_document.tenant_id,dispatch_document.movement_id)
 JOIN reconforge.stock_sales_orders dispatch_stock ON(dispatch_stock.tenant_id,dispatch_stock.id)=(dispatch_movement.tenant_id,dispatch_movement.source_reference)
 WHERE dispatch_layer.tenant_id=t AND dispatch_layer.workspace_id=w AND dispatch_layer.legal_entity_id=e AND dispatch_layer.item_id=i
 AND dispatch_stock.source->>'schema_version'='stock-sales-monetary-order-v2') THEN
  RETURN reconforge.monetary_transfer_cost_snapshot(t,w,o,e,i);
 END IF;
"""
_COST_ORIGINALS = r""" IF cost->>'schema_version'='inventory-transfer-cost-v4' THEN
  PERFORM reconforge.monetary_transfer_cost_originals(t,cost);RETURN;
 END IF;
"""
_STOCK_ORIGINS = r""" IF EXISTS(SELECT 1 FROM reconforge.inventory_movements dispatch_movement
 JOIN reconforge.inventory_movement_lines dispatch_detail ON(dispatch_detail.tenant_id,dispatch_detail.movement_id)=(dispatch_movement.tenant_id,dispatch_movement.id)
 WHERE(dispatch_movement.tenant_id,dispatch_movement.workspace_id,dispatch_movement.organization_id,dispatch_movement.legal_entity_id,dispatch_detail.item_id)=(t,w,o,e,i)
 AND dispatch_movement.source_type='Generated' AND(dispatch_movement.movement_number~'^CR3(R)?-[A-F0-9]{32}$'
 OR EXISTS(SELECT 1 FROM reconforge.stock_sales_orders dispatch_stock
  WHERE(dispatch_stock.tenant_id,dispatch_stock.id)=(dispatch_movement.tenant_id,dispatch_movement.source_reference)
  AND dispatch_stock.source->>'schema_version'='stock-sales-monetary-order-v2'))) THEN
  PERFORM reconforge.monetary_transfer_stock_origins(t,w,o,e,i);RETURN;
 END IF;
"""
UPGRADED_FUNCTIONS = {
    "inventory_cost_layer_guard": _cost(),
    "guard_inventory_receipt_layer_history_complete": _history(),
    "guard_inventory_receipt_link": _chronology(),
    "customer_partial_return_zero_layer_guard": _prepend("customer_partial_return_zero_layer_guard", _ZERO_LAYER),
    "customer_partial_return_zero_stock_active": _prepend("customer_partial_return_zero_stock_active", _ZERO_ACTIVE),
    "customer_partial_return_zero_stock_plan": _prepend("customer_partial_return_zero_stock_plan", _ZERO_PLAN),
    "it1_cost_snapshot": _prepend("it1_cost_snapshot", _COST_SNAPSHOT),
    "it1_cost_originals": _prepend("it1_cost_originals", _COST_ORIGINALS),
    "it1_stock_origins": _prepend("it1_stock_origins", _STOCK_ORIGINS),
}
if set(ORIGINAL_FUNCTIONS) != set(_SIGNATURES) or set(UPGRADED_FUNCTIONS) != set(_SIGNATURES):
    raise ValueError("The finite physical dispatch inventory differs.")


def preflight(*, upgraded: bool) -> str:
    """Reject drift in all nine exact bodies and their execution attributes."""
    functions = UPGRADED_FUNCTIONS if upgraded else ORIGINAL_FUNCTIONS
    checks = []
    for name, (arguments, returns, volatility, names, definer) in _SIGNATURES.items():
        _, body = _body(functions[name])
        values = {
            "SIGNATURE": name + "(" + arguments + ")", "RETURNS": returns, "VOLATILITY": volatility,
            "DEFINER": "TRUE" if definer else "FALSE",
            "CONFIG": "search_path=pg_catalog, reconforge" if definer else "search_path=pg_catalog",
            "ARGNAMES": "ARRAY[" + ",".join("'" + value + "'" for value in names) + "]::text[]" if names else "NULL::text[]",
            "BODY_HASH": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        }
        statement = r""" SELECT * INTO native FROM pg_catalog.pg_proc WHERE oid=pg_catalog.to_regprocedure('reconforge.@@SIGNATURE@@');
 IF native.oid IS NULL OR native.prosecdef IS DISTINCT FROM @@DEFINER@@ OR native.proretset OR native.proleakproof OR native.proisstrict
 OR native.prokind<>'f' OR native.proparallel<>'u' OR native.provariadic<>0 OR native.pronargdefaults<>0
 OR native.proargmodes IS NOT NULL OR native.proallargtypes IS NOT NULL OR native.procost<>100 OR native.prorows<>0
 OR native.proargnames IS DISTINCT FROM @@ARGNAMES@@ OR native.prorettype<>'pg_catalog.@@RETURNS@@'::regtype
 OR native.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
 OR native.provolatile<>'@@VOLATILITY@@' OR native.proconfig IS DISTINCT FROM ARRAY['@@CONFIG@@']::text[]
 OR encode(sha256(convert_to(native.prosrc,'UTF8')),'hex')<>'@@BODY_HASH@@' THEN
  RAISE EXCEPTION USING ERRCODE='23514',CONSTRAINT='customer_partial_return_monetary_owner',MESSAGE='Retained physical execution contract drift';
 END IF;
"""
        for key, value in values.items():
            statement = statement.replace("@@" + key + "@@", value)
        checks.append(statement)
    return "DO $cr149physical$ DECLARE native RECORD;BEGIN\n" + "".join(checks) + "END $cr149physical$;\n"


UPGRADE_SQL = preflight(upgraded=False) + "\n".join(UPGRADED_FUNCTIONS.values())
DOWNGRADE_SQL = preflight(upgraded=True) + "\n".join(
    value.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1) for value in ORIGINAL_FUNCTIONS.values())
