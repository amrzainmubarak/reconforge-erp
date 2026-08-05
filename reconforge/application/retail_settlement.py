"""Application boundary for the local retail POS settlement control."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from reconforge.domain.retail_settlement import (
    RetailPosBatch,
    RetailProcessorSettlement,
    RetailSettlementError,
    RetailSettlementRun,
    run_retail_settlement,
)
from reconforge.io.records import RecordIngressError, read_json_record_document
from reconforge.io.structured import StructuredDocumentError, read_json_document
from reconforge.utils.money import Money


def _required(record: dict[str, Any], key: str) -> Any:
    if key not in record:
        raise RetailSettlementError(f"retail input is missing {key}.")
    return record[key]


def _money(record: dict[str, Any], key: str, currency: str) -> Money:
    return Money.from_exact(_required(record, key), currency)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_pos(record: dict[str, Any]) -> RetailPosBatch:
    currency = str(_required(record, "currency")).upper()
    return RetailPosBatch(
        batch_id=_required(record, "batch_id"),
        store_id=_required(record, "store_id"),
        business_date=_required(record, "business_date"),
        currency=currency,
        card_sales=_money(record, "card_sales", currency),
        card_refunds=_money(record, "card_refunds", currency),
        cash_sales=_money(record, "cash_sales", currency),
        cash_refunds=_money(record, "cash_refunds", currency),
        gift_sales=_money(record, "gift_sales", currency),
        gift_refunds=_money(record, "gift_refunds", currency),
        transaction_count=_required(record, "transaction_count"),
        source_reference=_required(record, "source_reference"),
    )


def _parse_settlement(record: dict[str, Any]) -> RetailProcessorSettlement:
    currency = str(_required(record, "currency")).upper()
    return RetailProcessorSettlement(
        settlement_id=_required(record, "settlement_id"),
        batch_id=_required(record, "batch_id"),
        store_id=_required(record, "store_id"),
        settlement_date=_required(record, "settlement_date"),
        currency=currency,
        card_gross=_money(record, "card_gross", currency),
        refunds=_money(record, "refunds", currency),
        fees=_money(record, "fees", currency),
        chargebacks=_money(record, "chargebacks", currency),
        net_settlement=_money(record, "net_settlement", currency),
        provider_reference=_required(record, "provider_reference"),
    )


def read_retail_pos_batches(path: Path) -> tuple[tuple[RetailPosBatch, ...], str]:
    """Read a bounded JSON array of POS batch records and return its digest."""

    try:
        document = read_json_record_document(path, envelope_keys=("records", "batches", "data"))
    except RecordIngressError as exc:
        raise RetailSettlementError(f"retail POS input rejected ({exc.code}).") from exc
    try:
        return tuple(_parse_pos(record) for record in document.records), document.checksum_sha256
    except (KeyError, TypeError, ValueError) as exc:
        raise RetailSettlementError("retail POS input does not match the closed record contract.") from exc


def read_retail_settlements(path: Path) -> tuple[tuple[RetailProcessorSettlement, ...], str]:
    """Read a bounded JSON array of processor settlement records."""

    try:
        document = read_json_record_document(path, envelope_keys=("records", "settlements", "data"))
    except RecordIngressError as exc:
        raise RetailSettlementError(f"retail settlement input rejected ({exc.code}).") from exc
    try:
        return tuple(_parse_settlement(record) for record in document.records), document.checksum_sha256
    except (KeyError, TypeError, ValueError) as exc:
        raise RetailSettlementError("retail settlement input does not match the closed record contract.") from exc


def run_retail_settlement_files(
    pos_path: Path,
    settlement_path: Path,
    *,
    currency: str,
    tolerance: str,
) -> RetailSettlementRun:
    """Run the bounded control from two local export files."""

    pos_batches, pos_digest = read_retail_pos_batches(pos_path)
    settlements, settlement_digest = read_retail_settlements(settlement_path)
    try:
        tolerance_money = Money.from_exact(tolerance, currency)
    except Exception as exc:
        raise RetailSettlementError("retail settlement tolerance is invalid.") from exc
    return run_retail_settlement(
        pos_batches,
        settlements,
        tolerance=tolerance_money,
        input_digests=(pos_digest, settlement_digest),
    )


def write_retail_settlement_report(run: RetailSettlementRun, output_path: Path) -> None:
    """Write one self-digesting, JSON-safe report."""

    payload = run.to_dict()
    payload["artifact_type"] = "reconforge-retail-settlement"
    payload["artifact_digest"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def verify_retail_settlement_report(path: Path) -> dict[str, Any]:
    """Verify the artifact digest and return the parsed payload."""

    try:
        payload = read_json_document(path)
    except (OSError, UnicodeError, StructuredDocumentError) as exc:
        raise RetailSettlementError("retail settlement report cannot be read.") from exc
    if not isinstance(payload, dict) or payload.get("artifact_type") != "reconforge-retail-settlement":
        raise RetailSettlementError("retail settlement report artifact type is invalid.")
    artifact_digest = payload.get("artifact_digest")
    without_digest = {key: value for key, value in payload.items() if key != "artifact_digest"}
    expected = hashlib.sha256(
        json.dumps(without_digest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    if not isinstance(artifact_digest, str) or artifact_digest != expected:
        raise RetailSettlementError("retail settlement report digest verification failed.")
    return payload


__all__ = [
    "read_retail_pos_batches",
    "read_retail_settlements",
    "run_retail_settlement_files",
    "verify_retail_settlement_report",
    "write_retail_settlement_report",
]
