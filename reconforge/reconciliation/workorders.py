"""Workshop and work-order control reconciliation."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from reconforge.config import ReconForgeConfig
from reconforge.reconciliation.risk import assess_risk


@dataclass(frozen=True)
class WorkorderReconciliationResult:
    """Output frames from work-order reconciliation."""

    parts_issued_without_work_order: pd.DataFrame
    closed_work_orders_with_pending_stock: pd.DataFrame
    work_orders_with_cost_but_no_invoice: pd.DataFrame
    direct_purchase_fitting_risk: pd.DataFrame
    old_part_return_missing: pd.DataFrame
    cancelled_po_linked_to_movement: pd.DataFrame
    all_exceptions: pd.DataFrame
    summary: pd.DataFrame


def _clean_status(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    return "" if text in {"nan", "nat", "none"} else text


def _movement_types(config: ReconForgeConfig, group: str) -> set[str]:
    return {value.upper() for value in config.movement_type_mapping.get(group, [])}


def _add_risk(frame: pd.DataFrame, exception_type: str, config: ReconForgeConfig, amount_column: str | None = None) -> pd.DataFrame:
    enriched = frame.copy()
    scores: list[int] = []
    levels: list[str] = []
    for _, row in enriched.iterrows():
        amount = float(row.get(amount_column, 0.0) or 0.0) if amount_column else 0.0
        assessment = assess_risk(exception_type, config, amount=amount)
        scores.append(assessment.score)
        levels.append(assessment.level)
    enriched["exception_type"] = exception_type
    enriched["risk_score"] = scores
    enriched["risk_level"] = levels
    return enriched


def _valid_work_orders(work_orders: pd.DataFrame) -> set[str]:
    return set(work_orders["work_order"].astype(str).str.strip())


def find_parts_issued_without_work_order(stock_moves: pd.DataFrame, work_orders: pd.DataFrame, config: ReconForgeConfig) -> pd.DataFrame:
    """Find stock issues that do not reference a valid work order."""

    issue_types = _movement_types(config, "issue") | _movement_types(config, "direct_fit")
    valid = _valid_work_orders(work_orders)
    stock = stock_moves.copy()
    movement_mask = stock["movement_type"].astype(str).str.upper().isin(issue_types)
    invalid_wo = ~stock["work_order"].astype(str).str.strip().isin(valid)
    return stock[movement_mask & invalid_wo].copy()


def find_closed_work_orders_with_pending_stock(stock_moves: pd.DataFrame, work_orders: pd.DataFrame, config: ReconForgeConfig) -> pd.DataFrame:
    """Find stock issues posted after work-order closure."""

    issue_types = _movement_types(config, "issue") | _movement_types(config, "direct_fit")
    closed = work_orders[work_orders["status"].map(_clean_status).eq("closed")].copy()
    stock = stock_moves[stock_moves["movement_type"].astype(str).str.upper().isin(issue_types)].copy()
    merged = stock.merge(closed[["work_order", "closed_date", "status"]], on="work_order", how="inner", suffixes=("", "_wo"))
    late = merged[(merged["closed_date"].notna()) & (merged["date"] > merged["closed_date"])].copy()
    return late


def find_work_orders_with_cost_but_no_invoice(work_orders: pd.DataFrame, invoices: pd.DataFrame) -> pd.DataFrame:
    """Find work orders that carry cost but do not have a posted/paid invoice."""

    posted_status = {"posted", "paid", "open"}
    invoice_status = invoices[["work_order", "status", "invoice_amount"]].copy()
    invoice_status["is_valid_invoice"] = invoice_status["status"].map(_clean_status).isin(posted_status)
    valid_invoiced = set(invoice_status[invoice_status["is_valid_invoice"]]["work_order"].astype(str))
    candidates = work_orders[work_orders["actual_cost"].fillna(0).gt(0)].copy()
    return candidates[~candidates["work_order"].astype(str).isin(valid_invoiced)].copy()


def find_direct_purchase_fitting_risk(stock_moves: pd.DataFrame, purchase_orders: pd.DataFrame, config: ReconForgeConfig) -> pd.DataFrame:
    """Find direct purchase-and-fit cases without a normal stores process."""

    direct_types = _movement_types(config, "direct_fit")
    direct_stock = stock_moves[stock_moves["movement_type"].astype(str).str.upper().isin(direct_types)].copy()
    linked_pos = purchase_orders[purchase_orders["linked_work_order"].astype(str).str.strip().ne("")].copy()
    po_risk = linked_pos.merge(
        direct_stock[["source_document", "work_order", "product_code", "total_cost", "warehouse", "movement_type"]],
        left_on=["po_number", "linked_work_order", "product_code"],
        right_on=["source_document", "work_order", "product_code"],
        how="inner",
        suffixes=("_po", "_stock"),
    )
    if po_risk.empty:
        return po_risk
    po_risk["control_gap"] = "Direct purchase fitted to work order without normal stock receipt and issue trail"
    return po_risk


def find_old_part_return_missing(stock_moves: pd.DataFrame, old_parts_returns: pd.DataFrame, config: ReconForgeConfig) -> pd.DataFrame:
    """Find issues where an old-part return is required but missing."""

    required_categories = {category.lower() for category in config.required_old_part_categories}
    stock = stock_moves[stock_moves["category"].astype(str).str.lower().isin(required_categories)].copy()
    if stock.empty:
        return stock

    returns = old_parts_returns.groupby(["work_order", "product_code"], as_index=False)["returned_quantity"].sum()
    merged = stock.merge(returns, on=["work_order", "product_code"], how="left")
    merged["returned_quantity"] = merged["returned_quantity"].fillna(0)
    missing = merged[merged["returned_quantity"].lt(merged["quantity"].fillna(0))].copy()
    missing["missing_return_quantity"] = missing["quantity"].fillna(0) - missing["returned_quantity"]
    return missing


def find_cancelled_po_linked_to_movement(stock_moves: pd.DataFrame, purchase_orders: pd.DataFrame) -> pd.DataFrame:
    """Find movements linked to cancelled purchase orders."""

    cancelled = purchase_orders[purchase_orders["status"].map(_clean_status).eq("cancelled")].copy()
    if cancelled.empty:
        return cancelled
    linked = stock_moves.merge(cancelled, left_on="source_document", right_on="po_number", how="inner", suffixes=("_stock", "_po"))
    return linked


def _summary(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame([{"metric": name, "count": len(frame)} for name, frame in frames.items()])


def _concat_exceptions(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Concatenate exception frames while returning a typed empty frame safely."""

    non_empty = [frame for frame in frames.values() if not frame.empty]
    if not non_empty:
        return pd.DataFrame(columns=["exception_type", "risk_score", "risk_level"])
    return pd.concat(non_empty, ignore_index=True, sort=False)


def reconcile_workorders(
    stock_moves: pd.DataFrame,
    work_orders: pd.DataFrame,
    purchase_orders: pd.DataFrame,
    old_parts_returns: pd.DataFrame,
    invoices: pd.DataFrame,
    config: ReconForgeConfig,
) -> WorkorderReconciliationResult:
    """Run workshop and work-order control checks."""

    missing_wo = _add_risk(
        find_parts_issued_without_work_order(stock_moves, work_orders, config),
        "parts_issued_without_work_order",
        config,
        "total_cost",
    )
    pending_stock = _add_risk(
        find_closed_work_orders_with_pending_stock(stock_moves, work_orders, config),
        "closed_work_order_with_pending_stock",
        config,
        "total_cost",
    )
    cost_no_invoice = _add_risk(
        find_work_orders_with_cost_but_no_invoice(work_orders, invoices),
        "work_order_cost_without_invoice",
        config,
        "actual_cost",
    )
    direct_fit = _add_risk(
        find_direct_purchase_fitting_risk(stock_moves, purchase_orders, config),
        "direct_purchase_fit",
        config,
        "total_cost",
    )
    old_part_missing = _add_risk(
        find_old_part_return_missing(stock_moves, old_parts_returns, config),
        "missing_old_part_return",
        config,
        "total_cost",
    )
    cancelled_po = _add_risk(
        find_cancelled_po_linked_to_movement(stock_moves, purchase_orders),
        "cancelled_po_linked_to_movement",
        config,
        "total_cost",
    )

    frames = {
        "parts_issued_without_work_order": missing_wo,
        "closed_work_orders_with_pending_stock": pending_stock,
        "work_orders_with_cost_but_no_invoice": cost_no_invoice,
        "direct_purchase_fitting_risk": direct_fit,
        "old_part_return_missing": old_part_missing,
        "cancelled_po_linked_to_movement": cancelled_po,
    }
    all_exceptions = _concat_exceptions(frames)
    return WorkorderReconciliationResult(
        parts_issued_without_work_order=missing_wo,
        closed_work_orders_with_pending_stock=pending_stock,
        work_orders_with_cost_but_no_invoice=cost_no_invoice,
        direct_purchase_fitting_risk=direct_fit,
        old_part_return_missing=old_part_missing,
        cancelled_po_linked_to_movement=cancelled_po,
        all_exceptions=all_exceptions,
        summary=_summary(frames),
    )


def result_frames(result: WorkorderReconciliationResult) -> dict[str, pd.DataFrame]:
    """Return work-order result frames for writing."""

    return {
        "summary": result.summary,
        "parts_issued_without_work_order": result.parts_issued_without_work_order,
        "closed_work_orders_with_pending_stock": result.closed_work_orders_with_pending_stock,
        "work_orders_with_cost_but_no_invoice": result.work_orders_with_cost_but_no_invoice,
        "direct_purchase_fitting_risk": result.direct_purchase_fitting_risk,
        "old_part_return_missing": result.old_part_return_missing,
        "cancelled_po_linked_to_movement": result.cancelled_po_linked_to_movement,
        "all_exceptions": result.all_exceptions,
    }
