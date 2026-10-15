"""Fail-closed AR reads for the fixed monetary Stock source protocol.

The native owner closes writes and visibility. These reads validate its bounded
projection against actual AR allocations without replaying every journal for
every row in an aging report. An absent migration remains explicitly legacy;
an incomplete migration never falls back to legacy economics.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from reconforge.domain.operational_fx_tax import MAX_MINOR
from reconforge.platform.common import PlatformError

MONETARY_TABLES = (
    "stock_sales_monetary_origins",
    "customer_partial_return_monetary_plans",
    "customer_partial_return_monetary_entries",
    "customer_partial_return_monetary_events",
    "customer_partial_return_monetary_history",
    "customer_partial_return_monetary_restorations",
    "customer_partial_return_monetary_commands",
)
_HELPERS = (
    ("monetary_stock_invoice_credit", "numeric"),
    ("monetary_stock_invoice_balance", "jsonb"),
)
_OBJECTS = (*MONETARY_TABLES, *[name for name, _ in _HELPERS])
CATALOG_FIELDS = tuple(f"{name}_{kind}" for kind in ("present", "valid") for name in _OBJECTS)


MONETARY_SCHEMA_SQL = """WITH monetary_helpers AS (
    SELECT p.* FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
    WHERE n.nspname='reconforge' AND p.proname IN ('monetary_stock_invoice_credit','monetary_stock_invoice_balance')
), expected_tables(name) AS (VALUES
    ('stock_sales_monetary_origins'), ('customer_partial_return_monetary_plans'),
    ('customer_partial_return_monetary_entries'), ('customer_partial_return_monetary_events'),
    ('customer_partial_return_monetary_history'), ('customer_partial_return_monetary_restorations'),
    ('customer_partial_return_monetary_commands')
), expected_helpers(name,result_type) AS (VALUES
    ('monetary_stock_invoice_credit','pg_catalog.numeric'), ('monetary_stock_invoice_balance','pg_catalog.jsonb')
), proofs AS (
    SELECT e.name,c.oid IS NOT NULL AS present,
        COALESCE(c.relkind='r' AND c.relrowsecurity AND c.relforcerowsecurity,FALSE) AS valid
    FROM expected_tables e LEFT JOIN pg_catalog.pg_class c ON c.oid=pg_catalog.to_regclass('reconforge.'||e.name)
    UNION ALL
    SELECT e.name,EXISTS(SELECT 1 FROM monetary_helpers q WHERE q.proname=e.name),
        COALESCE(p.prorettype=pg_catalog.to_regtype(e.result_type) AND p.prokind='f'
          AND NOT p.proretset AND NOT p.prosecdef AND NOT p.proleakproof AND NOT p.proisstrict
          AND p.proparallel='u' AND p.pronargdefaults=0 AND p.proargnames=ARRAY['t','i']::text[]
          AND l.lanname='plpgsql' AND p.provolatile='s' AND p.proconfig=ARRAY['search_path=pg_catalog']::text[]
          AND (SELECT COUNT(*) FROM monetary_helpers q WHERE q.proname=e.name)=1,FALSE)
    FROM expected_helpers e
    LEFT JOIN monetary_helpers p ON p.oid=pg_catalog.to_regprocedure('reconforge.'||e.name||'(text,text)')
    LEFT JOIN pg_catalog.pg_language l ON l.oid=p.prolang
) SELECT pg_catalog.jsonb_object_agg(name||'_present',present)
    || pg_catalog.jsonb_object_agg(name||'_valid',valid) AS profile FROM proofs"""


def monetary_return_schema(connection: Any) -> bool:
    """Recheck all seven FORCE-RLS relations and both exact STABLE invoker helpers.

    Public reads share the calling statement's MVCC snapshot. Native mutation
    closures must use their separate VOLATILE current-state implementation.
    """
    row = connection.execute(MONETARY_SCHEMA_SQL).fetchone()
    try:
        profile = row["profile"] if isinstance(row, Mapping) else row[0]
        if isinstance(profile, Mapping):
            if set(profile) != set(CATALOG_FIELDS):
                raise ValueError("Unexpected catalog fields")
            flags = tuple(profile[key] for key in CATALOG_FIELDS)
        else:
            raise ValueError("Missing catalog profile")
        if len(flags) != len(CATALOG_FIELDS) or any(type(flag) is not bool for flag in flags):
            raise ValueError("Invalid catalog flags")
    except (TypeError, KeyError, IndexError, ValueError) as exc:
        raise PlatformError("Monetary-return schema integration cannot be verified.") from exc
    if not any(flags):
        return False
    if all(flags):
        return True
    raise PlatformError("Monetary-return schema integration is incomplete or malformed; complete the native migration.")


def natural_minor_text(value: object, *, bounded: bool = True) -> int:
    """Parse canonical SQL/JSON integer text without truncation or coercion."""
    if type(value) is not str or re.fullmatch(r"0|[1-9][0-9]*", value) is None:
        raise PlatformError("Monetary-return evidence requires exact nonnegative integer text.")
    try:
        result = int(value)
    except ValueError as exc:
        raise PlatformError("Monetary-return integer evidence cannot be represented.") from exc
    if bounded and result > MAX_MINOR:
        raise PlatformError("Monetary-return evidence exceeds the original monetary bound.")
    return result
BALANCE_MINOR_FIELDS = (
    "transaction_original_gross_minor", "functional_original_gross_minor",
    "transaction_collected_minor", "transaction_credited_minor",
    "transaction_outstanding_minor", "functional_outstanding_minor",
    "transaction_refund_entitlement_minor", "functional_refund_entitlement_minor",
    "transaction_refunded_minor", "functional_refund_released_minor",
    "transaction_refund_due_minor", "functional_refund_due_minor",
)
BALANCE_FIELDS = frozenset((*BALANCE_MINOR_FIELDS, "schema_version", "history_version", "history_fingerprint", "active_plan_id", "active_revaluation_plan_id"))


def monetary_invoice_balance(value: object, *, total_minor: int, allocated_minor: int) -> dict[str, Any]:
    """Validate the closed owner projection and its independent AR prefix."""
    if not isinstance(value, Mapping) or set(value) != BALANCE_FIELDS:
        raise PlatformError("Original monetary invoice balance is absent or malformed.")
    result = dict(value)
    if (result["schema_version"] != "stock-monetary-balance-v1"
            or type(result["history_version"]) is not int or not 0 <= result["history_version"] <= 256
            or type(result["history_fingerprint"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", result["history_fingerprint"]) is None):
        raise PlatformError("Original monetary invoice history is malformed.")
    # Prefix membership is deliberately finite. Native owner closure supplies
    # actual referenced-plan identity, visibility and immutable history checks.
    for key, prefix in (("active_plan_id", r"(?:FX1|CR3|CRF3|CR3R|CRF3R)"),
                        ("active_revaluation_plan_id", r"FX1")):
        item = result[key]
        if item is not None and (type(item) is not str or re.fullmatch(prefix + r"-[0-9a-f]{32}", item) is None):
            raise PlatformError("Original monetary invoice plan identity is malformed.")
    money = {key: natural_minor_text(result[key]) for key in BALANCE_MINOR_FIELDS}
    if type(total_minor) is not int or type(allocated_minor) is not int or not 0 <= allocated_minor <= MAX_MINOR:
        raise PlatformError("Actual AR monetary authority is malformed.")
    credited = money["transaction_credited_minor"]
    entitlement = max(allocated_minor + credited - total_minor, 0)
    if (money["transaction_original_gross_minor"] <= 0 or money["functional_original_gross_minor"] <= 0
            or money["transaction_original_gross_minor"] != total_minor
            or money["transaction_collected_minor"] != allocated_minor
            or allocated_minor > total_minor
            or not 0 <= credited <= total_minor
            or money["transaction_outstanding_minor"] != max(total_minor - allocated_minor - credited, 0)
            or money["transaction_refund_entitlement_minor"] != entitlement
            or money["transaction_refund_due_minor"] != entitlement - money["transaction_refunded_minor"]
            or money["functional_refund_due_minor"] != money["functional_refund_entitlement_minor"] - money["functional_refund_released_minor"]
            or money["functional_refund_entitlement_minor"] > money["functional_original_gross_minor"]
            or (entitlement == 0 and money["functional_refund_entitlement_minor"] != 0)
            or (money["transaction_refunded_minor"] == 0 and money["functional_refund_released_minor"] != 0)
            or (money["transaction_outstanding_minor"] == 0 and money["functional_outstanding_minor"] != 0)
            or (money["transaction_refund_due_minor"] == 0 and money["functional_refund_due_minor"] != 0)):
        raise PlatformError("Original monetary invoice balance disagrees with actual AR authority or carrying conservation.")
    return result
