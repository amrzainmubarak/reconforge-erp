"""Command-line interface for ReconForge ERP."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import pandas as pd
import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from reconforge import __version__
from reconforge.ai.summaries import explain_exception_file
from reconforge.anonymizer.engine import anonymize_directory
from reconforge.benchmark.runner import run_benchmark
from reconforge.config import load_config, write_default_config
from reconforge.dashboard.app import create_app
from reconforge.evidence.binder import generate_evidence_binder
from reconforge.generator.synthetic import generate_synthetic_dataset
from reconforge.io.excel import audit_metadata, write_excel_workbook
from reconforge.io.readers import read_required_datasets
from reconforge.io.writers import ensure_output_dir, frame_to_records, write_json, write_report_frames
from reconforge.mappings.inspector import inspect_mapping_inputs
from reconforge.mappings.validator import validate_mapping_pack
from reconforge.periods import compare_period_outputs
from reconforge.reconciliation.matching import MatchingStrategy
from reconforge.reconciliation.stock_gl import reconcile_stock_gl
from reconforge.reconciliation.stock_gl import result_frames as stock_gl_result_frames
from reconforge.reconciliation.workorders import reconcile_workorders
from reconforge.reconciliation.workorders import result_frames as workorder_result_frames
from reconforge.reports.client_pack import generate_client_pack
from reconforge.reports.management_pack import generate_management_pack
from reconforge.reports.wip_aging import aging_summary, generate_wip_aging
from reconforge.review.state import (
    ALLOWED_STATUSES,
    collect_exception_frame,
    export_review_register,
    load_review_state,
    merge_review_state_with_exceptions,
    save_review_state,
    update_review_status,
)
from reconforge.rules.engine import run_rule_pack, write_rule_results
from reconforge.rules.explain import explain_rule
from reconforge.rules.loader import load_rule_pack
from reconforge.schemas import DatasetName
from reconforge.studio.app import create_studio_app
from reconforge.validators import issues_to_frame, validate_input_directory

console = Console()
app = typer.Typer(help="ReconForge ERP reconciliation intelligence CLI.")
reconcile_app = typer.Typer(help="Run reconciliation controls.")
report_app = typer.Typer(help="Generate audit and management reports.")
rules_app = typer.Typer(help="Validate, list, and run control-pack rules.")
mappings_app = typer.Typer(help="Validate ERP mapping profiles.")
generate_app = typer.Typer(help="Generate synthetic ERP datasets.")
explain_app = typer.Typer(help="Explain exceptions and controls deterministically.")
review_app = typer.Typer(help="Review exceptions with local JSON state.")
demo_app = typer.Typer(help="Run first-time-user demo workflows.")
compare_app = typer.Typer(help="Compare generated exception outputs across periods.")
app.add_typer(reconcile_app, name="reconcile")
app.add_typer(report_app, name="report")
app.add_typer(rules_app, name="rules")
app.add_typer(mappings_app, name="mappings")
app.add_typer(generate_app, name="generate")
app.add_typer(explain_app, name="explain")
app.add_typer(review_app, name="review")
app.add_typer(demo_app, name="demo")
app.add_typer(compare_app, name="compare")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"ReconForge ERP {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[bool, typer.Option("--version", callback=_version_callback, help="Show version and exit.")] = False,
) -> None:
    """ReconForge ERP command group."""


def _print_frame(title: str, frame: pd.DataFrame, max_rows: int = 12) -> None:
    table = Table(title=title, show_lines=False)
    visible = frame.head(max_rows)
    for column in visible.columns:
        table.add_column(str(column))
    for _, row in visible.iterrows():
        table.add_row(*(str(row[column]) for column in visible.columns))
    console.print(table)
    if len(frame) > max_rows:
        console.print(f"[dim]Showing {max_rows} of {len(frame)} rows.[/dim]")


def _config_option(config_path: Path | None) -> Path | None:
    return config_path


def _print_success_paths(paths: list[Path]) -> None:
    for path in paths:
        console.print(f"[green]Written:[/green] {path}")


@app.command("init")
def init_workspace(
    workspace: Annotated[Path, typer.Argument(help="Workspace directory to create.")] = Path("."),
) -> None:
    """Create a ReconForge project workspace."""

    for folder in ("input", "output", "config", "reports", "logs"):
        (workspace / folder).mkdir(parents=True, exist_ok=True)
    config_path = write_default_config(workspace / "config" / "reconforge.yml")
    readme_path = workspace / "README.md"
    if not readme_path.exists():
        readme_path.write_text(
            "# ReconForge Workspace\n\nPlace ERP exports in `input/` and generated reports will be written to `output/` or `reports/`.\n",
            encoding="utf-8",
        )
    console.print(f"[green]Workspace ready:[/green] {workspace}")
    console.print(f"Default config: {config_path}")


@app.command("validate")
def validate(
    input_path: Annotated[Path, typer.Argument(help="Directory containing ERP input files.")],
) -> None:
    """Validate input files and cross-references."""

    issues = validate_input_directory(input_path)
    frame = issues_to_frame(issues)
    if frame.empty:
        console.print("[green]Validation passed with no issues.[/green]")
        return
    _print_frame("Validation Issues", frame)
    error_count = int(frame["severity"].astype(str).eq("error").sum())
    warning_count = int(frame["severity"].astype(str).eq("warning").sum())
    console.print(f"Errors: {error_count} | Warnings: {warning_count}")
    if error_count:
        raise typer.Exit(code=1)


@reconcile_app.command("stock-gl")
def reconcile_stock_gl_command(
    input_path: Annotated[Path, typer.Option("--input", help="Directory containing stock_moves and gl_entries.")],
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path("config/reconforge.yml"),
    output_path: Annotated[Path, typer.Option("--output", help="Output directory.")] = Path("output"),
    matching_strategy: Annotated[
        str,
        typer.Option("--matching-strategy", help="Matching strategy: standard, strict, aggressive, audit-safe."),
    ] = "standard",
) -> None:
    """Compare stock movements with GL postings."""

    config = load_config(_config_option(config_path))
    datasets = read_required_datasets(input_path, [DatasetName.STOCK_MOVES, DatasetName.GL_ENTRIES])
    if matching_strategy not in {"standard", "strict", "aggressive", "audit-safe"}:
        console.print("[red]matching strategy must be one of: standard, strict, aggressive, audit-safe[/red]")
        raise typer.Exit(code=1)
    result = reconcile_stock_gl(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.GL_ENTRIES],
        config,
        matching_strategy=cast(MatchingStrategy, matching_strategy),
    )
    output_dir = ensure_output_dir(output_path)
    frames = stock_gl_result_frames(result)
    write_report_frames(frames, output_dir, "stock_gl")
    workbook_path = write_excel_workbook(
        frames,
        output_dir / "stock_gl_reconciliation.xlsx",
        metadata=audit_metadata(config.company_name, "Stock to GL Reconciliation", config.output_currency),
    )
    write_json(
        {
            "summary": frame_to_records(result.summary),
            "matched_transactions": frame_to_records(result.matched_transactions),
            "all_exceptions": frame_to_records(result.all_exceptions),
        },
        output_dir,
        "stock_gl_reconciliation",
    )
    _print_frame("Stock-GL Summary", result.summary)
    console.print(f"[green]Stock-GL reconciliation written to:[/green] {workbook_path}")


@reconcile_app.command("workorders")
def reconcile_workorders_command(
    input_path: Annotated[Path, typer.Option("--input", help="Directory containing workshop ERP files.")],
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path("config/reconforge.yml"),
    output_path: Annotated[Path, typer.Option("--output", help="Output directory.")] = Path("output"),
) -> None:
    """Reconcile spare-parts issues, work orders, purchase orders, returns, and invoices."""

    config = load_config(_config_option(config_path))
    datasets = read_required_datasets(
        input_path,
        [
            DatasetName.STOCK_MOVES,
            DatasetName.WORK_ORDERS,
            DatasetName.PURCHASE_ORDERS,
            DatasetName.OLD_PARTS_RETURNS,
            DatasetName.INVOICES,
        ],
    )
    result = reconcile_workorders(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.WORK_ORDERS],
        datasets[DatasetName.PURCHASE_ORDERS],
        datasets[DatasetName.OLD_PARTS_RETURNS],
        datasets[DatasetName.INVOICES],
        config,
    )
    output_dir = ensure_output_dir(output_path)
    frames = workorder_result_frames(result)
    write_report_frames(frames, output_dir, "workorders")
    workbook_path = write_excel_workbook(
        frames,
        output_dir / "workorder_reconciliation.xlsx",
        metadata=audit_metadata(config.company_name, "Work Order Reconciliation", config.output_currency),
    )
    write_json(
        {"summary": frame_to_records(result.summary), "all_exceptions": frame_to_records(result.all_exceptions)},
        output_dir,
        "workorder_reconciliation",
    )
    _print_frame("Work-Order Summary", result.summary)
    console.print(f"[green]Work-order reconciliation written to:[/green] {workbook_path}")


@report_app.command("wip-aging")
def wip_aging_command(
    input_path: Annotated[Path, typer.Option("--input", help="Directory containing work_orders.")],
    output_path: Annotated[Path, typer.Option("--output", help="Output directory.")] = Path("output"),
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path("config/reconforge.yml"),
) -> None:
    """Generate WIP aging by work order, customer, equipment, department, and bucket."""

    config = load_config(_config_option(config_path))
    datasets = read_required_datasets(input_path, [DatasetName.WORK_ORDERS])
    wip = generate_wip_aging(datasets[DatasetName.WORK_ORDERS], config)
    summary = aging_summary(wip)
    output_dir = ensure_output_dir(output_path)
    frames = {"wip_aging": wip, "wip_aging_summary": summary}
    write_report_frames(frames, output_dir, "wip")
    workbook_path = write_excel_workbook(
        frames,
        output_dir / "wip_aging.xlsx",
        metadata=audit_metadata(config.company_name, "WIP Aging", config.output_currency),
    )
    write_json({"wip_aging": frame_to_records(wip), "summary": frame_to_records(summary)}, output_dir, "wip_aging")
    _print_frame("WIP Aging Summary", summary)
    console.print(f"[green]WIP aging report written to:[/green] {workbook_path}")


@report_app.command("management-pack")
def management_pack_command(
    input_path: Annotated[Path, typer.Option("--input", help="Directory containing all sample ERP files.")],
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path("config/reconforge.yml"),
    output_path: Annotated[Path, typer.Option("--output", help="Output directory.")] = Path("output"),
) -> None:
    """Generate a complete Excel management pack and companion outputs."""

    config = load_config(_config_option(config_path))
    datasets = read_required_datasets(
        input_path,
        [
            DatasetName.STOCK_MOVES,
            DatasetName.GL_ENTRIES,
            DatasetName.WORK_ORDERS,
            DatasetName.PURCHASE_ORDERS,
            DatasetName.OLD_PARTS_RETURNS,
            DatasetName.INVOICES,
        ],
    )
    stock_result = reconcile_stock_gl(datasets[DatasetName.STOCK_MOVES], datasets[DatasetName.GL_ENTRIES], config)
    workorder_result = reconcile_workorders(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.WORK_ORDERS],
        datasets[DatasetName.PURCHASE_ORDERS],
        datasets[DatasetName.OLD_PARTS_RETURNS],
        datasets[DatasetName.INVOICES],
        config,
    )
    wip = generate_wip_aging(datasets[DatasetName.WORK_ORDERS], config)
    artifacts = generate_management_pack(input_path, ensure_output_dir(output_path), config, stock_result, workorder_result, wip)
    console.print(f"[green]Management pack:[/green] {artifacts.excel_path}")
    console.print(f"[green]JSON summary:[/green] {artifacts.json_path}")
    console.print(f"[green]HTML dashboard report:[/green] {artifacts.html_path}")


@report_app.command("evidence-binder")
def evidence_binder_command(
    input_path: Annotated[Path, typer.Option("--input", help="Generated ReconForge output directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Evidence binder output directory.")] = Path("output/evidence"),
) -> None:
    """Generate audit evidence folders for High and Critical exceptions."""

    artifacts = generate_evidence_binder(input_path, output_path)
    console.print(f"[green]Evidence cases generated:[/green] {len(artifacts)}")
    if artifacts:
        _print_frame("Evidence Cases", pd.DataFrame([artifact.model_dump() for artifact in artifacts]))


@report_app.command("client-pack")
def client_pack_command(
    input_path: Annotated[Path, typer.Option("--input", help="Generated ReconForge output directory.")] = Path("output"),
    output_path: Annotated[Path, typer.Option("--output", help="Client handoff pack directory.")] = Path("output/client_pack"),
    redact_names: Annotated[bool, typer.Option("--redact-names", help="Redact customer, supplier, employee, reviewer, and equipment identifiers where practical.")] = False,
    redact_amounts: Annotated[bool, typer.Option("--redact-amounts", help="Bucket or redact monetary values where practical.")] = False,
    exclude_raw_records: Annotated[bool, typer.Option("--exclude-raw-records", help="Exclude source-record evidence extracts from the pack.")] = False,
    summary_only: Annotated[bool, typer.Option("--summary-only", help="Create only generated handoff notes plus the source summary when available.")] = False,
    exclude_evidence: Annotated[bool, typer.Option("--exclude-evidence", help="Exclude the evidence folder from the client pack.")] = False,
    include_manifest_checksums: Annotated[bool, typer.Option("--include-manifest-checksums", help="Add SHA-256 checksums for included client-pack files.")] = False,
) -> None:
    """Create a local consultant/client handoff folder from generated outputs."""

    try:
        artifacts = generate_client_pack(
            input_path,
            output_path,
            redact_names=redact_names,
            redact_amounts=redact_amounts,
            exclude_raw_records=exclude_raw_records,
            summary_only=summary_only,
            exclude_evidence=exclude_evidence,
            include_manifest_checksums=include_manifest_checksums,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Client handoff pack:[/green] {artifacts.output_dir}")
    console.print(
        f"Included files: {len(artifacts.included_files)} | Missing optional files: {len(artifacts.missing_optional_files)} | Excluded files: {len(artifacts.excluded_files)}",
    )
    _print_success_paths(artifacts.included_files)


@rules_app.command("validate")
def rules_validate_command(
    pack_path: Annotated[Path, typer.Option("--pack", help="Control pack directory.")],
) -> None:
    """Validate a control pack."""

    pack = load_rule_pack(pack_path)
    console.print(f"[green]Control pack valid:[/green] {pack.metadata.pack_id} ({len(pack.rules)} rules)")


@mappings_app.command("validate")
def mappings_validate_command(
    pack_path: Annotated[Path, typer.Option("--pack", help="ERP mapping control-pack directory.")],
) -> None:
    """Validate an ERP mapping profile and its control-pack files."""

    result = validate_mapping_pack(pack_path)
    table = Table(title=f"Mapping Profile Validation: {result.pack_path}")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for check in result.checks:
        style = "green" if check.passed else "red"
        table.add_row(check.name, f"[{style}]{check.status}[/{style}]", check.detail)
    console.print(table)
    passed = sum(1 for check in result.checks if check.passed)
    failed = len(result.checks) - passed
    summary_style = "green" if result.passed else "red"
    console.print(f"[{summary_style}]Summary: {passed} passed, {failed} failed[/{summary_style}]")
    if not result.passed:
        raise typer.Exit(code=1)


def _run_mapping_inspection(input_path: Path, pack_path: Path, output_path: Path) -> None:
    try:
        result = inspect_mapping_inputs(input_path, pack_path, output_path)
    except (OSError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    summary = result.summary
    table = Table(title=f"Mapping Inspection: {result.profile_id}")
    table.add_column("Metric")
    table.add_column("Value")
    for key, value in summary.items():
        table.add_row(key.replace("_", " "), str(value))
    console.print(table)
    _print_success_paths([result.report_markdown_path, result.report_json_path])


@mappings_app.command("inspect")
def mappings_inspect_command(
    input_path: Annotated[Path, typer.Option("--input", help="Folder containing local CSV/XLSX ERP exports.")],
    pack_path: Annotated[Path, typer.Option("--pack", help="ERP mapping control-pack directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Mapping inspection report directory.")] = Path("output/mapping_wizard"),
) -> None:
    """Inspect local export headers against an ERP mapping profile."""

    _run_mapping_inspection(input_path, pack_path, output_path)


@mappings_app.command("wizard")
def mappings_wizard_command(
    input_path: Annotated[Path, typer.Option("--input", help="Folder containing local CSV/XLSX ERP exports.")],
    pack_path: Annotated[Path, typer.Option("--pack", help="ERP mapping control-pack directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Mapping inspection report directory.")] = Path("output/mapping_wizard"),
) -> None:
    """Generate a draft local mapping report for ERP exports."""

    _run_mapping_inspection(input_path, pack_path, output_path)


@rules_app.command("list")
def rules_list_command(
    pack_path: Annotated[Path, typer.Option("--pack", help="Control pack directory.")],
) -> None:
    """List rules in a control pack."""

    pack = load_rule_pack(pack_path)
    frame = pd.DataFrame(
        [
            {
                "rule_id": rule.rule_id,
                "rule_name": rule.rule_name,
                "severity": rule.severity,
                "entity_type": rule.entity_type,
                "source_file": rule.source_file,
                "risk_impact": rule.risk_impact,
            }
            for rule in pack.rules
        ],
    )
    _print_frame(f"Rules: {pack.metadata.name}", frame, max_rows=100)


@rules_app.command("run")
def rules_run_command(
    input_path: Annotated[Path, typer.Option("--input", help="Directory containing ERP input files.")],
    pack_path: Annotated[Path, typer.Option("--pack", help="Control pack directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Rule output directory.")] = Path("output/rules"),
) -> None:
    """Run a control pack against ERP exports."""

    results = run_rule_pack(input_path, pack_path)
    paths = write_rule_results(results, output_path)
    console.print(f"[green]Rule results:[/green] {len(results)} triggered controls")
    _print_success_paths(paths)


@rules_app.command("explain")
def rules_explain_command(
    pack_path: Annotated[Path, typer.Option("--pack", help="Control pack directory.")],
    rule_id: Annotated[str, typer.Option("--rule", help="Rule ID to explain.")],
) -> None:
    """Explain a control-pack rule in deterministic plain English."""

    try:
        console.print(explain_rule(str(pack_path), rule_id))
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@app.command("anonymize")
def anonymize_command(
    input_path: Annotated[Path, typer.Option("--input", help="Input ERP export directory.")],
    output_path: Annotated[Path, typer.Option("--output", help="Anonymized output directory.")],
    mask_amounts: Annotated[bool, typer.Option("--mask-amounts", help="Mask monetary amounts.")] = False,
    amount_noise_percent: Annotated[float, typer.Option("--amount-noise-percent", help="Maximum percentage noise for masked amounts.")] = 15.0,
    seed: Annotated[int, typer.Option("--seed", help="Deterministic anonymization seed.")] = 42,
    preserve_dates: Annotated[bool, typer.Option("--preserve-dates", help="Keep dates unchanged.")] = False,
    date_shift_days: Annotated[int, typer.Option("--date-shift-days", help="Shift dates by this many days.")] = 0,
    profile: Annotated[str, typer.Option("--profile", help="Anonymization profile: consulting-safe or public-demo.")] = "consulting-safe",
) -> None:
    """Anonymize ERP exports while preserving referential integrity."""

    paths = anonymize_directory(
        input_path,
        output_path,
        mask_amounts=mask_amounts,
        amount_noise_percent=amount_noise_percent,
        seed=seed,
        preserve_dates=preserve_dates,
        date_shift_days=date_shift_days,
        profile=profile,
    )
    console.print(f"[green]Anonymized files:[/green] {len(paths)}")
    _print_success_paths(paths)


@generate_app.command("synthetic")
def generate_synthetic_command(
    rows: Annotated[int, typer.Option("--rows", help="Number of stock movement rows to generate.", min=1)] = 1000,
    output_path: Annotated[Path, typer.Option("--output", help="Synthetic output directory.")] = Path("benchmarks/small_1k"),
    exception_rate: Annotated[float, typer.Option("--exception-rate", help="Approximate exception rate.")] = 0.15,
    critical_rate: Annotated[float, typer.Option("--critical-rate", help="Approximate critical exception rate.")] = 0.05,
    seed: Annotated[int, typer.Option("--seed", help="Deterministic generation seed.")] = 42,
    industry: Annotated[str, typer.Option("--industry", help="Industry profile: workshop, manufacturing, fleet, dealership, service.")] = "workshop",
    currency: Annotated[str, typer.Option("--currency", help="Output currency code for synthetic monetary rows.")] = "USD",
) -> None:
    """Generate synthetic ERP CSV exports matching ReconForge schema."""

    paths = generate_synthetic_dataset(
        rows,
        output_path,
        exception_rate=exception_rate,
        critical_rate=critical_rate,
        seed=seed,
        industry=industry,
        currency=currency,
    )
    console.print(f"[green]Synthetic dataset generated:[/green] {output_path}")
    _print_success_paths(paths)


@app.command("benchmark")
def benchmark_command(
    input_path: Annotated[Path, typer.Option("--input", help="Input dataset directory.")],
    engine: Annotated[str, typer.Option("--engine", help="Benchmark engine: pandas or duckdb.")] = "pandas",
    output_path: Annotated[Path, typer.Option("--output", help="Benchmark output directory.")] = Path("output/benchmark"),
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path("config/reconforge.yml"),
) -> None:
    """Benchmark reconciliation runtime and output metrics."""

    try:
        metrics = run_benchmark(input_path, output_path, engine_name=engine, config_path=config_path)
    except (ValueError, RuntimeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    _print_frame("Benchmark", pd.DataFrame([metrics.to_dict()]))


@explain_app.command("exception")
def explain_exception_command(
    input_path: Annotated[Path, typer.Option("--input", help="Local JSON exception file.")],
    exception_id: Annotated[str, typer.Option("--exception-id", help="Exception ID, rule ID, move ID, or entry ID.")],
) -> None:
    """Explain an exception without requiring an AI API."""

    try:
        console.print(explain_exception_file(input_path, exception_id))
    except (OSError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


@review_app.command("list")
def review_list_command(
    input_path: Annotated[Path, typer.Option("--input", help="Generated ReconForge output directory.")] = Path("output"),
) -> None:
    """List local exceptions with review status."""

    state_path = input_path / "review_state.json"
    exceptions = collect_exception_frame(input_path)
    merged = merge_review_state_with_exceptions(exceptions, load_review_state(state_path))
    if merged.empty:
        console.print("[yellow]No generated exceptions found.[/yellow]")
        return
    columns = [
        "exception_id",
        "status",
        "reviewer",
        "updated_at",
        "severity",
        "exception_type",
        "amount_impact",
        "source_file",
    ]
    visible = merged[[column for column in columns if column in merged.columns]]
    _print_frame("Exception Review State", visible, max_rows=100)
    if "status" in merged.columns:
        counts = merged["status"].astype(str).value_counts().to_dict()
        summary = " | ".join(f"{status}: {count}" for status, count in counts.items())
        console.print(f"[dim]Review statuses:[/dim] {summary}")


@review_app.command("set-status")
def review_set_status_command(
    exception_id: Annotated[str, typer.Option("--exception-id", help="Exception ID to update.")],
    status: Annotated[str, typer.Option("--status", help=f"Status: {', '.join(ALLOWED_STATUSES)}")],
    input_path: Annotated[Path, typer.Option("--input", help="Generated ReconForge output directory.")] = Path("output"),
    reviewer: Annotated[str, typer.Option("--reviewer", help="Reviewer name or initials.")] = "",
    note: Annotated[str, typer.Option("--note", help="Reviewer note.")] = "",
    decision_reason: Annotated[str, typer.Option("--decision-reason", help="Decision reason.")] = "",
    accepted_risk_reason: Annotated[str, typer.Option("--accepted-risk-reason", help="Accepted-risk reason.")] = "",
    escalation_owner: Annotated[str, typer.Option("--escalation-owner", help="Escalation owner.")] = "",
) -> None:
    """Set local review status for one exception."""

    state_path = input_path / "review_state.json"
    state = load_review_state(state_path)
    try:
        entry = update_review_status(
            exception_id,
            status,
            state,
            reviewer=reviewer,
            note=note,
            decision_reason=decision_reason,
            accepted_risk_reason=accepted_risk_reason,
            escalation_owner=escalation_owner,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    save_review_state(state_path, state)
    console.print(
        f"[green]Review updated:[/green] {entry['exception_id']} | {entry['status']} | {state_path}",
    )


@review_app.command("export")
def review_export_command(
    input_path: Annotated[Path, typer.Option("--input", help="Generated ReconForge output directory.")] = Path("output"),
    output_path: Annotated[Path, typer.Option("--output", help="Review register workbook path.")] = Path("output/review_register.xlsx"),
) -> None:
    """Export exception review state as an Excel register."""

    path = export_review_register(input_path, output_path)
    console.print(f"[green]Review register written:[/green] {path}")


@compare_app.command("periods", context_settings={"allow_extra_args": True})
def compare_periods_command(
    ctx: typer.Context,
    inputs: Annotated[list[Path], typer.Option("--inputs", help="Generated output folders to compare, in period order.")],
    output_path: Annotated[Path, typer.Option("--output", help="Period comparison output directory.")] = Path("output/period_comparison"),
) -> None:
    """Compare exception outputs from two or more generated periods."""

    period_inputs = [*inputs, *(Path(value) for value in ctx.args)]
    try:
        artifacts = compare_period_outputs(period_inputs, output_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Period comparison:[/green] {output_path}")
    _print_success_paths([artifacts.workbook_path, artifacts.html_path, artifacts.json_path, artifacts.markdown_path])


@demo_app.command("run")
def demo_run_command(
    output_path: Annotated[Path, typer.Option("--output", help="Demo output directory.")] = Path("output/demo"),
    input_path: Annotated[Path, typer.Option("--input", help="Sample ERP export directory.")] = Path("examples/sample_data"),
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path("config/reconforge.yml"),
    rules_pack: Annotated[Path, typer.Option("--rules-pack", help="Control pack to run during the demo.")] = Path("control-packs/audit-basic"),
) -> None:
    """Run the local 10-minute sample workflow end to end."""

    issues = validate_input_directory(input_path)
    issue_frame = issues_to_frame(issues)
    error_count = int(issue_frame["severity"].astype(str).eq("error").sum()) if not issue_frame.empty else 0
    if error_count:
        _print_frame("Demo Data Validation Issues", issue_frame)
        console.print("[red]Demo stopped because sample data has validation errors.[/red]")
        raise typer.Exit(code=1)

    config = load_config(_config_option(config_path))
    datasets = read_required_datasets(
        input_path,
        [
            DatasetName.STOCK_MOVES,
            DatasetName.GL_ENTRIES,
            DatasetName.WORK_ORDERS,
            DatasetName.PURCHASE_ORDERS,
            DatasetName.OLD_PARTS_RETURNS,
            DatasetName.INVOICES,
        ],
    )
    output_dir = ensure_output_dir(output_path)
    stock_result = reconcile_stock_gl(datasets[DatasetName.STOCK_MOVES], datasets[DatasetName.GL_ENTRIES], config)
    workorder_result = reconcile_workorders(
        datasets[DatasetName.STOCK_MOVES],
        datasets[DatasetName.WORK_ORDERS],
        datasets[DatasetName.PURCHASE_ORDERS],
        datasets[DatasetName.OLD_PARTS_RETURNS],
        datasets[DatasetName.INVOICES],
        config,
    )
    wip = generate_wip_aging(datasets[DatasetName.WORK_ORDERS], config)

    stock_frames = stock_gl_result_frames(stock_result)
    workorder_frames = workorder_result_frames(workorder_result)
    write_report_frames(stock_frames, output_dir, "stock_gl")
    write_report_frames(workorder_frames, output_dir, "workorders")
    stock_workbook = write_excel_workbook(
        stock_frames,
        output_dir / "stock_gl_reconciliation.xlsx",
        metadata=audit_metadata(config.company_name, "Stock to GL Reconciliation", config.output_currency),
    )
    workorder_workbook = write_excel_workbook(
        workorder_frames,
        output_dir / "workorder_reconciliation.xlsx",
        metadata=audit_metadata(config.company_name, "Work Order Reconciliation", config.output_currency),
    )

    rule_paths = write_rule_results(run_rule_pack(input_path, rules_pack), output_dir / "rules")
    artifacts = generate_management_pack(input_path, output_dir, config, stock_result, workorder_result, wip)

    state_path = output_dir / "review_state.json"
    state = load_review_state(state_path)
    exceptions = collect_exception_frame(output_dir)
    if not exceptions.empty:
        exception_id = str(exceptions.iloc[0]["exception_id"])
        update_review_status(
            exception_id,
            "Under Review",
            state,
            reviewer="Demo Reviewer",
            note="Initial sample review started from the one-command demo.",
            decision_reason="Validate source posting and operational evidence.",
        )
    save_review_state(state_path, state)
    register_path = export_review_register(output_dir, output_dir / "review_register.xlsx")
    evidence_artifacts = generate_evidence_binder(output_dir, output_dir / "evidence")
    client_pack_artifacts = generate_client_pack(output_dir, output_dir / "client_pack")

    paths = [
        artifacts.excel_path,
        output_dir / "executive_report.html",
        output_dir / "dashboard.html",
        artifacts.markdown_path,
        state_path,
        register_path,
        output_dir / "evidence",
        client_pack_artifacts.output_dir,
        stock_workbook,
        workorder_workbook,
        *rule_paths,
    ]
    _print_frame(
        "Demo Workflow",
        pd.DataFrame(
            [
                {"step": "validated_sample_data", "result": f"{len(issue_frame)} validation issues, {error_count} errors"},
                {"step": "stock_to_gl_exceptions", "result": len(stock_result.all_exceptions)},
                {"step": "workorder_exceptions", "result": len(workorder_result.all_exceptions)},
                {"step": "rules_triggered", "result": len(rule_paths)},
                {"step": "evidence_cases", "result": len(evidence_artifacts)},
                {"step": "review_state_entries", "result": len(state)},
            ],
        ),
        max_rows=20,
    )
    _print_success_paths(paths)
    console.print("\n[bold]Next steps[/bold]")
    console.print(f"1. Open dashboard: {output_dir / 'dashboard.html'}")
    console.print(f"2. Open executive report: {output_dir / 'executive_report.html'}")
    console.print(f"3. Open management pack: {output_dir / 'management_pack.xlsx'}")
    console.print(f"4. Open evidence binder: {output_dir / 'evidence' / 'index.html'}")
    console.print(f"5. Review client handoff pack: {client_pack_artifacts.output_dir}")
    console.print(f"6. Run Studio: reconforge studio --input {input_path} --output {output_dir}")
    console.print(f"7. Review or export the register: {register_path}")


@app.command("dashboard")
def dashboard(
    input_path: Annotated[Path, typer.Option("--input", help="Generated output directory to serve.")] = Path("output"),
    host: Annotated[str, typer.Option("--host", help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Bind port.")] = 8501,
) -> None:
    """Start the local dashboard server for generated reports."""

    if not input_path.exists():
        console.print(f"[red]Output directory does not exist:[/red] {input_path}")
        raise typer.Exit(code=1)
    console.print(f"[green]Starting ReconForge dashboard:[/green] http://{host}:{port}")
    uvicorn.run(create_app(input_path), host=host, port=port, log_level="info")


@app.command("studio")
def studio(
    input_path: Annotated[Path, typer.Option("--input", help="ERP input directory for Studio views.")] = Path("examples/sample_data"),
    output_path: Annotated[Path, typer.Option("--output", help="Generated output directory for downloads/evidence.")] = Path("output"),
    host: Annotated[str, typer.Option("--host", help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Bind port.")] = 8601,
) -> None:
    """Start ReconForge Studio, a local review workspace."""

    console.print(f"[green]Starting ReconForge Studio:[/green] http://{host}:{port}")
    uvicorn.run(create_studio_app(input_path, output_path), host=host, port=port, log_level="info")


@app.command("doctor")
def doctor(
    input_path: Annotated[Path, typer.Option("--input", help="Optional sample data directory to inspect.")] = Path("examples/sample_data"),
    config_path: Annotated[Path, typer.Option("--config", help="ReconForge YAML config.")] = Path("config/reconforge.yml"),
    output_path: Annotated[Path, typer.Option("--output", help="Output directory to inspect.")] = Path("output"),
) -> None:
    """Check environment, dependencies, sample data, config, and report output path."""

    checks = []
    checks.append(("Python package", "OK", f"ReconForge ERP {__version__}"))
    try:
        config = load_config(_config_option(config_path))
        checks.append(("Config", "OK", f"{config_path} | {config.company_name}"))
    except ValueError as exc:
        checks.append(("Config", "FAIL", str(exc)))
    checks.append(("Sample data", "OK" if input_path.exists() else "WARN", str(input_path)))
    checks.append(("Output path", "OK", str(ensure_output_dir(output_path))))
    issues = validate_input_directory(input_path) if input_path.exists() else []
    structural_errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    checks.append(("Validation", "OK" if structural_errors == 0 else "FAIL", f"{structural_errors} errors, {warnings} warnings"))

    table = Table(title="ReconForge Doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for check, status, detail in checks:
        style = "green" if status == "OK" else "yellow" if status == "WARN" else "red"
        table.add_row(check, f"[{style}]{status}[/{style}]", detail)
    console.print(table)
    if any(status == "FAIL" for _, status, _ in checks):
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
