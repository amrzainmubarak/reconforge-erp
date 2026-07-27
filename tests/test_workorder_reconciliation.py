from __future__ import annotations

import pandas as pd

from reconforge.config import ReconForgeConfig
from reconforge.reconciliation.workorders import reconcile_workorders
from reconforge.schemas import DatasetName


def _run(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig):
    return reconcile_workorders(
        sample_datasets[DatasetName.STOCK_MOVES],
        sample_datasets[DatasetName.WORK_ORDERS],
        sample_datasets[DatasetName.PURCHASE_ORDERS],
        sample_datasets[DatasetName.OLD_PARTS_RETURNS],
        sample_datasets[DatasetName.INVOICES],
        config,
    )


def test_parts_issued_without_work_order_detected(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    result = _run(sample_datasets, config)
    assert "STK-ISS-1008" in set(result.parts_issued_without_work_order["source_document"])


def test_direct_purchase_fitting_risk_detected(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    result = _run(sample_datasets, config)
    assert "PO-9004" in set(result.direct_purchase_fitting_risk["po_number"])


def test_old_part_return_missing_detected(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    result = _run(sample_datasets, config)
    assert "WO-1007" in set(result.old_part_return_missing["work_order"])


def test_work_order_cost_without_invoice_detected(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    result = _run(sample_datasets, config)
    assert "WO-1006" in set(result.work_orders_with_cost_but_no_invoice["work_order"])


def test_work_order_cost_without_invoice_includes_invalid_actual_cost() -> None:
    stock_moves = pd.DataFrame(
        columns=[
            "movement_type",
            "work_order",
            "source_document",
            "date",
            "total_cost",
            "quantity",
            "product_code",
            "category",
            "warehouse",
        ],
    )
    work_orders = pd.DataFrame(
        [
            {"work_order": "WO-INVALID", "status": "open", "closed_date": "2026-01-01", "actual_cost": "not-a-number"},
            {"work_order": "WO-ZERO", "status": "open", "closed_date": "2026-01-01", "actual_cost": "0.00"},
        ],
    )
    purchase_orders = pd.DataFrame(columns=["po_number", "linked_work_order", "product_code", "status"])
    old_parts_returns = pd.DataFrame(columns=["work_order", "product_code", "returned_quantity"])
    invoices = pd.DataFrame(columns=["work_order", "status", "invoice_amount"])
    result = reconcile_workorders(
        stock_moves=stock_moves,
        work_orders=work_orders,
        purchase_orders=purchase_orders,
        old_parts_returns=old_parts_returns,
        invoices=invoices,
        config=ReconForgeConfig(
            movement_type_mapping={"issue": [], "receipt": [], "direct_fit": [], "return": []},
            required_old_part_categories=[],
        ),
    )
    assert "WO-INVALID" in set(result.work_orders_with_cost_but_no_invoice["work_order"])
    assert "WO-ZERO" not in set(result.work_orders_with_cost_but_no_invoice["work_order"])
    row = result.work_orders_with_cost_but_no_invoice[
        result.work_orders_with_cost_but_no_invoice["work_order"].astype(str).eq("WO-INVALID")
    ].iloc[0]
    assert row["amount_parse_status"] == "missing_or_invalid"


def test_cancelled_po_linked_to_movement_detected(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    result = _run(sample_datasets, config)
    assert "PO-9006" in set(result.cancelled_po_linked_to_movement["po_number"])


def test_over_precise_jpy_work_order_cost_is_flagged_as_invalid() -> None:
    stock_moves = pd.DataFrame(columns=["movement_type", "work_order", "source_document", "date", "total_cost", "quantity", "product_code", "category", "warehouse"])
    work_orders = pd.DataFrame(
        [{"work_order": "WO-JPY", "status": "open", "closed_date": "2026-01-01", "actual_cost": "100.75", "currency": "JPY"}],
    )
    purchase_orders = pd.DataFrame(columns=["po_number", "linked_work_order", "product_code", "status"])
    old_parts_returns = pd.DataFrame(columns=["work_order", "product_code", "returned_quantity"])
    invoices = pd.DataFrame(columns=["work_order", "status", "invoice_amount"])

    result = reconcile_workorders(
        stock_moves=stock_moves,
        work_orders=work_orders,
        purchase_orders=purchase_orders,
        old_parts_returns=old_parts_returns,
        invoices=invoices,
        config=ReconForgeConfig(
            movement_type_mapping={"issue": [], "receipt": [], "direct_fit": [], "return": []},
            required_old_part_categories=[],
        ),
    )

    row = result.work_orders_with_cost_but_no_invoice[
        result.work_orders_with_cost_but_no_invoice["work_order"].astype(str).eq("WO-JPY")
    ].iloc[0]
    assert row["amount_parse_status"] == "missing_or_invalid"


def test_workorder_summary_has_all_control_categories(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    result = _run(sample_datasets, config)
    expected = {
        "parts_issued_without_work_order",
        "closed_work_orders_with_pending_stock",
        "work_orders_with_cost_but_no_invoice",
        "direct_purchase_fitting_risk",
        "old_part_return_missing",
        "cancelled_po_linked_to_movement",
    }
    assert expected == set(result.summary["metric"])


def test_reconcile_workorders_returns_empty_exceptions_without_crash() -> None:
    stock_moves = pd.DataFrame(
        columns=[
            "movement_type",
            "work_order",
            "source_document",
            "date",
                "total_cost",
                "quantity",
                "product_code",
                "category",
                "warehouse",
            ],
        )
    work_orders = pd.DataFrame(columns=["work_order", "status", "closed_date", "actual_cost"])
    purchase_orders = pd.DataFrame(columns=["po_number", "linked_work_order", "product_code", "status"])
    old_parts_returns = pd.DataFrame(columns=["work_order", "product_code", "returned_quantity"])
    invoices = pd.DataFrame(columns=["work_order", "status", "invoice_amount"])

    result = reconcile_workorders(
        stock_moves=stock_moves,
        work_orders=work_orders,
        purchase_orders=purchase_orders,
        old_parts_returns=old_parts_returns,
        invoices=invoices,
        config=ReconForgeConfig(
            movement_type_mapping={"issue": [], "receipt": [], "direct_fit": [], "return": []},
            required_old_part_categories=[],
        ),
    )

    assert result.all_exceptions.empty
    assert {"exception_type", "risk_score", "risk_level"} <= set(result.all_exceptions.columns)
