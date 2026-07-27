"""Synthetic enterprise-style demo package generator.

The generator is intentionally local-only and deterministic for file-based
demo assets. It does not add product workflow behavior; it assembles synthetic
records and optionally seeds the existing local DB-backed foundation services.
"""

from __future__ import annotations

import csv
import json
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from reconforge.db import DatabaseError, connect, resolve_db_path, run_migrations
from reconforge.domain.models import DEFAULT_LOCAL_FIRST_NOTE
from reconforge.io.generated import GeneratedArtifactError, read_generated_json_document
from reconforge.io.writers import json_default
from reconforge.platform.accounts import AccountReconciliationService
from reconforge.platform.close import CloseManagementService
from reconforge.platform.common import PlatformError
from reconforge.platform.controls import ControlTestingService
from reconforge.platform.evidence import EvidenceRegistryService
from reconforge.platform.exceptions import ExceptionQueueService
from reconforge.platform.intercompany import IntercompanyService
from reconforge.platform.journals import JournalControlService
from reconforge.platform.matching import MatchingService
from reconforge.platform.metrics import MetricsService
from reconforge.reconciliation.matching import RECORD_IDENTITY_POLICY
from reconforge.utils.money import STRICT_FINANCIAL_INPUT_POLICY

SYNTHETIC_DATA_MARKER = "SYNTHETIC_ENTERPRISE_DEMO_ONLY"
DEMO_GENERATED_AT = "2026-06-01T09:00:00Z"
DEMO_PERIOD = "2026-05"
DEMO_PRIOR_PERIOD = "2026-04"
WORKSPACE = "default"


class EnterpriseDemoError(ValueError):
    """Raised for safe, user-facing enterprise demo generation errors."""


@dataclass(frozen=True)
class EnterpriseDemoResult:
    """Generated synthetic enterprise demo package details."""

    output_dir: Path
    manifest_path: Path
    readme_path: Path
    walkthrough_path: Path
    demo_script_path: Path
    db_path: Path | None
    generated_paths: list[Path]
    record_counts: dict[str, int]


def generate_enterprise_demo(output_path: Path | str, *, db_path: Path | str | None = None) -> EnterpriseDemoResult:
    """Generate a repeatable local synthetic enterprise demo folder."""

    try:
        output_dir = _prepare_output_dir(output_path)
        data = _build_synthetic_records()
        generated_paths = _write_source_assets(output_dir, data)
        with tempfile.TemporaryDirectory(prefix="reconforge-enterprise-demo-") as temp_dir:
            working_db, persisted_db = _prepare_working_db(
                db_path=db_path,
                output_dir=output_dir,
                temp_dir=Path(temp_dir),
            )
            report_paths, record_counts = _seed_platform_reports(working_db, output_dir)
            generated_paths.extend(report_paths)
        readme_path = _write_readme(output_dir, record_counts, persisted_db is not None)
        walkthrough_path = _write_walkthrough(output_dir)
        demo_script_path = _write_demo_script(output_dir, persisted_db is not None)
        checklist_path = _write_screenshots_checklist(output_dir)
        generated_paths.extend([readme_path, walkthrough_path, demo_script_path, checklist_path])

        manifest_path = _write_manifest(output_dir, record_counts, persisted_db)
        generated_paths.append(manifest_path)
    except EnterpriseDemoError:
        raise
    except (DatabaseError, OSError, PlatformError, csv.Error, json.JSONDecodeError) as exc:
        raise EnterpriseDemoError("Unable to generate the synthetic enterprise demo package.") from exc

    return EnterpriseDemoResult(
        output_dir=output_dir,
        manifest_path=manifest_path,
        readme_path=readme_path,
        walkthrough_path=walkthrough_path,
        demo_script_path=demo_script_path,
        db_path=persisted_db,
        generated_paths=sorted(set(generated_paths)),
        record_counts=record_counts,
    )


def _prepare_output_dir(output_path: Path | str) -> Path:
    raw = str(output_path)
    if not raw.strip() or _has_control_character(raw):
        raise EnterpriseDemoError("Unsafe demo output path. Use a local folder path without control characters.")
    path = Path(output_path).expanduser()
    if any(part == ".." for part in path.parts):
        raise EnterpriseDemoError("Unsafe demo output path. Parent traversal segments are not allowed.")
    if path.exists() and path.is_symlink():
        raise EnterpriseDemoError("Unsafe demo output path. Symlink output directories are not allowed.")
    if path.exists() and not path.is_dir():
        raise EnterpriseDemoError("Unsafe demo output path. The output path must be a directory.")
    if path.parent.exists() and not path.parent.is_dir():
        raise EnterpriseDemoError("Unsafe demo output path. The output parent must be a directory.")
    resolved = path.resolve(strict=False)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _prepare_working_db(*, db_path: Path | str | None, output_dir: Path, temp_dir: Path) -> tuple[Path, Path | None]:
    if db_path is None:
        working_db = temp_dir / "reconforge-enterprise-demo.db"
        run_migrations(working_db)
        return working_db, None

    raw_db_path = Path(db_path).expanduser()
    if any(part == ".." for part in raw_db_path.parts) or _has_control_character(str(db_path)):
        raise EnterpriseDemoError("Unsafe demo database path. Parent traversal and control characters are not allowed.")
    resolved_db = resolve_db_path(raw_db_path.resolve(strict=False))
    if not _is_relative_to(resolved_db, output_dir):
        raise EnterpriseDemoError("Demo database path must be inside the enterprise demo output directory.")
    if resolved_db.exists():
        resolved_db.unlink()
    run_migrations(resolved_db)
    return resolved_db, resolved_db


def _has_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _build_synthetic_records() -> dict[str, list[dict[str, Any]]]:
    entities = [
        {
            "entity_code": "SYN-US01",
            "entity_name": "Synthetic North Operations",
            "region": "North America",
            "currency": "USD",
            "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        },
        {
            "entity_code": "SYN-UK01",
            "entity_name": "Synthetic EMEA Services",
            "region": "EMEA",
            "currency": "GBP",
            "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        },
        {
            "entity_code": "SYN-MX01",
            "entity_name": "Synthetic LATAM Distribution",
            "region": "LATAM",
            "currency": "MXN",
            "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        },
    ]
    periods = [
        {
            "period_name": DEMO_PRIOR_PERIOD,
            "start_date": "2026-04-01",
            "end_date": "2026-04-30",
            "status": "Synthetic prior period",
            "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        },
        {
            "period_name": DEMO_PERIOD,
            "start_date": "2026-05-01",
            "end_date": "2026-05-31",
            "status": "Synthetic current period",
            "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        },
    ]
    account_catalog = [
        ("1000", "Cash and bank", 428500.0, "medium"),
        ("1200", "Trade receivables", 265000.0, "medium"),
        ("1300", "Inventory valuation", 710000.0, "high"),
        ("2000", "Accounts payable", -318000.0, "medium"),
        ("3999", "Intercompany clearing", 84000.0, "high"),
        ("5000", "Cost of goods sold", 925000.0, "high"),
    ]
    entity_factors = {"SYN-US01": 1.0, "SYN-UK01": 0.62, "SYN-MX01": 0.48}
    period_factors = {DEMO_PRIOR_PERIOD: 0.97, DEMO_PERIOD: 1.0}
    currencies = {record["entity_code"]: record["currency"] for record in entities}
    trial_balance: list[dict[str, Any]] = []
    for period in periods:
        for entity in entities:
            entity_code = str(entity["entity_code"])
            for account_code, account_name, base_balance, risk_rating in account_catalog:
                trial_balance.append(
                    {
                        "period": period["period_name"],
                        "entity_code": entity_code,
                        "account_code": account_code,
                        "account_name": account_name,
                        "balance": round(
                            base_balance * entity_factors[entity_code] * period_factors[str(period["period_name"])], 2
                        ),
                        "currency": currencies[entity_code],
                        "risk_rating": risk_rating,
                        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
                    },
                )
    journals = [
        {
            "journal_id": "JRN-SYN-001",
            "period_name": DEMO_PERIOD,
            "entity_code": "SYN-US01",
            "posting_date": "2026-06-02",
            "account_code": "9999",
            "amount": "175000.00",
            "currency": "USD",
            "reference": "",
            "approver": "",
            "is_manual": "true",
            "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        },
        {
            "journal_id": "JRN-SYN-002",
            "period_name": DEMO_PERIOD,
            "entity_code": "SYN-UK01",
            "posting_date": "2026-05-30",
            "account_code": "5000",
            "amount": "27500.00",
            "currency": "GBP",
            "reference": "WO-SYN-1001",
            "approver": "Synthetic Reviewer",
            "is_manual": "true",
            "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        },
        {
            "journal_id": "JRN-SYN-003",
            "period_name": DEMO_PERIOD,
            "entity_code": "SYN-MX01",
            "posting_date": "2026-05-20",
            "account_code": "1300",
            "amount": "49000.00",
            "currency": "MXN",
            "reference": "INV-SYN-2040",
            "approver": "Synthetic Controller",
            "is_manual": "false",
            "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        },
    ]
    intercompany = [
        _intercompany_row("IC-SYN-001", "SYN-US01", "SYN-UK01", "2026-05-10", "1000.00", "USD", "REF-IC-SYN-001"),
        _intercompany_row("IC-SYN-002", "SYN-UK01", "SYN-US01", "2026-05-11", "-1000.00", "USD", "REF-IC-SYN-001"),
        _intercompany_row("IC-SYN-003", "SYN-US01", "SYN-MX01", "2026-05-17", "5000.00", "USD", "REF-IC-SYN-002"),
        _intercompany_row("IC-SYN-004", "SYN-MX01", "SYN-US01", "2026-05-18", "-4750.00", "USD", "REF-IC-SYN-002"),
        _intercompany_row("IC-SYN-005", "SYN-UK01", "SYN-MX01", "2026-05-21", "1200.00", "GBP", "REF-IC-SYN-003"),
    ]
    controls = [
        {
            "control_code": "SYN-CTRL-001",
            "name": "Manual journal review",
            "owner": "Synthetic Controller",
            "frequency": "monthly",
            "description": "Check that synthetic manual journals have a review reference.",
            "risk_rating": "high",
            "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        },
        {
            "control_code": "SYN-CTRL-002",
            "name": "Intercompany imbalance review",
            "owner": "Synthetic Accounting Lead",
            "frequency": "monthly",
            "description": "Check synthetic intercompany references for offsetting entries.",
            "risk_rating": "high",
            "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        },
        {
            "control_code": "SYN-CTRL-003",
            "name": "Evidence completeness check",
            "owner": "Synthetic Reviewer",
            "frequency": "monthly",
            "description": "Check that selected synthetic workpapers have local evidence references.",
            "risk_rating": "medium",
            "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        },
    ]
    matching_left = [
        _match_row("LED-SYN-001", "REF-MATCH-SYN-001", "1250.00", "2026-05-05"),
        _match_row("LED-SYN-002", "REF-MATCH-SYN-002", "2500.00", "2026-05-07"),
        _match_row("LED-SYN-003", "REF-MATCH-SYN-003", "4000.00", "2026-05-09"),
        _match_row("LED-SYN-004", "REF-MATCH-SYN-004", "750.00", "2026-05-12"),
    ]
    matching_right = [
        _match_row("BANK-SYN-001", "REF-MATCH-SYN-001", "1250.00", "2026-05-05"),
        _match_row("BANK-SYN-002", "REF-MATCH-SYN-002", "2499.50", "2026-05-08"),
        _match_row("BANK-SYN-003", "REF-MATCH-SYN-003", "4000.00", "2026-05-09"),
    ]
    close_tasks = [
        _close_task("CLOSE-SYN-001", "Load synthetic trial balance exports", "Complete", "Synthetic Accounting Lead"),
        _close_task("CLOSE-SYN-002", "Prepare synthetic account reconciliations", "Complete", "Synthetic Preparer"),
        _close_task("CLOSE-SYN-003", "Review synthetic unresolved exceptions", "Blocked", "Synthetic Reviewer"),
        _close_task("CLOSE-SYN-004", "Verify synthetic evidence coverage", "In Progress", "Synthetic Reviewer"),
        _close_task("CLOSE-SYN-005", "Review synthetic close readiness", "Not Started", "Synthetic Controller"),
    ]
    inventory = [
        _inventory_on_hand(
            "SYN-PART-001",
            "Synthetic brake pad kit",
            "EA",
            "SYN-US-MAIN",
            "North main store",
            "STOCK",
            "SYN-US01",
            "LOT-SYN-2605",
            "Lot",
            "148",
        ),
        _inventory_on_hand(
            "SYN-LUBE-001",
            "Synthetic workshop lubricant",
            "L",
            "SYN-US-MAIN",
            "North main store",
            "BULK",
            "SYN-US01",
            "LOT-SYN-2604",
            "Lot",
            "72.500",
        ),
        _inventory_on_hand(
            "SYN-SENSOR-001",
            "Synthetic sensor module",
            "EA",
            "SYN-UK-SERVICE",
            "EMEA service store",
            "SECURE",
            "SYN-UK01",
            "SER-SYN-0042",
            "Serial",
            "1",
        ),
        _inventory_on_hand(
            "SYN-PART-002",
            "Synthetic filter element",
            "EA",
            "SYN-MX-DIST",
            "LATAM distribution store",
            "PICK",
            "SYN-MX01",
            "",
            "None",
            "94",
        ),
        _inventory_on_hand(
            "SYN-PART-003",
            "Synthetic belt assembly",
            "EA",
            "SYN-MX-DIST",
            "LATAM distribution store",
            "QUARANTINE",
            "SYN-MX01",
            "",
            "None",
            "-3",
        ),
        _inventory_movement(
            "RCV/SYN/0048",
            "Receipt",
            "Posted",
            "2026-05-04",
            "SYN-US01",
            "",
            "SYN-US-MAIN/STOCK",
            2,
            "180",
        ),
        _inventory_movement(
            "TRF/SYN/0019",
            "Transfer",
            "Posted",
            "2026-05-12",
            "SYN-US01",
            "SYN-US-MAIN/STOCK",
            "SYN-US-MAIN/BULK",
            1,
            "25.500",
        ),
        _inventory_movement(
            "DLV/SYN/0032",
            "Delivery",
            "Posted",
            "2026-05-19",
            "SYN-UK01",
            "SYN-UK-SERVICE/SECURE",
            "",
            1,
            "1",
        ),
        _inventory_movement(
            "ADJ/SYN/0007",
            "Adjustment",
            "Draft",
            "2026-05-29",
            "SYN-MX01",
            "SYN-MX-DIST/QUARANTINE",
            "",
            1,
            "3",
        ),
        _inventory_exception(
            "INV-NEGATIVE-STOCK",
            "high",
            "SYN-PART-003",
            "SYN-MX-DIST/QUARANTINE",
            "-3",
            "Posted local movements produce a synthetic negative on-hand quantity.",
        ),
        _inventory_exception(
            "INV-EXPIRED-STOCK",
            "high",
            "SYN-LUBE-001",
            "SYN-US-MAIN/BULK",
            "72.500",
            "Synthetic positive on-hand is assigned to an expired tracked lot.",
        ),
        _inventory_exception(
            "INV-MISSING-ACCOUNT",
            "medium",
            "SYN-PART-002",
            "",
            "",
            "Synthetic active stock item has no local inventory account reference.",
        ),
        _inventory_count(
            "COUNT/SYN/0024",
            "Approved",
            "2026-05-28",
            "SYN-MX01",
            "SYN-MX-DIST",
            "QUARANTINE",
            1,
            1,
            1,
            "ADJ/SYN/0007",
        ),
        _inventory_count(
            "COUNT/SYN/0025",
            "Counting",
            "2026-05-30",
            "SYN-US01",
            "SYN-US-MAIN",
            "STOCK",
            2,
            1,
            0,
            "",
        ),
        _inventory_reorder_signal(
            "high",
            "SYN-PART-003",
            "Synthetic belt assembly",
            "EA",
            "SYN-MX-DIST",
            "QUARANTINE",
            "-3",
            "5",
            "18",
            "21",
            12,
        ),
        _inventory_reorder_signal(
            "medium",
            "SYN-PART-002",
            "Synthetic filter element",
            "EA",
            "SYN-MX-DIST",
            "PICK",
            "94",
            "100",
            "160",
            "66",
            8,
        ),
        _inventory_valuation(
            "VAL/SYN/0048",
            "RCV/SYN/0048",
            "Receipt",
            "Approved",
            "2026-05-04",
            "SYN-US01",
            "USD",
            "4500.00",
            "IV-VAL/SYN/0048",
            "Draft",
        ),
        _inventory_valuation(
            "VAL/SYN/0032",
            "DLV/SYN/0032",
            "Delivery",
            "Approved",
            "2026-05-19",
            "SYN-UK01",
            "GBP",
            "185.00",
            "IV-VAL/SYN/0032",
            "Draft",
        ),
        _inventory_valuation_reversal(
            "IVR/SYN/0032",
            "VAL/SYN/0032",
            "REV/DLV/SYN/0032",
            "Delivery",
            "Receipt",
            "Approved",
            "2026-05-23",
            "SYN-UK01",
            "GBP",
            "185.00",
            "Restore",
            1,
            "IVR-IVR/SYN/0032",
            "Draft",
        ),
        _inventory_cost_layer(
            "SYN-LAYER-US-0048-01",
            "VAL/SYN/0048",
            "SYN-PART-001",
            "Synthetic brake pad kit",
            "EA",
            "LOT-SYN-2605",
            "SYN-US01",
            "USD",
            "180",
            "148",
            "4500.00",
            "3700.00",
        ),
        _inventory_cost_layer(
            "SYN-LAYER-UK-0017-01",
            "VAL/SYN/0017",
            "SYN-SENSOR-001",
            "Synthetic sensor module",
            "EA",
            "SER-SYN-0042",
            "SYN-UK01",
            "GBP",
            "1",
            "1",
            "185.00",
            "185.00",
        ),
    ]
    return {
        "entities": entities,
        "periods": periods,
        "trial_balance": trial_balance,
        "journals": journals,
        "intercompany": intercompany,
        "controls": controls,
        "matching_left": matching_left,
        "matching_right": matching_right,
        "close_tasks": close_tasks,
        "inventory": inventory,
    }


def _intercompany_row(
    transaction_id: str,
    entity_code: str,
    counterparty_code: str,
    posting_date: str,
    amount: str,
    currency: str,
    reference: str,
) -> dict[str, str]:
    return {
        "transaction_id": transaction_id,
        "period_name": DEMO_PERIOD,
        "entity_code": entity_code,
        "counterparty_code": counterparty_code,
        "posting_date": posting_date,
        "amount": amount,
        "currency": currency,
        "reference": reference,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
    }


def _match_row(row_id: str, reference: str, amount: str, date_text: str) -> dict[str, str]:
    return {
        "id": row_id,
        "reference": reference,
        "amount": amount,
        "date": date_text,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
    }


def _close_task(task_id: str, name: str, status: str, owner: str) -> dict[str, str]:
    return {
        "task_id": task_id,
        "period_name": DEMO_PERIOD,
        "name": name,
        "status": status,
        "owner": owner,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
    }


def _inventory_on_hand(
    item_code: str,
    item_name: str,
    uom_code: str,
    warehouse_code: str,
    warehouse_name: str,
    location_code: str,
    entity_code: str,
    lot_serial_code: str,
    tracking_type: str,
    quantity: str,
) -> dict[str, Any]:
    return {
        "record_type": "on_hand",
        "item_code": item_code,
        "item_name": item_name,
        "uom_code": uom_code,
        "warehouse_code": warehouse_code,
        "warehouse_name": warehouse_name,
        "location_code": location_code,
        "entity_code": entity_code,
        "lot_serial_code": lot_serial_code,
        "tracking_type": tracking_type,
        "quantity": quantity,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
    }


def _inventory_movement(
    movement_number: str,
    movement_type: str,
    status: str,
    movement_date: str,
    entity_code: str,
    from_location: str,
    to_location: str,
    line_count: int,
    quantity: str,
) -> dict[str, Any]:
    return {
        "record_type": "movement",
        "movement_number": movement_number,
        "movement_type": movement_type,
        "status": status,
        "movement_date": movement_date,
        "entity_code": entity_code,
        "from_location": from_location,
        "to_location": to_location,
        "line_count": line_count,
        "quantity": quantity,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
    }


def _inventory_exception(
    control_code: str,
    risk_rating: str,
    item_code: str,
    location: str,
    quantity: str,
    description: str,
) -> dict[str, str]:
    return {
        "record_type": "exception",
        "control_code": control_code,
        "risk_rating": risk_rating,
        "item_code": item_code,
        "location": location,
        "quantity": quantity,
        "description": description,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
    }


def _inventory_count(
    count_number: str,
    status: str,
    count_date: str,
    entity_code: str,
    warehouse_code: str,
    location_code: str,
    line_count: int,
    counted_line_count: int,
    variance_line_count: int,
    adjustment_movement_number: str,
) -> dict[str, Any]:
    return {
        "record_type": "count",
        "count_number": count_number,
        "status": status,
        "count_date": count_date,
        "entity_code": entity_code,
        "warehouse_code": warehouse_code,
        "location_code": location_code,
        "line_count": line_count,
        "counted_line_count": counted_line_count,
        "variance_line_count": variance_line_count,
        "adjustment_movement_number": adjustment_movement_number,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
    }


def _inventory_reorder_signal(
    risk_rating: str,
    item_code: str,
    item_name: str,
    uom_code: str,
    warehouse_code: str,
    location_code: str,
    on_hand_quantity: str,
    minimum_quantity: str,
    target_quantity: str,
    suggested_quantity: str,
    lead_time_days: int,
) -> dict[str, Any]:
    return {
        "record_type": "reorder_signal",
        "risk_rating": risk_rating,
        "item_code": item_code,
        "item_name": item_name,
        "uom_code": uom_code,
        "warehouse_code": warehouse_code,
        "location_code": location_code,
        "on_hand_quantity": on_hand_quantity,
        "minimum_quantity": minimum_quantity,
        "target_quantity": target_quantity,
        "suggested_quantity": suggested_quantity,
        "lead_time_days": lead_time_days,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
    }


def _inventory_valuation(
    valuation_number: str,
    movement_number: str,
    movement_type: str,
    status: str,
    valuation_date: str,
    entity_code: str,
    currency_code: str,
    total_value: str,
    finance_entry_number: str,
    finance_entry_status: str,
) -> dict[str, Any]:
    return {
        "record_type": "valuation",
        "valuation_number": valuation_number,
        "movement_number": movement_number,
        "movement_type": movement_type,
        "status": status,
        "valuation_date": valuation_date,
        "entity_code": entity_code,
        "costing_method": "FIFO",
        "currency_code": currency_code,
        "total_value": total_value,
        "finance_entry_number": finance_entry_number,
        "finance_entry_status": finance_entry_status,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
    }


def _inventory_cost_layer(
    layer_id: str,
    valuation_number: str,
    item_code: str,
    item_name: str,
    uom_code: str,
    lot_serial_code: str,
    entity_code: str,
    currency_code: str,
    original_quantity: str,
    remaining_quantity: str,
    original_value: str,
    remaining_value: str,
) -> dict[str, Any]:
    return {
        "record_type": "cost_layer",
        "layer_id": layer_id,
        "valuation_number": valuation_number,
        "item_code": item_code,
        "item_name": item_name,
        "uom_code": uom_code,
        "lot_serial_code": lot_serial_code,
        "entity_code": entity_code,
        "currency_code": currency_code,
        "original_quantity": original_quantity,
        "remaining_quantity": remaining_quantity,
        "original_value": original_value,
        "remaining_value": remaining_value,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
    }


def _inventory_valuation_reversal(
    reversal_number: str,
    original_valuation_number: str,
    reversal_movement_number: str,
    original_movement_type: str,
    reversal_movement_type: str,
    status: str,
    reversal_date: str,
    entity_code: str,
    currency_code: str,
    total_value: str,
    layer_effect: str,
    layer_effect_count: int,
    finance_entry_number: str,
    finance_entry_status: str,
) -> dict[str, Any]:
    return {
        "record_type": "valuation_reversal",
        "reversal_number": reversal_number,
        "original_valuation_number": original_valuation_number,
        "reversal_movement_number": reversal_movement_number,
        "original_movement_type": original_movement_type,
        "reversal_movement_type": reversal_movement_type,
        "status": status,
        "reversal_date": reversal_date,
        "entity_code": entity_code,
        "currency_code": currency_code,
        "total_value": total_value,
        "layer_effect": layer_effect,
        "layer_effect_count": layer_effect_count,
        "finance_entry_number": finance_entry_number,
        "finance_entry_status": finance_entry_status,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
    }


def _write_source_assets(output_dir: Path, data: dict[str, list[dict[str, Any]]]) -> list[Path]:
    paths = [
        _write_json_file(output_dir / "sample_entities.json", _records_payload(data["entities"])),
        _write_json_file(output_dir / "sample_periods.json", _records_payload(data["periods"])),
        _write_csv_file(output_dir / "sample_trial_balance.csv", data["trial_balance"]),
        _write_csv_file(output_dir / "sample_journals.csv", data["journals"]),
        _write_csv_file(output_dir / "sample_intercompany.csv", data["intercompany"]),
        _write_csv_file(output_dir / "sample_controls.csv", data["controls"]),
        _write_csv_file(output_dir / "sample_matching_left.csv", data["matching_left"]),
        _write_csv_file(output_dir / "sample_matching_right.csv", data["matching_right"]),
        _write_json_file(output_dir / "sample_close_tasks.json", _records_payload(data["close_tasks"])),
        _write_json_file(output_dir / "sample_inventory_control.json", _records_payload(data["inventory"])),
    ]
    evidence_dir = output_dir / "sample_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_paths = _write_evidence_files(evidence_dir)
    evidence_refs = [
        {
            "evidence_code": f"EVD-SYN-{index:03d}",
            "local_path": f"sample_evidence/{path.name}",
            "provenance_type": "synthetic-local-file",
            "redaction_status": "synthetic",
            "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        }
        for index, path in enumerate(evidence_paths, start=1)
    ]
    paths.extend(evidence_paths)
    paths.append(_write_json_file(output_dir / "sample_evidence_references.json", _records_payload(evidence_refs)))
    paths.append(
        _write_json_file(
            output_dir / "sample_account_reconciliations.json", _records_payload(_account_reconciliation_samples(data))
        )
    )
    return paths


def _write_evidence_files(evidence_dir: Path) -> list[Path]:
    evidence_files = {
        "trial_balance_support.md": "Synthetic trial balance support for the current demo period.",
        "manual_journal_review.md": "Synthetic note showing a manual journal that needs review evidence.",
        "intercompany_support.md": "Synthetic intercompany matching support with one imbalanced reference.",
        "control_test_workpaper.md": "Synthetic control testing workpaper for local demo walkthroughs.",
        "matching_support.md": "Synthetic matching support showing matched and unmatched local records.",
    }
    paths: list[Path] = []
    for filename, description in evidence_files.items():
        path = evidence_dir / filename
        path.write_text(
            "\n".join(
                [
                    f"# {description}",
                    "",
                    f"Synthetic data marker: `{SYNTHETIC_DATA_MARKER}`",
                    "",
                    "This file is generated for a local ReconForge demo. It is not real business evidence,",
                    "does not contain live operational data, and does not support audit opinions or compliance certification.",
                    "",
                ],
            ),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def _account_reconciliation_samples(data: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in data["trial_balance"]:
        if row["period"] != DEMO_PERIOD:
            continue
        samples.append(
            {
                "reconciliation_id": f"REC-{row['period']}-{row['entity_code']}-{row['account_code']}",
                "period_name": row["period"],
                "entity_code": row["entity_code"],
                "account_code": row["account_code"],
                "account_name": row["account_name"],
                "balance": row["balance"],
                "currency": row["currency"],
                "status": "Draft",
                "risk_rating": row["risk_rating"],
                "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
            },
        )
    return samples


def _seed_platform_reports(db_path: Path, output_dir: Path) -> tuple[list[Path], dict[str, int]]:
    connection = connect(db_path, require_exists=True)
    try:
        accounts = AccountReconciliationService(connection)
        close = CloseManagementService(connection)
        evidence = EvidenceRegistryService(connection)
        journals = JournalControlService(connection)
        intercompany = IntercompanyService(connection)
        controls = ControlTestingService(connection)
        matching = MatchingService(connection)
        exceptions = ExceptionQueueService(connection)
        metrics = MetricsService(connection)

        for account_code, account_name, risk_rating in _template_accounts():
            accounts.create_template(
                account_code=account_code,
                name=f"Synthetic {account_name} reconciliation",
                risk_rating=risk_rating,
                materiality_threshold="10000",
                required_evidence="Synthetic local support file",
                owner="Synthetic Preparer",
                reviewer="Synthetic Reviewer",
            )
        accounts.import_trial_balance(output_dir / "sample_trial_balance.csv", default_period=DEMO_PERIOD)
        current_reconciliations = accounts.list_reconciliations(period_name=DEMO_PERIOD)
        if current_reconciliations:
            first_reconciliation_id = str(current_reconciliations[0]["id"])
            accounts.prepare(
                reconciliation_id=first_reconciliation_id,
                preparer="Synthetic Preparer",
                actor_label="Synthetic Preparer",
            )
            accounts.submit(first_reconciliation_id, actor_label="Synthetic Preparer")
            accounts.review(
                first_reconciliation_id,
                reviewer="Synthetic Reviewer",
                actor_label="Synthetic Reviewer",
            )
            accounts.complete(first_reconciliation_id, actor_label="Synthetic Completer")
        else:
            first_reconciliation_id = "REC-SYNTHETIC"

        close_period = close.period_init(period_name=DEMO_PERIOD, start_date="2026-05-01", end_date="2026-05-31")
        close_tasks = close.list_tasks(period_id=str(close_period["id"]))
        _set_close_task_statuses(close, close_tasks)

        evidence.requirement(
            object_type="reconciliation",
            object_id=first_reconciliation_id,
            requirement_code="TB-SYN",
            description="Synthetic trial balance support",
        )
        first_task_id = str(close_tasks[0]["id"]) if close_tasks else "CLOSE-SYNTHETIC"
        evidence.requirement(
            object_type="close_task",
            object_id=first_task_id,
            requirement_code="CLOSE-SYN",
            description="Synthetic close task support",
        )
        evidence.requirement(
            object_type="journal",
            object_id="JRN-SYN-001",
            requirement_code="JRN-SYN",
            description="Synthetic manual journal support",
        )
        registered_evidence = [
            evidence.register(
                output_dir / "sample_evidence" / "trial_balance_support.md",
                evidence_code="EVD-SYN-TB",
                provenance_type="synthetic-local-file",
                redaction_status="synthetic",
                object_type="reconciliation",
                object_id=first_reconciliation_id,
            ),
            evidence.register(
                output_dir / "sample_evidence" / "control_test_workpaper.md",
                evidence_code="EVD-SYN-CLOSE",
                provenance_type="synthetic-local-file",
                redaction_status="synthetic",
                object_type="close_task",
                object_id=first_task_id,
            ),
            evidence.register(
                output_dir / "sample_evidence" / "manual_journal_review.md",
                evidence_code="EVD-SYN-JRN",
                provenance_type="synthetic-local-file",
                redaction_status="synthetic",
                object_type="journal",
                object_id="JRN-SYN-001",
            ),
        ]

        journals.import_journals(output_dir / "sample_journals.csv", default_period=DEMO_PERIOD)
        journal_exception_count = journals.policy_run(
            period_name=DEMO_PERIOD,
            period_end="2026-05-31",
            high_value_threshold="100000",
            high_risk_accounts="9999,3999",
        )

        intercompany.import_transactions(output_dir / "sample_intercompany.csv", default_period=DEMO_PERIOD)
        intercompany_case_count = intercompany.match(period_name=DEMO_PERIOD, tolerance="1")

        controls.import_library(output_dir / "sample_controls.csv")
        control_plan_count = controls.plan_tests(period_name=DEMO_PERIOD, sample_size=3)
        for index, plan in enumerate(controls.list_plans(period_name=DEMO_PERIOD), start=1):
            controls.record_result(
                plan_id=str(plan["id"]),
                result_status="Completed",
                effectiveness_status="Ineffective" if index == 2 else "Effective",
                note="Synthetic control test result for local demo only.",
                evidence_id=str(registered_evidence[min(index - 1, len(registered_evidence) - 1)]["id"]),
            )

        match_result = matching.run(
            left_path=output_dir / "sample_matching_left.csv",
            right_path=output_dir / "sample_matching_right.csv",
            name="synthetic-enterprise-demo-match",
            amount_tolerance="1",
            date_window_days=2,
            financial_input_policy=STRICT_FINANCIAL_INPUT_POLICY,
            record_identity_policy=RECORD_IDENTITY_POLICY,
        )
        match_rows = matching.results(match_result.job_id)
        for match_row in match_rows:
            if match_row["status"] == "Unmatched":
                exceptions.upsert_exception(
                    source_type="matching",
                    source_id=f"MATCH-{match_row['left_id']}",
                    description="Synthetic matching record did not find a right-side candidate.",
                    period_name=DEMO_PERIOD,
                    risk_rating="medium",
                )

        metric_rows = metrics.compute(period_name=DEMO_PERIOD)
        output_reports = _write_report_payloads(
            output_dir,
            account_rows=accounts.list_reconciliations(period_name=DEMO_PERIOD),
            close_rows=close.list_tasks(period_id=str(close_period["id"])),
            evidence_rows=evidence.list_evidence(),
            journal_report=journals.report(),
            journal_rows=journals.exceptions(period_name=DEMO_PERIOD),
            intercompany_rows=intercompany.cases(),
            control_report=controls.report(),
            control_rows=controls.list_plans(period_name=DEMO_PERIOD),
            match_rows=match_rows,
            exception_rows=exceptions.list(period_name=DEMO_PERIOD),
            metric_rows=metric_rows,
        )
    finally:
        connection.close()

    record_counts = {
        "entities": 3,
        "periods": 2,
        "trial_balance_rows": 36,
        "journals": 3,
        "journal_exceptions": journal_exception_count,
        "intercompany_transactions": 5,
        "intercompany_cases": intercompany_case_count,
        "controls": 3,
        "control_test_plans": control_plan_count,
        "matching_left_records": 4,
        "matching_results": match_result.result_count,
        "matching_matched": match_result.matched_count,
        "unified_exceptions": len(_read_records(output_dir / "sample_unified_exceptions.json")),
        "metrics": len(metric_rows),
    }
    _write_json_file(output_dir / "reports" / "platform_snapshot.json", _payload({"record_counts": record_counts}))
    return output_reports + [output_dir / "reports" / "platform_snapshot.json"], record_counts


def _template_accounts() -> list[tuple[str, str, str]]:
    return [
        ("1000", "cash and bank", "medium"),
        ("1200", "trade receivables", "medium"),
        ("1300", "inventory valuation", "high"),
        ("2000", "accounts payable", "medium"),
        ("3999", "intercompany clearing", "high"),
        ("5000", "cost of goods sold", "high"),
    ]


def _set_close_task_statuses(close: CloseManagementService, close_tasks: list[dict[str, Any]]) -> None:
    statuses = [
        ("Complete", ""),
        ("Complete", ""),
        ("Blocked", "Synthetic journal exception review remains open."),
        ("In Progress", ""),
        ("Not Started", ""),
    ]
    for task, (status, blocker_reason) in zip(close_tasks, statuses, strict=False):
        close.task_status(task_id=str(task["id"]), status=status, blocker_reason=blocker_reason)


def _write_report_payloads(
    output_dir: Path,
    *,
    account_rows: list[dict[str, Any]],
    close_rows: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    journal_report: dict[str, Any],
    journal_rows: list[dict[str, Any]],
    intercompany_rows: list[dict[str, Any]],
    control_report: dict[str, Any],
    control_rows: list[dict[str, Any]],
    match_rows: list[dict[str, Any]],
    exception_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
) -> list[Path]:
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    sanitized_accounts = [
        _project(
            row, ["period_name", "entity_code", "account_code", "account_name", "status", "balance", "risk_rating"]
        )
        for row in account_rows
    ]
    sanitized_close = [
        _project(
            row, ["period_name", "task_code", "name", "owner", "category", "risk_rating", "status", "blocker_reason"]
        )
        for row in close_rows
    ]
    sanitized_evidence = [_relative_evidence_record(row, output_dir) for row in evidence_rows]
    sanitized_journals = [
        _project(
            row,
            [
                "policy_code",
                "risk_rating",
                "description",
                "status",
                "journal_id",
                "period_name",
                "entity_code",
                "account_code",
                "amount",
            ],
        )
        for row in journal_rows
    ]
    sanitized_intercompany = [
        _project(
            row,
            [
                "period_name",
                "entity_code",
                "counterparty_code",
                "reference",
                "imbalance_amount",
                "currency",
                "status",
                "settlement_status",
            ],
        )
        for row in intercompany_rows
    ]
    sanitized_controls = [
        _project(
            row, ["period_name", "control_code", "name", "owner", "frequency", "risk_rating", "status", "sample_size"]
        )
        for row in control_rows
    ]
    sanitized_matches = [
        _project(
            row,
            [
                "left_id",
                "right_id",
                "match_type",
                "confidence",
                "explanation",
                "amount_difference",
                "date_difference_days",
                "status",
            ],
        )
        for row in match_rows
    ]
    sanitized_exceptions = [
        _project(
            row,
            [
                "source_type",
                "period_name",
                "entity_code",
                "account_code",
                "control_code",
                "risk_rating",
                "owner",
                "status",
                "description",
            ],
        )
        for row in exception_rows
    ]
    sanitized_metrics = [
        _project(row, ["metric_key", "name", "description", "period_name", "value", "value_text", "lineage"])
        for row in metric_rows
    ]
    paths = [
        _write_json_file(reports_dir / "account_reconciliations.json", _records_payload(sanitized_accounts)),
        _write_json_file(reports_dir / "close_tasks.json", _records_payload(sanitized_close)),
        _write_json_file(reports_dir / "evidence_registry.json", _records_payload(sanitized_evidence)),
        _write_json_file(
            reports_dir / "journal_controls.json",
            _payload({"summary": journal_report, "records": _stable_records(sanitized_journals)}),
        ),
        _write_json_file(reports_dir / "intercompany_cases.json", _records_payload(sanitized_intercompany)),
        _write_json_file(
            reports_dir / "control_testing.json",
            _payload({"summary": control_report, "records": _stable_records(sanitized_controls)}),
        ),
        _write_json_file(reports_dir / "matching_results.json", _records_payload(sanitized_matches)),
        _write_json_file(reports_dir / "unified_exceptions.json", _records_payload(sanitized_exceptions)),
        _write_json_file(reports_dir / "dashboard_metrics.json", _records_payload(sanitized_metrics)),
        _write_json_file(output_dir / "sample_unified_exceptions.json", _records_payload(sanitized_exceptions)),
        _write_json_file(output_dir / "sample_metrics.json", _records_payload(sanitized_metrics)),
        _write_dashboard_summary(reports_dir / "dashboard_summary.md", sanitized_metrics),
    ]
    return paths


def _relative_evidence_record(row: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    projected = _project(
        row,
        ["evidence_code", "source_path", "checksum_sha256", "provenance_type", "redaction_status", "evidence_status"],
    )
    source_path = Path(str(projected.get("source_path", "")))
    try:
        projected["source_path"] = source_path.relative_to(output_dir).as_posix()
    except ValueError:
        projected["source_path"] = source_path.name
    return projected


def _project(row: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    projected = {key: row.get(key, "") for key in keys}
    projected["synthetic_data_marker"] = SYNTHETIC_DATA_MARKER
    return projected


def _write_dashboard_summary(path: Path, metrics: list[dict[str, Any]]) -> Path:
    lines = [
        "# Synthetic Enterprise Demo Dashboard Summary",
        "",
        f"Synthetic data marker: `{SYNTHETIC_DATA_MARKER}`",
        "",
        "All values are generated from synthetic local demo data. They do not represent real customers, ROI, adoption, revenue, compliance certification, or audit opinions.",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for metric in metrics:
        lines.append(f"| {metric['metric_key']} | {metric['value']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_readme(output_dir: Path, record_counts: dict[str, int], db_created: bool) -> Path:
    db_line = (
        "- `reconforge.db` - optional local SQLite demo database seeded from existing platform services."
        if db_created
        else "- No SQLite database was persisted. Re-run with `--db output/enterprise_demo/reconforge.db` to keep one locally."
    )
    lines = [
        "# ReconForge Synthetic Enterprise Demo",
        "",
        f"Synthetic data marker: `{SYNTHETIC_DATA_MARKER}`",
        "",
        "This folder is a local-first demo package generated entirely from synthetic data.",
        "It contains no real customers, no fake logos, no testimonials, no fake ROI, no adoption claims, and no revenue claims.",
        "It does not provide an audit opinion, compliance certification, legal signature, direct ERP connector, or replacement claim for ERP or audit systems.",
        "",
        "## What Is Included",
        "",
        "- Synthetic multi-entity and period reference files.",
        "- Synthetic trial balance, journal, intercompany, control, matching, evidence, exception, and metric examples.",
        "- Local report JSON and Markdown outputs under `reports/`.",
        db_line,
        "- `demo_manifest.json` with record counts and generated file checksums.",
        "",
        "## Record Counts",
        "",
        "| Area | Count |",
        "| --- | ---: |",
    ]
    for key in sorted(record_counts):
        lines.append(f"| {key} | {record_counts[key]} |")
    lines.extend(
        [
            "",
            "## Local Walkthrough",
            "",
            "Open `demo_walkthrough.md` for a guided flow. Open `demo_script.md` for a presenter script.",
            "The demo is designed to show ReconForge platform foundations from local files only.",
            "",
        ],
    )
    path = output_dir / "README.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_walkthrough(output_dir: Path) -> Path:
    lines = [
        "# Synthetic Enterprise Demo Walkthrough",
        "",
        f"Synthetic data marker: `{SYNTHETIC_DATA_MARKER}`",
        "",
        "This walkthrough uses synthetic data only. It includes no real customers, no fake ROI, no testimonials, and no compliance certification.",
        "",
        "## Suggested Flow",
        "",
        "1. Review `sample_entities.json` and `sample_periods.json` for the synthetic multi-entity setup.",
        "2. Open `sample_trial_balance.csv` to see period/entity/account balances.",
        "3. Review `reports/account_reconciliations.json` and `reports/close_tasks.json` for local workflow state examples.",
        "4. Review `sample_journals.csv`, `sample_intercompany.csv`, and `sample_controls.csv` for control examples.",
        "5. Open `reports/unified_exceptions.json` to see journal, intercompany, control testing, and matching exceptions in one local queue.",
        "6. Open `reports/dashboard_metrics.json` or `reports/dashboard_summary.md` for local metric snapshots.",
        "7. Review `sample_evidence/` and `reports/evidence_registry.json` for checksum/provenance aids.",
        "",
        "## Boundary Notes",
        "",
        "- Local-first demo only; no cloud upload, telemetry, SaaS storage, or external calls are used.",
        "- Export-based examples only; this is not a direct ERP connector.",
        "- Evidence checksums are integrity aids only, not legal signatures or assurance conclusions.",
        "- The demo database, when generated, is sample state for walkthroughs and tests only.",
        "",
    ]
    path = output_dir / "demo_walkthrough.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_demo_script(output_dir: Path, db_created: bool) -> Path:
    command = "reconforge demo enterprise --output output/enterprise_demo"
    if db_created:
        command += " --db output/enterprise_demo/reconforge.db"
    lines = [
        "# Demo Script",
        "",
        f"Synthetic data marker: `{SYNTHETIC_DATA_MARKER}`",
        "",
        "Opening: This is a local ReconForge demo built from fully synthetic data. It does not show real customers, ROI, logos, testimonials, compliance certification, or audit opinions.",
        "",
        "Command to generate:",
        "",
        "```bash",
        command,
        "```",
        "",
        "Narration:",
        "",
        "1. Start with the generated README and manifest to confirm the synthetic-only boundary.",
        "2. Show the entity and period files to explain the multi-entity local scenario.",
        "3. Move through account reconciliations, close tasks, evidence references, and control examples.",
        "4. Show the unified exception queue and metric snapshots as examples of the platform foundations.",
        "5. Close by restating that the demo is export-based, local-first, and not a direct ERP connector or assurance product.",
        "",
    ]
    path = output_dir / "demo_script.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_screenshots_checklist(output_dir: Path) -> Path:
    lines = [
        "# Screenshots Checklist",
        "",
        f"Synthetic data marker: `{SYNTHETIC_DATA_MARKER}`",
        "",
        "Use screenshots from this folder only when showing synthetic local demo data.",
        "",
        "- Capture `README.md` synthetic-only statement.",
        "- Capture `reports/dashboard_summary.md` metrics table.",
        "- Capture `reports/unified_exceptions.json` with synthetic exception rows.",
        "- Capture `sample_evidence/` and `reports/evidence_registry.json` for checksum/provenance aids.",
        "- Do not add logos, testimonials, fake ROI, fake adoption, or real business data to screenshots.",
        "",
    ]
    path = output_dir / "screenshots_checklist.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_manifest(output_dir: Path, record_counts: dict[str, int], db_path: Path | None) -> Path:
    generated_files = []
    for path in sorted(
        (
            file_path
            for file_path in output_dir.rglob("*")
            if file_path.is_file() and file_path.name != "demo_manifest.json"
        ),
        key=lambda file_path: file_path.relative_to(output_dir).as_posix(),
    ):
        generated_files.append(
            {
                "path": path.relative_to(output_dir).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _checksum_file(path),
            },
        )
    database_path = db_path.relative_to(output_dir).as_posix() if db_path is not None else ""
    manifest = {
        "schema_version": 1,
        "package_name": "synthetic-enterprise-demo",
        "generated_at": DEMO_GENERATED_AT,
        "synthetic_data_only": True,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        "local_first": True,
        "external_calls": False,
        "workspace": WORKSPACE,
        "local_first_note": DEFAULT_LOCAL_FIRST_NOTE,
        "database": {
            "requested": db_path is not None,
            "created": db_path is not None,
            "path": database_path,
        },
        "record_counts": record_counts,
        "claim_boundaries": [
            "synthetic data only",
            "no real customers",
            "no fake ROI",
            "no fake logos",
            "no testimonials",
            "no audit opinion",
            "no compliance certification",
            "no direct ERP connector",
            "local-first demo only",
        ],
        "generated_files": generated_files,
        "manifest_excludes": ["demo_manifest.json"],
    }
    return _write_json_file(output_dir / "demo_manifest.json", manifest)


def _records_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    return _payload({"records": _stable_records(records)})


def _payload(extra: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "synthetic_data_only": True,
        "synthetic_data_marker": SYNTHETIC_DATA_MARKER,
        "generated_at": DEMO_GENERATED_AT,
    }
    payload.update(extra)
    return payload


def _write_json_file(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")
    return path


def _stable_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda record: json.dumps(record, sort_keys=True, default=json_default))


def _write_csv_file(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return path
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _checksum_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read_records(path: Path) -> list[dict[str, Any]]:
    try:
        payload = read_generated_json_document(path, mode="display").payload
    except GeneratedArtifactError as exc:
        raise EnterpriseDemoError("Synthetic enterprise demo JSON failed safety validation.") from exc
    records = payload.get("records", [])
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]
