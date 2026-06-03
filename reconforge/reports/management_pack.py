"""Management pack generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from reconforge.config import ReconForgeConfig
from reconforge.io.excel import add_summary_chart, audit_metadata, write_excel_workbook
from reconforge.io.writers import frame_to_records, write_json, write_report_frames
from reconforge.reconciliation.stock_gl import StockGLReconciliationResult
from reconforge.reconciliation.stock_gl import result_frames as stock_gl_frames
from reconforge.reconciliation.workorders import WorkorderReconciliationResult
from reconforge.reconciliation.workorders import result_frames as workorder_frames
from reconforge.reports.html import write_html_dashboard
from reconforge.reports.markdown import write_markdown_summary
from reconforge.reports.wip_aging import aging_summary
from reconforge.review.state import load_review_state, merge_review_state_with_exceptions
from reconforge.validators import issues_to_frame, validate_input_directory


@dataclass(frozen=True)
class ManagementPackArtifacts:
    """Generated management pack artifact paths."""

    excel_path: Path
    json_path: Path
    markdown_path: Path
    html_path: Path
    csv_json_paths: list[Path]


def _executive_summary(
    stock_result: StockGLReconciliationResult,
    workorder_result: WorkorderReconciliationResult,
    wip_aging: pd.DataFrame,
) -> pd.DataFrame:
    matched_amount = float(stock_result.matched_transactions.get("stock_amount", pd.Series(dtype=float)).sum())
    unmatched_stock_amount = float(stock_result.stock_without_gl.get("total_cost", pd.Series(dtype=float)).sum())
    unmatched_gl_amount = float(stock_result.gl_without_stock.get("amount", pd.Series(dtype=float)).sum())
    exception_count = len(stock_result.all_exceptions) + len(workorder_result.all_exceptions)
    critical_count = int(
        pd.concat([stock_result.all_exceptions, workorder_result.all_exceptions], ignore_index=True, sort=False)
        .get("risk_level", pd.Series(dtype=str))
        .astype(str)
        .eq("Critical")
        .sum(),
    )
    return pd.DataFrame(
        [
            {"metric": "matched_amount", "value": round(matched_amount, 2)},
            {"metric": "unmatched_stock_amount", "value": round(unmatched_stock_amount, 2)},
            {"metric": "unmatched_gl_amount", "value": round(unmatched_gl_amount, 2)},
            {"metric": "exception_count", "value": exception_count},
            {"metric": "critical_risk_count", "value": critical_count},
            {"metric": "open_wip_orders", "value": len(wip_aging)},
        ],
    )


def _risk_scoring(stock_result: StockGLReconciliationResult, workorder_result: WorkorderReconciliationResult) -> pd.DataFrame:
    combined = pd.concat([stock_result.all_exceptions, workorder_result.all_exceptions], ignore_index=True, sort=False)
    if combined.empty or "risk_level" not in combined.columns:
        return pd.DataFrame(columns=["risk_level", "exception_count"])
    return combined.groupby("risk_level", as_index=False).agg(exception_count=("risk_level", "count"))


def _amount_impact_series(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    amount = pd.Series([0.0] * len(frame), index=frame.index)
    for field in ("amount_impact", "total_cost", "amount", "total_price", "actual_cost", "estimated_cost", "invoice_amount"):
        if field not in frame.columns:
            continue
        values = pd.to_numeric(frame[field], errors="coerce").fillna(0).abs()
        amount = amount.mask(amount.eq(0), values)
    return amount


def _severity_series(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=str)
    severity = pd.Series([""] * len(frame), index=frame.index)
    for field in ("risk_level", "severity"):
        if field in frame.columns:
            severity = severity.mask(severity.str.strip().eq(""), frame[field].astype(str))
    return severity.str.lower()


def _top_control_themes(combined: pd.DataFrame) -> pd.DataFrame:
    if combined.empty:
        return pd.DataFrame(columns=["control_theme", "exception_count", "amount_impact"])
    theme_column = "exception_type" if "exception_type" in combined.columns else "rule_name" if "rule_name" in combined.columns else ""
    if not theme_column:
        return pd.DataFrame(columns=["control_theme", "exception_count", "amount_impact"])
    themed = combined.assign(
        control_theme=combined[theme_column].astype(str),
        amount_impact=_amount_impact_series(combined),
    )
    return (
        themed.groupby("control_theme", as_index=False)
        .agg(exception_count=("control_theme", "count"), amount_impact=("amount_impact", "sum"))
        .sort_values(["exception_count", "amount_impact"], ascending=False)
        .head(5)
    )


def _control_value_summary(combined: pd.DataFrame, wip_aging: pd.DataFrame, output_dir: Path) -> pd.DataFrame:
    total_exceptions = len(combined)
    merged = merge_review_state_with_exceptions(combined, load_review_state(output_dir / "review_state.json"))
    status = merged.get("status", pd.Series(["New"] * len(merged))).astype(str)
    high_critical = int(_severity_series(combined).isin({"high", "critical"}).sum())
    unresolved = int((~status.isin({"Resolved", "Accepted Risk"})).sum()) if total_exceptions else 0
    accepted_risk = int(status.eq("Accepted Risk").sum())
    escalated = int(status.eq("Escalated").sum())
    reviewed = int(status.ne("New").sum())
    review_completion_rate = round((reviewed / total_exceptions) * 100, 2) if total_exceptions else 0.0
    estimated_value_impact = round(float(_amount_impact_series(combined).sum()), 2) if total_exceptions else 0.0
    wip_source = wip_aging.get("actual_cost", wip_aging.get("estimated_cost", pd.Series([0] * len(wip_aging))))
    wip_exposure = round(float(pd.to_numeric(wip_source, errors="coerce").fillna(0).sum()), 2) if not wip_aging.empty else 0.0
    return pd.DataFrame(
        [
            {"metric": "total_exceptions", "value": total_exceptions, "meaning": "All detected reconciliation and operational exceptions."},
            {"metric": "high_or_critical_exceptions", "value": high_critical, "meaning": "Exceptions requiring priority finance, audit, or operations review."},
            {"metric": "unresolved_exceptions", "value": unresolved, "meaning": "Exceptions not yet resolved or formally accepted as risk."},
            {"metric": "accepted_risk_count", "value": accepted_risk, "meaning": "Exceptions explicitly accepted with documented rationale."},
            {"metric": "escalated_count", "value": escalated, "meaning": "Exceptions assigned for escalation."},
            {"metric": "estimated_value_impact", "value": estimated_value_impact, "meaning": "Simple sum of available exception amount fields; not a savings claim."},
            {"metric": "wip_exposure", "value": wip_exposure, "meaning": "Available WIP cost exposure from open work-order aging data."},
            {"metric": "review_completion_rate_pct", "value": review_completion_rate, "meaning": "Percent of exceptions with a status other than New."},
        ],
    )


def _risk_matrix(combined: pd.DataFrame) -> pd.DataFrame:
    if combined.empty:
        return pd.DataFrame(columns=["risk_level", "exception_type", "exception_count", "amount_impact"])
    amount = combined.get("total_cost", combined.get("amount", pd.Series([0] * len(combined))))
    matrix = combined.assign(amount_impact=pd.to_numeric(amount, errors="coerce").fillna(0))
    group_cols = [column for column in ["risk_level", "exception_type"] if column in matrix.columns]
    if not group_cols:
        return pd.DataFrame(columns=["risk_level", "exception_type", "exception_count", "amount_impact"])
    return matrix.groupby(group_cols, as_index=False).agg(exception_count=("exception_type", "count"), amount_impact=("amount_impact", "sum"))


def _control_effectiveness(stock_result: StockGLReconciliationResult, workorder_result: WorkorderReconciliationResult) -> pd.DataFrame:
    total_stock = len(stock_result.matched_transactions) + len(stock_result.stock_without_gl)
    match_rate = len(stock_result.matched_transactions) / total_stock if total_stock else 0.0
    return pd.DataFrame(
        [
            {"control": "Stock to GL matching", "metric": "match_rate", "value": round(match_rate, 4)},
            {"control": "Stock to GL matching", "metric": "unmatched_stock_count", "value": len(stock_result.stock_without_gl)},
            {"control": "Stock to GL matching", "metric": "unmatched_gl_count", "value": len(stock_result.gl_without_stock)},
            {"control": "Work order governance", "metric": "exception_count", "value": len(workorder_result.all_exceptions)},
        ],
    )


def _configuration_used(config: ReconForgeConfig) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"parameter": "amount_tolerance", "value": config.amount_tolerance},
            {"parameter": "date_tolerance_days", "value": config.date_tolerance_days},
            {"parameter": "output_currency", "value": config.output_currency},
            {"parameter": "company_name", "value": config.company_name},
            {"parameter": "report_title", "value": config.report_title},
        ],
    )


def _recommended_actions(stock_result: StockGLReconciliationResult, workorder_result: WorkorderReconciliationResult, wip_aging: pd.DataFrame) -> pd.DataFrame:
    actions = [
        {"priority": "High", "owner": "Finance", "action": "Clear stock movements without GL postings before period close.", "trigger_count": len(stock_result.stock_without_gl)},
        {"priority": "High", "owner": "Stores", "action": "Investigate GL expenses without matching stock movement evidence.", "trigger_count": len(stock_result.gl_without_stock)},
        {"priority": "High", "owner": "Workshop", "action": "Resolve direct purchase-and-fit cases with receipt, issue, and approval evidence.", "trigger_count": len(workorder_result.direct_purchase_fitting_risk)},
        {"priority": "Medium", "owner": "Workshop", "action": "Collect or document old-part returns for controlled categories.", "trigger_count": len(workorder_result.old_part_return_missing)},
        {"priority": "Medium", "owner": "Finance Controller", "action": "Review WIP older than 90 days and agree closure or provisioning actions.", "trigger_count": int(wip_aging["aging_days"].gt(90).sum()) if not wip_aging.empty else 0},
    ]
    return pd.DataFrame(actions)


def _audit_log(config: ReconForgeConfig, input_path: Path) -> pd.DataFrame:
    metadata = audit_metadata(config.company_name, config.report_title, config.output_currency)
    metadata["input_path"] = str(input_path)
    metadata["amount_tolerance"] = str(config.amount_tolerance)
    metadata["date_tolerance_days"] = str(config.date_tolerance_days)
    return pd.DataFrame([metadata])


def management_summary_dict(executive_summary: pd.DataFrame) -> dict[str, float | int | str]:
    """Convert executive summary frame to a dictionary."""

    summary: dict[str, float | int | str] = {}
    for _, row in executive_summary.iterrows():
        summary[str(row["metric"])] = row["value"]
    return summary


def generate_management_pack(
    input_path: Path,
    output_dir: Path,
    config: ReconForgeConfig,
    stock_result: StockGLReconciliationResult,
    workorder_result: WorkorderReconciliationResult,
    wip_aging: pd.DataFrame,
) -> ManagementPackArtifacts:
    """Generate the full Excel, JSON, CSV, Markdown, and HTML management pack."""

    output_dir.mkdir(parents=True, exist_ok=True)
    executive_summary = _executive_summary(stock_result, workorder_result, wip_aging)
    risk_scoring = _risk_scoring(stock_result, workorder_result)
    recommended_actions = _recommended_actions(stock_result, workorder_result, wip_aging)
    wip_summary = aging_summary(wip_aging)
    audit_log = _audit_log(config, input_path)
    combined_exceptions = pd.concat([stock_result.all_exceptions, workorder_result.all_exceptions], ignore_index=True, sort=False)
    control_value_summary = _control_value_summary(combined_exceptions, wip_aging, output_dir)
    top_control_themes = _top_control_themes(combined_exceptions)
    high_risk = (
        combined_exceptions[
            pd.to_numeric(combined_exceptions.get("risk_score", pd.Series([0] * len(combined_exceptions))), errors="coerce").fillna(0).ge(61)
        ].copy()
        if not combined_exceptions.empty
        else pd.DataFrame()
    )
    data_quality_warnings = issues_to_frame(validate_input_directory(input_path))

    sheets = {
        "Executive Summary": executive_summary,
        "Control Value Summary": control_value_summary,
        "KPI Dashboard": executive_summary,
        "Reconciliation Summary": stock_result.summary,
        "Stock vs GL Mismatch": stock_result.all_exceptions,
        "Stock Without GL": stock_result.stock_without_gl,
        "GL Without Stock": stock_result.gl_without_stock,
        "Amount Variances": stock_result.value_differences,
        "Work Order Exceptions": workorder_result.all_exceptions,
        "WIP Aging": wip_aging,
        "Control Pack Results": pd.DataFrame(),
        "High Risk Exceptions": high_risk,
        "Evidence Register": pd.DataFrame(),
        "WIP Aging Summary": wip_summary,
        "Risk Scoring": risk_scoring,
        "Risk Matrix": _risk_matrix(combined_exceptions),
        "Top Control Themes": top_control_themes,
        "Control Effectiveness": _control_effectiveness(stock_result, workorder_result),
        "Recommended Actions": recommended_actions,
        "Audit Log": audit_log,
        "Data Quality Warnings": data_quality_warnings,
        "Configuration Used": _configuration_used(config),
    }
    excel_path = write_excel_workbook(
        sheets,
        output_dir / "management_pack.xlsx",
        metadata=audit_metadata(config.company_name, config.report_title, config.output_currency),
    )
    add_summary_chart(excel_path, "Risk Scoring", "Exceptions by Risk Level")
    add_summary_chart(excel_path, "WIP Aging Summary", "WIP Aging Buckets")

    all_frames = {
        **{f"stock_gl_{name}": frame for name, frame in stock_gl_frames(stock_result).items()},
        **{f"workorders_{name}": frame for name, frame in workorder_frames(workorder_result).items()},
        "wip_aging": wip_aging,
        "wip_aging_summary": wip_summary,
    }
    csv_json_paths = write_report_frames(all_frames, output_dir, "management_pack")

    payload: dict[str, Any] = {
        "executive_summary": frame_to_records(executive_summary),
        "control_value_summary": frame_to_records(control_value_summary),
        "top_control_themes": frame_to_records(top_control_themes),
        "risk_scoring": frame_to_records(risk_scoring),
        "stock_gl_summary": frame_to_records(stock_result.summary),
        "workorder_summary": frame_to_records(workorder_result.summary),
        "wip_aging": frame_to_records(wip_aging),
        "top_exceptions": frame_to_records(combined_exceptions.sort_values("risk_score", ascending=False).head(25)) if not combined_exceptions.empty and "risk_score" in combined_exceptions.columns else [],
    }
    json_path = write_json(payload, output_dir, "management_pack")
    critical_count = int(combined_exceptions.get("risk_level", pd.Series(dtype=str)).astype(str).eq("Critical").sum()) if not combined_exceptions.empty else 0
    markdown_path = write_markdown_summary(
        output_dir / "summary.md",
        config,
        stock_result.summary,
        workorder_result.summary,
        wip_aging,
        critical_count,
    )
    write_markdown_summary(
        output_dir / "management_summary.md",
        config,
        stock_result.summary,
        workorder_result.summary,
        wip_aging,
        critical_count,
    )
    html_path = write_html_dashboard(
        output_dir / "dashboard.html",
        config,
        management_summary_dict(executive_summary),
        combined_exceptions.sort_values("risk_score", ascending=False) if not combined_exceptions.empty and "risk_score" in combined_exceptions.columns else combined_exceptions,
        wip_aging,
        control_value_summary=control_value_summary,
        top_control_themes=top_control_themes,
        recommended_actions=recommended_actions,
    )
    write_html_dashboard(
        output_dir / "executive_report.html",
        config,
        management_summary_dict(executive_summary),
        combined_exceptions.sort_values("risk_score", ascending=False) if not combined_exceptions.empty and "risk_score" in combined_exceptions.columns else combined_exceptions,
        wip_aging,
        control_value_summary=control_value_summary,
        top_control_themes=top_control_themes,
        recommended_actions=recommended_actions,
    )

    return ManagementPackArtifacts(
        excel_path=excel_path,
        json_path=json_path,
        markdown_path=markdown_path,
        html_path=html_path,
        csv_json_paths=csv_json_paths,
    )
