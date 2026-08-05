"""Application boundary for local CAMT.053 to ledger reconciliation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from reconforge.connectors.camt053 import Camt053Error, parse_camt053_file
from reconforge.domain.bank_statement_control import (
    BankLedgerRecord,
    BankStatementControlError,
    BankStatementControlRun,
    BankStatementRecord,
    run_bank_statement_control,
)
from reconforge.io.records import RecordIngressError, read_json_record_document
from reconforge.utils.money import Money


def _required(record: dict[str, Any], key: str) -> Any:
    if key not in record:
        raise BankStatementControlError(f"bank ledger input is missing {key}.")
    return record[key]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_ledger_records(path: Path) -> tuple[tuple[BankLedgerRecord, ...], str]:
    try:
        document = read_json_record_document(path, envelope_keys=("records", "ledger", "data"))
    except RecordIngressError as exc:
        raise BankStatementControlError(f"bank ledger input rejected ({exc.code}).") from exc
    records: list[BankLedgerRecord] = []
    try:
        for record in document.records:
            currency = str(_required(record, "currency")).upper()
            records.append(
                BankLedgerRecord(
                    record_id=_required(record, "record_id"),
                    account_id=_required(record, "account_id"),
                    booking_date=_required(record, "booking_date"),
                    amount=Money.from_exact(_required(record, "amount"), currency),
                    reference=_required(record, "reference"),
                    source_reference=_required(record, "source_reference"),
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise BankStatementControlError("bank ledger input does not match the closed record contract.") from exc
    return tuple(records), document.checksum_sha256


def _statement_records(path: Path) -> tuple[tuple[BankStatementRecord, ...], str]:
    try:
        statement = parse_camt053_file(str(path))
    except (Camt053Error, OSError) as exc:
        raise BankStatementControlError("CAMT.053 statement input is invalid.") from exc
    records: list[BankStatementRecord] = []
    for line in statement.lines:
        try:
            amount = Money.from_exact(line.signed_amount, line.currency)
            records.append(
                BankStatementRecord(
                    line_id=line.line_id,
                    account_id=line.account_id,
                    booking_date=line.booking_date,
                    amount=amount,
                    reference=" | ".join(
                        item
                        for item in (line.line_id, line.bank_reference, line.end_to_end_id, line.transaction_id, line.remittance_information)
                        if item
                    ),
                    source_reference=statement.statement_id,
                )
            )
        except (TypeError, ValueError) as exc:
            raise BankStatementControlError("CAMT.053 line cannot be projected into the bank control.") from exc
    return tuple(records), statement.source_digest


def run_bank_statement_control_files(
    statement_path: Path,
    ledger_path: Path,
    *,
    currency: str,
    tolerance: str,
    date_window_days: int = 1,
) -> BankStatementControlRun:
    """Run the local CAMT.053 and ledger export control."""

    bank_lines, statement_digest = _statement_records(statement_path)
    ledger_records, ledger_digest = _read_ledger_records(ledger_path)
    try:
        amount_tolerance = Money.from_exact(tolerance, currency)
    except Exception as exc:
        raise BankStatementControlError("bank statement amount tolerance is invalid.") from exc
    return run_bank_statement_control(
        bank_lines,
        ledger_records,
        amount_tolerance=amount_tolerance,
        date_window_days=date_window_days,
        input_digests=(statement_digest, ledger_digest, _sha256(statement_path), _sha256(ledger_path)),
    )


def write_bank_statement_report(run: BankStatementControlRun, output_path: Path) -> None:
    """Write a self-digesting bank control artifact."""

    payload = run.to_dict()
    payload["artifact_type"] = "reconforge-bank-statement-control"
    payload["artifact_digest"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def verify_bank_statement_report(path: Path) -> dict[str, Any]:
    """Verify one local bank control artifact through the bounded reader."""

    from reconforge.io.structured import StructuredDocumentError, read_json_document

    try:
        payload = read_json_document(path)
    except (OSError, UnicodeError, StructuredDocumentError) as exc:
        raise BankStatementControlError("bank statement report cannot be read.") from exc
    if not isinstance(payload, dict) or payload.get("artifact_type") != "reconforge-bank-statement-control":
        raise BankStatementControlError("bank statement report artifact type is invalid.")
    artifact_digest = payload.get("artifact_digest")
    without_digest = {key: value for key, value in payload.items() if key != "artifact_digest"}
    expected = hashlib.sha256(
        json.dumps(without_digest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    ).hexdigest()
    if not isinstance(artifact_digest, str) or artifact_digest != expected:
        raise BankStatementControlError("bank statement report digest verification failed.")
    return payload


__all__ = [
    "run_bank_statement_control_files",
    "verify_bank_statement_report",
    "write_bank_statement_report",
]
