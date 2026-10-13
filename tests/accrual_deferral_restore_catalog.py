"""Finite PostgreSQL dump/reparse equivalence for six existing CHECKs.

PostgreSQL flattens nested conjunctions when pg_dump's CHECK text is parsed
again. Only the exact original and restored definitions observed here are
equivalent; all other definitions, including every AD1 definition, stay exact.
"""

from typing import Any

_REASON = "CHECK ((((length(reason) >= 1) AND (length(reason) <= 500)) AND (reason = btrim(reason)) AND (reason !~ '[[:cntrl:]]'::text)))"
_RESTORED_REASON = "CHECK (((length(reason) >= 1) AND (length(reason) <= 500) AND (reason = btrim(reason)) AND (reason !~ '[[:cntrl:]]'::text)))"
LEGACY_CHECK_REPARSE = {
    ("commercial_collection_cancellations", "commercial_collection_cancellations_reason_check"): (
        "CHECK ((((length(reason) >= 1) AND (length(reason) <= 500)) AND (btrim(reason) <> ''::text)))",
        "CHECK (((length(reason) >= 1) AND (length(reason) <= 500) AND (btrim(reason) <> ''::text)))"),
    ("inventory_receipt_plans", "inventory_receipt_plans_reason_check"): (_REASON, _RESTORED_REASON),
    ("inventory_receipt_reviews", "inventory_receipt_reviews_reason_check"): (_REASON, _RESTORED_REASON),
    ("inventory_receipt_links", "inventory_receipt_links_reason_check"): (_REASON, _RESTORED_REASON),
    ("supplier_return_plans", "supplier_return_plans_number_check"): (
        "CHECK ((((length(number) >= 5) AND (length(number) <= 64)) AND (\"left\"(number, 4) = 'SR1-'::text)))",
        "CHECK (((length(number) >= 5) AND (length(number) <= 64) AND (\"left\"(number, 4) = 'SR1-'::text)))"),
    ("procurement_partial_order_lines", "procurement_partial_order_lines_check1"): (
        "CHECK ((((total_minor >= 1) AND (total_minor <= '9000000000000000000'::bigint)) AND ((quantity * (unit_price_minor)::numeric) = (total_minor)::numeric)))",
        "CHECK (((total_minor >= 1) AND (total_minor <= '9000000000000000000'::bigint) AND ((quantity * (unit_price_minor)::numeric) = (total_minor)::numeric)))"),
}


def retained_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    constraints = []
    for table, name, definition in catalog["constraints"]:
        forms = LEGACY_CHECK_REPARSE.get((table, name))
        constraints.append((table, name, forms[1] if forms and definition == forms[0] else definition))
    return {**catalog, "constraints": constraints}
