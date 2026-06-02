from __future__ import annotations

from datetime import date
from pathlib import Path

from reconforge.config import ReconForgeConfig
from reconforge.io.writers import frame_to_records
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.reconciliation.workorders import reconcile_workorders
from reconforge.reports.html import write_html_dashboard
from reconforge.reports.management_pack import generate_management_pack
from reconforge.reports.markdown import write_markdown_summary
from reconforge.reports.wip_aging import generate_wip_aging
from reconforge.schemas import DatasetName


def test_wip_aging_generates_90_plus_bucket(sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    wip = generate_wip_aging(sample_datasets[DatasetName.WORK_ORDERS], config, as_of=date(2026, 6, 2))
    assert "90+" in set(wip["aging_bucket"])
    assert "WO-1005" in set(wip["work_order"])


def test_frame_to_records_serializes_dates(sample_datasets: dict[DatasetName, object]) -> None:
    records = frame_to_records(sample_datasets[DatasetName.WORK_ORDERS].head(1))
    assert isinstance(records[0]["opened_date"], str)


def test_markdown_summary_written(tmp_path: Path, sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    stock_result = reconcile_stock_gl(sample_datasets[DatasetName.STOCK_MOVES], sample_datasets[DatasetName.GL_ENTRIES], config)
    wip = generate_wip_aging(sample_datasets[DatasetName.WORK_ORDERS], config, as_of=date(2026, 6, 2))
    path = write_markdown_summary(tmp_path / "summary.md", config, stock_result.summary, stock_result.summary, wip, 1)
    assert path.exists()
    assert "Executive Summary" in path.read_text(encoding="utf-8")


def test_html_dashboard_written(tmp_path: Path, sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    stock_result = reconcile_stock_gl(sample_datasets[DatasetName.STOCK_MOVES], sample_datasets[DatasetName.GL_ENTRIES], config)
    wip = generate_wip_aging(sample_datasets[DatasetName.WORK_ORDERS], config, as_of=date(2026, 6, 2))
    path = write_html_dashboard(tmp_path / "dashboard.html", config, {"exception_count": 3}, stock_result.all_exceptions, wip)
    assert path.exists()
    assert "Top Exceptions" in path.read_text(encoding="utf-8")


def test_management_pack_smoke(tmp_path: Path, sample_datasets: dict[DatasetName, object], config: ReconForgeConfig) -> None:
    stock_result = reconcile_stock_gl(sample_datasets[DatasetName.STOCK_MOVES], sample_datasets[DatasetName.GL_ENTRIES], config)
    workorder_result = reconcile_workorders(
        sample_datasets[DatasetName.STOCK_MOVES],
        sample_datasets[DatasetName.WORK_ORDERS],
        sample_datasets[DatasetName.PURCHASE_ORDERS],
        sample_datasets[DatasetName.OLD_PARTS_RETURNS],
        sample_datasets[DatasetName.INVOICES],
        config,
    )
    wip = generate_wip_aging(sample_datasets[DatasetName.WORK_ORDERS], config, as_of=date(2026, 6, 2))
    artifacts = generate_management_pack(Path("examples/sample_data"), tmp_path, config, stock_result, workorder_result, wip)
    assert artifacts.excel_path.exists()
    assert artifacts.json_path.exists()
    assert artifacts.markdown_path.exists()
    assert artifacts.html_path.exists()
