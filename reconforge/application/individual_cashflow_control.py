"""Application boundary for local individual/freelancer cashflow controls."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from reconforge.domain.individual_cashflow_control import (
    CashBudgetLine,
    CashTransaction,
    IndividualCashflowControlError,
    IndividualCashflowControlRun,
    run_individual_cashflow_control,
    verify_individual_cashflow_payload,
)
from reconforge.io.records import RecordIngressError, read_json_record_document
from reconforge.utils.money import Money


def _required(record: Mapping[str, Any], key: str) -> Any:
    if key not in record:
        raise IndividualCashflowControlError(f"individual cashflow input is missing {key}.")
    return record[key]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_records(path: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        document = read_json_record_document(path, envelope_keys=("records", "data"))
    except RecordIngressError as exc:
        raise IndividualCashflowControlError(f"individual cashflow input rejected ({exc.code}).") from exc
    return list(document.records), document.checksum_sha256


def _transactions(records: Iterable[Mapping[str, Any]], *, currency: str) -> tuple[CashTransaction, ...]:
    try:
        return tuple(
            CashTransaction(
                transaction_id=_required(record, "transaction_id"),
                transaction_date=_required(record, "transaction_date"),
                flow_type=_required(record, "flow_type"),
                category=_required(record, "category"),
                amount=Money.from_exact(_required(record, "amount"), record.get("currency", currency)),
                reference=_required(record, "reference"),
                source_reference=_required(record, "source_reference"),
            )
            for record in records
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise IndividualCashflowControlError("transaction input does not match the closed record contract.") from exc


def _budgets(records: Iterable[Mapping[str, Any]], *, currency: str) -> tuple[CashBudgetLine, ...]:
    try:
        return tuple(
            CashBudgetLine(
                budget_id=_required(record, "budget_id"),
                period=_required(record, "period"),
                flow_type=_required(record, "flow_type"),
                category=_required(record, "category"),
                limit=Money.from_exact(_required(record, "limit"), record.get("currency", currency)),
                source_reference=_required(record, "source_reference"),
            )
            for record in records
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise IndividualCashflowControlError("budget input does not match the closed record contract.") from exc


def run_individual_cashflow_control_records(
    transactions: Iterable[Mapping[str, Any]],
    budgets: Iterable[Mapping[str, Any]] = (),
    *,
    currency: str,
    input_digests: tuple[str, ...] = (),
) -> IndividualCashflowControlRun:
    """Run the control from trusted-in-memory mappings (used by the local API)."""

    transaction_records = list(transactions)
    budget_records = list(budgets)
    if len(transaction_records) > 10_000 or len(budget_records) > 10_000:
        raise IndividualCashflowControlError("API cashflow record limit exceeded.")
    return run_individual_cashflow_control(
        _transactions(transaction_records, currency=currency),
        _budgets(budget_records, currency=currency),
        input_digests=input_digests,
    )


def run_individual_cashflow_control_files(
    transactions_path: Path,
    budgets_path: Path | None = None,
    *,
    currency: str,
) -> IndividualCashflowControlRun:
    """Run the local cashflow control over bounded JSON exports."""

    transaction_records, transaction_digest = _read_records(transactions_path)
    if budgets_path is None:
        budget_records: list[dict[str, Any]] = []
        budget_digest = ""
    else:
        budget_records, budget_digest = _read_records(budgets_path)
    digests: tuple[str, ...] = (transaction_digest, _sha256(transactions_path))
    if budgets_path is not None:
        digests += (budget_digest, _sha256(budgets_path))
    return run_individual_cashflow_control_records(
        transaction_records,
        budget_records,
        currency=currency,
        input_digests=digests,
    )


def write_individual_cashflow_report(run: IndividualCashflowControlRun, output_path: Path) -> None:
    """Write a self-digesting individual cashflow artifact."""

    payload = run.to_dict()
    payload["artifact_type"] = "reconforge-individual-cashflow-control"
    payload["artifact_digest"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def verify_individual_cashflow_report(path: Path) -> dict[str, Any]:
    """Verify one local individual cashflow report."""

    from reconforge.io.structured import StructuredDocumentError, read_json_document

    try:
        payload = read_json_document(path)
    except (OSError, UnicodeError, StructuredDocumentError) as exc:
        raise IndividualCashflowControlError("individual cashflow report cannot be read.") from exc
    if not isinstance(payload, dict) or payload.get("artifact_type") != "reconforge-individual-cashflow-control":
        raise IndividualCashflowControlError("individual cashflow report artifact type is invalid.")
    artifact_digest = payload.get("artifact_digest")
    without_digest = {key: value for key, value in payload.items() if key != "artifact_digest"}
    expected = hashlib.sha256(
        json.dumps(without_digest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    if not isinstance(artifact_digest, str) or artifact_digest != expected:
        raise IndividualCashflowControlError("individual cashflow report digest verification failed.")
    verify_individual_cashflow_payload(payload)
    return payload


__all__ = [
    "run_individual_cashflow_control_files",
    "run_individual_cashflow_control_records",
    "verify_individual_cashflow_report",
    "write_individual_cashflow_report",
]
