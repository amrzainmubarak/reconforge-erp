from __future__ import annotations

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


def test_cancelled_po_linked_to_movement_detected(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    result = _run(sample_datasets, config)
    assert "PO-9006" in set(result.cancelled_po_linked_to_movement["po_number"])


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
